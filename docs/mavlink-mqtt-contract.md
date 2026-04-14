# MAVLink-MQTT Bridge Contract Specification

> **Date:** 2026-04-14
> **Status:** Draft
> **Version:** 0.1.0
> **Companion to:** architecture.md v0.4.0

This document defines the exact contract between the MAVLink-MQTT bridge and Home Assistant. It specifies every MAVLink message mapping, every MQTT payload schema, and every state machine that governs the drone lifecycle.

---

## 1. MAVLink-to-MQTT Telemetry Mapping

### 1.1 `drone_hass/{drone_id}/telemetry/flight`

**Publish rate:** 1 Hz (idle/loiter), 2 Hz (during mission). QoS 0.

| MQTT Field | MAVLink Source | Message ID | Field(s) | Conversion |
|-----------|----------------|------------|----------|------------|
| `lat` | `GLOBAL_POSITION_INT` | #33 | `lat` | degE7 -> degrees: divide by 1e7 |
| `lon` | `GLOBAL_POSITION_INT` | #33 | `lon` | degE7 -> degrees: divide by 1e7 |
| `alt` | `GLOBAL_POSITION_INT` | #33 | `relative_alt` | mm -> m: divide by 1000 |
| `heading` | `GLOBAL_POSITION_INT` | #33 | `hdg` | cdeg -> deg: divide by 100. Value 65535 (UINT16_MAX) means unknown. |
| `speed_x` | `GLOBAL_POSITION_INT` | #33 | `vx` | cm/s -> m/s: divide by 100 |
| `speed_y` | `GLOBAL_POSITION_INT` | #33 | `vy` | cm/s -> m/s: divide by 100 |
| `speed_z` | `GLOBAL_POSITION_INT` | #33 | `vz` | cm/s -> m/s: divide by 100. Positive = DOWN in MAVLink NED frame; INVERT sign for MQTT (positive = up). |
| `ground_speed` | Computed | — | `sqrt(vx^2 + vy^2)` from GLOBAL_POSITION_INT | cm/s -> m/s after computation |
| `flight_mode` | `HEARTBEAT` | #0 | `custom_mode` | ArduCopter mode enum lookup (see Section 1.8) |
| `armed` | `HEARTBEAT` | #0 | `base_mode` | Bitfield: `base_mode & MAV_MODE_FLAG_SAFETY_ARMED (128)` != 0 |
| `is_flying` | Computed | — | See note below | — |
| `gps_fix` | `GPS_RAW_INT` | #24 | `fix_type` | Direct: 0=no GPS, 1=no fix, 2=2D, 3=3D, 4=DGPS, 5=RTK float, 6=RTK fixed |
| `satellite_count` | `GPS_RAW_INT` | #24 | `satellites_visible` | Direct (uint8) |
| `timestamp` | Bridge local | — | — | Unix epoch seconds (UTC) at publish time |

**`is_flying` computation:** True when `armed == true` AND `relative_alt > 500` (500mm = 0.5m threshold to filter ground-level noise). This is a bridge-side heuristic, not a MAVLink field.

