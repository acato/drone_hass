"""MAVSDK stream readers + MQTT telemetry publishers.

Readers: one coroutine per MAVSDK telemetry stream, writes to DroneState.
Publishers: one coroutine per MQTT topic, ticks at contract rate, snapshots
state, validates payload via Pydantic, publishes.

All coroutines are designed to run under an asyncio.TaskGroup so a single
failure cancels the whole set — matches the bridge's fail-fast posture.
"""

from __future__ import annotations

import asyncio
import math
import time
from typing import TYPE_CHECKING

import aiomqtt

from .flight_modes import mavsdk_to_arducopter
from .log import get_logger
from .models import BatteryTelemetry, FlightTelemetry, PositionTelemetry
from .state import DroneState

if TYPE_CHECKING:
    from mavsdk import System

log = get_logger(__name__)


def _nan_to_none(v: float | None) -> float | None:
    """MAVSDK signals unknown with NaN; Pydantic/JSON want null."""
    if v is None:
        return None
    return None if math.isnan(v) else v


# ---------- MAVSDK readers ----------


async def read_position(drone: "System", state: DroneState) -> None:
    async for p in drone.telemetry.position():
        state.lat = p.latitude_deg
        state.lon = p.longitude_deg
        state.abs_alt_m = p.absolute_altitude_m
        state.rel_alt_m = p.relative_altitude_m
        state.touch("position")


async def read_heading(drone: "System", state: DroneState) -> None:
    async for h in drone.telemetry.heading():
        state.heading_deg = h.heading_deg
        state.touch("heading")


async def read_velocity(drone: "System", state: DroneState) -> None:
    async for v in drone.telemetry.velocity_ned():
        state.vel_n_mps = v.north_m_s
        state.vel_e_mps = v.east_m_s
        state.vel_d_mps = v.down_m_s
        state.touch("velocity")


async def read_armed(drone: "System", state: DroneState) -> None:
    async for a in drone.telemetry.armed():
        state.armed = bool(a)
        state.touch("armed")


async def read_in_air(drone: "System", state: DroneState) -> None:
    async for a in drone.telemetry.in_air():
        state.in_air = bool(a)
        state.touch("in_air")


async def read_flight_mode(drone: "System", state: DroneState) -> None:
    async for m in drone.telemetry.flight_mode():
        # MAVSDK FlightMode is an IntEnum-like; name attr gives 'HOLD' etc.
        name = getattr(m, "name", str(m))
        state.flight_mode = mavsdk_to_arducopter(name)
        state.touch("flight_mode")


async def read_gps_info(drone: "System", state: DroneState) -> None:
    async for g in drone.telemetry.gps_info():
        state.num_satellites = int(g.num_satellites)
        # MAVSDK FixType: NO_GPS=0, NO_FIX=1, FIX_2D=2, FIX_3D=3, FIX_DGPS=4, RTK_FLOAT=5, RTK_FIXED=6
        fix = getattr(g.fix_type, "value", g.fix_type)
        state.gps_fix_type = int(fix)
        state.touch("gps")


async def read_battery(drone: "System", state: DroneState) -> None:
    async for b in drone.telemetry.battery():
        state.battery_voltage_v = _nan_to_none(b.voltage_v)
        state.battery_charge_percent = _nan_to_none(b.remaining_percent)  # already 0..100
        state.battery_current_a = _nan_to_none(getattr(b, "current_battery_a", None))
        state.battery_temperature_c = _nan_to_none(getattr(b, "temperature_degc", None))
        state.battery_time_remaining_s = _nan_to_none(getattr(b, "time_remaining_s", None))
        state.touch("battery")


# ---------- MQTT publishers ----------


