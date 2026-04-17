"""MQTT command handlers → MAVSDK Action calls.

Subscribes to drone_hass/{drone_id}/command/+ and dispatches each message to an
async handler. Handlers enforce preconditions, call MAVSDK, and raise
CommandError(code, reason) on failure. A single response is published to
drone_hass/{drone_id}/command/{action}/response for every request.

ComplianceGate hook is a placeholder — Phase 0 step 7 will replace
`_authorize_placeholder` with the real gate.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

import aiomqtt
from pydantic import ValidationError

from .log import get_logger
from .models import CommandRequest, CommandResponse, TakeoffParams

if TYPE_CHECKING:
    from .state import DroneState

log = get_logger(__name__)

# Per-command timeout for the MAVLink COMMAND_ACK (contract §2.2–2.5: 5 s).
COMMAND_ACK_TIMEOUT_S = 5.0

# Replay protection window (contract §7.4 request_base description).
COMMAND_MAX_AGE_S = 30


class CommandError(Exception):
    """Handler-layer failure surfaced to MQTT as {success: false, error: code}."""

    def __init__(self, code: str, reason: str | None = None) -> None:
        super().__init__(f"{code}: {reason}" if reason else code)
        self.code = code
        self.reason = reason


# ---------- Precondition helpers ----------


def _require_gps_fix(state: "DroneState", minimum: int = 3) -> None:
    if state.gps_fix_type < minimum:
        raise CommandError(
            "gps_not_ready",
            f"fix_type={state.gps_fix_type} satellites={state.num_satellites}",
        )


def _require_flying(state: "DroneState") -> None:
    if not state.in_air:
        raise CommandError("not_flying")


def _require_not_flying(state: "DroneState") -> None:
    if state.in_air:
        raise CommandError("already_airborne")


def _authorize_placeholder() -> None:
    """Replaced by ComplianceGate in Phase 0 step 7.

    Part 107 mode today: always authorizes. Part 108 mode will require an
    active authorization token created by the HA-side notification flow.
    """
    return None


# ---------- MAVSDK call wrapper ----------


async def _call_action(
    coro: Awaitable[Any],
    *,
    error_code: str,
    timeout_s: float = COMMAND_ACK_TIMEOUT_S,
) -> None:
    """Invoke a MAVSDK action with timeout + ActionError translation."""
    from mavsdk.action import ActionError  # local import: optional at test time

    try:
        await asyncio.wait_for(coro, timeout=timeout_s)
    except TimeoutError as exc:
        raise CommandError(f"{error_code}_timeout", "no response from flight controller") from exc
    except ActionError as exc:
        # ActionError wraps MAV_RESULT. Its str() includes the textual reason.
        raise CommandError(f"{error_code}_failed", str(exc)) from exc


# ---------- Handlers ----------

# Each handler takes (bridge, req) and either returns a dict (response `data`)
# or None. Preconditions raise CommandError which the dispatcher maps to a
# failure response.


async def _handle_arm(bridge: Any, req: CommandRequest) -> dict | None:
    if bridge.state.armed:
        raise CommandError("already_armed")
    _require_gps_fix(bridge.state)
    _authorize_placeholder()
    await _call_action(bridge.drone.action.arm(), error_code="arm")
    return None


async def _handle_takeoff(bridge: Any, req: CommandRequest) -> dict | None:
    try:
        params = TakeoffParams.model_validate(req.params or {})
    except ValidationError as exc:
        raise CommandError("invalid_params", str(exc)) from exc

    _require_not_flying(bridge.state)
    _require_gps_fix(bridge.state)
    _authorize_placeholder()

    if not bridge.state.armed:
        await _call_action(bridge.drone.action.arm(), error_code="arm")

    # set_takeoff_altitude has no ACK to wait on — it just stores the param.
    await bridge.drone.action.set_takeoff_altitude(params.altitude_m)
    await _call_action(bridge.drone.action.takeoff(), error_code="takeoff")
    return {"target_altitude_m": params.altitude_m}


async def _handle_land(bridge: Any, req: CommandRequest) -> dict | None:
    _require_flying(bridge.state)
    await _call_action(bridge.drone.action.land(), error_code="land")
    return None


async def _handle_return_to_home(bridge: Any, req: CommandRequest) -> dict | None:
    _require_flying(bridge.state)
    await _call_action(bridge.drone.action.return_to_launch(), error_code="rtl")
    return None


Handler = Callable[[Any, CommandRequest], Awaitable[dict | None]]

HANDLERS: dict[str, Handler] = {
    "arm": _handle_arm,
    "takeoff": _handle_takeoff,
    "land": _handle_land,
    "return_to_home": _handle_return_to_home,
}


# ---------- Dispatch / consumer ----------


async def _publish_response(
    mqtt: aiomqtt.Client,
    topic: str,
    resp: CommandResponse,
) -> None:
    payload = resp.model_dump_json().encode("utf-8")
    await mqtt.publish(topic, payload=payload, qos=1, retain=False)


def _parse_request(raw: bytes) -> CommandRequest:
    return CommandRequest.model_validate_json(raw)


async def dispatch(
    bridge: Any,
    action: str,
    raw_payload: bytes,
    response_topic: str,
) -> None:
    """Validate, dispatch, and publish response. Never raises."""
    assert bridge._mqtt is not None

    try:
        req = _parse_request(raw_payload)
    except ValidationError as exc:
        log.warning("command.invalid_envelope", action=action, error=str(exc))
        # No correlation id to return — drop silently per contract (id is required).
        return

    logger = log.bind(action=action, id=req.id)

    # Replay protection
    if req.timestamp is not None and abs(time.time() - req.timestamp) > COMMAND_MAX_AGE_S:
        logger.warning("command.stale", age_s=time.time() - req.timestamp)
        await _publish_response(
            bridge._mqtt, response_topic,
            CommandResponse(id=req.id, success=False, error="stale_command"),
        )
        return

    handler = HANDLERS.get(action)
    if handler is None:
        logger.warning("command.unknown")
        await _publish_response(
            bridge._mqtt, response_topic,
            CommandResponse(id=req.id, success=False, error="unknown_command"),
        )
        return

    logger.info("command.received")
    try:
        data = await handler(bridge, req)
    except CommandError as exc:
        logger.warning("command.failed", code=exc.code, reason=exc.reason)
        await _publish_response(
            bridge._mqtt, response_topic,
            CommandResponse(
                id=req.id, success=False, error=exc.code,
                data={"reason": exc.reason} if exc.reason else None,
            ),
        )
        return
    except Exception as exc:
        logger.exception("command.unhandled_error")
        await _publish_response(
            bridge._mqtt, response_topic,
            CommandResponse(
                id=req.id, success=False, error="internal_error",
                data={"reason": repr(exc)},
            ),
        )
        return

    logger.info("command.success")
    await _publish_response(
        bridge._mqtt, response_topic,
        CommandResponse(id=req.id, success=True, data=data),
    )


async def run_consumer(bridge: Any) -> None:
    """Subscribe to command/+ and dispatch each message.

    Runs under Bridge's TaskGroup — a cancellation propagates normally.
    """
    assert bridge._mqtt is not None
    base = bridge.config.base_topic
    topic_filter = f"{base}/command/+"

    await bridge._mqtt.subscribe(topic_filter, qos=1)
    log.info("commands.subscribed", filter=topic_filter)

    async for msg in bridge._mqtt.messages:
        topic_str = str(msg.topic)
        # Ignore our own response publishes if they slip through the filter.
        if topic_str.endswith("/response"):
            continue
        action = topic_str.rsplit("/", 1)[-1]
        response_topic = f"{base}/command/{action}/response"
        # Dispatch in background so a slow MAVLink ACK doesn't block the consumer.
        asyncio.create_task(
            dispatch(bridge, action, msg.payload, response_topic),
            name=f"command.{action}",
        )
