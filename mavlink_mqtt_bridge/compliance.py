"""ComplianceGate — Part 107 enforcement skeleton.

Per architecture.md §8.7 the gate runs a set of common pre-flight checks and
then a mode-specific authorization step. This module implements:

  * Common gates derivable from DroneState today (GPS fix, battery, not-airborne).
  * Part 107 path: single-use time-limited authorization token, granted by HA
    via command/authorize_flight (RPIC tap), consumed on successful arm.
  * Part 108 path: stub — raises gate_unimplemented. Phase 3 delivers it.

Placeholders (always pass in Phase 0, wired in Phase 3):
  * Operational area (GeoJSON polygon containment + altitude ceiling)
  * Weather envelope (wind, rain, visibility)
  * DAA health
  * Dock lid state

The gate publishes two MQTT artifacts:
  * state/compliance — retained, reflects current mode + authorization state
  * compliance/safety_gate — per authorization attempt, pass/fail + per-gate detail

Flight ID: a UUID generated when a token is granted; carried through safety
gate events, and (Phase 3) through the flight_log and DAA event chain.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum

from .log import get_logger
from .models import SafetyGateEvent, SafetyGateOutcome
from .state import DroneState

log = get_logger(__name__)


class OperationalMode(str, Enum):
    PART_107 = "part_107"
    PART_108 = "part_108"


class ComplianceError(Exception):
    """Surfaced to the command dispatcher as a failure reason."""

    def __init__(self, code: str, reason: str | None = None) -> None:
        super().__init__(f"{code}: {reason}" if reason else code)
        self.code = code
        self.reason = reason


@dataclass
class AuthorizationToken:
    """Time-limited, single-use flight authorization (§15 threat model)."""

    flight_id: str
    rpic_id: str
    trigger: str
    issued_at: int
    expires_at: int
    used: bool = False
    used_at: int | None = None

    def is_valid(self, now: int | None = None) -> bool:
        now = now if now is not None else int(time.time())
        return not self.used and now < self.expires_at


@dataclass
class GateContext:
    """Per-attempt inputs to authorize_flight — extends naturally as we add
    weather, op-area, DAA, dock. Phase 0 = state-only."""

    state: DroneState
    mission_valid: bool = True   # no missions yet; honest default


@dataclass
class AuthorizationResult:
    """Returned by authorize_flight — carries the outcome and the event we
    want published to compliance/safety_gate so the caller can publish once."""

    ok: bool
    flight_id: str
    event: SafetyGateEvent


class ComplianceGate:
    """Mode-switching compliance gate.

    Not thread-safe. Owned by Bridge and called sequentially from the command
    dispatcher (which itself creates one task per inbound command, but command
    serialization is ArduPilot's problem, not the gate's).
    """

    # Battery floor before the gate will authorize a new flight. Mirrors
    # contract §2.7 execute_mission default (30%). Applied when battery
    # telemetry is present; skipped while MAVSDK hasn't reported yet.
    MIN_BATTERY_PERCENT_TO_AUTHORIZE = 30.0

    def __init__(self, mode: OperationalMode) -> None:
        self.mode = mode
        self._token: AuthorizationToken | None = None
        self._fc_on_duty: bool = False   # Part 108 — set via command/set_fc_on_duty

    # ---------- Public API ----------

    def grant_authorization(self, rpic_id: str, valid_for_s: int, trigger: str) -> AuthorizationToken:
        """Create/replace the current authorization token. Idempotent — a
        second tap within the window replaces the first (latest wins).
        """
        if self.mode is not OperationalMode.PART_107:
            raise ComplianceError(
                "wrong_mode",
                f"authorize_flight is only valid in Part 107 mode (current={self.mode.value})",
            )
        now = int(time.time())
        self._token = AuthorizationToken(
            flight_id=str(uuid.uuid4()),
            rpic_id=rpic_id,
            trigger=trigger,
            issued_at=now,
            expires_at=now + valid_for_s,
        )
        log.info(
            "compliance.auth.granted",
            flight_id=self._token.flight_id,
            rpic_id=rpic_id,
            expires_at=self._token.expires_at,
            trigger=trigger,
        )
        return self._token

    def revoke_authorization(self) -> None:
        if self._token is not None:
            log.info("compliance.auth.revoked", flight_id=self._token.flight_id)
        self._token = None

    def set_fc_on_duty(self, on_duty: bool) -> None:
        self._fc_on_duty = on_duty

    def authorization_snapshot(self) -> tuple[bool, int | None]:
        """Returns (active, expires_at) for state/compliance publishing."""
        if self._token is None or not self._token.is_valid():
            return False, None
        return True, self._token.expires_at

    def authorize_flight(self, ctx: GateContext) -> AuthorizationResult:
        """Run common gates + mode-specific gate. Returns result (pass/fail)
        and the SafetyGateEvent to be published by the caller.

        Does NOT consume the token — that's consume_authorization() after the
        command the gate was gating (arm) actually succeeds.
        """
        gates = self._run_common_gates(ctx)
        failed = [name for name, passed in _iter_gate_flags(gates) if passed is False]

        # Mode-specific: even if common gates pass, Part 107 needs an active token.
        if not failed:
            if self.mode is OperationalMode.PART_107:
                if self._token is None or not self._token.is_valid():
                    failed.append("rpic_authorization")
            elif self.mode is OperationalMode.PART_108:
                # Phase 3. Explicit stub so nobody thinks Part 108 silently passes.
                raise ComplianceError(
                    "gate_unimplemented",
                    "Part 108 compliance gate not implemented — this is a Phase 3 deliverable",
                )

        flight_id = self._token.flight_id if self._token is not None else str(uuid.uuid4())
        event = SafetyGateEvent(
            flight_id=flight_id,
            outcome="pass" if not failed else "fail",
            gates=gates,
            failed_gates=failed,
            timestamp=int(time.time()),
        )
        log.info(
            "compliance.gate",
            mode=self.mode.value,
            outcome=event.outcome,
            failed=failed,
            flight_id=flight_id,
        )
        return AuthorizationResult(ok=not failed, flight_id=flight_id, event=event)

    def consume_authorization(self) -> None:
        """Mark the current token as used. Called after a successful arm.

        Idempotent — calling without an active token is a no-op; subsequent
        calls against a used token also no-op.
        """
        if self._token is None or self._token.used:
            return
        self._token.used = True
        self._token.used_at = int(time.time())
        log.info(
            "compliance.auth.consumed",
            flight_id=self._token.flight_id,
            rpic_id=self._token.rpic_id,
        )

    # ---------- Gate implementations ----------

    def _run_common_gates(self, ctx: GateContext) -> SafetyGateOutcome:
        s = ctx.state
        gps_ok = s.gps_fix_type >= 3
        # Battery telemetry may not have arrived yet — fail open here (we still
        # have ArduPilot's own pre-arm battery check as a backstop).
        if s.battery_charge_percent is None:
            battery_ok = True
        else:
            battery_ok = s.battery_charge_percent >= self.MIN_BATTERY_PERCENT_TO_AUTHORIZE
        return SafetyGateOutcome(
            battery_ok=battery_ok,
            gps_ok=gps_ok,
            # Phase 0 placeholders — wire in Phase 3:
            connection_ok=True,          # TODO: add heartbeat-lost watchdog
            weather_ok=True,              # TODO: consume telemetry/weather entity
            daa_healthy=True,             # TODO: consume state/daa
            operational_area_valid=True,  # TODO: GeoJSON polygon + altitude ceiling
            not_airborne=not s.in_air,
            dock_lid_open=None,           # TODO: consume dock state (Phase 7)
            fc_on_duty=self._fc_on_duty if self.mode is OperationalMode.PART_108 else None,
            mission_valid=ctx.mission_valid,
        )


def _iter_gate_flags(outcome: SafetyGateOutcome):
    """Yield (name, value) pairs for every gate flag; skips None (n/a) fields."""
    for field_name, value in outcome.model_dump().items():
        if isinstance(value, bool):
            yield field_name, value
