"""MAVSDK FlightMode <-> ArduCopter mode string mapping.

MAVSDK abstracts flight modes across autopilots; its enum is not 1:1 with
ArduCopter's custom_mode. Where MAVSDK doesn't distinguish modes that
ArduCopter treats separately (e.g., POSHOLD vs LOITER both look like HOLD),
we default to the closest ArduCopter mode that appears in the contract.

Full ArduCopter coverage requires raw HEARTBEAT.custom_mode via
mavlink_passthrough; that's a Phase 0.x refinement. For SITL MVP this is
sufficient — the main modes (GUIDED, AUTO, RTL, LAND, LOITER) map cleanly.
"""

from __future__ import annotations

from .models import ArduCopterMode

# MAVSDK FlightMode enum names (telemetry_pb2.FlightMode) -> ArduCopter mode.
# Keep as strings so this module doesn't need to import mavsdk at import time.
_MAVSDK_TO_ARDUCOPTER: dict[str, ArduCopterMode] = {
    "UNKNOWN": "UNKNOWN",
    "READY": "UNKNOWN",
    "TAKEOFF": "GUIDED",       # ArduCopter takeoff is a command under GUIDED/AUTO
    "HOLD": "LOITER",          # MAVSDK HOLD ~= Copter LOITER
    "MISSION": "AUTO",
    "RETURN_TO_LAUNCH": "RTL",
    "LAND": "LAND",
    "OFFBOARD": "GUIDED",      # MAVSDK OFFBOARD == Copter GUIDED (external control)
    "FOLLOW_ME": "FOLLOW",
    "MANUAL": "STABILIZE",
    "ALTCTL": "ALT_HOLD",
    "POSCTL": "POSHOLD",
    "ACRO": "ACRO",
    "STABILIZED": "STABILIZE",
    "RATTITUDE": "UNKNOWN",
}


def mavsdk_to_arducopter(mavsdk_mode_name: str) -> ArduCopterMode:
    """Map a MAVSDK FlightMode enum name to an ArduCopter mode string.

    Input should be the MAVSDK enum *name* (e.g. 'HOLD', 'MISSION'). MAVSDK's
    Python client exposes this via `str(flight_mode)` or `.name` depending on
    version. Unknown names fall back to 'UNKNOWN' rather than raising — flight
    modes are non-safety-critical display data.
    """
    return _MAVSDK_TO_ARDUCOPTER.get(mavsdk_mode_name, "UNKNOWN")