**MAVLink request rates:** Use `SET_MESSAGE_INTERVAL` (msg #511) at bridge startup:
- `GLOBAL_POSITION_INT` (#33): request at 5 Hz (200000 us interval). Bridge downsamples to 1-2 Hz for MQTT.
- `HEARTBEAT` (#0): sent automatically at 1 Hz by ArduPilot. No interval change needed.
- `GPS_RAW_INT` (#24): request at 2 Hz (500000 us interval). Bridge publishes latest on each telemetry cycle.

**Why over-request from MAVLink:** The bridge receives at MAVLink rate but publishes to MQTT at a lower rate, always using the freshest value. This avoids aliasing and ensures the HA display is never stale by more than one MAVLink interval.

### 1.2 `drone_hass/{drone_id}/telemetry/battery`

**Publish rate:** 0.2 Hz (every 5 seconds). QoS 0.

| MQTT Field | MAVLink Source | Message ID | Field(s) | Conversion |
|-----------|----------------|------------|----------|------------|
| `charge_percent` | `BATTERY_STATUS` | #147 | `battery_remaining` | Direct (int8, 0-100). Value -1 means unknown. |
| `voltage_mv` | `BATTERY_STATUS` | #147 | `voltages[0]` | Direct (uint16, mV). Value UINT16_MAX = unknown. For multi-cell, `voltages[]` array has per-cell voltages; sum all non-UINT16_MAX entries for pack voltage. |
| `current_ma` | `BATTERY_STATUS` | #147 | `current_battery` | cA -> mA: multiply by 10. Value -1 = unknown. Sign convention: positive = discharge in MAVLink; NEGATE for MQTT (negative = discharge, positive = charge). |
| `temperature_c` | `BATTERY_STATUS` | #147 | `temperature` | cdegC -> degC: divide by 100. Value INT16_MAX = unknown. |
| `remaining_mah` | `BATTERY_STATUS` | #147 | `current_consumed` | Compute: `full_charge_mah - current_consumed`. `current_consumed` is mAh consumed since full charge. |
| `full_charge_mah` | ArduPilot parameter | — | `BATT_CAPACITY` param | Fetched once at startup via PARAM_REQUEST_READ. Static value. |
| `flight_time_remaining_s` | `BATTERY_STATUS` | #147 | `time_remaining` | Direct (uint32, seconds). Value 0 = unknown. ArduPilot populates this in ArduCopter 4.4+. |
| `timestamp` | Bridge local | — | — | Unix epoch seconds (UTC) |

**MAVLink request rate:** `BATTERY_STATUS` (#147): request at 1 Hz (1000000 us). Bridge downsamples to 0.2 Hz.

**Pack voltage computation detail:** ArduPilot sends per-cell voltages in `voltages[0..9]` (up to 10 cells) and `voltages_ext[0..3]` (4 more cells, MAVLink v2 extension). For a 4S pack, sum `voltages[0..3]`. Any cell reading UINT16_MAX (65535) should be excluded from the sum.

### 1.3 `drone_hass/{drone_id}/telemetry/gimbal`

**Publish rate:** 1 Hz. QoS 0.

| MQTT Field | MAVLink Source | Message ID | Field(s) | Conversion |
|-----------|----------------|------------|----------|------------|
| `pitch` | `GIMBAL_DEVICE_ATTITUDE_STATUS` | #285 | `q` (quaternion) | Convert quaternion [w,x,y,z] to Euler angles; extract pitch. Degrees. |
| `roll` | `GIMBAL_DEVICE_ATTITUDE_STATUS` | #285 | `q` (quaternion) | Extract roll from quaternion. Degrees. |
| `yaw` | `GIMBAL_DEVICE_ATTITUDE_STATUS` | #285 | `q` (quaternion) | Extract yaw from quaternion. Degrees (0-360). |
| `mode` | `GIMBAL_DEVICE_ATTITUDE_STATUS` | #285 | `flags` | Bitfield: `GIMBAL_DEVICE_FLAGS_YAW_LOCK (4)` set -> "YAW_LOCK", else "YAW_FOLLOW" |

**Fallback:** If no `GIMBAL_DEVICE_ATTITUDE_STATUS` is received (gimbal does not support MAVLink gimbal protocol v2), fall back to `MOUNT_ORIENTATION` (#265, deprecated but still emitted by ArduPilot with `MNT_TYPE` configured):
- `pitch` = `MOUNT_ORIENTATION.pitch` (cdeg -> deg: /100)
- `roll` = `MOUNT_ORIENTATION.roll` (cdeg -> deg: /100)
- `yaw` = `MOUNT_ORIENTATION.yaw_absolute` (cdeg -> deg: /100)
- `mode` = "UNKNOWN"

**If neither message available:** Publish `{"pitch": null, "roll": null, "yaw": null, "mode": "NOT_AVAILABLE"}` so HA entities show unavailable rather than stale data.

**MAVLink request rate:** `GIMBAL_DEVICE_ATTITUDE_STATUS` (#285): request at 2 Hz (500000 us).

### 1.4 `drone_hass/{drone_id}/telemetry/camera`

**Publish rate:** On change only (event-driven). QoS 1.

| MQTT Field | MAVLink Source | Message ID | Field(s) | Conversion |
|-----------|----------------|------------|----------|------------|
| `is_recording` | `CAMERA_CAPTURE_STATUS` | #262 | `video_status` | 0 = idle (false), 1 = recording (true), 2 = error (false + flag) |
| `recording_time_s` | `CAMERA_CAPTURE_STATUS` | #262 | `recording_time_s` | Direct (float, seconds). Only meaningful when `video_status == 1`. |
| `storage_remaining_mb` | `STORAGE_INFORMATION` | #261 | `available_capacity` | Direct (float, MiB). Request periodically. |

**Camera protocol detail:** The MAVLink Camera Protocol v2 requires an initial handshake:
1. Send `MAV_CMD_REQUEST_MESSAGE` (#512) with param1=`CAMERA_INFORMATION` (msg #259) to discover camera capabilities
2. Subscribe to `CAMERA_CAPTURE_STATUS` (#262) — ArduPilot streams this when a camera is configured
3. Periodically request `STORAGE_INFORMATION` (#261) via `MAV_CMD_REQUEST_MESSAGE`

**Important:** Many companion-computer camera setups (GStreamer pipeline) do NOT speak MAVLink camera protocol. In that case, camera state is managed bridge-side: the bridge tracks whether it issued start/stop recording commands and reports accordingly. `storage_remaining_mb` comes from the companion computer's filesystem (queried via SSH or a sidecar API, not MAVLink).

**MAVLink request rate:** `CAMERA_CAPTURE_STATUS` (#262): request at 0.5 Hz (2000000 us). `STORAGE_INFORMATION` (#261): request once every 30 seconds.

### 1.5 `drone_hass/{drone_id}/telemetry/signal`

**Publish rate:** 1 Hz. QoS 0.

| MQTT Field | MAVLink Source | Message ID | Field(s) | Conversion |
|-----------|----------------|------------|----------|------------|
| `rssi` | `RADIO_STATUS` | #109 | `rssi` | uint8, 0-254 (ArduPilot-specific scaling). Convert: `(rssi / 1.9) - 127` for approximate dBm. Or publish raw and note the unit. See note. |
| `remote_rssi` | `RADIO_STATUS` | #109 | `remrssi` | Same conversion as `rssi` |
| `noise` | `RADIO_STATUS` | #109 | `noise` | uint8, raw noise floor reading |

**Note on RSSI source:** `RADIO_STATUS` (#109) is emitted by SiK-firmware radios (the 915 MHz backup link). If the primary C2 link is WiFi, `RADIO_STATUS` represents the backup link signal, not the primary.

For WiFi RSSI: the bridge should query the companion computer's WiFi interface (e.g., `iwconfig wlan0` or `/proc/net/wireless`) and merge that into the signal topic. This is NOT a MAVLink message -- it's a bridge-side measurement.

**Recommended MQTT payload extension for dual-link:**

```json
{
  "primary_link": "wifi",
  "primary_rssi_dbm": -62,
  "backup_link": "sik_915mhz",
  "backup_rssi_raw": 180,
  "backup_remote_rssi_raw": 165,
  "backup_noise_raw": 40
}
```

**MAVLink request rate:** `RADIO_STATUS` (#109) is autonomously emitted by the radio hardware at ~1 Hz. No interval request needed.

### 1.6 `drone_hass/{drone_id}/telemetry/position`

**Publish rate:** 0.1 Hz (every 10 seconds). QoS 0. Purpose: HA device_tracker without recorder churn.

| MQTT Field | MAVLink Source | Message ID | Field(s) | Conversion |
|-----------|----------------|------------|----------|------------|
| `lat` | `GLOBAL_POSITION_INT` | #33 | `lat` | degE7 -> degrees: divide by 1e7 |
| `lon` | `GLOBAL_POSITION_INT` | #33 | `lon` | degE7 -> degrees: divide by 1e7 |
| `alt` | `GLOBAL_POSITION_INT` | #33 | `relative_alt` | mm -> m: divide by 1000 |

Same source as `telemetry/flight` but published at 1/10th the rate. The bridge reuses the latest `GLOBAL_POSITION_INT` it already has in memory.

### 1.7 DAA Topics

#### `drone_hass/{drone_id}/daa/traffic`

**Publish rate:** On detection, per contact, max 5 Hz aggregate. QoS 1.

| MQTT Field | MAVLink Source | Message ID | Field(s) | Conversion |
|-----------|----------------|------------|----------|------------|
| `icao` | `ADSB_VEHICLE` | #246 | `ICAO_address` | uint32 -> hex string, zero-padded 6 chars (e.g., "A12345") |
| `callsign` | `ADSB_VEHICLE` | #246 | `callsign` | char[9], trim trailing spaces/nulls |
| `lat` | `ADSB_VEHICLE` | #246 | `lat` | degE7 -> degrees: divide by 1e7 |
| `lon` | `ADSB_VEHICLE` | #246 | `lon` | degE7 -> degrees: divide by 1e7 |
| `altitude_m` | `ADSB_VEHICLE` | #246 | `altitude` | mm -> m: divide by 1000. This is AMSL altitude. |
| `heading` | `ADSB_VEHICLE` | #246 | `heading` | cdeg -> deg: divide by 100 |
| `ground_speed_mps` | `ADSB_VEHICLE` | #246 | `hor_velocity` | cm/s -> m/s: divide by 100 |
| `vertical_speed_mps` | `ADSB_VEHICLE` | #246 | `ver_velocity` | cm/s -> m/s: divide by 100. Positive = UP. |
| `squawk` | `ADSB_VEHICLE` | #246 | `squawk` | uint16, direct |
| `altitude_type` | `ADSB_VEHICLE` | #246 | `altitude_type` | 0 = pressure (QNH), 1 = geometric (GPS). Important for collision geometry. |
| `emitter_type` | `ADSB_VEHICLE` | #246 | `emitter_type` | Enum: 0=no info, 1=light, 2=small, ... 14=UAV, etc. |
| `flags` | `ADSB_VEHICLE` | #246 | `flags` | Bitfield indicating which fields are valid (ADSB_FLAGS enum) |
| `distance_m` | Computed | — | Haversine from drone position to traffic position | Use drone's `GLOBAL_POSITION_INT` lat/lon and traffic lat/lon |
| `threat_level` | Computed | — | See Section 5 (DAA state machine) | Bridge computes from distance, closure rate, altitude separation |
| `timestamp` | Bridge local | — | — | Unix epoch seconds (UTC) |

**MAVLink note:** `ADSB_VEHICLE` (#246) is emitted by ArduPilot when the ADS-B In receiver (connected via serial) reports traffic. ArduPilot parses the receiver's GDL90 or MAVLink output and emits this message. The `ADSB_VEHICLE` message rate is driven by traffic volume, not a request interval.

**Validity flags:** The `flags` field is critical. Before using any field, check its corresponding flag:
- `ADSB_FLAGS_VALID_COORDS (1)` — lat/lon valid
- `ADSB_FLAGS_VALID_ALTITUDE (2)` — altitude valid
- `ADSB_FLAGS_VALID_HEADING (4)` — heading valid
- `ADSB_FLAGS_VALID_VELOCITY (8)` — horizontal velocity valid
- `ADSB_FLAGS_VALID_CALLSIGN (16)` — callsign valid
- `ADSB_FLAGS_VALID_SQUAWK (32)` — squawk valid

If a flag is not set, publish the corresponding MQTT field as `null`.

#### `drone_hass/{drone_id}/daa/avoidance`

**Publish rate:** On avoidance event. QoS 1.

This topic is NOT directly sourced from a single MAVLink message. It is synthesized by the bridge from multiple signals:

| MQTT Field | Source | Detail |
|-----------|--------|--------|
| `trigger_icao` | Bridge state | ICAO of the traffic contact that triggered avoidance |
| `action` | `STATUSTEXT` (#253) + flight mode change | ArduPilot's AP_Avoidance logs actions via STATUSTEXT (e.g., "Avoidance: climbing"). The bridge also detects mode changes to AVOID_ADSB mode. |
| `original_alt` | Bridge state | Drone altitude (from `GLOBAL_POSITION_INT`) at moment avoidance triggered |
| `new_alt` | `GLOBAL_POSITION_INT` | Drone altitude after avoidance maneuver stabilizes |
| `original_position` | Bridge state | Drone lat/lon at avoidance trigger |
| `new_position` | `GLOBAL_POSITION_INT` | Drone lat/lon after avoidance maneuver |
| `threat_distance_m` | Computed | Distance to triggering traffic at the moment of avoidance |
| `timestamp` | Bridge local | Unix epoch seconds (UTC) |

**ArduPilot AP_Avoidance internals:** ArduPilot evaluates ADS-B threats using these parameters:
- `AVD_ENABLE` — enable/disable avoidance
- `AVD_F_ACTION` — action on fail (0=none, 1=report, 2=climb/descend, 3=move horizontally, 4=move perpendicular, 5=RTL, 6=hover)
- `AVD_F_DIST` — distance threshold for fail (m)
- `AVD_F_TIME` — time-to-closest-point threshold for fail (s)
- `AVD_W_ACTION` — action on warn
- `AVD_W_DIST` / `AVD_W_TIME` — warning thresholds

The flight mode changes to `AVOID_ADSB` (mode 19 in ArduCopter) when avoidance is active.

### 1.8 ArduCopter Flight Mode Mapping

The `custom_mode` field in `HEARTBEAT` maps to ArduCopter modes. The bridge must translate these numeric IDs to the string names published in MQTT.

| custom_mode | ArduCopter Mode | MQTT String |
|-------------|-----------------|-------------|
| 0 | STABILIZE | `"STABILIZE"` |
| 1 | ACRO | `"ACRO"` |
| 2 | ALT_HOLD | `"ALT_HOLD"` |
| 3 | AUTO | `"AUTO"` |
| 4 | GUIDED | `"GUIDED"` |
| 5 | LOITER | `"LOITER"` |
| 6 | RTL | `"RTL"` |
| 7 | CIRCLE | `"CIRCLE"` |
| 9 | LAND | `"LAND"` |
| 11 | DRIFT | `"DRIFT"` |
| 13 | SPORT | `"SPORT"` |
| 14 | FLIP | `"FLIP"` |
| 15 | AUTOTUNE | `"AUTOTUNE"` |
| 16 | POSHOLD | `"POSHOLD"` |
| 17 | BRAKE | `"BRAKE"` |
| 18 | THROW | `"THROW"` |
| 19 | AVOID_ADSB | `"AVOID_ADSB"` |
| 20 | GUIDED_NOGPS | `"GUIDED_NOGPS"` |
| 21 | SMART_RTL | `"SMART_RTL"` |
| 22 | FLOWHOLD | `"FLOWHOLD"` |
| 23 | FOLLOW | `"FOLLOW"` |
| 24 | ZIGZAG | `"ZIGZAG"` |
| 25 | SYSTEMID | `"SYSTEMID"` |
| 26 | AUTOROTATE | `"AUTOROTATE"` |
| 27 | AUTO_RTL | `"AUTO_RTL"` |

**HEARTBEAT decoding detail:**
- `type` field must be `MAV_TYPE_QUADROTOR (2)` (or appropriate type for the airframe)
- `autopilot` field must be `MAV_AUTOPILOT_ARDUPILOTMEGA (3)`
- `system_status` field: `MAV_STATE_STANDBY (3)` = disarmed, `MAV_STATE_ACTIVE (4)` = armed, `MAV_STATE_CRITICAL (5)` = failsafe, `MAV_STATE_EMERGENCY (6)` = emergency

---

## 2. MQTT Command-to-MAVLink Mapping

### 2.1 General Command Pattern

Every command follows request/response over MQTT:

```
HA publishes:  drone_hass/{drone_id}/command/{action}
               {"id": "uuid-correlation-id", "params": {...}}

Bridge publishes: drone_hass/{drone_id}/command/{action}/response
                  {"id": "uuid-correlation-id", "success": true/false, "error": null/"message", "data": {...}}
```

The bridge MUST:
1. Validate the command payload against the JSON schema (Section 7)
2. Check preconditions specific to the command
3. Translate to MAVLink command(s)
4. Wait for MAVLink acknowledgment (`COMMAND_ACK` #77)
5. Publish MQTT response with the correlation ID
6. Timeout after the specified duration if no ACK received

### 2.2 `arm`

**MAVLink sequence:**
1. Send `COMMAND_LONG` (#76):
   - `command`: `MAV_CMD_COMPONENT_ARM_DISARM` (400)
   - `param1`: 1 (arm)
   - `param2`: 0 (normal arm; set to 21196 for force-arm, which the bridge MUST NEVER use)
   - `target_system`: aircraft system ID
   - `target_component`: `MAV_COMP_ID_AUTOPILOT` (1)
2. Wait for `COMMAND_ACK` (#77) with `command` = 400

**Preconditions (bridge-enforced):**
- Connection state is `online`
- Aircraft is not already armed (`armed == false`)
- GPS fix >= 3D (`gps_fix >= 3`)
- ComplianceGate has authorized a flight (active authorization token exists)

**Timeout:** 5 seconds

**Error mapping:**

| MAV_RESULT | MQTT Error |
|-----------|------------|
| `MAV_RESULT_ACCEPTED (0)` | `success: true` |
| `MAV_RESULT_DENIED (1)` | `"error": "arm_denied: pre-arm checks failed"` |
| `MAV_RESULT_FAILED (4)` | `"error": "arm_failed: command execution failed"` |
| `MAV_RESULT_TEMPORARILY_REJECTED (1)` | `"error": "arm_temporarily_rejected"` |
| Timeout | `"error": "arm_timeout: no response from flight controller"` |

**Note:** ArduPilot has extensive pre-arm checks (GPS, compass, accelerometer, battery, etc.). If arming is denied, the reason is usually in a `STATUSTEXT` (#253) message emitted just before or after the ACK. The bridge should capture the most recent STATUSTEXT and include it in the error response data:

```json
{"id": "...", "success": false, "error": "arm_denied", "data": {"reason": "PreArm: GPS not healthy"}}
```

### 2.3 `takeoff`

**MAVLink sequence:**
1. If not armed, execute `arm` sequence first (Section 2.2)
2. Send `COMMAND_LONG` (#76):
   - `command`: `MAV_CMD_NAV_TAKEOFF` (22)
   - `param7`: target altitude in meters (relative to home, from bridge config; default 10m for hover)
   - All other params: 0
3. Wait for `COMMAND_ACK` (#77) with `command` = 22
4. ArduPilot switches to GUIDED mode and climbs to target altitude

**Preconditions:**
- Connection state is `online`
- ComplianceGate authorization active
- Operational area validated
- `is_flying == false`
- Dock lid is open (bridge checks `dock_lid_open` state from MQTT if dock integration is enabled)

**Timeout:** 5 seconds for ACK. The bridge also monitors altitude to confirm takeoff within 30 seconds.

**Error mapping:** Same as arm, plus:

| Condition | MQTT Error |
|----------|------------|
| Already airborne | `"error": "already_airborne"` |
| Dock lid not open | `"error": "dock_lid_not_open"` |
| No authorization | `"error": "not_authorized: ComplianceGate has not authorized flight"` |

### 2.4 `land`

**MAVLink sequence:**
1. Send `COMMAND_LONG` (#76):
   - `command`: `MAV_CMD_NAV_LAND` (21)
   - `param5`: latitude (0 = current position)
   - `param6`: longitude (0 = current position)
   - `param7`: altitude (0 = ground level)
2. Wait for `COMMAND_ACK`
3. ArduPilot enters LAND mode

**Preconditions:**
- `is_flying == true`

**Timeout:** 5 seconds for ACK.

### 2.5 `return_to_home`

**MAVLink sequence:**
1. Send `COMMAND_LONG` (#76):
   - `command`: `MAV_CMD_NAV_RETURN_TO_LAUNCH` (20)
   - All params: 0
2. Wait for `COMMAND_ACK`
3. ArduPilot enters RTL mode, climbs to RTL_ALT, flies to home, descends, lands

**Preconditions:**
- `is_flying == true`

**Timeout:** 5 seconds for ACK.

**Note:** RTL altitude is controlled by the ArduPilot parameter `RTL_ALT` (cm). This should be set during aircraft configuration to a value above the tallest obstacles (recommend 35m / 3500cm for this property with 100ft trees).

### 2.6 `cancel_rth`

**MAVLink sequence:**
1. Send `COMMAND_LONG` (#76):
   - `command`: `MAV_CMD_DO_SET_MODE` (176)
   - `param1`: `MAV_MODE_FLAG_CUSTOM_MODE_ENABLED` (1)
   - `param2`: 5 (LOITER mode)
2. Wait for `COMMAND_ACK`
3. Verify mode change via next `HEARTBEAT`

**Preconditions:**
- Current flight_mode is `"RTL"` or `"SMART_RTL"`
- `is_flying == true`

**Timeout:** 5 seconds

### 2.7 `execute_mission`

This is the most complex command. It involves the full MAVLink mission protocol handshake.

**Params:** `{"mission_id": "full_perimeter"}`

**Full MAVLink sequence:**

```
Phase 1: Retrieve and validate mission definition
  1. Bridge looks up mission_id from its retained mission store
     (loaded from drone_hass/{drone_id}/missions/{mission_id})
  2. Validate all waypoints within operational area (GeoJSON polygon + altitude ceiling)
  3. Validate speed limits, altitude limits
  4. Check ComplianceGate authorization

Phase 2: Translate JSON waypoints to MAVLink mission items
  For each waypoint, create one or more MAV_CMD items:
    - NAV waypoint:      MAV_CMD_NAV_WAYPOINT (16) or MAV_CMD_NAV_SPLINE_WAYPOINT (82)
    - Speed change:      MAV_CMD_DO_CHANGE_SPEED (178)
    - Gimbal pitch:      MAV_CMD_DO_MOUNT_CONTROL (205)
    - Stay/loiter:       MAV_CMD_NAV_LOITER_TIME (19) — for waypoints with stay_ms > 0
    - Take photo:        MAV_CMD_IMAGE_START_CAPTURE (2000)
    - Start recording:   MAV_CMD_VIDEO_START_CAPTURE (2500)
    - Stop recording:    MAV_CMD_VIDEO_STOP_CAPTURE (2501)
    - Final RTL:         MAV_CMD_NAV_RETURN_TO_LAUNCH (20)

Phase 3: Upload via MAVLink mission protocol
  Bridge -> FC:  MISSION_COUNT (#44)
                   target_system, target_component,
                   count = total_mission_items,
                   mission_type = MAV_MISSION_TYPE_MISSION (0)

  FC -> Bridge:  MISSION_REQUEST_INT (#51)
                   seq = 0 (requests first item)

  Bridge -> FC:  MISSION_ITEM_INT (#73)
                   seq = 0,
                   frame = MAV_FRAME_GLOBAL_RELATIVE_ALT_INT (6),
                   command = MAV_CMD_NAV_WAYPOINT (16),
                   x = lat_degE7, y = lon_degE7, z = alt_m,
                   param1 = hold_time_s, param2 = acceptance_radius_m,
                   param3 = pass_radius (0 = fly through),
                   param4 = yaw_deg (NaN = auto),
                   autocontinue = 1,
                   mission_type = 0

  FC -> Bridge:  MISSION_REQUEST_INT (#51)
                   seq = 1

  ... (repeat for each mission item) ...

  FC -> Bridge:  MISSION_ACK (#47)
                   type = MAV_MISSION_ACCEPTED (0)

Phase 4: Start mission
  Bridge -> FC:  Set mode to AUTO:
                   COMMAND_LONG: MAV_CMD_DO_SET_MODE (176)
                   param1 = MAV_MODE_FLAG_CUSTOM_MODE_ENABLED (1)
                   param2 = 3 (AUTO mode)

  OR arm + takeoff first if not airborne (see Section 2.3), then:
  Bridge -> FC:  COMMAND_LONG: MAV_CMD_MISSION_START (300)
                   param1 = 0 (first item), param2 = 0 (last item, 0 = all)

Phase 5: Monitor execution
  FC -> Bridge:  MISSION_CURRENT (#42) — current waypoint index, continuously
  FC -> Bridge:  MISSION_ITEM_REACHED (#46) — emitted when each waypoint is reached

  Bridge publishes mission progress to MQTT state/mission on each update.
```

**Mission item translation details:**

| JSON `flight_path_mode` | MAVLink Command |
|------------------------|----------------|
| `"STRAIGHT"` | `MAV_CMD_NAV_WAYPOINT` (16) |
| `"SPLINE"` | `MAV_CMD_NAV_SPLINE_WAYPOINT` (82) |

| JSON waypoint action | MAVLink DO command inserted BEFORE the next NAV command |
|---------------------|-------------------------------------------------------|
| `"TAKE_PHOTO"` | `MAV_CMD_IMAGE_START_CAPTURE` (2000): param3=1 (single image) |
| `"START_RECORD"` | `MAV_CMD_VIDEO_START_CAPTURE` (2500) |
| `"STOP_RECORD"` | `MAV_CMD_VIDEO_STOP_CAPTURE` (2501) |

| JSON `finish_action` | Final mission item |
|---------------------|-------------------|
| `"RTL"` | `MAV_CMD_NAV_RETURN_TO_LAUNCH` (20) |
| `"LAND"` | `MAV_CMD_NAV_LAND` (21) at last waypoint position |
| `"HOVER"` | `MAV_CMD_NAV_LOITER_UNLIM` (17) at last waypoint |

**Waypoint altitude:** JSON `alt` is in meters above takeoff (relative). The MAVLink frame `MAV_FRAME_GLOBAL_RELATIVE_ALT_INT` (6) means z is meters relative to home position, which matches.

**Waypoint coordinates:** JSON `lat`/`lon` are in decimal degrees. MAVLink `MISSION_ITEM_INT` uses `x`/`y` in degE7. Multiply by 1e7 and round to int32.

**Speed per waypoint:** If a waypoint specifies `speed_mps` different from the mission default, insert a `MAV_CMD_DO_CHANGE_SPEED` (178) DO command before the NAV command:
- `param1`: 1 (ground speed)
- `param2`: speed in m/s
- `param3`: -1 (no throttle change)

**Gimbal per waypoint:** If `gimbal_pitch` is specified, insert `MAV_CMD_DO_MOUNT_CONTROL` (205):
- `param1`: pitch in degrees (negative = down)
- `param2`: 0 (roll)
- `param3`: 0 (yaw, or specific value)
- `param7`: `MAV_MOUNT_MODE_MAVLINK_TARGETING` (2)

**Mission upload error mapping:**

| MISSION_ACK type | MQTT Error |
|-----------------|------------|
| `MAV_MISSION_ACCEPTED (0)` | Upload success, proceed to start |
| `MAV_MISSION_ERROR (1)` | `"error": "mission_upload_error"` |
| `MAV_MISSION_UNSUPPORTED (2)` | `"error": "mission_unsupported_command"` |
| `MAV_MISSION_NO_SPACE (3)` | `"error": "mission_no_space: too many waypoints"` |
| `MAV_MISSION_INVALID (4)` | `"error": "mission_invalid_parameters"` |
| `MAV_MISSION_INVALID_SEQUENCE (6)` | `"error": "mission_sequence_error"` (retry upload) |
| Timeout (no ACK within 10s) | `"error": "mission_upload_timeout"` |
| Bridge validation failure | `"error": "waypoint_outside_operational_area: wp N at lat,lon"` |

**Timeout:** 10 seconds for the entire upload handshake. 5 seconds for each individual MISSION_REQUEST_INT. 5 seconds for mission start ACK.

**Preconditions:**
- Connection state is `online`
- ComplianceGate authorization active
- Mission definition exists for `mission_id`
- All waypoints within operational area
- Battery above minimum threshold (configurable, default 30%)
- DAA system healthy (in Part 108 mode)
- No mission currently executing (`mission.status` is `idle` or `completed` or `error`)

### 2.8 `pause_mission`

**MAVLink sequence:**
1. Send `COMMAND_LONG` (#76):
   - `command`: `MAV_CMD_DO_SET_MODE` (176)
   - `param1`: `MAV_MODE_FLAG_CUSTOM_MODE_ENABLED` (1)
   - `param2`: 17 (BRAKE mode — stops immediately and holds position)
2. Wait for `COMMAND_ACK`
3. Bridge records current mission waypoint index for resume

**Alternative if BRAKE mode unavailable:** Set mode to 5 (LOITER).

**Preconditions:**
- `mission.status == "executing"`

**Timeout:** 5 seconds

### 2.9 `resume_mission`

**MAVLink sequence:**
1. Send `COMMAND_LONG` (#76):
   - `command`: `MAV_CMD_DO_SET_MODE` (176)
   - `param1`: `MAV_MODE_FLAG_CUSTOM_MODE_ENABLED` (1)
   - `param2`: 3 (AUTO mode)
2. Wait for `COMMAND_ACK`
3. ArduPilot resumes mission from current waypoint

**Preconditions:**
- `mission.status == "paused"`
- ComplianceGate authorization still valid

**Timeout:** 5 seconds

### 2.10 `stop_mission`

**MAVLink sequence:**
1. Send `COMMAND_LONG` (#76):
   - `command`: `MAV_CMD_DO_SET_MODE` (176)
   - `param1`: `MAV_MODE_FLAG_CUSTOM_MODE_ENABLED` (1)
   - `param2`: 5 (LOITER mode — hold position)
2. Wait for `COMMAND_ACK`
3. Bridge updates mission state to `"aborted"`
4. **Does NOT auto-RTL** — the operator decides next action (RTL, land, etc.)

**Preconditions:**
- `mission.status` is `"executing"` or `"paused"`

**Timeout:** 5 seconds

### 2.11 `take_photo`

**MAVLink sequence:**
1. Send `COMMAND_LONG` (#76):
   - `command`: `MAV_CMD_IMAGE_START_CAPTURE` (2000)
   - `param1`: 0 (camera ID, 0 = all)
   - `param2`: 0 (interval, 0 = single capture)
   - `param3`: 1 (total images)
2. Wait for `COMMAND_ACK`

**Preconditions:**
- Connection state is `online`
- Camera available (received `CAMERA_INFORMATION` at startup)

**Timeout:** 5 seconds

### 2.12 `start_recording`

**MAVLink sequence:**
1. Send `COMMAND_LONG` (#76):
   - `command`: `MAV_CMD_VIDEO_START_CAPTURE` (2500)
   - `param1`: 0 (camera ID)
   - `param2`: 0 (status frequency Hz, 0 = default)
2. Wait for `COMMAND_ACK`

**Preconditions:** Same as `take_photo`.

**Timeout:** 5 seconds

### 2.13 `stop_recording`

**MAVLink sequence:**
1. Send `COMMAND_LONG` (#76):
   - `command`: `MAV_CMD_VIDEO_STOP_CAPTURE` (2501)
   - `param1`: 0 (camera ID)
2. Wait for `COMMAND_ACK`

**Timeout:** 5 seconds

### 2.14 `set_gimbal`

**Params:** `{"pitch": -45.0, "mode": "YAW_FOLLOW"}`

**MAVLink sequence:**
1. Send `COMMAND_LONG` (#76):
   - `command`: `MAV_CMD_DO_MOUNT_CONTROL` (205)
   - `param1`: pitch (degrees, negative = down)
   - `param2`: 0 (roll)
   - `param3`: 0 (yaw)
   - `param7`: `MAV_MOUNT_MODE_MAVLINK_TARGETING` (2)
2. Wait for `COMMAND_ACK`

**If gimbal supports MAVLink gimbal protocol v2:**
1. Send `GIMBAL_MANAGER_SET_PITCHYAW` (#287):
   - `pitch`: radians (convert degrees to radians)
   - `yaw`: radians
   - `flags`: `GIMBAL_MANAGER_FLAGS_YAW_LOCK (4)` if mode is `"YAW_LOCK"`, else 0
   - `gimbal_device_id`: 0 (all)

**Preconditions:** Connection state is `online`.

**Timeout:** 5 seconds

### 2.15 `reset_gimbal`

Same as `set_gimbal` with pitch=0, mode="YAW_FOLLOW".

### 2.16 `start_stream` / `stop_stream`

These are NOT MAVLink commands. The bridge manages the RTSP stream pipeline:

- `start_stream`: Bridge signals the companion computer (or camera) to begin streaming, then publishes the RTSP URL to `state/stream`. If using Siyi A8 Mini, the camera streams RTSP continuously; this command may just tell go2rtc to begin pulling.
- `stop_stream`: Bridge signals the companion to stop the stream. Updates `state/stream`.

**MQTT response includes:** `{"rtsp_url": "rtsp://10.0.0.50:8554/drone"}`

### 2.17 `set_home`

**Params:** `{"lat": 47.6062, "lon": -122.3321}`

**MAVLink sequence:**
1. Send `COMMAND_LONG` (#76):
   - `command`: `MAV_CMD_DO_SET_HOME` (179)
   - `param1`: 0 (use specified location, not current)
   - `param5`: latitude (degrees)
   - `param6`: longitude (degrees)
   - `param7`: altitude (0 = use current altitude)
2. Wait for `COMMAND_ACK`

**Preconditions:**
- Home location must be within operational area
- Aircraft should be on the ground (setting home while airborne is valid but unusual)

**Timeout:** 5 seconds

### 2.18 `set_operational_mode`

**Params:** `{"mode": "part_107"}`  or `{"mode": "part_108"}`

This is a bridge-internal command. No MAVLink is involved.

The bridge:
1. Validates the mode value
2. Updates its `ComplianceGate` configuration
3. Publishes updated `state/compliance`
4. Logs compliance event

### 2.19 `set_fc_on_duty`

**Params:** `{"on_duty": true, "fc_id": "alessandro"}`

Bridge-internal command. No MAVLink.

The bridge:
1. Updates Flight Coordinator status
2. Publishes updated `state/compliance`
3. Logs compliance event (personnel log)

---

## 3. Drone Lifecycle State Machine

### 3.1 States

```
DISCONNECTED
  │
  ├── (heartbeat received) ──► CONNECTED_DISARMED
  │                              │
  │                              ├── (pre-flight checks pass + authorization) ──► PREFLIGHT_CHECKS
  │                              │                                                   │
  │                              │                                                   ├── (all checks pass) ──► ARMING
  │                              │                                                   │                          │
  │                              │                                                   │                          ├── (arm ACK success) ──► ARMED_GROUND
  │                              │                                                   │                          │                          │
  │                              │                                                   │                          │                          ├── (takeoff cmd) ──► TAKING_OFF
  │                              │                                                   │                          │                          │                      │
  │                              │                                                   │                          │                          │                      ├── (alt reached) ──► AIRBORNE_IDLE
  │                              │                                                   │                          │                          │                      │                      │
  │                              │                                                   │                          │                          │                      │                      ├── (mission start) ──► MISSION_EXECUTING
  │                              │                                                   │                          │                          │                      │                      │                         │
  │                              │                                                   │                          │                          │                      │                      │                         ├── (pause) ──► MISSION_PAUSED
  │                              │                                                   │                          │                          │                      │                      │                         │                │
  │                              │                                                   │                          │                          │                      │                      │                         │                ├── (resume) ──► MISSION_EXECUTING
  │                              │                                                   │                          │                          │                      │                      │                         │                └── (stop) ──► AIRBORNE_IDLE
  │                              │                                                   │                          │                          │                      │                      │                         │
  │                              │                                                   │                          │                          │                      │                      │                         ├── (mission complete) ──► RETURNING_HOME
  │                              │                                                   │                          │                          │                      │                      │                         ├── (stop) ──► AIRBORNE_IDLE
  │                              │                                                   │                          │                          │                      │                      │                         └── (avoidance) ──► DAA_AVOIDANCE
  │                              │                                                   │                          │                          │                      │                      │                                             │
  │                              │                                                   │                          │                          │                      │                      │                                             └── (clear) ──► MISSION_EXECUTING (resumes)
  │                              │                                                   │                          │                          │                      │                      │
  │                              │                                                   │                          │                          │                      │                      ├── (RTL cmd) ──► RETURNING_HOME
  │                              │                                                   │                          │                          │                      │                      └── (land cmd) ──► LANDING
  │                              │                                                   │                          │                          │                      │
  │                              │                                                   │                          │                          │                      │
  │                              │                                                   │                          │                          │
  │                              │                                                   │                          │                          ├── (disarm cmd or timeout) ──► CONNECTED_DISARMED
  │                              │                                                   │                          │
  │                              │                                                   │                          ├── (arm denied) ──► CONNECTED_DISARMED + error
  │                              │                                                   │
  │                              │                                                   ├── (check failed) ──► CONNECTED_DISARMED + error
  │                              │
  │                              │
  │                              ├── (heartbeat lost) ──► DISCONNECTED
  │
  │
  RETURNING_HOME ──► (alt descending + near home) ──► LANDING ──► (disarmed detected) ──► CONNECTED_DISARMED
  │
  LANDING ──► (disarmed detected) ──► CONNECTED_DISARMED
  │
  DAA_AVOIDANCE ──► (RTL triggered by AP_Avoidance) ──► RETURNING_HOME
  │
  FAILSAFE ──► (from ANY airborne state, on GCS loss / low battery / EKF failure / geofence breach)
           ──► RETURNING_HOME or LANDING (depending on failsafe action)
```

### 3.2 Formal State Table

| State | Entry Trigger | Exit Triggers | MQTT state/connection | MQTT state/flight | MQTT state/mission |
|-------|--------------|---------------|----------------------|-------------------|-------------------|
| `DISCONNECTED` | No heartbeat for 5s, or initial state | Heartbeat received | `"offline"` | — | — |
| `CONNECTED_DISARMED` | Heartbeat received + not armed | Arm success, heartbeat lost | `"online"` | `"landed"` | `{status: "idle"}` |
| `PREFLIGHT_CHECKS` | Execute_mission or takeoff command received | All checks pass, any check fails | `"online"` | `"landed"` | `{status: "preflight"}` |
| `ARMING` | Preflight checks pass | Arm ACK, arm denied, timeout | `"online"` | `"landed"` | (unchanged) |
| `ARMED_GROUND` | Arm ACK success | Takeoff cmd, disarm, timeout | `"online"` | `"landed"` | (unchanged) |
| `TAKING_OFF` | Takeoff command sent | Alt reached, failure | `"online"` | `"airborne"` | (unchanged) |
| `AIRBORNE_IDLE` | Takeoff complete, mission stop, pause | Mission start, RTL, land | `"online"` | `"airborne"` | `{status: "idle"}` or `{status: "paused"}` |
| `MISSION_EXECUTING` | Mission started or resumed | Pause, stop, complete, avoidance, failsafe | `"online"` | `"airborne"` | `{status: "executing", progress: N}` |
| `MISSION_PAUSED` | Pause command | Resume, stop | `"online"` | `"airborne"` | `{status: "paused"}` |
| `DAA_AVOIDANCE` | AP_Avoidance mode detected | Threat clears, RTL | `"online"` | `"airborne"` | `{status: "paused"}` (mission is effectively paused) |
| `RETURNING_HOME` | RTL command or mission complete RTL | Enters landing phase | `"online"` | `"returning_home"` | `{status: "returning"}` |
| `LANDING` | Land command or final descent in RTL | Disarmed | `"online"` | `"landing"` | `{status: "landing"}` |
| `FAILSAFE` | GCS loss, low battery, EKF fail, geofence | Transitions to RTL/Land per ArduPilot config | `"online"` | `"returning_home"` or `"landing"` | `{status: "error", error: "failsafe_*"}` |

### 3.3 State Detection from MAVLink

The bridge determines state by combining multiple MAVLink signals:

| State Determination | MAVLink Signal(s) |
|--------------------|-------------------|
| Armed/disarmed | `HEARTBEAT.base_mode & 128` |
| Flight mode | `HEARTBEAT.custom_mode` (see Section 1.8) |
| Airborne | `armed == true AND relative_alt > 0.5m` |
| RTL active | `custom_mode == 6` (RTL) or `custom_mode == 21` (SMART_RTL) |
| Landing | `custom_mode == 9` (LAND) |
| AUTO/mission | `custom_mode == 3` (AUTO) |
| Avoidance active | `custom_mode == 19` (AVOID_ADSB) |
| Failsafe | `HEARTBEAT.system_status == MAV_STATE_CRITICAL (5)` |
| Emergency | `HEARTBEAT.system_status == MAV_STATE_EMERGENCY (6)` |
| Mission progress | `MISSION_CURRENT (#42).seq` / total waypoints |
| Waypoint reached | `MISSION_ITEM_REACHED (#46).seq` |
| EKF status | `EKF_STATUS_REPORT (#193)` — flag degraded/failed |

### 3.4 Part 107 vs Part 108 State Machine Differences

| Aspect | Part 107 | Part 108 |
|--------|----------|----------|
| `PREFLIGHT_CHECKS` entry | Requires active RPIC authorization token | Requires FC on duty + DAA healthy; no per-flight human authorization |
| ComplianceGate in PREFLIGHT | Blocks until RPIC tap received (120s timeout) | Autonomous: checks pass -> proceed immediately |
| `FAILSAFE` notification | RPIC gets push notification: "drone in failsafe" | Flight Coordinator gets push notification + compliance event |
| Mission abort authority | RPIC via MQTT command | Flight Coordinator via MQTT command |
| State persisted to compliance log | Authorization source = "rpic_tap" | Authorization source = "autonomous_part108" |

---

## 4. Mission State Machine

### 4.1 States

```
IDLE ──► VALIDATING ──► UPLOADING ──► STARTING ──► EXECUTING ──► COMPLETING ──► COMPLETED
  ▲          │              │            │            │    │          │
  │          │              │            │            │    │          └──► IDLE
  │          ▼              ▼            ▼            │    ▼
  │       REJECTED     UPLOAD_FAILED  START_FAILED   │  PAUSED ──► EXECUTING
  │          │              │            │            │    │
  │          └──► IDLE      └──► IDLE    └──► IDLE   │    └──► ABORTED ──► IDLE
  │                                                  │
  │                                                  ├──► ABORTED ──► IDLE
  │                                                  ├──► DAA_INTERRUPTED ──► EXECUTING (if clears)
  │                                                  │                   └──► ABORTED (if RTL triggered)
  │                                                  └──► FAILSAFE_INTERRUPTED ──► (exits mission SM)
  │
  └──────────────────────────────────────────────────────────────────────────────
```

### 4.2 Formal State Table

| State | Entry | Exit | MQTT `state/mission` status | Actions |
|-------|-------|------|----------------------------|---------|
| `IDLE` | Initial, or after completion/abort | `execute_mission` command | `"idle"` | — |
| `VALIDATING` | `execute_mission` received | Validation pass or fail | `"validating"` | Check waypoints against operational area, altitude, speed. Check battery. Check ComplianceGate. |
| `REJECTED` | Validation failed | Automatic -> IDLE | `"error"` | Publish error response with rejection reason. Log compliance event. |
| `UPLOADING` | Validation passed | Upload complete or failed | `"uploading"` | Execute MAVLink mission upload protocol (Section 2.7, Phases 2-3) |
| `UPLOAD_FAILED` | MISSION_ACK with error, or timeout | Automatic -> IDLE | `"error"` | Publish error response. Log compliance event. |
| `STARTING` | Upload success (MISSION_ACK accepted) | Mode changes to AUTO, or timeout | `"starting"` | Send arm (if needed), takeoff (if needed), set AUTO mode, MISSION_START |
| `START_FAILED` | Arm denied, takeoff failed, mode change failed | Automatic -> IDLE | `"error"` | Publish error. Log compliance event. Disarm if was armed. |
| `EXECUTING` | Mode = AUTO confirmed | Mission complete, pause, stop, avoidance, failsafe | `"executing"` | Publish progress updates from MISSION_CURRENT. Publish waypoint reached events. |
| `PAUSED` | Pause command -> BRAKE/LOITER mode | Resume or stop | `"paused"` | Record current waypoint index |
| `COMPLETING` | Last waypoint reached + finish_action executing | Aircraft enters RTL/LAND/LOITER per finish_action | `"completing"` | — |
| `COMPLETED` | Aircraft has landed (if RTL/LAND) or is loitering (if HOVER) | Automatic transition | `"completed"` | Log flight record. Publish success response. -> IDLE after 5s |
| `ABORTED` | Stop command | -> IDLE | `"aborted"` | Log partial mission record. Aircraft remains in LOITER. |
| `DAA_INTERRUPTED` | Mode changes to AVOID_ADSB during mission | Threat clears (mode returns to AUTO) or RTL | `"executing"` (with `daa_interrupted: true`) | Log DAA event. AP_Avoidance handles maneuver. |
| `FAILSAFE_INTERRUPTED` | Failsafe detected during mission | Exits mission SM entirely | `"error"` with `error: "failsafe"` | Log failsafe event. Mission is over. |

### 4.3 Upload Protocol State Machine (detail)

The MAVLink mission upload handshake has its own internal states:

```
UPLOAD_IDLE
  │── (send MISSION_COUNT) ──► WAITING_REQUEST
                                 │
                                 ├── (MISSION_REQUEST_INT received) ──► SENDING_ITEM
                                 │                                       │
                                 │                                       └── (item sent) ──► WAITING_REQUEST
                                 │
                                 ├── (MISSION_ACK type=0 received) ──► UPLOAD_COMPLETE
                                 │
                                 ├── (MISSION_ACK type!=0 received) ──► UPLOAD_ERROR
                                 │
                                 └── (timeout 5s no request) ──► UPLOAD_TIMEOUT
                                       │
                                       ├── (retry < 3) ──► resend last item ──► WAITING_REQUEST
                                       └── (retry >= 3) ──► UPLOAD_ERROR
```

**Retry logic:** If a `MISSION_REQUEST_INT` is received for a seq that was already sent, the bridge resends that item (the FC did not receive it). Up to 3 retries per item.

**Out-of-sequence handling:** If the FC requests a seq that is not the expected next item, the bridge logs a warning and sends the requested item (the FC drives the sequence).

### 4.4 Mission Progress MQTT Updates

During `EXECUTING` state, the bridge publishes to `state/mission` on every `MISSION_CURRENT` or `MISSION_ITEM_REACHED`:

```json
{
  "status": "executing",
  "mission_id": "full_perimeter",
  "progress": 0.45,
  "current_waypoint": 4,
  "total_waypoints": 9,
  "error": null,
  "daa_interrupted": false,
  "started_at": 1739980800,
  "elapsed_s": 47
}
```

`progress` = `current_waypoint / total_waypoints` (nav waypoints only, not DO commands).

---

## 5. DAA (Detect and Avoid) State Machine

### 5.1 Threat Level Classification

The bridge computes `threat_level` for each ADS-B contact using distance and closure rate:

| Level | Criteria | Color (HA) |
|-------|----------|------------|
| `none` | Distance > 3000m OR contact diverging | — (not published after timeout) |
| `advisory` | Distance 1500-3000m AND closing | Blue |
| `warning` | Distance 500-1500m AND closing, OR time_to_CPA < 60s | Yellow |
| `critical` | Distance < 500m AND closing, OR time_to_CPA < 30s | Red |

**Closure rate computation:**
```
closure_rate = (distance_prev - distance_current) / dt
time_to_CPA = distance_current / closure_rate  (if closure_rate > 0)
```

**CPA = Closest Point of Approach.** This is a simplified 2D calculation. Full 3D CPA should include altitude separation:
```
slant_distance = sqrt(horizontal_distance^2 + altitude_separation^2)
```

Contacts with altitude separation > 150m (500ft) are always `none` regardless of horizontal distance (they are not a threat at this property's operating altitude of 24-37m AGL).

### 5.2 DAA States (Per-Contact)

Each tracked ADS-B contact has its own state:

```
UNTRACKED ──► (ADSB_VEHICLE received) ──► TRACKING_NONE
                                            │
                                            ├── (closing, distance < 3000m) ──► TRACKING_ADVISORY
                                            │                                    │
                                            │                                    ├── (closing, distance < 1500m) ──► TRACKING_WARNING
                                            │                                    │                                    │
                                            │                                    │                                    ├── (distance < 500m) ──► TRACKING_CRITICAL
                                            │                                    │                                    │                          │
                                            │                                    │                                    │                          ├── (AP_Avoidance triggers) ──► AVOIDANCE_ACTIVE
                                            │                                    │                                    │                          │                               │
                                            │                                    │                                    │                          │                               ├── (threat clears) ──► TRACKING_* (recalc)
                                            │                                    │                                    │                          │                               └── (RTL triggered) ──► AVOIDANCE_RTL
                                            │                                    │                                    │                          │
                                            │                                    │                                    │                          └── (receding) ──► TRACKING_WARNING
                                            │                                    │                                    │
                                            │                                    │                                    └── (receding) ──► TRACKING_ADVISORY
                                            │                                    │
                                            │                                    └── (receding) ──► TRACKING_NONE
                                            │
                                            └── (no update for 60s) ──► UNTRACKED (contact removed)
```

### 5.3 Global DAA State (Published to `state/daa`)

The bridge maintains an aggregate DAA state:

| `state/daa` field | Source |
|------------------|--------|
| `healthy` | True if ADS-B receiver is reporting (last `ADSB_VEHICLE` or heartbeat from receiver within 30s) |
| `contacts` | Count of currently tracked contacts (any level except UNTRACKED) |
| `highest_threat` | Highest threat_level across all contacts: `"none"`, `"advisory"`, `"warning"`, `"critical"` |
| `last_check` | Timestamp of last ADS-B data processed |

### 5.4 Avoidance Maneuver Detection

ArduPilot's AP_Avoidance handles the actual avoidance maneuver. The bridge detects this by monitoring:

1. **Flight mode change to AVOID_ADSB (19):** Primary signal. Detected in HEARTBEAT.
2. **STATUSTEXT messages:** ArduPilot logs avoidance actions (e.g., `"Avoidance: climb to 45m"`).
3. **Parameter configuration at startup:** Bridge reads `AVD_ENABLE`, `AVD_F_ACTION`, `AVD_W_ACTION`, `AVD_F_DIST`, `AVD_W_DIST`, `AVD_F_TIME`, `AVD_W_TIME` to understand what the FC will do.

### 5.5 What Gets Published to MQTT

| Event | Topic | Payload |
|-------|-------|---------|
| New contact detected | `daa/traffic` | Full traffic payload (Section 1.7) |
| Contact update | `daa/traffic` | Updated payload (same ICAO, new position/speed/threat) |
| Threat level change | `daa/traffic` | Updated payload with new `threat_level` |
| Avoidance maneuver starts | `daa/avoidance` | Trigger ICAO, action, positions |
| Avoidance maneuver ends | `daa/avoidance` | `action: "clear"`, return to previous state |
| Contact lost (60s timeout) | `state/daa` | Decremented `contacts` count |

### 5.6 What Gets Written to Compliance Log

Every DAA event is written to the compliance recorder (Section 11.2 of architecture):

| Event | Compliance Record |
|-------|------------------|
| Any contact at `warning` or above | `daa_event` record with full contact details, own position, threat assessment |
| Any avoidance maneuver | `daa_avoidance` record with full trajectory (pre/during/post avoidance) |
| ADS-B receiver health change | `daa_health` record |
| DAA system unhealthy for > 30s while airborne | `daa_anomaly` record -> triggers RTL recommendation |

---

## 6. Connection/Heartbeat State Machine

### 6.1 States

```
DISCONNECTED ──► (heartbeat received) ──► CONNECTED
                                           │
                                           ├── (no heartbeat for 5s) ──► HEARTBEAT_LOST
                                           │                              │
                                           │                              ├── (heartbeat resumes within 15s) ──► CONNECTED
                                           │                              │
                                           │                              └── (no heartbeat for 15s total) ──► DISCONNECTED
                                           │
                                           └── (MAVSDK connection error) ──► DISCONNECTED
```

### 6.2 Timing Parameters

| Parameter | Value | Rationale |
|-----------|-------|-----------|
| Heartbeat expected interval | 1 Hz (1s) | ArduPilot default HEARTBEAT rate |
| Heartbeat warning threshold | 3 missed (3s) | Transient link quality issue |
| Heartbeat lost threshold | 5 missed (5s) | Publish `HEARTBEAT_LOST`, begin reconnect attempts |
| Disconnected threshold | 15s total | Publish `DISCONNECTED`, MQTT LWT fires if bridge dies |
| Reconnect interval | 2s between attempts | Exponential backoff: 2s, 4s, 8s, 16s, cap at 30s |
| MAVSDK connection timeout | 10s | Initial connection attempt |

### 6.3 MQTT Mapping

| State | `state/connection` payload | Action |
|-------|---------------------------|--------|
| `DISCONNECTED` | `"offline"` (retained) | LWT also publishes `"offline"` if bridge process dies |
| `CONNECTED` | `"online"` (retained) | Clear any stale LWT |
| `HEARTBEAT_LOST` | `"degraded"` (retained) | HA can show warning indicator. Not yet offline. |

### 6.4 LWT (Last Will and Testament)

Configured on MQTT connect:

```
Topic:   drone_hass/{drone_id}/state/connection
Payload: "offline"
QoS:     1
Retain:  true
```

On successful connection, bridge immediately publishes `"online"` to the same topic (retained, QoS 1), overwriting any stale LWT.

### 6.5 Bridge Startup Handshake

When the bridge process starts:

1. Connect to MQTT broker with LWT configured
2. Subscribe to `drone_hass/{drone_id}/command/#` and `drone_hass/{drone_id}/missions/#`
3. Publish `"offline"` to `state/connection` (retained) — indicates bridge is up but drone not connected yet
4. Attempt MAVSDK connection to flight controller
5. Wait for first `HEARTBEAT`
6. Read key parameters: `BATT_CAPACITY`, `RTL_ALT`, `AVD_ENABLE`, `AVD_F_ACTION`, `AVD_F_DIST`, `AVD_W_DIST`, `AVD_F_TIME`, `AVD_W_TIME`, `FENCE_ENABLE`, `FENCE_TYPE`
7. Request message intervals for telemetry streams (`SET_MESSAGE_INTERVAL`)
8. Publish `"online"` to `state/connection` (retained)
9. Begin telemetry publishing loop

### 6.6 ArduPilot GCS Heartbeat (Bridge -> FC)

The bridge MUST send its own HEARTBEAT to the flight controller at 1 Hz. This is how ArduPilot knows the GCS is connected. If ArduPilot stops receiving GCS heartbeats, it triggers the GCS failsafe (configurable: continue, RTL, land, SmartRTL).

MAVSDK-Python handles this automatically when a `System` connection is active. If using pymavlink directly, the bridge must explicitly send:

```python
# pymavlink example
mav.mav.heartbeat_send(
    mavutil.mavlink.MAV_TYPE_GCS,           # type = 6
    mavutil.mavlink.MAV_AUTOPILOT_INVALID,  # autopilot = 8
    0,                                       # base_mode
    0,                                       # custom_mode
    mavutil.mavlink.MAV_STATE_ACTIVE         # system_status = 4
)
```

---

## 7. JSON Schemas (Draft 2020-12)

### 7.1 Telemetry Payloads

#### `telemetry/flight`

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "drone_hass/telemetry/flight",
  "title": "Flight Telemetry",
  "type": "object",
  "required": ["lat", "lon", "alt", "heading", "speed_x", "speed_y", "speed_z",
               "ground_speed", "flight_mode", "armed", "is_flying",
               "gps_fix", "satellite_count", "timestamp"],
  "properties": {
    "lat": {
      "type": "number",
      "minimum": -90,
      "maximum": 90,
      "description": "Latitude in decimal degrees (WGS84)"
    },
    "lon": {
      "type": "number",
      "minimum": -180,
      "maximum": 180,
      "description": "Longitude in decimal degrees (WGS84)"
    },
    "alt": {
      "type": "number",
      "description": "Altitude in meters relative to takeoff point"
    },
    "heading": {
      "type": ["number", "null"],
      "minimum": 0,
      "maximum": 360,
      "description": "Heading in degrees (0=North, clockwise). Null if unknown."
    },
    "speed_x": {
      "type": "number",
      "description": "North velocity in m/s (NED frame, North positive)"
    },
    "speed_y": {
      "type": "number",
      "description": "East velocity in m/s (NED frame, East positive)"
    },
    "speed_z": {
      "type": "number",
      "description": "Vertical velocity in m/s (positive = UP, opposite of MAVLink NED convention)"
    },
    "ground_speed": {
      "type": "number",
      "minimum": 0,
      "description": "Horizontal ground speed in m/s"
    },
    "flight_mode": {
      "type": "string",
      "enum": ["STABILIZE", "ACRO", "ALT_HOLD", "AUTO", "GUIDED", "LOITER",
               "RTL", "CIRCLE", "LAND", "DRIFT", "SPORT", "FLIP", "AUTOTUNE",
               "POSHOLD", "BRAKE", "THROW", "AVOID_ADSB", "GUIDED_NOGPS",
               "SMART_RTL", "FLOWHOLD", "FOLLOW", "ZIGZAG", "SYSTEMID",
               "AUTOROTATE", "AUTO_RTL", "UNKNOWN"],
      "description": "ArduCopter flight mode name"
    },
    "armed": {
      "type": "boolean",
      "description": "True if motors are armed"
    },
    "is_flying": {
      "type": "boolean",
      "description": "True if armed and altitude > 0.5m (bridge heuristic)"
    },
    "gps_fix": {
      "type": "integer",
      "minimum": 0,
      "maximum": 6,
      "description": "GPS fix type: 0=none, 1=no fix, 2=2D, 3=3D, 4=DGPS, 5=RTK float, 6=RTK fixed"
    },
    "satellite_count": {
      "type": "integer",
      "minimum": 0,
      "maximum": 255,
      "description": "Number of visible GPS satellites"
    },
    "timestamp": {
      "type": "integer",
      "description": "Unix epoch seconds (UTC)"
    }
  },
  "additionalProperties": false
}
```

#### `telemetry/battery`

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "drone_hass/telemetry/battery",
  "title": "Battery Telemetry",
  "type": "object",
  "required": ["charge_percent", "voltage_mv", "current_ma", "temperature_c",
               "remaining_mah", "full_charge_mah", "flight_time_remaining_s", "timestamp"],
  "properties": {
    "charge_percent": {
      "type": ["integer", "null"],
      "minimum": 0,
      "maximum": 100,
      "description": "Battery state of charge (%). Null if unknown."
    },
    "voltage_mv": {
      "type": ["integer", "null"],
      "minimum": 0,
      "description": "Pack voltage in millivolts. Null if unknown."
    },
    "current_ma": {
      "type": ["integer", "null"],
      "description": "Current in milliamps. Negative = discharging, positive = charging. Null if unknown."
    },
    "temperature_c": {
      "type": ["number", "null"],
      "description": "Battery temperature in degrees Celsius. Null if unknown."
    },
    "remaining_mah": {
      "type": ["integer", "null"],
      "minimum": 0,
      "description": "Estimated remaining capacity in mAh. Null if unknown."
    },
    "full_charge_mah": {
      "type": ["integer", "null"],
      "minimum": 0,
      "description": "Full charge capacity in mAh (from BATT_CAPACITY parameter). Null if not configured."
    },
    "flight_time_remaining_s": {
      "type": ["integer", "null"],
      "minimum": 0,
      "description": "Estimated flight time remaining in seconds. Null if unknown."
    },
    "timestamp": {
      "type": "integer",
      "description": "Unix epoch seconds (UTC)"
    }
  },
  "additionalProperties": false
}
```

#### `telemetry/gimbal`

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "drone_hass/telemetry/gimbal",
  "title": "Gimbal Telemetry",
  "type": "object",
  "required": ["pitch", "roll", "yaw", "mode"],
  "properties": {
    "pitch": {
      "type": ["number", "null"],
      "minimum": -180,
      "maximum": 180,
      "description": "Gimbal pitch in degrees (negative = down). Null if unavailable."
    },
    "roll": {
      "type": ["number", "null"],
      "minimum": -180,
      "maximum": 180,
      "description": "Gimbal roll in degrees. Null if unavailable."
    },
    "yaw": {
      "type": ["number", "null"],
      "minimum": 0,
      "maximum": 360,
      "description": "Gimbal yaw in degrees (0=North, clockwise). Null if unavailable."
    },
    "mode": {
      "type": "string",
      "enum": ["YAW_FOLLOW", "YAW_LOCK", "NOT_AVAILABLE", "UNKNOWN"],
      "description": "Gimbal yaw behavior mode"
    }
  },
  "additionalProperties": false
}
```

#### `telemetry/camera`

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "drone_hass/telemetry/camera",
  "title": "Camera Telemetry",
  "type": "object",
  "required": ["is_recording", "recording_time_s", "storage_remaining_mb"],
  "properties": {
    "is_recording": {
      "type": "boolean",
      "description": "True if video recording is active"
    },
    "recording_time_s": {
      "type": ["number", "null"],
      "minimum": 0,
      "description": "Elapsed recording time in seconds. Null if not recording."
    },
    "storage_remaining_mb": {
      "type": ["number", "null"],
      "minimum": 0,
      "description": "Available storage in MiB. Null if unknown."
    }
  },
  "additionalProperties": false
}
```

#### `telemetry/signal`

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "drone_hass/telemetry/signal",
  "title": "Signal Telemetry",
  "type": "object",
  "required": ["primary_link", "primary_rssi_dbm"],
  "properties": {
    "primary_link": {
      "type": "string",
      "enum": ["wifi", "sik_915mhz", "lte", "unknown"],
      "description": "Primary C2 link type"
    },
    "primary_rssi_dbm": {
      "type": ["integer", "null"],
      "description": "Primary link RSSI in dBm. Null if unavailable."
    },
    "backup_link": {
      "type": ["string", "null"],
      "enum": ["wifi", "sik_915mhz", "lte", null],
      "description": "Backup C2 link type. Null if no backup."
    },
    "backup_rssi_raw": {
      "type": ["integer", "null"],
      "minimum": 0,
      "maximum": 254,
      "description": "Backup link RSSI (raw SiK value 0-254). Null if unavailable."
    },
    "backup_remote_rssi_raw": {
      "type": ["integer", "null"],
      "minimum": 0,
      "maximum": 254,
      "description": "Backup link remote RSSI. Null if unavailable."
    },
    "backup_noise_raw": {
      "type": ["integer", "null"],
      "minimum": 0,
      "maximum": 254,
      "description": "Backup link noise floor. Null if unavailable."
    }
  },
  "additionalProperties": false
}
```

#### `telemetry/position`

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "drone_hass/telemetry/position",
  "title": "Position (Device Tracker)",
  "type": "object",
  "required": ["lat", "lon", "alt"],
  "properties": {
    "lat": {
      "type": "number",
      "minimum": -90,
      "maximum": 90
    },
    "lon": {
      "type": "number",
      "minimum": -180,
      "maximum": 180
    },
    "alt": {
      "type": "number",
      "description": "Altitude in meters relative to takeoff"
    }
  },
  "additionalProperties": false
}
```

### 7.2 DAA Payloads

#### `daa/traffic`

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "drone_hass/daa/traffic",
  "title": "DAA Traffic Contact",
  "type": "object",
  "required": ["icao", "threat_level", "timestamp"],
  "properties": {
    "icao": {
      "type": "string",
      "pattern": "^[0-9A-F]{6}$",
      "description": "ICAO 24-bit address as hex string"
    },
    "callsign": {
      "type": ["string", "null"],
      "maxLength": 8,
      "description": "ATC callsign. Null if not available."
    },
    "lat": {
      "type": ["number", "null"],
      "minimum": -90,
      "maximum": 90,
      "description": "Traffic latitude. Null if coords not valid."
    },
    "lon": {
      "type": ["number", "null"],
      "minimum": -180,
      "maximum": 180,
      "description": "Traffic longitude. Null if coords not valid."
    },
    "altitude_m": {
      "type": ["number", "null"],
      "description": "Traffic altitude in meters AMSL. Null if not valid."
    },
    "altitude_type": {
      "type": ["string", "null"],
      "enum": ["pressure", "geometric", null],
      "description": "Altitude reference: pressure (QNH) or geometric (GPS)"
    },
    "heading": {
      "type": ["number", "null"],
      "minimum": 0,
      "maximum": 360,
      "description": "Traffic heading in degrees. Null if not valid."
    },
    "ground_speed_mps": {
      "type": ["number", "null"],
      "minimum": 0,
      "description": "Traffic ground speed in m/s. Null if not valid."
    },
    "vertical_speed_mps": {
      "type": ["number", "null"],
      "description": "Traffic vertical speed in m/s (positive=up). Null if not valid."
    },
    "squawk": {
      "type": ["integer", "null"],
      "description": "Transponder squawk code. Null if not valid."
    },
    "emitter_type": {
      "type": "integer",
      "minimum": 0,
      "maximum": 18,
      "description": "ADSB emitter type enum (0=no info, 1=light, 14=UAV, etc.)"
    },
    "distance_m": {
      "type": ["number", "null"],
      "minimum": 0,
      "description": "Horizontal distance from drone to traffic in meters. Null if position unknown."
    },
    "altitude_separation_m": {
      "type": ["number", "null"],
      "description": "Altitude difference (traffic alt - drone alt) in meters. Null if unknown."
    },
    "threat_level": {
      "type": "string",
      "enum": ["none", "advisory", "warning", "critical"],
      "description": "Bridge-computed threat assessment"
    },
    "flags": {
      "type": "integer",
      "description": "ADSB_FLAGS bitfield indicating which fields are valid"
    },
    "timestamp": {
      "type": "integer",
      "description": "Unix epoch seconds (UTC)"
    }
  },
  "additionalProperties": false
}
```

#### `daa/avoidance`

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "drone_hass/daa/avoidance",
  "title": "DAA Avoidance Event",
  "type": "object",
  "required": ["trigger_icao", "action", "timestamp"],
  "properties": {
    "trigger_icao": {
      "type": "string",
      "pattern": "^[0-9A-F]{6}$",
      "description": "ICAO of traffic contact that triggered avoidance"
    },
    "action": {
      "type": "string",
      "enum": ["climb", "descend", "lateral", "perpendicular", "rtl", "hover", "clear", "report_only"],
      "description": "Avoidance action taken by AP_Avoidance"
    },
    "original_alt": {
      "type": ["number", "null"],
      "description": "Drone altitude (m, relative) at avoidance trigger"
    },
    "new_alt": {
      "type": ["number", "null"],
      "description": "Drone altitude (m, relative) after avoidance stabilized"
    },
    "original_position": {
      "type": ["object", "null"],
      "properties": {
        "lat": { "type": "number" },
        "lon": { "type": "number" }
      },
      "required": ["lat", "lon"]
    },
    "new_position": {
      "type": ["object", "null"],
      "properties": {
        "lat": { "type": "number" },
        "lon": { "type": "number" }
      },
      "required": ["lat", "lon"]
    },
    "threat_distance_m": {
      "type": ["number", "null"],
      "minimum": 0,
      "description": "Distance to triggering traffic at moment of avoidance"
    },
    "timestamp": {
      "type": "integer",
      "description": "Unix epoch seconds (UTC)"
    }
  },
  "additionalProperties": false
}
```

### 7.3 State Payloads

#### `state/connection`

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "drone_hass/state/connection",
  "title": "Connection State",
  "type": "string",
  "enum": ["online", "offline", "degraded"]
}
```

#### `state/flight`

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "drone_hass/state/flight",
  "title": "Flight State",
  "type": "string",
  "enum": ["landed", "airborne", "returning_home", "landing"]
}
```

#### `state/mission`

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "drone_hass/state/mission",
  "title": "Mission State",
  "type": "object",
  "required": ["status", "mission_id", "progress", "current_waypoint", "total_waypoints", "error"],
  "properties": {
    "status": {
      "type": "string",
      "enum": ["idle", "validating", "preflight", "uploading", "starting", "executing",
               "paused", "completing", "completed", "aborted", "returning", "landing", "error"]
    },
    "mission_id": {
      "type": ["string", "null"],
      "description": "Active mission identifier. Null when idle."
    },
    "progress": {
      "type": "number",
      "minimum": 0,
      "maximum": 1,
      "description": "Mission progress 0.0 to 1.0"
    },
    "current_waypoint": {
      "type": "integer",
      "minimum": 0,
      "description": "Current waypoint index (0-based)"
    },
    "total_waypoints": {
      "type": "integer",
      "minimum": 0,
      "description": "Total navigation waypoints in mission"
    },
    "error": {
      "type": ["string", "null"],
      "description": "Error message if status is 'error'. Null otherwise."
    },
    "daa_interrupted": {
      "type": "boolean",
      "default": false,
      "description": "True if mission is paused due to DAA avoidance maneuver"
    },
    "started_at": {
      "type": ["integer", "null"],
      "description": "Unix epoch seconds when mission execution began. Null if not started."
    },
    "elapsed_s": {
      "type": ["integer", "null"],
      "minimum": 0,
      "description": "Elapsed mission time in seconds. Null if not started."
    }
  },
  "additionalProperties": false
}
```

#### `state/stream`

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "drone_hass/state/stream",
  "title": "Stream State",
  "type": "object",
  "required": ["is_streaming"],
  "properties": {
    "is_streaming": {
      "type": "boolean"
    },
    "rtsp_url": {
      "type": ["string", "null"],
      "format": "uri",
      "description": "RTSP URL of active stream. Null if not streaming."
    },
    "resolution": {
      "type": ["string", "null"],
      "description": "Stream resolution (e.g., '1080p', '4K'). Null if not streaming."
    },
    "bitrate_kbps": {
      "type": ["integer", "null"],
      "minimum": 0,
      "description": "Stream bitrate in kbps. Null if not streaming."
    }
  },
  "additionalProperties": false
}
```

#### `state/daa`

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "drone_hass/state/daa",
  "title": "DAA System State",
  "type": "object",
  "required": ["healthy", "contacts", "last_check"],
  "properties": {
    "healthy": {
      "type": "boolean",
      "description": "True if ADS-B receiver is operational and reporting"
    },
    "contacts": {
      "type": "integer",
      "minimum": 0,
      "description": "Number of currently tracked ADS-B contacts"
    },
    "highest_threat": {
      "type": "string",
      "enum": ["none", "advisory", "warning", "critical"],
      "default": "none",
      "description": "Highest threat level across all contacts"
    },
    "last_check": {
      "type": "integer",
      "description": "Unix epoch seconds of last ADS-B data processed"
    }
  },
  "additionalProperties": false
}
```

#### `state/compliance`

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "drone_hass/state/compliance",
  "title": "Compliance State",
  "type": "object",
  "required": ["mode", "fc_on_duty", "operational_area_valid"],
  "properties": {
    "mode": {
      "type": "string",
      "enum": ["part_107", "part_108"],
      "description": "Current operational mode"
    },
    "fc_on_duty": {
      "type": "boolean",
      "description": "True if a Flight Coordinator is currently on duty"
    },
    "fc_id": {
      "type": ["string", "null"],
      "description": "Identifier of the current Flight Coordinator. Null if none."
    },
    "operational_area_valid": {
      "type": "boolean",
      "description": "True if an operational area is configured and valid"
    },
    "operational_area_id": {
      "type": ["string", "null"],
      "description": "ID of the configured operational area. Null if none."
    }
  },
  "additionalProperties": false
}
```

### 7.4 Command Request Payloads

#### Generic Command Request

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "drone_hass/command/request_base",
  "title": "Command Request Base",
  "type": "object",
  "required": ["id"],
  "properties": {
    "id": {
      "type": "string",
      "format": "uuid",
      "description": "Correlation ID for request/response matching"
    },
    "params": {
      "type": "object",
      "description": "Command-specific parameters"
    },
    "timestamp": {
      "type": "integer",
      "description": "Unix epoch seconds. Bridge rejects commands older than 30s (replay protection)."
    }
  }
}
```

#### `command/arm`

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "drone_hass/command/arm",
  "title": "Arm Command",
  "allOf": [{ "$ref": "drone_hass/command/request_base" }],
  "properties": {
    "params": {
      "type": "object",
      "properties": {},
      "additionalProperties": false
    }
  }
}
```

#### `command/takeoff`

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "drone_hass/command/takeoff",
  "title": "Takeoff Command",
  "allOf": [{ "$ref": "drone_hass/command/request_base" }],
  "properties": {
    "params": {
      "type": "object",
      "properties": {
        "altitude_m": {
          "type": "number",
          "minimum": 2,
          "maximum": 37,
          "default": 10,
          "description": "Target hover altitude in meters (relative). Max is operational area ceiling."
        }
      },
      "additionalProperties": false
    }
  }
}
```

#### `command/execute_mission`

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "drone_hass/command/execute_mission",
  "title": "Execute Mission Command",
  "allOf": [{ "$ref": "drone_hass/command/request_base" }],
  "properties": {
    "params": {
      "type": "object",
      "required": ["mission_id"],
      "properties": {
        "mission_id": {
          "type": "string",
          "description": "ID of the mission definition to execute"
        }
      },
      "additionalProperties": false
    }
  }
}
```

#### `command/set_gimbal`

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "drone_hass/command/set_gimbal",
  "title": "Set Gimbal Command",
  "allOf": [{ "$ref": "drone_hass/command/request_base" }],
  "properties": {
    "params": {
      "type": "object",
      "required": ["pitch"],
      "properties": {
        "pitch": {
          "type": "number",
          "minimum": -90,
          "maximum": 30,
          "description": "Gimbal pitch in degrees (negative = down)"
        },
        "mode": {
          "type": "string",
          "enum": ["YAW_FOLLOW", "YAW_LOCK"],
          "default": "YAW_FOLLOW"
        }
      },
      "additionalProperties": false
    }
  }
}
```

#### `command/set_operational_mode`

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "drone_hass/command/set_operational_mode",
  "title": "Set Operational Mode Command",
  "allOf": [{ "$ref": "drone_hass/command/request_base" }],
  "properties": {
    "params": {
      "type": "object",
      "required": ["mode"],
      "properties": {
        "mode": {
          "type": "string",
          "enum": ["part_107", "part_108"]
        }
      },
      "additionalProperties": false
    }
  }
}
```

#### `command/set_fc_on_duty`

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "drone_hass/command/set_fc_on_duty",
  "title": "Set Flight Coordinator On Duty Command",
  "allOf": [{ "$ref": "drone_hass/command/request_base" }],
  "properties": {
    "params": {
      "type": "object",
      "required": ["on_duty"],
      "properties": {
        "on_duty": {
          "type": "boolean"
        },
        "fc_id": {
          "type": "string",
          "description": "Flight Coordinator identifier. Required when on_duty=true."
        }
      },
      "additionalProperties": false
    }
  }
}
```

#### `command/set_home`

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "drone_hass/command/set_home",
  "title": "Set Home Position Command",
  "allOf": [{ "$ref": "drone_hass/command/request_base" }],
  "properties": {
    "params": {
      "type": "object",
      "required": ["lat", "lon"],
      "properties": {
        "lat": {
          "type": "number",
          "minimum": -90,
          "maximum": 90
        },
        "lon": {
          "type": "number",
          "minimum": -180,
          "maximum": 180
        }
      },
      "additionalProperties": false
    }
  }
}
```

### 7.5 Command Response Payload

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "drone_hass/command/response",
  "title": "Command Response",
  "type": "object",
  "required": ["id", "success"],
  "properties": {
    "id": {
      "type": "string",
      "format": "uuid",
      "description": "Correlation ID matching the request"
    },
    "success": {
      "type": "boolean"
    },
    "error": {
      "type": ["string", "null"],
      "description": "Error identifier. Null on success."
    },
    "data": {
      "type": ["object", "null"],
      "description": "Command-specific response data. Null if none.",
      "properties": {
        "reason": {
          "type": "string",
          "description": "Human-readable error detail (e.g., ArduPilot pre-arm failure reason)"
        },
        "rtsp_url": {
          "type": "string",
          "format": "uri",
          "description": "RTSP URL returned by start_stream"
        }
      }
    }
  },
  "additionalProperties": false
}
```

### 7.6 Mission Definition Payload

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "drone_hass/mission_definition",
  "title": "Mission Definition",
  "type": "object",
  "required": ["id", "name", "speed_mps", "finish_action", "waypoints"],
  "properties": {
    "id": {
      "type": "string",
      "pattern": "^[a-z0-9_]+$",
      "description": "Mission identifier (alphanumeric + underscore)"
    },
    "name": {
      "type": "string",
      "maxLength": 64,
      "description": "Human-readable mission name"
    },
    "speed_mps": {
      "type": "number",
      "minimum": 0.5,
      "maximum": 15,
      "description": "Default speed in m/s for all waypoints"
    },
    "finish_action": {
      "type": "string",
      "enum": ["RTL", "LAND", "HOVER"],
      "description": "Action after last waypoint"
    },
    "heading_mode": {
      "type": "string",
      "enum": ["AUTO", "MANUAL", "NEXT_WAYPOINT"],
      "default": "AUTO",
      "description": "How aircraft heading is controlled during mission"
    },
    "flight_path_mode": {
      "type": "string",
      "enum": ["STRAIGHT", "SPLINE"],
      "default": "STRAIGHT",
      "description": "Path interpolation between waypoints"
    },
    "waypoints": {
      "type": "array",
      "minItems": 1,
      "maxItems": 200,
      "items": {
        "type": "object",
        "required": ["lat", "lon", "alt"],
        "properties": {
          "lat": {
            "type": "number",
            "minimum": -90,
            "maximum": 90
          },
          "lon": {
            "type": "number",
            "minimum": -180,
            "maximum": 180
          },
          "alt": {
            "type": "number",
            "minimum": 2,
            "maximum": 37,
            "description": "Altitude in meters relative to takeoff. Max = operational area ceiling."
          },
          "speed_mps": {
            "type": ["number", "null"],
            "minimum": 0.5,
            "maximum": 15,
            "description": "Speed override for this waypoint. Null = use mission default."
          },
          "gimbal_pitch": {
            "type": ["number", "null"],
            "minimum": -90,
            "maximum": 30,
            "description": "Gimbal pitch at this waypoint. Null = no change."
          },
          "stay_ms": {
            "type": "integer",
            "minimum": 0,
            "default": 0,
            "description": "Loiter time at waypoint in milliseconds. 0 = fly through."
          },
          "actions": {
            "type": "array",
            "items": {
              "type": "string",
              "enum": ["TAKE_PHOTO", "START_RECORD", "STOP_RECORD"]
            },
            "default": [],
            "description": "Camera actions to execute at this waypoint"
          }
        },
        "additionalProperties": false
      }
    }
  },
  "additionalProperties": false
}
```

### 7.7 Compliance Event Payloads

#### `compliance/flight_log`

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "drone_hass/compliance/flight_log",
  "title": "Compliance Flight Log",
  "type": "object",
  "required": ["event_type", "flight_id", "timestamp"],
  "properties": {
    "event_type": {
      "const": "flight_log"
    },
    "flight_id": {
      "type": "string",
      "format": "uuid",
      "description": "Unique flight identifier"
    },
    "trigger": {
      "type": "string",
      "description": "What triggered the flight (e.g., 'alarm', 'manual', 'test')"
    },
    "authorization": {
      "type": "object",
      "properties": {
        "mode": { "type": "string", "enum": ["part_107", "part_108"] },
        "authorized_by": { "type": "string", "description": "RPIC ID or 'autonomous'" },
        "authorized_at": { "type": "integer", "description": "Unix epoch" }
      },
      "required": ["mode", "authorized_by", "authorized_at"]
    },
    "mission_id": {
      "type": ["string", "null"]
    },
    "weather_at_launch": {
      "type": "object",
      "properties": {
        "wind_speed_mph": { "type": "number" },
        "wind_gust_mph": { "type": ["number", "null"] },
        "temperature_c": { "type": "number" },
        "humidity_pct": { "type": ["number", "null"] },
        "raining": { "type": "boolean" }
      }
    },
    "takeoff_time": {
      "type": ["integer", "null"],
      "description": "Unix epoch of takeoff"
    },
    "landing_time": {
      "type": ["integer", "null"],
      "description": "Unix epoch of landing"
    },
    "max_altitude_m": {
      "type": ["number", "null"]
    },
    "max_distance_m": {
      "type": ["number", "null"],
      "description": "Max horizontal distance from home"
    },
    "max_speed_mps": {
      "type": ["number", "null"]
    },
    "outcome": {
      "type": "string",
      "enum": ["completed", "aborted", "failsafe", "error"],
      "description": "How the flight ended"
    },
    "daa_events_count": {
      "type": "integer",
      "minimum": 0,
      "description": "Number of DAA events during this flight"
    },
    "avoidance_maneuvers_count": {
      "type": "integer",
      "minimum": 0,
      "description": "Number of avoidance maneuvers during this flight"
    },
    "timestamp": {
      "type": "integer",
      "description": "Unix epoch when this record was written"
    },
    "prev_hash": {
      "type": "string",
      "description": "SHA-256 hash of the previous compliance record (hash chain)"
    }
  },
  "additionalProperties": false
}
```

#### `compliance/daa_events`

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "drone_hass/compliance/daa_events",
  "title": "Compliance DAA Event",
  "type": "object",
  "required": ["event_type", "flight_id", "contact", "own_position", "threat_level", "timestamp"],
  "properties": {
    "event_type": {
      "const": "daa_event"
    },
    "flight_id": {
      "type": "string",
      "format": "uuid"
    },
    "contact": {
      "type": "object",
      "properties": {
        "icao": { "type": "string" },
        "callsign": { "type": ["string", "null"] },
        "lat": { "type": ["number", "null"] },
        "lon": { "type": ["number", "null"] },
        "altitude_m": { "type": ["number", "null"] },
        "heading": { "type": ["number", "null"] },
        "ground_speed_mps": { "type": ["number", "null"] },
        "emitter_type": { "type": "integer" }
      },
      "required": ["icao"]
    },
    "own_position": {
      "type": "object",
      "properties": {
        "lat": { "type": "number" },
        "lon": { "type": "number" },
        "alt": { "type": "number" }
      },
      "required": ["lat", "lon", "alt"]
    },
    "threat_level": {
      "type": "string",
      "enum": ["advisory", "warning", "critical"]
    },
    "distance_m": {
      "type": ["number", "null"]
    },
    "closure_rate_mps": {
      "type": ["number", "null"],
      "description": "Positive = closing"
    },
    "avoidance_action": {
      "type": ["string", "null"],
      "enum": ["climb", "descend", "lateral", "perpendicular", "rtl", "hover", "report_only", null],
      "description": "Avoidance action taken, if any. Null if no avoidance triggered."
    },
    "timestamp": {
      "type": "integer"
    },
    "prev_hash": {
      "type": "string"
    }
  },
  "additionalProperties": false
}
```

#### `compliance/weather_log`

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "drone_hass/compliance/weather_log",
  "title": "Compliance Weather Record",
  "type": "object",
  "required": ["event_type", "decision", "conditions", "timestamp"],
  "properties": {
    "event_type": {
      "const": "weather_record"
    },
    "flight_id": {
      "type": ["string", "null"],
      "format": "uuid",
      "description": "Associated flight, if this is a launch decision"
    },
    "decision": {
      "type": "string",
      "enum": ["go", "no_go"],
      "description": "Whether weather passed the go/no-go gate"
    },
    "conditions": {
      "type": "object",
      "properties": {
        "wind_speed_mph": { "type": "number" },
        "wind_gust_mph": { "type": ["number", "null"] },
        "temperature_c": { "type": "number" },
        "humidity_pct": { "type": ["number", "null"] },
        "raining": { "type": "boolean" }
      },
      "required": ["wind_speed_mph", "temperature_c", "raining"]
    },
    "no_go_reasons": {
      "type": "array",
      "items": { "type": "string" },
      "description": "List of conditions that failed. Empty if go."
    },
    "timestamp": {
      "type": "integer"
    },
    "prev_hash": {
      "type": "string"
    }
  },
  "additionalProperties": false
}
```

#### `compliance/personnel_log`

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "drone_hass/compliance/personnel_log",
  "title": "Compliance Personnel Record",
  "type": "object",
  "required": ["event_type", "role", "person_id", "action", "timestamp"],
  "properties": {
    "event_type": {
      "const": "personnel_log"
    },
    "role": {
      "type": "string",
      "enum": ["rpic", "flight_coordinator", "operations_supervisor", "visual_observer"],
      "description": "Role of the person"
    },
    "person_id": {
      "type": "string",
      "description": "Identifier of the person"
    },
    "action": {
      "type": "string",
      "enum": ["on_duty", "off_duty"],
      "description": "Whether going on or off duty"
    },
    "timestamp": {
      "type": "integer"
    },
    "prev_hash": {
      "type": "string"
    }
  },
  "additionalProperties": false
}
```

#### `compliance/safety_gate`

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "drone_hass/compliance/safety_gate",
  "title": "Compliance Safety Gate Record",
  "type": "object",
  "required": ["event_type", "flight_id", "outcome", "gates", "timestamp"],
  "properties": {
    "event_type": {
      "const": "safety_gate"
    },
    "flight_id": {
      "type": "string",
      "format": "uuid"
    },
    "outcome": {
      "type": "string",
      "enum": ["pass", "fail"],
      "description": "Overall gate outcome"
    },
    "gates": {
      "type": "object",
      "properties": {
        "battery_ok": { "type": "boolean" },
        "gps_ok": { "type": "boolean" },
        "connection_ok": { "type": "boolean" },
        "weather_ok": { "type": "boolean" },
        "daa_healthy": { "type": "boolean" },
        "operational_area_valid": { "type": "boolean" },
        "not_airborne": { "type": "boolean" },
        "dock_lid_open": { "type": ["boolean", "null"] },
        "fc_on_duty": { "type": ["boolean", "null"], "description": "Null in Part 107 mode (not applicable)" },
        "mission_valid": { "type": "boolean" }
      }
    },
    "failed_gates": {
      "type": "array",
      "items": { "type": "string" },
      "description": "List of gate names that failed. Empty if all pass."
    },
    "timestamp": {
      "type": "integer"
    },
    "prev_hash": {
      "type": "string"
    }
  },
  "additionalProperties": false
}
```

### 7.8 Operational Area Definition

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "drone_hass/operational_area",
  "title": "Operational Area Definition",
  "type": "object",
  "required": ["id", "name", "boundary", "altitude_floor_m", "altitude_ceiling_m", "airspace_class"],
  "properties": {
    "id": {
      "type": "string"
    },
    "name": {
      "type": "string"
    },
    "boundary": {
      "type": "object",
      "required": ["type", "coordinates"],
      "properties": {
        "type": {
          "const": "Polygon"
        },
        "coordinates": {
          "type": "array",
          "items": {
            "type": "array",
            "items": {
              "type": "array",
              "items": { "type": "number" },
              "minItems": 2,
              "maxItems": 2,
              "description": "[lon, lat] per GeoJSON convention"
            },
            "minItems": 4,
            "description": "Linear ring (first and last point must be identical)"
          },
          "minItems": 1
        }
      }
    },
    "altitude_floor_m": {
      "type": "number",
      "minimum": 0,
      "description": "Minimum altitude in meters AGL"
    },
    "altitude_ceiling_m": {
      "type": "number",
      "minimum": 1,
      "maximum": 122,
      "description": "Maximum altitude in meters AGL. 122m = 400ft Part 107 limit."
    },
    "lateral_buffer_m": {
      "type": "number",
      "minimum": 0,
      "default": 5,
      "description": "Buffer inside boundary for waypoint validation"
    },
    "airspace_class": {
      "type": "string",
      "enum": ["B", "C", "D", "E", "G"],
      "description": "FAA airspace classification at this location"
    }
  },
  "additionalProperties": false
}
```

---

## 8. MQTT Topic Reference (Complete)

| Topic | Direction | QoS | Retain | Rate | Schema |
|-------|-----------|-----|--------|------|--------|
| `drone_hass/{id}/telemetry/flight` | Bridge->HA | 0 | No | 1-2 Hz | 7.1 flight |
| `drone_hass/{id}/telemetry/battery` | Bridge->HA | 0 | No | 0.2 Hz | 7.1 battery |
| `drone_hass/{id}/telemetry/gimbal` | Bridge->HA | 0 | No | 1 Hz | 7.1 gimbal |
| `drone_hass/{id}/telemetry/camera` | Bridge->HA | 1 | No | On change | 7.1 camera |
| `drone_hass/{id}/telemetry/signal` | Bridge->HA | 0 | No | 1 Hz | 7.1 signal |
| `drone_hass/{id}/telemetry/position` | Bridge->HA | 0 | No | 0.1 Hz | 7.1 position |
| `drone_hass/{id}/daa/traffic` | Bridge->HA | 1 | No | On detection | 7.2 traffic |
| `drone_hass/{id}/daa/avoidance` | Bridge->HA | 1 | No | On event | 7.2 avoidance |
| `drone_hass/{id}/state/connection` | Bridge->HA | 1 | Yes | On change | 7.3 connection |
| `drone_hass/{id}/state/flight` | Bridge->HA | 1 | Yes | On change | 7.3 flight |
| `drone_hass/{id}/state/mission` | Bridge->HA | 1 | Yes | On change | 7.3 mission |
| `drone_hass/{id}/state/stream` | Bridge->HA | 1 | Yes | On change | 7.3 stream |
| `drone_hass/{id}/state/daa` | Bridge->HA | 1 | Yes | On change | 7.3 daa |
| `drone_hass/{id}/state/compliance` | Bridge->HA | 1 | Yes | On change | 7.3 compliance |
| `drone_hass/{id}/command/{action}` | HA->Bridge | 1 | No | On demand | 7.4 per command |
| `drone_hass/{id}/command/{action}/response` | Bridge->HA | 1 | No | Per command | 7.5 response |
| `drone_hass/{id}/missions/{mission_id}` | HA->Bridge | 1 | Yes | On change | 7.6 mission_def |
| `drone_hass/{id}/compliance/flight_log` | Bridge->HA | 1 | No | Per flight | 7.7 flight_log |
| `drone_hass/{id}/compliance/daa_events` | Bridge->HA | 1 | No | Per event | 7.7 daa_events |
| `drone_hass/{id}/compliance/weather_log` | Bridge->HA | 1 | No | Per decision | 7.7 weather_log |
| `drone_hass/{id}/compliance/personnel_log` | Bridge->HA | 1 | No | Per change | 7.7 personnel_log |
| `drone_hass/{id}/compliance/safety_gate` | Bridge->HA | 1 | No | Per launch attempt | 7.7 safety_gate |

---

## 9. Implementation Notes for the HA Expert

### 9.1 Entity Creation from MQTT

The HA integration subscribes to `drone_hass/{drone_id}/#` and creates entities by mapping topics to platforms:

- `telemetry/*` -> `sensor` platform (numeric values, enums)
- `state/connection` -> `binary_sensor` (connectivity device class)
- `state/flight` -> `sensor` (enum) + `binary_sensor` (airborne = flight in {airborne, returning_home})
- `state/mission` -> `sensor` (mission_status attribute comes from status field)
- `daa/*` -> `sensor` (contact count), `binary_sensor` (daa_healthy)
- `compliance/*` -> write to HA's persistent_notification or a dedicated compliance entity

### 9.2 MQTT Publish ACL

For security (Section 13 of architecture), the MQTT ACL should restrict:
- HA client can PUBLISH to: `drone_hass/+/command/#` and `drone_hass/+/missions/#`
- HA client can SUBSCRIBE to: `drone_hass/#`
- Bridge client can PUBLISH to: `drone_hass/+/telemetry/#`, `drone_hass/+/state/#`, `drone_hass/+/daa/#`, `drone_hass/+/compliance/#`, `drone_hass/+/command/+/response`
- Bridge client can SUBSCRIBE to: `drone_hass/+/command/#` and `drone_hass/+/missions/#`

### 9.3 Recorder Impact

At the publish rates specified:
- `telemetry/flight` at 1 Hz = 86,400 state changes/day per entity. **Use `recorder: exclude` for the raw flight telemetry entity** or create separate `_display` entities that update at 0.2 Hz.
- `telemetry/position` at 0.1 Hz = 8,640 state changes/day. Acceptable for device_tracker.
- `telemetry/battery` at 0.2 Hz = 17,280 state changes/day. Acceptable.
- All `state/*` topics update only on change. Minimal recorder impact.

Recommendation: the integration should register entities with appropriate `entity_category` and `should_poll: False`. Flight telemetry sensors that update at 1 Hz should be created with `entity_registry_enabled_default=False` or excluded from the default recorder configuration.

### 9.4 Timestamp Handling

All MQTT payloads include `timestamp` as Unix epoch seconds (UTC). The HA integration should use this as the entity's `last_updated` value rather than the MQTT receipt time, to correctly reflect when the measurement was taken (especially relevant if there is network latency between bridge and broker).
