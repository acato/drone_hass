"""Command dispatch: preconditions, success path, error mapping, replay."""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

import pytest

from mavlink_mqtt_bridge import commands
from mavlink_mqtt_bridge.commands import CommandError, dispatch
from mavlink_mqtt_bridge.compliance import ComplianceGate, OperationalMode
from mavlink_mqtt_bridge.models import CommandRequest
from mavlink_mqtt_bridge.state import DroneState


# ---------- Fakes ----------


class FakeMqtt:
    def __init__(self) -> None:
        self.published: list[tuple[str, bytes]] = []

    async def publish(self, topic: str, payload: bytes, qos: int = 0, retain: bool = False) -> None:
        self.published.append((topic, payload))


@dataclass
class FakeAction:
    """Stand-in for mavsdk.action.* with scripted success/failure."""

    arm_raises: BaseException | None = None
    takeoff_raises: BaseException | None = None
    land_raises: BaseException | None = None
    rtl_raises: BaseException | None = None

    arm_calls: int = 0
    takeoff_calls: int = 0
    takeoff_alt_set: float | None = None
    land_calls: int = 0
    rtl_calls: int = 0

    async def arm(self) -> None:
        self.arm_calls += 1
        if self.arm_raises:
            raise self.arm_raises

    async def set_takeoff_altitude(self, alt: float) -> None:
        self.takeoff_alt_set = alt

    async def takeoff(self) -> None:
        self.takeoff_calls += 1
        if self.takeoff_raises:
            raise self.takeoff_raises

    async def land(self) -> None:
        self.land_calls += 1
        if self.land_raises:
            raise self.land_raises

    async def return_to_launch(self) -> None:
        self.rtl_calls += 1
        if self.rtl_raises:
            raise self.rtl_raises


@dataclass
class FakeDrone:
    action: FakeAction = field(default_factory=FakeAction)


@dataclass
class FakeConfig:
    base_topic: str = "drone_hass/sitl1"


@dataclass
class FakeBridge:
    drone: FakeDrone = field(default_factory=FakeDrone)
    state: DroneState = field(default_factory=DroneState)
    config: FakeConfig = field(default_factory=FakeConfig)
    _mqtt: FakeMqtt = field(default_factory=FakeMqtt)
    gate: ComplianceGate = field(default_factory=lambda: ComplianceGate(OperationalMode.PART_107))


def _ready_state() -> DroneState:
    s = DroneState()
    s.gps_fix_type = 3
    s.num_satellites = 12
    return s


def _authorized_bridge() -> FakeBridge:
    """FakeBridge with a fresh Part 107 authorization token already granted."""
    b = FakeBridge(state=_ready_state())
    b.gate.grant_authorization(rpic_id="test-rpic", valid_for_s=120, trigger="test")
    return b


def _req(params: dict | None = None, timestamp: int | None = None) -> bytes:
    payload = {"id": str(uuid.uuid4())}
    if params is not None:
        payload["params"] = params
    if timestamp is not None:
        payload["timestamp"] = timestamp
    return json.dumps(payload).encode("utf-8")


def _last_response(bridge: FakeBridge) -> dict:
    assert bridge._mqtt.published, "no response published"
    _, payload = bridge._mqtt.published[-1]
    return json.loads(payload)


# ---------- Success path ----------


async def test_arm_success_publishes_success_response() -> None:
    b = _authorized_bridge()
    await dispatch(b, "arm", _req(), f"{b.config.base_topic}/command/arm/response")
    resp = _last_response(b)
    assert resp["success"] is True
    assert resp["error"] is None
    assert b.drone.action.arm_calls == 1


async def test_takeoff_arms_first_if_needed_and_sets_altitude() -> None:
    b = _authorized_bridge()
    await dispatch(
        b, "takeoff",
        _req(params={"altitude_m": 15.0}),
        f"{b.config.base_topic}/command/takeoff/response",
    )
    resp = _last_response(b)
    assert resp["success"] is True
    assert resp["data"]["target_altitude_m"] == 15.0
    assert b.drone.action.arm_calls == 1
    assert b.drone.action.takeoff_alt_set == 15.0
    assert b.drone.action.takeoff_calls == 1


async def test_takeoff_default_altitude_is_10m() -> None:
    b = _authorized_bridge()
    await dispatch(b, "takeoff", _req(), f"{b.config.base_topic}/command/takeoff/response")
    assert b.drone.action.takeoff_alt_set == 10.0


async def test_land_success() -> None:
    b = FakeBridge(state=_ready_state())
    b.state.in_air = True
    await dispatch(b, "land", _req(), f"{b.config.base_topic}/command/land/response")
    resp = _last_response(b)
    assert resp["success"] is True
    assert b.drone.action.land_calls == 1


