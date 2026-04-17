"""Contract payload validation."""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from mavlink_mqtt_bridge.models import BatteryTelemetry, FlightTelemetry, PositionTelemetry


def test_flight_round_trip_matches_contract_fields() -> None:
    f = FlightTelemetry(
        lat=47.6, lon=-122.3, alt=25.0,
        heading=90.0, speed_x=1.2, speed_y=0.0, speed_z=0.5,
        ground_speed=1.2, flight_mode="GUIDED",
        armed=True, is_flying=True,
        gps_fix=3, satellite_count=14, timestamp=1729000000,
    )
    payload = json.loads(f.model_dump_json())
    # All required fields from contract §7.1 are present
    required = {
        "lat", "lon", "alt", "heading", "speed_x", "speed_y", "speed_z",
        "ground_speed", "flight_mode", "armed", "is_flying",
        "gps_fix", "satellite_count", "timestamp",
    }
    assert required.issubset(payload.keys())


def test_flight_rejects_out_of_range_lat() -> None:
    with pytest.raises(ValidationError):
        FlightTelemetry(
            lat=95.0, lon=0.0, alt=0.0, heading=0.0,
            speed_x=0.0, speed_y=0.0, speed_z=0.0, ground_speed=0.0,
            flight_mode="GUIDED", armed=False, is_flying=False,
            gps_fix=3, satellite_count=10, timestamp=0,
        )


def test_flight_rejects_unknown_mode() -> None:
    with pytest.raises(ValidationError):
        FlightTelemetry(
            lat=0.0, lon=0.0, alt=0.0, heading=None,
            speed_x=0.0, speed_y=0.0, speed_z=0.0, ground_speed=0.0,
            flight_mode="HELICOPTER_BARREL_ROLL",  # type: ignore[arg-type]
            armed=False, is_flying=False,
            gps_fix=0, satellite_count=0, timestamp=0,
        )


def test_flight_heading_accepts_null() -> None:
    f = FlightTelemetry(
        lat=0, lon=0, alt=0, heading=None,
        speed_x=0, speed_y=0, speed_z=0, ground_speed=0,
        flight_mode="UNKNOWN", armed=False, is_flying=False,
        gps_fix=0, satellite_count=0, timestamp=0,
    )
    assert json.loads(f.model_dump_json())["heading"] is None


def test_battery_accepts_all_nulls() -> None:
    b = BatteryTelemetry(
        charge_percent=None, voltage_mv=None, current_ma=None,
        temperature_c=None, remaining_mah=None, full_charge_mah=None,
        flight_time_remaining_s=None, timestamp=1,
    )
    parsed = json.loads(b.model_dump_json())
    assert parsed["timestamp"] == 1
    assert all(parsed[k] is None for k in (
        "charge_percent", "voltage_mv", "current_ma",
        "temperature_c", "remaining_mah", "full_charge_mah",
        "flight_time_remaining_s",
    ))


def test_position_requires_all_three() -> None:
    with pytest.raises(ValidationError):
        PositionTelemetry(lat=0.0, lon=0.0)  # type: ignore[call-arg]


def test_models_are_immutable() -> None:
    p = PositionTelemetry(lat=0, lon=0, alt=0)
    with pytest.raises(ValidationError):
        p.lat = 1.0  # type: ignore[misc]
