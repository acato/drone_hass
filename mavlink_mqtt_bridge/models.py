"""MQTT payload models matching docs/mavlink-mqtt-contract.md section 7.1.

Pydantic enforces the contract at publish time: shape, bounds, required fields.
If a field is unknown, models use None and the contract's nullable JSON Schema
still validates.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

ArduCopterMode = Literal[
    "STABILIZE", "ACRO", "ALT_HOLD", "AUTO", "GUIDED", "LOITER", "RTL", "CIRCLE",
    "LAND", "DRIFT", "SPORT", "FLIP", "AUTOTUNE", "POSHOLD", "BRAKE", "THROW",
    "AVOID_ADSB", "GUIDED_NOGPS", "SMART_RTL", "FLOWHOLD", "FOLLOW", "ZIGZAG",
    "SYSTEMID", "AUTOROTATE", "AUTO_RTL", "UNKNOWN",
]

ConnectionState = Literal["online", "offline", "degraded"]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class FlightTelemetry(_Strict):
    """`drone_hass/{drone_id}/telemetry/flight` — 1 Hz, QoS 0."""

    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    alt: float
    heading: float | None = Field(ge=0, le=360)
    speed_x: float
    speed_y: float
    speed_z: float  # positive = UP (opposite of MAVLink NED)
    ground_speed: float = Field(ge=0)
    flight_mode: ArduCopterMode
    armed: bool
    is_flying: bool
    gps_fix: int = Field(ge=0, le=6)
    satellite_count: int = Field(ge=0, le=255)
    timestamp: int


class BatteryTelemetry(_Strict):
    """`drone_hass/{drone_id}/telemetry/battery` — 0.2 Hz, QoS 0."""

    charge_percent: int | None = Field(ge=0, le=100)
    voltage_mv: int | None = Field(ge=0)
    current_ma: int | None
    temperature_c: float | None
    remaining_mah: int | None = Field(ge=0)
    full_charge_mah: int | None = Field(ge=0)
    flight_time_remaining_s: int | None = Field(ge=0)
    timestamp: int


class PositionTelemetry(_Strict):
    """`drone_hass/{drone_id}/telemetry/position` — 0.1 Hz, QoS 0."""

    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    alt: float


# ---------- Command request/response (contract §7.4 / §7.5) ----------


class CommandRequest(BaseModel):
    """Generic command request envelope — contract §7.4."""

    model_config = ConfigDict(extra="allow")  # action-specific params vary

    id: str = Field(min_length=1, description="Correlation ID (expected UUID)")
    params: dict | None = None
    timestamp: int | None = None


class TakeoffParams(_Strict):
    """Params for command/takeoff — contract §7.4."""

    altitude_m: float = Field(default=10.0, ge=2.0, le=37.0)


class CommandResponse(_Strict):
    """Command response envelope — contract §7.5."""

    id: str
    success: bool
    error: str | None = None
    data: dict | None = None


class AuthorizeFlightParams(_Strict):
    """Params for command/authorize_flight (Part 107 RPIC tap).

    Not in the original contract §2.x enumeration; added as the Part 107
    mechanism for delivering the time-limited, single-use authorization
    token the bridge requires before arm/takeoff (threat model §15).
    """

    rpic_id: str = Field(min_length=1, description="RPIC identifier (phone label, operator name, etc.)")
    valid_for_s: int = Field(default=120, ge=5, le=900)
    trigger: str = Field(default="manual", description="What triggered this authorization: 'alarm', 'manual', 'test'")


# ---------- Compliance (contract §7.7, §9.4) ----------


class ComplianceState(_Strict):
    """`drone_hass/{drone_id}/state/compliance` — retained, QoS 1."""

    mode: Literal["part_107", "part_108"]
    fc_on_duty: bool
    operational_area_valid: bool
    authorization_active: bool
    authorization_expires_at: int | None = None


class SafetyGateOutcome(_Strict):
    """Per-gate result for compliance/safety_gate events."""

    battery_ok: bool
    gps_ok: bool
    connection_ok: bool
    weather_ok: bool
    daa_healthy: bool
    operational_area_valid: bool
    not_airborne: bool
    dock_lid_open: bool | None = None
    fc_on_duty: bool | None = None   # Null in Part 107
    mission_valid: bool


class SafetyGateEvent(_Strict):
    """`drone_hass/{drone_id}/compliance/safety_gate` — QoS 1, contract §7.7."""

    event_type: Literal["safety_gate"] = "safety_gate"
    flight_id: str
    outcome: Literal["pass", "fail"]
    gates: SafetyGateOutcome
    failed_gates: list[str]
    timestamp: int
    # prev_hash deliberately omitted — Phase 3 hash chain adds it.