async def test_rtl_success() -> None:
    b = FakeBridge(state=_ready_state())
    b.state.in_air = True
    await dispatch(
        b, "return_to_home", _req(),
        f"{b.config.base_topic}/command/return_to_home/response",
    )
    resp = _last_response(b)
    assert resp["success"] is True
    assert b.drone.action.rtl_calls == 1


# ---------- Preconditions ----------


async def test_arm_rejected_if_already_armed() -> None:
    b = FakeBridge(state=_ready_state())
    b.state.armed = True
    await dispatch(b, "arm", _req(), f"{b.config.base_topic}/command/arm/response")
    resp = _last_response(b)
    assert resp["success"] is False
    assert resp["error"] == "already_armed"
    assert b.drone.action.arm_calls == 0


async def test_arm_rejected_without_gps_fix() -> None:
    b = FakeBridge(state=DroneState())  # gps_fix_type=0 by default
    await dispatch(b, "arm", _req(), f"{b.config.base_topic}/command/arm/response")
    resp = _last_response(b)
    assert resp["success"] is False
    assert resp["error"] == "gps_not_ready"
    assert "fix_type=0" in resp["data"]["reason"]


async def test_takeoff_rejected_if_already_airborne() -> None:
    b = FakeBridge(state=_ready_state())
    b.state.in_air = True
    await dispatch(b, "takeoff", _req(), f"{b.config.base_topic}/command/takeoff/response")
    resp = _last_response(b)
    assert resp["success"] is False
    assert resp["error"] == "already_airborne"
    assert b.drone.action.takeoff_calls == 0


async def test_land_rejected_if_not_flying() -> None:
    b = FakeBridge(state=_ready_state())
    # in_air=False by default
    await dispatch(b, "land", _req(), f"{b.config.base_topic}/command/land/response")
    resp = _last_response(b)
    assert resp["success"] is False
    assert resp["error"] == "not_flying"
    assert b.drone.action.land_calls == 0


async def test_rtl_rejected_if_not_flying() -> None:
    b = FakeBridge(state=_ready_state())
    await dispatch(
        b, "return_to_home", _req(),
        f"{b.config.base_topic}/command/return_to_home/response",
    )
    resp = _last_response(b)
    assert resp["success"] is False
    assert resp["error"] == "not_flying"
    assert b.drone.action.rtl_calls == 0


async def test_takeoff_rejects_out_of_range_altitude() -> None:
    b = FakeBridge(state=_ready_state())
    await dispatch(
        b, "takeoff",
        _req(params={"altitude_m": 500.0}),
        f"{b.config.base_topic}/command/takeoff/response",
    )
    resp = _last_response(b)
    assert resp["success"] is False
    assert resp["error"] == "invalid_params"


# ---------- Dispatcher edge cases ----------


async def test_unknown_command_returns_error() -> None:
    b = FakeBridge(state=_ready_state())
    await dispatch(
        b, "self_destruct", _req(),
        f"{b.config.base_topic}/command/self_destruct/response",
    )
    resp = _last_response(b)
    assert resp["success"] is False
    assert resp["error"] == "unknown_command"


async def test_stale_command_rejected() -> None:
    b = FakeBridge(state=_ready_state())
    old = int(time.time()) - 120
    await dispatch(
        b, "arm", _req(timestamp=old),
        f"{b.config.base_topic}/command/arm/response",
    )
    resp = _last_response(b)
    assert resp["success"] is False
    assert resp["error"] == "stale_command"
    assert b.drone.action.arm_calls == 0


async def test_fresh_command_accepted() -> None:
    b = _authorized_bridge()
    now = int(time.time())
    await dispatch(
        b, "arm", _req(timestamp=now),
        f"{b.config.base_topic}/command/arm/response",
    )
    resp = _last_response(b)
    assert resp["success"] is True


async def test_invalid_envelope_drops_silently() -> None:
    """No correlation id means no response can be sent."""
    b = FakeBridge(state=_ready_state())
    await dispatch(b, "arm", b"{not json", f"{b.config.base_topic}/command/arm/response")
    assert b._mqtt.published == []


async def test_correlation_id_roundtrips() -> None:
    b = _authorized_bridge()
    req_id = "11111111-2222-3333-4444-555555555555"
    raw = json.dumps({"id": req_id}).encode("utf-8")
    await dispatch(b, "arm", raw, f"{b.config.base_topic}/command/arm/response")
    resp = _last_response(b)
    assert resp["id"] == req_id


# ---------- ActionError mapping ----------


class FakeActionError(Exception):
    """Replaces mavsdk.action.ActionError for unit testing error mapping."""


@pytest.fixture
def patch_action_error(monkeypatch):
    import mavsdk.action as action_module

    monkeypatch.setattr(action_module, "ActionError", FakeActionError)
    yield FakeActionError


