"""Publisher payload shaping — verifies unit conversions & NED->ENU flip."""

from __future__ import annotations

import json
import math

from mavlink_mqtt_bridge.state import DroneState
from mavlink_mqtt_bridge.telemetry import (
    BatteryPublisher,
    FlightPublisher,
    PositionPublisher,
    _nan_to_none,
)


def test_nan_to_none_handles_mavsdk_unknown() -> None:
    assert _nan_to_none(math.nan) is None
    assert _nan_to_none(None) is None
    assert _nan_to_none(0.0) == 0.0
    assert _nan_to_none(-12.5) == -12.5


class _FakeClient:
    async def publish(self, *args, **kwargs):  # pragma: no cover
        raise AssertionError("unit tests should not publish")


def _new(cls, state: DroneState, **kw):
    return cls(
        mqtt=_FakeClient(),  # type: ignore[arg-type]
        base_topic="drone_hass/sitl1",
        state=state,
        name="test",
        topic_suffix="x",
        period_s=1.0,
        **kw,
    )


def test_flight_payload_none_when_no_position() -> None:
    pub = _new(FlightPublisher, DroneState())
    assert pub._build_payload() is None


def test_flight_payload_includes_contract_fields_and_flips_z() -> None:
    s = DroneState()
    s.lat, s.lon, s.rel_alt_m = 47.6, -122.3, 25.0
    s.heading_deg = 90.0
    s.vel_n_mps, s.vel_e_mps, s.vel_d_mps = 3.0, 4.0, -2.5  # rising at 2.5 m/s
    s.armed, s.in_air = True, True
    s.flight_mode = "GUIDED"
    s.gps_fix_type, s.num_satellites = 3, 14

    pub = _new(FlightPublisher, s)
    payload = json.loads(pub._build_payload())

    assert payload["lat"] == 47.6
    assert payload["alt"] == 25.0
    assert payload["speed_x"] == 3.0
    assert payload["speed_y"] == 4.0
    # NED down=-2.5 -> ENU up=+2.5
    assert payload["speed_z"] == 2.5
    assert payload["ground_speed"] == 5.0
    assert payload["flight_mode"] == "GUIDED"
    assert payload["armed"] is True
    assert payload["is_flying"] is True
    assert payload["gps_fix"] == 3
    assert payload["satellite_count"] == 14
    assert isinstance(payload["timestamp"], int)


def test_battery_converts_units_and_flips_current_sign() -> None:
    s = DroneState()
    s.battery_voltage_v = 16.8
    s.battery_charge_percent = 87.0           # MAVSDK 2.x is 0..100
    s.battery_current_a = 12.5                # positive = discharging in MAVSDK
    s.battery_temperature_c = 24.5
    s.battery_time_remaining_s = 420.0
    pub = _new(BatteryPublisher, s)
    payload = json.loads(pub._build_payload())
    assert payload["voltage_mv"] == 16800
    assert payload["charge_percent"] == 87
    assert payload["current_ma"] == -12500    # flipped: negative = discharging in contract
    assert payload["temperature_c"] == 24.5
    assert payload["flight_time_remaining_s"] == 420
    # Fields needing BATT_CAPACITY param read are null until implemented
    assert payload["remaining_mah"] is None
    assert payload["full_charge_mah"] is None


def test_battery_percent_100_stays_in_range() -> None:
    """Regression: MAVSDK 2.x remaining_percent is 0..100, not 0..1."""
    s = DroneState()
    s.battery_charge_percent = 100.0
    pub = _new(BatteryPublisher, s)
    payload = json.loads(pub._build_payload())
    assert payload["charge_percent"] == 100


def test_battery_handles_all_unknown() -> None:
    pub = _new(BatteryPublisher, DroneState())
    payload = json.loads(pub._build_payload())
    for k in ("charge_percent", "voltage_mv", "current_ma",
              "temperature_c", "flight_time_remaining_s"):
        assert payload[k] is None


def test_position_payload_matches_contract() -> None:
    s = DroneState()
    s.lat, s.lon, s.rel_alt_m = 47.6, -122.3, 25.0
    pub = _new(PositionPublisher, s)
    payload = json.loads(pub._build_payload())
    assert payload == {"lat": 47.6, "lon": -122.3, "alt": 25.0}
