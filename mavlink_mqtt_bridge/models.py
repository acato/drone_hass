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