async def test_arm_failure_maps_to_arm_failed(patch_action_error) -> None:
    b = _authorized_bridge()
    b.drone.action.arm_raises = FakeActionError("PreArm: Baro not healthy")
    await dispatch(b, "arm", _req(), f"{b.config.base_topic}/command/arm/response")
    resp = _last_response(b)
    assert resp["success"] is False
    assert resp["error"] == "arm_failed"
    assert "Baro" in resp["data"]["reason"]


async def test_command_error_has_code_attribute() -> None:
    e = CommandError("foo", "because")
    assert e.code == "foo"
    assert e.reason == "because"
    assert "foo" in str(e) and "because" in str(e)


# ---------- ComplianceGate integration ----------


async def test_arm_without_authorization_fails() -> None:
    b = FakeBridge(state=_ready_state())   # no grant_authorization
    await dispatch(b, "arm", _req(), f"{b.config.base_topic}/command/arm/response")
    resp = _last_response(b)
    assert resp["success"] is False
    assert resp["error"] == "not_authorized"
    assert b.drone.action.arm_calls == 0


async def test_arm_publishes_safety_gate_event() -> None:
    b = _authorized_bridge()
    await dispatch(b, "arm", _req(), f"{b.config.base_topic}/command/arm/response")
    topics = [t for t, _ in b._mqtt.published]
    assert f"{b.config.base_topic}/compliance/safety_gate" in topics

    gate_payload = next(
        json.loads(p) for t, p in b._mqtt.published
        if t == f"{b.config.base_topic}/compliance/safety_gate"
    )
    assert gate_payload["outcome"] == "pass"
    assert gate_payload["event_type"] == "safety_gate"


async def test_arm_consumes_token_so_second_arm_fails() -> None:
    b = _authorized_bridge()
    await dispatch(b, "arm", _req(), f"{b.config.base_topic}/command/arm/response")
    assert _last_response(b)["success"] is True

    # Simulate a disarm -> re-arm scenario by dropping the armed flag;
    # the token should already be consumed, so the second arm is rejected.
    b.state.armed = False
    b._mqtt.published.clear()
    await dispatch(b, "arm", _req(), f"{b.config.base_topic}/command/arm/response")
    resp = _last_response(b)
    assert resp["success"] is False
    assert resp["error"] == "not_authorized"


async def test_authorize_flight_command_grants_token() -> None:
    b = FakeBridge(state=_ready_state())
    await dispatch(
        b, "authorize_flight",
        _req(params={"rpic_id": "alice", "valid_for_s": 60, "trigger": "alarm"}),
        f"{b.config.base_topic}/command/authorize_flight/response",
    )
    resp = _last_response(b)
    assert resp["success"] is True
    assert "flight_id" in resp["data"]
    assert "expires_at" in resp["data"]
    # Token now active — subsequent arm should pass
    await dispatch(b, "arm", _req(), f"{b.config.base_topic}/command/arm/response")
    assert _last_response(b)["success"] is True


async def test_authorize_flight_publishes_compliance_state() -> None:
    b = FakeBridge(state=_ready_state())
    await dispatch(
        b, "authorize_flight",
        _req(params={"rpic_id": "alice"}),
        f"{b.config.base_topic}/command/authorize_flight/response",
    )
    state_msgs = [
        json.loads(p) for t, p in b._mqtt.published
        if t == f"{b.config.base_topic}/state/compliance"
    ]
    assert state_msgs, "state/compliance not published"
    latest = state_msgs[-1]
    assert latest["mode"] == "part_107"
    assert latest["authorization_active"] is True
    assert latest["authorization_expires_at"] is not None


async def test_authorize_flight_rejects_missing_rpic_id() -> None:
    b = FakeBridge(state=_ready_state())
    await dispatch(
        b, "authorize_flight",
        _req(params={"valid_for_s": 60}),   # no rpic_id
        f"{b.config.base_topic}/command/authorize_flight/response",
    )
    resp = _last_response(b)
    assert resp["success"] is False
    assert resp["error"] == "invalid_params"


async def test_arm_failure_does_not_consume_token() -> None:
    """If MAVSDK arm fails, the token remains valid for a retry."""
    import mavsdk.action as action_module

    class FakeActionError2(Exception):
        pass

    original = getattr(action_module, "ActionError", None)
    action_module.ActionError = FakeActionError2
    try:
        b = _authorized_bridge()
        b.drone.action.arm_raises = FakeActionError2("PreArm: temp failure")
        await dispatch(b, "arm", _req(), f"{b.config.base_topic}/command/arm/response")
        assert _last_response(b)["success"] is False
        # Token still valid
        active, _ = b.gate.authorization_snapshot()
        assert active is True
    finally:
        if original is not None:
            action_module.ActionError = original
