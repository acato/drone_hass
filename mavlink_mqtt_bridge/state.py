"""Shared in-memory snapshot of the drone's latest state.

MAVSDK exposes each telemetry field as its own async iterator. Readers push
latest values here; publishers read atomically when building MQTT payloads.

No asyncio.Lock: single-writer-per-field + GIL + atomic attribute assignment
is sufficient for primitive values. If we add composite/list fields later,
revisit.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field

from .models import ArduCopterMode


@dataclass
class DroneState:
    # Position (from MAVSDK telemetry.position())
    lat: float | None = None
    lon: float | None = None
    abs_alt_m: float | None = None
    rel_alt_m: float | None = None

    # Heading (from MAVSDK telemetry.heading())
    heading_deg: float | None = None

    # Velocity NED (from MAVSDK telemetry.velocity_ned())
    vel_n_mps: float | None = None
    vel_e_mps: float | None = None
    vel_d_mps: float | None = None  # NED: positive = DOWN

    # Flight status
    armed: bool = False
    in_air: bool = False
    flight_mode: ArduCopterMode = "UNKNOWN"

    # GPS
    gps_fix_type: int = 0      # 0..6 per contract
    num_satellites: int = 0

    # Battery (MAVSDK reports NaN for unknown values; readers normalize to None)
    battery_voltage_v: float | None = None
    battery_charge_percent: float | None = None   # 0..100 per MAVSDK 2.x docstring
    battery_current_a: float | None = None        # positive = discharge (MAVSDK convention)
    battery_temperature_c: float | None = None
    battery_time_remaining_s: float | None = None

    # Internal — per-field last-update timestamps for freshness checks.
    _updated_at: dict[str, float] = field(default_factory=dict)

    def touch(self, field_name: str) -> None:
        self._updated_at[field_name] = time.time()

    def age(self, field_name: str) -> float | None:
        t = self._updated_at.get(field_name)
        return None if t is None else time.time() - t

    @property
    def ground_speed_mps(self) -> float | None:
        if self.vel_n_mps is None or self.vel_e_mps is None:
            return None
        return math.hypot(self.vel_n_mps, self.vel_e_mps)
