"""DroneState snapshot behavior."""

from __future__ import annotations

import math
import time

import pytest

from mavlink_mqtt_bridge.state import DroneState


def test_defaults_are_safe() -> None:
    s = DroneState()
    assert s.lat is None and s.lon is None
    assert s.armed is False and s.in_air is False
    assert s.flight_mode == "UNKNOWN"
    assert s.gps_fix_type == 0
    assert s.ground_speed_mps is None


def test_ground_speed_computed_from_ned() -> None:
    s = DroneState()
    s.vel_n_mps = 3.0
    s.vel_e_mps = 4.0
    assert s.ground_speed_mps == pytest.approx(5.0)


def test_ground_speed_none_when_component_missing() -> None:
    s = DroneState()
    s.vel_n_mps = 3.0
    # vel_e_mps still None
    assert s.ground_speed_mps is None


def test_touch_and_age_per_field() -> None:
    s = DroneState()
    assert s.age("position") is None
    s.touch("position")
    age = s.age("position")
    assert age is not None and age < 0.1


def test_age_is_monotonic() -> None:
    s = DroneState()
    s.touch("velocity")
    a1 = s.age("velocity")
    time.sleep(0.02)
    a2 = s.age("velocity")
    assert a1 is not None and a2 is not None
    assert a2 > a1
