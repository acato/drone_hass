"""MAVSDK -> ArduCopter flight mode mapping."""

from __future__ import annotations

import pytest

from mavlink_mqtt_bridge.flight_modes import mavsdk_to_arducopter


@pytest.mark.parametrize(
    "mavsdk_name,expected",
    [
        ("MISSION", "AUTO"),
        ("RETURN_TO_LAUNCH", "RTL"),
        ("LAND", "LAND"),
        ("HOLD", "LOITER"),
        ("OFFBOARD", "GUIDED"),
        ("ACRO", "ACRO"),
        ("STABILIZED", "STABILIZE"),
        ("POSCTL", "POSHOLD"),
        ("ALTCTL", "ALT_HOLD"),
        ("MANUAL", "STABILIZE"),
        ("FOLLOW_ME", "FOLLOW"),
    ],
)
def test_known_mappings(mavsdk_name: str, expected: str) -> None:
    assert mavsdk_to_arducopter(mavsdk_name) == expected


def test_unknown_defaults_to_UNKNOWN() -> None:
    assert mavsdk_to_arducopter("EXPERIMENTAL_WARP_DRIVE") == "UNKNOWN"
    assert mavsdk_to_arducopter("") == "UNKNOWN"


def test_readiness_states_are_unknown() -> None:
    # READY and RATTITUDE don't map to a stable ArduCopter mode
    assert mavsdk_to_arducopter("READY") == "UNKNOWN"
    assert mavsdk_to_arducopter("RATTITUDE") == "UNKNOWN"