class Publisher:
    """Ticks at a fixed rate, builds payload from state, publishes to MQTT."""

    def __init__(
        self,
        mqtt: aiomqtt.Client,
        base_topic: str,
        state: DroneState,
        *,
        name: str,
        topic_suffix: str,
        period_s: float,
        qos: int = 0,
        retain: bool = False,
    ) -> None:
        self.mqtt = mqtt
        self.state = state
        self.name = name
        self.topic = f"{base_topic}/{topic_suffix}"
        self.period_s = period_s
        self.qos = qos
        self.retain = retain

    async def run(self) -> None:
        log.info("publisher.started", name=self.name, topic=self.topic, rate_hz=1 / self.period_s)
        # Align to the wall-clock period so rates stay steady under load.
        next_tick = asyncio.get_running_loop().time()
        while True:
            next_tick += self.period_s
            try:
                payload = self._build_payload()
            except Exception as exc:  # payload construction should never kill the task
                log.warning("publisher.payload_error", name=self.name, error=repr(exc))
                payload = None

            if payload is not None:
                await self.mqtt.publish(self.topic, payload=payload, qos=self.qos, retain=self.retain)

            sleep_for = next_tick - asyncio.get_running_loop().time()
            if sleep_for > 0:
                await asyncio.sleep(sleep_for)
            else:
                # We fell behind — reset schedule rather than fire a burst.
                next_tick = asyncio.get_running_loop().time()

    def _build_payload(self) -> bytes | None:
        raise NotImplementedError


class FlightPublisher(Publisher):
    def _build_payload(self) -> bytes | None:
        s = self.state
        if s.lat is None or s.lon is None or s.rel_alt_m is None:
            return None  # no position fix yet — skip this tick
        gs = s.ground_speed_mps or 0.0
        # MAVLink NED -> MQTT convention: positive z = UP
        speed_z = -s.vel_d_mps if s.vel_d_mps is not None else 0.0
        payload = FlightTelemetry(
            lat=s.lat,
            lon=s.lon,
            alt=s.rel_alt_m,
            heading=s.heading_deg,
            speed_x=s.vel_n_mps or 0.0,
            speed_y=s.vel_e_mps or 0.0,
            speed_z=speed_z,
            ground_speed=gs,
            flight_mode=s.flight_mode,
            armed=s.armed,
            is_flying=s.in_air,
            gps_fix=s.gps_fix_type,
            satellite_count=s.num_satellites,
            timestamp=int(time.time()),
        )
        return payload.model_dump_json().encode("utf-8")


class BatteryPublisher(Publisher):
    def _build_payload(self) -> bytes | None:
        s = self.state
        # MAVSDK 2.x Battery.remaining_percent is 0..100 (per vendored docstring).
        voltage_mv = int(s.battery_voltage_v * 1000) if s.battery_voltage_v is not None else None
        charge_pct = int(round(s.battery_charge_percent)) if s.battery_charge_percent is not None else None
        # Contract: current_ma negative=discharge. MAVSDK: current_battery_a positive=discharge. Flip.
        current_ma = (
            int(round(-s.battery_current_a * 1000)) if s.battery_current_a is not None else None
        )
        time_remaining_s = (
            int(round(s.battery_time_remaining_s)) if s.battery_time_remaining_s is not None else None
        )
        payload = BatteryTelemetry(
            charge_percent=charge_pct,
            voltage_mv=voltage_mv,
            current_ma=current_ma,
            temperature_c=s.battery_temperature_c,
            remaining_mah=None,        # Needs BATT_CAPACITY + capacity_consumed_ah math
            full_charge_mah=None,      # Needs BATT_CAPACITY param read
            flight_time_remaining_s=time_remaining_s,
            timestamp=int(time.time()),
        )
        return payload.model_dump_json().encode("utf-8")


class PositionPublisher(Publisher):
    def _build_payload(self) -> bytes | None:
        s = self.state
        if s.lat is None or s.lon is None or s.rel_alt_m is None:
            return None
        payload = PositionTelemetry(lat=s.lat, lon=s.lon, alt=s.rel_alt_m)
        return payload.model_dump_json().encode("utf-8")
