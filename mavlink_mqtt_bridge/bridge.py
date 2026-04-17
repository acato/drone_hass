"""Bridge coordinator — wires MAVSDK to MQTT.

Runs three concurrent cohorts under an asyncio.TaskGroup:
  1. MAVSDK stream readers — consume per-field telemetry into DroneState
  2. MQTT publishers — tick at contract rates, build validated payloads, publish
  3. Connection watchdog (future) — detect heartbeat loss, publish 'degraded'

A failure in any child cancels the rest. __main__ catches the group exception
and triggers a clean shutdown (publishing 'offline' before exit).
"""

from __future__ import annotations

import asyncio
from contextlib import AsyncExitStack

import aiomqtt
from mavsdk import System

from .commands import run_consumer as run_command_consumer
from .config import BridgeConfig
from .log import get_logger
from .state import DroneState
from .telemetry import (
    BatteryPublisher,
    FlightPublisher,
    PositionPublisher,
    read_armed,
    read_battery,
    read_flight_mode,
    read_gps_info,
    read_heading,
    read_in_air,
    read_position,
    read_velocity,
)

log = get_logger(__name__)


class Bridge:
    """Owns the MAVSDK System and the MQTT client for a single drone."""

    def __init__(self, config: BridgeConfig) -> None:
        self.config = config
        self.drone = System()
        self.state = DroneState()
        self._stack: AsyncExitStack | None = None
        self._mqtt: aiomqtt.Client | None = None

    @property
    def connection_topic(self) -> str:
        return f"{self.config.base_topic}/state/connection"

    async def run(self) -> None:
        async with AsyncExitStack() as stack:
            self._stack = stack
            self._mqtt = await stack.enter_async_context(
                aiomqtt.Client(
                    hostname=self.config.mqtt.host,
                    port=self.config.mqtt.port,
                    username=self.config.mqtt.username,
                    password=self.config.mqtt.password,
                    identifier=self.config.mqtt.client_id,
                    keepalive=self.config.mqtt.keepalive,
                    will=aiomqtt.Will(
                        topic=self.connection_topic,
                        payload=b"offline",
                        qos=1,
                        retain=True,
                    ),
                )
            )
            log.info(
                "mqtt.connected",
                host=self.config.mqtt.host,
                port=self.config.mqtt.port,
                base_topic=self.config.base_topic,
            )

            # Handshake step 3 (contract §6.5): publish offline until drone attaches.
            await self._publish_connection_state("offline")

            log.info("mavsdk.connecting", url=self.config.drone.mavlink_connection)
            await self.drone.connect(system_address=self.config.drone.mavlink_connection)

            async for conn in self.drone.core.connection_state():
                if conn.is_connected:
                    log.info("mavsdk.connected")
                    break

            await self._publish_connection_state("online")
            await self._run_tasks()

    async def _publish_connection_state(self, value: str) -> None:
        assert self._mqtt is not None
        await self._mqtt.publish(
            self.connection_topic,
            payload=value.encode("utf-8"),
            qos=1,
            retain=True,
        )
        log.info("connection.state", value=value)

    async def _run_tasks(self) -> None:
        assert self._mqtt is not None
        base = self.config.base_topic

        publishers = [
            FlightPublisher(
                self._mqtt, base, self.state,
                name="flight", topic_suffix="telemetry/flight",
                period_s=1.0, qos=0,
            ),
            BatteryPublisher(
                self._mqtt, base, self.state,
                name="battery", topic_suffix="telemetry/battery",
                period_s=5.0, qos=0,
            ),
            PositionPublisher(
                self._mqtt, base, self.state,
                name="position", topic_suffix="telemetry/position",
                period_s=10.0, qos=0,
            ),
        ]

        reader_coros = [
            read_position(self.drone, self.state),
            read_heading(self.drone, self.state),
            read_velocity(self.drone, self.state),
            read_armed(self.drone, self.state),
            read_in_air(self.drone, self.state),
            read_flight_mode(self.drone, self.state),
            read_gps_info(self.drone, self.state),
            read_battery(self.drone, self.state),
        ]

        async with asyncio.TaskGroup() as tg:
            for coro in reader_coros:
                tg.create_task(coro)
            for pub in publishers:
                tg.create_task(pub.run(), name=f"publisher.{pub.name}")
            tg.create_task(run_command_consumer(self), name="command.consumer")
