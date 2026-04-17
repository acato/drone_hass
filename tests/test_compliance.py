"""ComplianceGate: authorization token lifecycle, common gates, mode behavior."""

from __future__ import annotations

import time

import pytest

from mavlink_mqtt_bridge.compliance import (
    ComplianceError,
    ComplianceGate,
    GateContext,
    OperationalMode,
)
from mavlink_mqtt_bridge.state import DroneState


def _ready_state() -> DroneState:
    s = DroneState()
    s.gps_fix_type = 3
    s.num_satellites = 12
    return s


def _gate_p107() -> ComplianceGate:
    return ComplianceGate(OperationalMode.PART_107)


# ---------- Token lifecycle ----------


def test_grant_authorization_creates_valid_token() -> None:
    gate = _gate_p107()
    token = gate.grant_authorization(rpic_id="alice", valid_for_s=60, trigger="manual")
    assert token.rpic_id == "alice"
    assert token.trigger == "manual"
    assert token.used is False
    assert token.expires_at > token.issued_at
    assert token.is_valid() is True


def test_second_grant_replaces_first() -> None:
    gate = _gate_p107()
    t1 = gate.grant_authorization(rpic_id="alice", valid_for_s=60, trigger="manual")
    t2 = gate.grant_authorization(rpic_id="bob", valid_for_s=60, trigger="alarm")
    assert t1.flight_id != t2.flight_id
    active, _ = gate.authorization_snapshot()
    assert active is True
    # Only the latest token is the active one — enforcement is via authorize_flight.
    result = gate.authorize_flight(GateContext(state=_ready_state()))
    assert result.flight_id == t2.flight_id


def test_token_is_invalid_after_expiry() -> None:
    gate = _gate_p107()
    token = gate.grant_authorization(rpic_id="alice", valid_for_s=60, trigger="manual")
    # Simulate clock advance past expiry.
    token.expires_at = int(time.time()) - 5
    assert token.is_valid() is False
    active, _ = gate.authorization_snapshot()
    assert active is False


def test_consume_marks_token_used() -> None:
    gate = _gate_p107()
    token = gate.grant_authorization(rpic_id="alice", valid_for_s=60, trigger="manual")
    gate.consume_authorization()
    assert token.used is True
    assert token.used_at is not None
    assert token.is_valid() is False


def test_consume_is_idempotent_without_token() -> None:
    gate = _gate_p107()
    gate.consume_authorization()   # no token — should not raise
    gate.grant_authorization(rpic_id="alice", valid_for_s=60, trigger="manual")
    gate.consume_authorization()
    gate.consume_authorization()   # second consume — no-op


def test_revoke_clears_token() -> None:
    gate = _gate_p107()
    gate.grant_authorization(rpic_id="alice", valid_for_s=60, trigger="manual")
    gate.revoke_authorization()
    active, expires = gate.authorization_snapshot()
    assert active is False and expires is None


# ---------- Common gates ----------


def test_gate_fails_without_gps_fix() -> None:
    gate = _gate_p107()
    gate.grant_authorization(rpic_id="alice", valid_for_s=60, trigger="test")
    state = DroneState()  # gps_fix_type = 0
    result = gate.authorize_flight(GateContext(state=state))
    assert result.ok is False
    assert "gps_ok" in result.event.failed_gates


def test_gate_fails_if_airborne() -> None:
    gate = _gate_p107()
    gate.grant_authorization(rpic_id="alice", valid_for_s=60, trigger="test")
    state = _ready_state()
    state.in_air = True
    result = gate.authorize_flight(GateContext(state=state))
    assert result.ok is False
    assert "not_airborne" in result.event.failed_gates


def test_gate_fails_on_low_battery() -> None:
    gate = _gate_p107()
    gate.grant_authorization(rpic_id="alice", valid_for_s=60, trigger="test")
    state = _ready_state()
    state.battery_charge_percent = 15.0
    result = gate.authorize_flight(GateContext(state=state))
    assert result.ok is False
    assert "battery_ok" in result.event.failed_gates


def test_gate_passes_when_battery_unknown() -> None:
    """Fail-open on missing telemetry — ArduPilot's pre-arm is the backstop."""
    gate = _gate_p107()
    gate.grant_authorization(rpic_id="alice", valid_for_s=60, trigger="test")
    state = _ready_state()
    state.battery_charge_percent = None
    result = gate.authorize_flight(GateContext(state=state))
    assert result.ok is True
    assert result.event.outcome == "pass"


# ---------- Part 107 path ----------


def test_part107_requires_active_token() -> None:
    gate = _gate_p107()
    # No grant_authorization call
    result = gate.authorize_flight(GateContext(state=_ready_state()))
    assert result.ok is False
    assert "rpic_authorization" in result.event.failed_gates


def test_part107_passes_with_valid_token() -> None:
    gate = _gate_p107()
    token = gate.grant_authorization(rpic_id="alice", valid_for_s=60, trigger="manual")
    result = gate.authorize_flight(GateContext(state=_ready_state()))
    assert result.ok is True
    assert result.flight_id == token.flight_id
    assert result.event.failed_gates == []


def test_part107_rejects_used_token() -> None:
    gate = _gate_p107()
    gate.grant_authorization(rpic_id="alice", valid_for_s=60, trigger="manual")
    gate.consume_authorization()
    result = gate.authorize_flight(GateContext(state=_ready_state()))
    assert result.ok is False
    assert "rpic_authorization" in result.event.failed_gates


def test_safety_gate_event_shape_matches_contract() -> None:
    gate = _gate_p107()
    gate.grant_authorization(rpic_id="alice", valid_for_s=60, trigger="manual")
    result = gate.authorize_flight(GateContext(state=_ready_state()))
    payload = result.event.model_dump()
    assert payload["event_type"] == "safety_gate"
    assert payload["outcome"] == "pass"
    assert isinstance(payload["flight_id"], str) and len(payload["flight_id"]) > 0
    # Contract §7.7 required gate keys
    required_keys = {
        "battery_ok", "gps_ok", "connection_ok", "weather_ok", "daa_healthy",
        "operational_area_valid", "not_airborne", "mission_valid",
    }
    assert required_keys.issubset(payload["gates"].keys())
    # Part 107: fc_on_duty must be None (contract "Null in Part 107 mode")
    assert payload["gates"]["fc_on_duty"] is None


# ---------- Part 108 path (stub) ----------


def test_part108_gate_raises_unimplemented() -> None:
    gate = ComplianceGate(OperationalMode.PART_108)
    gate.set_fc_on_duty(True)
    with pytest.raises(ComplianceError) as exc:
        gate.authorize_flight(GateContext(state=_ready_state()))
    assert exc.value.code == "gate_unimplemented"
    assert "Phase 3" in (exc.value.reason or "")


def test_part108_rejects_authorize_flight_grant() -> None:
    gate = ComplianceGate(OperationalMode.PART_108)
    with pytest.raises(ComplianceError) as exc:
        gate.grant_authorization(rpic_id="alice", valid_for_s=60, trigger="manual")
    assert exc.value.code == "wrong_mode"


def test_part108_fc_on_duty_flag_appears_in_gate_outcome() -> None:
    """Common gates run even though Part 108 authorize_flight then errors out.

    We assert the FC flag by running just the private common-gates path via
    the gate's internal method. That's a deliberate test of the flag mapping.
    """
    gate = ComplianceGate(OperationalMode.PART_108)
    gate.set_fc_on_duty(True)
    outcome = gate._run_common_gates(GateContext(state=_ready_state()))
    assert outcome.fc_on_duty is True
