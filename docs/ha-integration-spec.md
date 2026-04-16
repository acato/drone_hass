# drone_hass Home Assistant Integration Design Specification

## 1. MQTT Integration Pattern

### Architecture Decision: Custom Integration with Own MQTT Client (aiomqtt)

**Recommendation: Custom integration (`custom_components/drone_hass/`) with its own MQTT subscriptions via HA's built-in MQTT component, NOT a standalone aiomqtt client.**

This is the third option that the architecture diagram shows as "aiomqtt" but which should actually use `homeassistant.components.mqtt` -- HA's managed MQTT client. Here is why.

**Option A: HA Built-in MQTT Discovery (auto-discovery payloads)**

The bridge would publish HA MQTT discovery config messages to `homeassistant/<platform>/drone_hass_<id>/<entity>/config` and HA would auto-create entities.

Pros:
- Zero custom integration code for entity creation
- Entities appear automatically when bridge publishes discovery
- Works with any MQTT broker HA is already connected to
- Native availability via MQTT LWT

Cons:
- No coordinator pattern -- each entity independently subscribes to its own topic
- Cannot implement the correlation-ID command/response pattern (services need to publish a command, then await a response on a different topic with a matching UUID)
- Cannot enforce config flow with legal acknowledgment, operational area upload, or compliance mode selection
- Cannot gate entity creation behind validation steps
- No place to put the state machine logic for the patrol workflow
- Every entity is a dumb MQTT sensor -- no shared state, no cross-entity intelligence (e.g., "make device_tracker unavailable when connection state is offline")
- Cannot fire custom HA events from MQTT messages
- DAA traffic data (variable number of contacts) does not map to a fixed set of discovery entities

**Verdict: Not viable.** The integration needs application logic that MQTT discovery cannot express.

**Option B: Custom integration with standalone aiomqtt client**

The integration bundles its own MQTT connection, independent of HA's MQTT integration.

Pros:
- Full control over connection lifecycle
- Can implement any subscription/publish pattern

Cons:
- Duplicate MQTT connection (HA already has one via the MQTT integration)
- Must reimplement connection management, reconnection, TLS, authentication -- all things HA's MQTT integration already handles
- User must configure MQTT credentials in two places
- Cannot use `mqtt.subscribe` / `mqtt.publish` HA services from automations to interact with the drone topics
- Violates HA integration best practices

**Verdict: Unnecessary complexity.**

**Option C (Selected): Custom integration using `homeassistant.components.mqtt` subscription API**

The integration uses HA's internal MQTT component API (`mqtt.async_subscribe`, `mqtt.async_publish`) which shares the existing broker connection the user has already configured.

Pros:
- Single MQTT connection (HA's existing broker config)
- No duplicate credentials
- Full coordinator pattern with shared state
- Can implement correlation-ID command/response
- Config flow with legal acknowledgment, validation, operational area
- Can fire custom HA events
- Can create entities dynamically (DAA contacts)
- Follows HA integration architecture patterns (like `zha`, `zwave_js`)
- Reconnection, TLS, authentication handled by HA's MQTT component

Cons:
- Requires HA's MQTT integration to be set up (reasonable prerequisite)
- Slightly more complex than pure discovery
- Must handle the case where the MQTT integration is not loaded

**This is the standard pattern for HA integrations that consume MQTT but need application logic** -- the same approach used by `tasmota`, `esphome` (for BLE proxy data), and several HACS integrations.

### How Entity Creation Works

The bridge does NOT publish HA discovery configs. The `drone_hass` integration creates entities from its own internal entity definitions when a config entry is set up. Entity availability is driven by the coordinator's state, not by individual MQTT retained messages.

Flow:
1. User adds integration via config flow
2. Config flow discovers available drones by subscribing to `drone_hass/+/state/connection` and collecting drone IDs that publish `"online"`
3. User selects a drone, completes compliance and legal steps
4. Integration creates a `DroneMqttCoordinator` for that drone
5. Coordinator subscribes to `drone_hass/{drone_id}/#`
6. Coordinator maintains a single state dict, updated by incoming MQTT messages
7. Platform setup (`sensor.py`, `binary_sensor.py`, etc.) creates entities that read from the coordinator's state dict
8. Entities call `self.coordinator.async_request_refresh()` is not needed -- coordinator pushes updates via `async_write_ha_state()` callbacks

### Coordinator Pattern with MQTT Subscriptions

```python
class DroneMqttCoordinator:
    """
    Central state holder. Subscribes once to drone_hass/{drone_id}/#,
    routes messages to internal state buckets, and notifies entity
    listeners on change.
    """

    def __init__(self, hass, entry, drone_id):
        self.hass = hass
        self.drone_id = drone_id
        self.data = {
            "connection": "offline",
            "flight": {},
            "battery": {},
            "gimbal": {},
            "camera": {},
            "signal": {},
            "position": {},
            "mission": {},
            "stream": {},
            "daa": {},
            "daa_traffic": [],  # List of current contacts
            "compliance": {},
        }
        self._entities: list[DronEntity] = []
        self._unsubscribe: list[Callable] = []
        self._pending_commands: dict[str, asyncio.Future] = {}
        self._ready: asyncio.Event = asyncio.Event()

    async def async_start(self):
        """Subscribe to all drone topics, then mark coordinator ready."""
        unsub = await mqtt.async_subscribe(
            self.hass,
            f"drone_hass/{self.drone_id}/#",
            self._on_message,
            qos=1,
            encoding="utf-8",            # decode bytes -> str for the handler
        )
        self._unsubscribe.append(unsub)
        self._ready.set()                # gate service calls until subscribed

    # Topics whose payloads are plain strings, never JSON. Keep this tuple in
    # sync with the wire contract in docs/mavlink-mqtt-contract.md.
    _NON_JSON_TOPIC_SUFFIXES = ("/state/connection",)   # LWT publishes "offline"/"online"

    @callback
    def _on_message(self, msg: ReceiveMessage) -> None:
        """Route MQTT message to state bucket, notify entities.

        Sync @callback because the body does no I/O. Per-message fan-out to all
        entities is intentionally simple: at ~30 entities x 10 Hz telemetry that
        is ~300 cheap state-machine writes per second. Per-entity topic routing
        is a known optimisation deferred until profiling justifies it.
        """
        topic = msg.topic
        raw: str = msg.payload                          # str because of encoding="utf-8"

        if any(topic.endswith(s) for s in self._NON_JSON_TOPIC_SUFFIXES):
            # Plain-string payload (LWT, simple state).
            parts = topic.split("/")
            # drone_hass/{drone_id}/state/connection -> parts[-2]=state, parts[-1]=connection
            self.data.setdefault(parts[-2], {})[parts[-1]] = raw
        else:
            # JSON payload — guard against malformed publishes from a misbehaving
            # bridge or a third-party publisher with broker write access.
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError:
                _LOGGER.warning("Malformed JSON on %s: %r", topic, raw[:200])
                return

            if topic.endswith("/telemetry/flight"):
                self.data["flight"] = payload
            elif topic.endswith("/telemetry/battery"):
                self.data["battery"] = payload
            # ... etc for all topic suffixes
            elif "/command/" in topic and topic.endswith("/response"):
                cmd_id = payload.get("id")
                fut = self._pending_commands.get(cmd_id)
                if fut and not fut.done():
                    fut.set_result(payload)

        for entity in self._entities:
            entity.async_write_ha_state()

    async def async_send_command(self, action, params=None, timeout=10):
        """Publish command with correlation ID, await response."""
        await self._ready.wait()                # do not publish before subscription is live
        cmd_id = str(uuid.uuid4())
        future = self.hass.loop.create_future()
        self._pending_commands[cmd_id] = future

        payload = {"id": cmd_id, "params": params or {}}
        await mqtt.async_publish(
            self.hass,
            f"drone_hass/{self.drone_id}/command/{action}",
            json.dumps(payload),
            qos=1,
        )

        try:
            result = await asyncio.wait_for(future, timeout=timeout)
            if not result.get("success"):
                raise HomeAssistantError(result.get("error", "Unknown error"))
            return result
        except asyncio.TimeoutError:
            raise HomeAssistantError(
                f"Command '{action}' timed out after {timeout}s"
            )
        finally:
            self._pending_commands.pop(cmd_id, None)

    async def async_stop(self):
        for unsub in self._unsubscribe:
            unsub()
```

### Connection Lifecycle

**MQTT broker goes down:**
- HA's MQTT component handles reconnection automatically
- During disconnect, all `async_publish` calls raise; service calls return errors to the caller
- Entity states freeze at last known value (HA's default behavior when no updates arrive)
- Entities do NOT go unavailable just because the broker is down -- they go unavailable when the bridge heartbeat times out (see below)

**Bridge goes offline (crash, network loss, restart):**
- Bridge's MQTT Last Will and Testament publishes `"offline"` to `drone_hass/{drone_id}/state/connection`
- Coordinator receives this, sets `self.data["connection"] = "offline"`
- All entities check `self.coordinator.data["connection"]` in their `available` property -- they all return `False`, marking every entity as unavailable
- If the bridge comes back and publishes `"online"`, entities become available again
- If HA never receives the LWT (broker was also down), the coordinator runs a watchdog: if no message is received on any topic for 30 seconds, it sets connection to `"offline"` locally

**Bridge restarts mid-flight:**
- Bridge reconnects to both MAVLink and MQTT
- Bridge publishes `"online"` on connection topic
- Bridge reads current aircraft state from MAVLink and publishes fresh telemetry/state
- HA entities recover automatically from the fresh state publications
- The in-progress mission continues on the flight controller regardless -- MAVLink missions are uploaded to the FC and execute autonomously
- Mission status entity recovers when bridge publishes current `state/mission`

**HA restarts while drone is airborne:**
- On HA restart, `drone_hass` integration loads, coordinator subscribes to topics
- Retained MQTT messages for `state/*` topics are delivered immediately (QoS 1, retain=true)
- Coordinator populates from retained state
- Non-retained telemetry topics begin flowing at their normal rate (1 Hz flight, 0.2 Hz battery)
- Entities become available within seconds of HA start
- Any in-progress automation is lost (HA does not persist running automations across restarts) -- but the mission continues on the flight controller and will RTL on completion regardless
- The bridge's compliance recorder captures the full flight independently of HA

---

## 2. Entity Design (Complete)

### Device: The Drone

**HA Device Registry entry:**
```python
device_info = {
    "identifiers": {(DOMAIN, drone_id)},
    "name": f"Drone {drone_id}",
    "manufacturer": "drone_hass",
    "model": "MAVLink Aircraft",
    "sw_version": bridge_version,  # from bridge heartbeat
}
```

Entity ID patterns use `{name}` which is the user-provided name from config flow, slugified. Example: if the user names the drone "patrol", entities are `sensor.patrol_battery`, etc.

#### Sensors

| Entity ID | Device Class | State Class | Unit | Icon | Source Topic / Field | Update Freq | Entity Category | Recorder Strategy | Availability |
|-----------|-------------|-------------|------|------|---------------------|-------------|-----------------|-------------------|-------------|
| `sensor.{name}_battery` | `battery` | `measurement` | `%` | `mdi:battery` | `telemetry/battery` -> `charge_percent` | 0.2 Hz | default | Keep -- valuable for long-term battery health tracking | bridge online |
| `sensor.{name}_battery_voltage` | `voltage` | `measurement` | `mV` | `mdi:flash-triangle` | `telemetry/battery` -> `voltage_mv` | 0.2 Hz | diagnostic | Keep -- battery health | bridge online |
| `sensor.{name}_battery_current` | `current` | `measurement` | `mA` | `mdi:current-dc` | `telemetry/battery` -> `current_ma` | 0.2 Hz | diagnostic | Exclude from recorder (only useful in-flight) | bridge online |
| `sensor.{name}_battery_temperature` | `temperature` | `measurement` | `C` | `mdi:thermometer` | `telemetry/battery` -> `temperature_c` | 0.2 Hz | diagnostic | Keep -- battery thermal tracking | bridge online |
| `sensor.{name}_flight_time_remaining` | `duration` | None | `s` | `mdi:timer-sand` | `telemetry/battery` -> `flight_time_remaining_s` | 0.2 Hz | default | Exclude from recorder | bridge online |
| `sensor.{name}_altitude` | `distance` | None | `m` | `mdi:arrow-up-bold` | `telemetry/flight` -> `alt` | 1 Hz | default | Exclude from recorder (high frequency, compliance recorder captures this) | bridge online |
| `sensor.{name}_ground_speed` | `speed` | None | `m/s` | `mdi:speedometer` | `telemetry/flight` -> `ground_speed` | 1 Hz | default | Exclude from recorder | bridge online |
| `sensor.{name}_heading` | None | None | `degrees` | `mdi:compass` | `telemetry/flight` -> `heading` | 1 Hz | default | Exclude from recorder | bridge online |
| `sensor.{name}_gps_satellites` | None | None | None | `mdi:satellite-variant` | `telemetry/flight` -> `satellite_count` | 1 Hz | diagnostic | Exclude from recorder | bridge online |
| `sensor.{name}_gps_fix` | None | None | None | `mdi:crosshairs-gps` | `telemetry/flight` -> `gps_fix` | 1 Hz | diagnostic | Exclude from recorder | bridge online |
| `sensor.{name}_signal_rssi` | `signal_strength` | `measurement` | `dBm` | `mdi:wifi` | `telemetry/signal` -> `rssi` | 1 Hz | diagnostic | Exclude from recorder | bridge online |
| `sensor.{name}_flight_mode` | `enum` | None | None | `mdi:airplane` | `telemetry/flight` -> `flight_mode` | on change | default | Keep -- useful for flight history. Options: `STABILIZE`, `LOITER`, `AUTO`, `GUIDED`, `RTL`, `LAND`, `BRAKE` | bridge online |
| `sensor.{name}_mission_status` | `enum` | None | None | `mdi:map-marker-path` | `state/mission` -> `status` | on change | default | Keep -- mission history. Options: `idle`, `uploading`, `executing`, `paused`, `completed`, `error` | bridge online |
| `sensor.{name}_mission_progress` | None | None | `%` | `mdi:progress-check` | `state/mission` -> `progress` (computed: `current_waypoint / total_waypoints * 100`) | on change | default | Exclude from recorder | bridge online AND mission active |
| `sensor.{name}_daa_contacts` | None | None | None | `mdi:airplane-alert` | `state/daa` -> `contacts` | on change | default | Keep -- traffic exposure history | bridge online |
| `sensor.{name}_daa_threat_level` | `enum` | None | None | `mdi:shield-alert` | derived from `daa/traffic` -- highest threat among active contacts | on change | default | Keep. Options: `clear`, `advisory`, `warning`, `critical` | bridge online |
| `sensor.{name}_operational_mode` | `enum` | None | None | `mdi:shield-check` | `state/compliance` -> `mode` | on change | default | Keep. Options: `part_107`, `part_108` | bridge online |
| `sensor.{name}_flight_state` | `enum` | None | None | `mdi:drone` | `state/flight` | on change | default | Keep -- flight history. Options: `landed`, `airborne`, `returning_home`, `landing` | bridge online |

**Notes on `state_class: measurement`:**
- Applied ONLY to sensors where HA's long-term statistics (mean/min/max over time) are meaningful: battery percentage, voltage, temperature, RSSI
- NOT applied to altitude, speed, heading -- these are transient flight telemetry that changes meaning when the drone is not flying. A "mean altitude" statistic is meaningless.
- NOT applied to enum sensors (flight_mode, mission_status, etc.)

#### Binary Sensors

| Entity ID | Device Class | Icon (on/off) | Source | Entity Category | Recorder | Availability |
|-----------|-------------|---------------|--------|-----------------|----------|-------------|
| `binary_sensor.{name}_connected` | `connectivity` | `mdi:lan-connect` / `mdi:lan-disconnect` | `state/connection` == `"online"` | diagnostic | Keep | Always available (this IS the availability signal) |
| `binary_sensor.{name}_airborne` | None | `mdi:drone` / `mdi:drone` | `state/flight` in (`airborne`, `returning_home`) | default | Keep -- flight event tracking | bridge online |
| `binary_sensor.{name}_armed` | None | `mdi:lock-open` / `mdi:lock` | `telemetry/flight` -> `armed` | default | Keep | bridge online |
| `binary_sensor.{name}_recording` | `running` | `mdi:record-rec` / `mdi:record` | `telemetry/camera` -> `is_recording` | default | Exclude | bridge online |
| `binary_sensor.{name}_streaming` | None | `mdi:video` / `mdi:video-off` | `state/stream` -> `is_streaming` | default | Exclude | bridge online |
| `binary_sensor.{name}_daa_healthy` | `problem` (inverted) | `mdi:shield-check` / `mdi:shield-alert` | `state/daa` -> `healthy` | default | Keep | bridge online |
| `binary_sensor.{name}_gps_lock` | None | `mdi:crosshairs-gps` / `mdi:crosshairs-question` | `telemetry/flight` -> `gps_fix` >= 3 | diagnostic | Exclude | bridge online |
| `binary_sensor.{name}_fc_on_duty` | None | `mdi:account-check` / `mdi:account-off` | `state/compliance` -> `fc_on_duty` | default | Keep -- personnel tracking | bridge online |
| `binary_sensor.{name}_operational_area_valid` | None | `mdi:map-check` / `mdi:map-marker-alert` | `state/compliance` -> `operational_area_valid` | diagnostic | Keep | bridge online |

Note on `binary_sensor.{name}_daa_healthy`: Uses device class `problem` with inverted logic. When DAA is healthy, `state/daa -> healthy` is `true`, so the binary sensor state is `off` (no problem). When DAA is unhealthy, state is `on` (problem detected). This gives the correct icon/color semantics in the HA frontend.

#### Camera

| Entity ID | Source | Notes |
|-----------|--------|-------|
| `camera.{name}_live` | RTSP URL from `state/stream` -> `rtsp_url`, proxied through go2rtc/mediamtx | Entity availability tied to `state/stream -> is_streaming`. When not streaming, entity shows a static "Stream Inactive" placeholder or last frame. WebRTC negotiation handled by go2rtc integration. |

The camera entity does not subscribe to an MQTT image topic. It uses HA's stream integration to consume the RTSP URL provided by the bridge. The RTSP URL is configured during config flow (media server step) and updated if the bridge publishes a new URL in `state/stream`.

#### Device Tracker

| Entity ID | Source | Notes |
|-----------|--------|-------|
| `device_tracker.{name}` | `telemetry/position` -> `lat`, `lon` | Published at 0.1 Hz (every 10 seconds) specifically to avoid recorder bloat. Separate from the 1 Hz `telemetry/flight` topic. When landed, position is static so the 0.1 Hz rate produces minimal DB writes. Source type: `gps`. Attributes include `altitude` from the position payload. |

### Device: The Dock (ESPHome -- External)

The dock is NOT part of the `drone_hass` integration. It is an independent ESPHome device with its own entities. The `drone_hass` automation references these entities but does not create them.

**Documented interface (entities the automation depends on):**

| Entity ID | Type | Device Class | Notes |
|-----------|------|-------------|-------|
| `cover.drone_dock_lid` | Cover | `garage` | Open/close/stop. ESPHome cover component with position. |
| `binary_sensor.dock_lid_open` | Binary Sensor | `opening` | Limit switch: fully open |
| `binary_sensor.dock_lid_closed` | Binary Sensor | `opening` | Limit switch: fully closed |
| `binary_sensor.dock_pad_clear` | Binary Sensor | `occupancy` | ToF/IR: drone present on pad (inverted -- `on` = pad is clear) |
| `binary_sensor.dock_smoke` | Binary Sensor | `smoke` | Smoke detector |
| `sensor.dock_temperature` | Sensor | `temperature` | Interior temp (C) |
| `sensor.dock_battery_zone_temp` | Sensor | `temperature` | Near-drone temp (C) |
| `sensor.dock_humidity` | Sensor | `humidity` | Interior RH (%) |
| `switch.dock_heater` | Switch | None | PTC heater relay |
| `switch.dock_fan` | Switch | None | Ventilation fan relay |
| `switch.dock_charger_power` | Switch | `outlet` | Smart outlet for charger |
| `sensor.dock_power_status` | Sensor | None | Mains/UPS status |
| `sensor.dock_wind_speed` | Sensor | `wind_speed` | Anemometer (mph) |
| `binary_sensor.dock_rain` | Binary Sensor | `moisture` | Rain gauge/sensor |

### Device: The Bridge Service

The bridge itself registers as a separate HA device to expose its health and config state. These entities are created by `drone_hass` from the bridge's MQTT heartbeat.

**HA Device Registry entry:**
```python
device_info = {
    "identifiers": {(DOMAIN, f"{drone_id}_bridge")},
    "name": f"Drone Bridge {drone_id}",
    "manufacturer": "drone_hass",
    "model": "MAVLink-MQTT Bridge",
    "sw_version": bridge_version,
    "via_device": (DOMAIN, drone_id),  # linked to drone device
}
```

| Entity ID | Platform | Device Class | State Class | Unit | Icon | Source | Update | Entity Category | Recorder | Availability |
|-----------|----------|-------------|-------------|------|------|--------|--------|-----------------|----------|-------------|
| `binary_sensor.{name}_bridge_connected` | binary_sensor | `connectivity` | -- | -- | `mdi:bridge` | `state/connection` | on change | diagnostic | Keep | always |
| `sensor.{name}_bridge_uptime` | sensor | `duration` | `total_increasing` | `s` | `mdi:clock-outline` | bridge heartbeat payload -> `uptime_s` | 60s | diagnostic | Exclude | bridge online |
| `sensor.{name}_compliance_mode` | sensor | `enum` | -- | -- | `mdi:gavel` | `state/compliance` -> `mode` | on change | config | Keep | bridge online |
| `sensor.{name}_fc_id` | sensor | -- | -- | -- | `mdi:account-hard-hat` | `state/compliance` -> `fc_id` | on change | default | Keep | bridge online |
| `sensor.{name}_mavlink_status` | sensor | `enum` | -- | -- | `mdi:connection` | bridge heartbeat -> `mavlink_connected` | 10s | diagnostic | Keep. Options: `connected`, `disconnected`, `degraded` | bridge online |

---

## 3. Service Design (Complete)

All services are in the `drone_hass` domain. All services require a `device_id` or `entity_id` target to identify which drone to command (supporting multi-drone). The integration resolves the target to a `drone_id` and coordinator.

### Command/Response Pattern

Every service:
1. Validates the coordinator is online (`data["connection"] == "online"`)
2. Generates a UUID correlation ID
3. Publishes to `drone_hass/{drone_id}/command/{action}` with `{"id": uuid, "params": {...}}`
4. Awaits response on `drone_hass/{drone_id}/command/{action}/response` with matching `id`
5. Returns success or raises `HomeAssistantError` on failure/timeout

### Service Definitions

#### `drone_hass.execute_mission`

| Attribute | Value |
|-----------|-------|
| Description | Upload and execute a waypoint mission |
| Fields | `mission_id` (string, required) -- must match a mission defined in `drone_hass/{drone_id}/missions/{mission_id}` |
| MQTT Command | `drone_hass/{drone_id}/command/execute_mission` with `{"id": uuid, "params": {"mission_id": "full_perimeter"}}` |
| Response Wait | 30s timeout (mission upload + arm + takeoff can take time) |
| Bridge Offline | Raises `ServiceCallError("Bridge is offline")` |
| Modes | Part 107: bridge requires valid authorization token (issued after RPIC tap). Part 108: bridge requires FC on duty + DAA healthy + safety gates. In both cases the bridge's ComplianceGate validates before executing. |
| Notes | The bridge validates the mission against the operational area before upload. If validation fails, the response includes the specific rejection reason. |

#### `drone_hass.return_to_home`

| Attribute | Value |
|-----------|-------|
| Description | Command Return to Launch |
| Fields | None |
| MQTT Command | `drone_hass/{drone_id}/command/return_to_home` |
| Response Wait | 10s |
| Bridge Offline | Raises error. Note: if bridge is offline, ArduPilot's GCS-loss failsafe will trigger RTL independently. |
| Modes | Available in all modes, at any time the drone is airborne. This is a safety command -- no compliance gate. |

#### `drone_hass.abort_mission`

| Attribute | Value |
|-----------|-------|
| Description | Immediately stop mission and hover in place (BRAKE mode) |
| Fields | None |
| MQTT Command | `drone_hass/{drone_id}/command/stop_mission` |
| Response Wait | 10s |
| Bridge Offline | Raises error |
| Modes | Available in all modes. Flight Coordinator override command in Part 108. |

#### `drone_hass.takeoff`

| Attribute | Value |
|-----------|-------|
| Description | Arm motors and take off to configured hover altitude |
| Fields | `altitude` (float, optional, default from config, meters AGL) |
| MQTT Command | `drone_hass/{drone_id}/command/takeoff` with `{"id": uuid, "params": {"altitude": 10.0}}` |
| Response Wait | 15s (arm pre-checks + motor spin-up + climb) |
| Bridge Offline | Raises error |
| Modes | Part 107: requires authorization token. Part 108: requires ComplianceGate pass. Bridge enforces this, not HA. |

#### `drone_hass.land`

| Attribute | Value |
|-----------|-------|
| Description | Land at current position |
| Fields | None |
| MQTT Command | `drone_hass/{drone_id}/command/land` |
| Response Wait | 10s (for ACK; actual landing takes longer) |
| Bridge Offline | Raises error |
| Modes | All modes. Safety command. |

#### `drone_hass.pause_mission`

| Attribute | Value |
|-----------|-------|
| Description | Pause executing mission, hold position (LOITER) |
| Fields | None |
| MQTT Command | `drone_hass/{drone_id}/command/pause_mission` |
| Response Wait | 10s |
| Bridge Offline | Raises error |
| Modes | All modes |

#### `drone_hass.resume_mission`

| Attribute | Value |
|-----------|-------|
| Description | Resume a paused mission from current waypoint |
| Fields | None |
| MQTT Command | `drone_hass/{drone_id}/command/resume_mission` |
| Response Wait | 10s |
| Bridge Offline | Raises error |
| Modes | All modes |

#### `drone_hass.take_photo`

| Attribute | Value |
|-----------|-------|
| Description | Capture a single photo |
| Fields | None |
| MQTT Command | `drone_hass/{drone_id}/command/take_photo` |
| Response Wait | 10s |
| Bridge Offline | Raises error |
| Modes | All modes. No compliance gate -- camera commands are non-safety-critical. |

#### `drone_hass.start_recording`

| Attribute | Value |
|-----------|-------|
| Description | Begin video recording on camera |
| Fields | None |
| MQTT Command | `drone_hass/{drone_id}/command/start_recording` |
| Response Wait | 10s |
| Bridge Offline | Raises error |
| Modes | All modes |

#### `drone_hass.stop_recording`

| Attribute | Value |
|-----------|-------|
| Description | Stop video recording |
| Fields | None |
| MQTT Command | `drone_hass/{drone_id}/command/stop_recording` |
| Response Wait | 10s |
| Bridge Offline | Raises error |
| Modes | All modes |

#### `drone_hass.start_stream`

| Attribute | Value |
|-----------|-------|
| Description | Start RTSP live stream from camera to media server |
| Fields | None |
| MQTT Command | `drone_hass/{drone_id}/command/start_stream` |
| Response Wait | 15s (stream negotiation can take a moment) |
| Bridge Offline | Raises error |
| Modes | All modes |

#### `drone_hass.stop_stream`

| Attribute | Value |
|-----------|-------|
| Description | Stop live stream |
| Fields | None |
| MQTT Command | `drone_hass/{drone_id}/command/stop_stream` |
| Response Wait | 10s |
| Bridge Offline | Raises error |
| Modes | All modes |

#### `drone_hass.set_gimbal`

| Attribute | Value |
|-----------|-------|
| Description | Set gimbal pitch angle |
| Fields | `pitch` (float, required, range -90.0 to +30.0 degrees), `mode` (string, optional, default `"YAW_FOLLOW"`, options: `"YAW_FOLLOW"`, `"YAW_LOCK"`) |
| MQTT Command | `drone_hass/{drone_id}/command/set_gimbal` with `{"id": uuid, "params": {"pitch": -45.0, "mode": "YAW_FOLLOW"}}` |
| Response Wait | 10s |
| Bridge Offline | Raises error |
| Modes | All modes |

#### `drone_hass.set_fc_on_duty`

| Attribute | Value |
|-----------|-------|
| Description | Toggle Flight Coordinator on-duty status |
| Fields | `on_duty` (boolean, required), `fc_id` (string, required -- identifier of the Flight Coordinator) |
| MQTT Command | `drone_hass/{drone_id}/command/set_fc_on_duty` with `{"id": uuid, "params": {"on_duty": true, "fc_id": "fc_alessandro"}}` |
| Response Wait | 10s |
| Bridge Offline | Raises error |
| Modes | Relevant for Part 108 mode. In Part 107 mode, the command succeeds but has no operational effect (logged for compliance). |
| Notes | Compliance recorder logs the personnel change with timestamp. |

#### `drone_hass.log_compliance_event`

| Attribute | Value |
|-----------|-------|
| Description | Write a compliance record to the sidecar |
| Fields | `event` (string, required), `details` (dict, optional) |
| MQTT Command | `drone_hass/{drone_id}/compliance/ha_event` (one-way publish, no response expected) |
| Response Wait | None (fire-and-forget, QoS 1) |
| Bridge Offline | Logs locally to HA logger as warning; message will be delivered when broker/bridge reconnects (QoS 1 with broker persistence) |
| Modes | All modes |

#### `drone_hass.set_operational_mode`

| Attribute | Value |
|-----------|-------|
| Description | Switch between Part 107 and Part 108 operating modes |
| Fields | `mode` (string, required, options: `"part_107"`, `"part_108"`) |
| MQTT Command | `drone_hass/{drone_id}/command/set_operational_mode` |
| Response Wait | 10s |
| Bridge Offline | Raises error |
| Modes | Cannot switch while airborne. Bridge rejects if drone is not landed. |
| Notes | Part 108 mode switch requires FC on duty and DAA healthy as preconditions. Bridge validates. |

---

## 4. Automation State Machine (HA Side)

This is the complete state machine for the alarm-triggered patrol workflow, designed to be implemented as an AppDaemon app or a complex HA automation with `choose`/`if` blocks. A blueprint is feasible for the simpler Part 107 path but an AppDaemon app is recommended for the full dual-mode state machine with proper error handling.

### States

```
IDLE
  |
  v (alarm trigger)
SAFETY_CHECK
  |
  +--> ABORTED (safety gate failed)
  |
  v (all gates pass)
DOCK_OPENING
  |
  +--> ABORTED (dock timeout / dock fault)
  |
  v (lid fully open)
AWAITING_AUTHORIZATION  [Part 107 only]
  |
  +--> ABORTED (RPIC ignores / timeout 120s)
  |
  v (RPIC taps LAUNCH)
LAUNCHING
  |
  +--> ABORTED (execute_mission fails / arm fails)
  |
  v (mission status -> "executing")
MISSION_ACTIVE
  |
  +--> FC_OVERRIDE (ABORT or RTH from Flight Coordinator)
  +--> ABORTED (mission error / link loss timeout)
  |
  v (mission status -> "completed" OR state/flight -> "returning_home")
RETURNING
  |
  v (state/flight -> "landed")
LANDED
  |
  v (delay 30s for props to stop + cooldown)
DOCK_CLOSING
  |
  +--> DOCK_FAULT (close timeout / obstruction)
  |
  v (lid fully closed)
COMPLETE
```

### Detailed State Transitions

#### IDLE -> SAFETY_CHECK

**Trigger:** `alarm_control_panel.home` state changes to `triggered`

**Guard:** Not already in any non-IDLE state (prevents re-entrant triggers while a mission is active). Implemented via an `input_boolean.drone_patrol_active` helper or a state variable in AppDaemon.

#### SAFETY_CHECK

**Entities checked (all modes):**

| Check | Entity | Condition | Failure Action |
|-------|--------|-----------|----------------|
| Bridge online | `binary_sensor.{name}_connected` | `on` | ABORT: "Bridge offline" |
| Not already airborne | `binary_sensor.{name}_airborne` | `off` | ABORT: "Already airborne" |
| Battery sufficient | `sensor.{name}_battery` | > 30% | ABORT: "Battery too low ({x}%)" |
| GPS lock | `binary_sensor.{name}_gps_lock` | `on` | ABORT: "No GPS lock" |
| Dock connected | `cover.drone_dock_lid` | not `unavailable` | ABORT: "Dock offline" |
| No smoke | `binary_sensor.dock_smoke` | `off` | ABORT: "Smoke detected in dock" |
| Dock temperature | `sensor.dock_temperature` | 5-40 C | ABORT: "Dock temp out of range" |
| Wind | `sensor.dock_wind_speed` | < 15 mph | ABORT: "Wind too high ({x} mph)" |
| Rain | `binary_sensor.dock_rain` | `off` | ABORT: "Rain detected" |
| DAA healthy | `binary_sensor.{name}_daa_healthy` | `on` | ABORT: "DAA system unhealthy" |
| Operational area valid | `binary_sensor.{name}_operational_area_valid` | `on` | ABORT: "Operational area invalid" |

**Additional checks for Part 108 mode:**

| Check | Entity | Condition | Failure Action |
|-------|--------|-----------|----------------|
| FC on duty | `binary_sensor.{name}_fc_on_duty` | `on` | ABORT: "No Flight Coordinator on duty" |
| Mode confirmed | `sensor.{name}_operational_mode` | `part_108` | ABORT: "Not in Part 108 mode" |

**On all gates pass:**
- Call `drone_hass.log_compliance_event` with event `"safety_check_passed"` and all gate values
- Select mission profile based on trigger source (which alarm sensor, which zone)
- Transition to DOCK_OPENING

**On any gate failure:**
- Call `drone_hass.log_compliance_event` with event `"safety_check_failed"` and failure reason
- Send notification to RPIC/FC: "Patrol aborted: {reason}"
- Transition to ABORTED -> IDLE

#### DOCK_OPENING

**Action:** `cover.open_cover` on `cover.drone_dock_lid`

**Wait:** `binary_sensor.dock_lid_open` becomes `on`, timeout 30 seconds

**On success:** Transition to AWAITING_AUTHORIZATION (Part 107) or LAUNCHING (Part 108)

**On timeout:**
- Log compliance event `"dock_open_failed"`
- Notify: "Dock lid failed to open"
- Transition to ABORTED -> IDLE

#### AWAITING_AUTHORIZATION (Part 107 Only)

**Action:** Send actionable push notification:
```yaml
service: notify.mobile_app_pilot_phone
data:
  title: "Perimeter Alert"
  message: >
    {{ trigger_source }} alarm. Battery {{ battery }}%.
    Wind {{ wind }} mph. DAA healthy. Dock open.
    Mission: {{ mission_id }}.
  data:
    actions:
      - action: "LAUNCH_DRONE"
        title: "LAUNCH DRONE"
      - action: "IGNORE_PATROL"
        title: "Ignore"
    push:
      sound:
        name: default
        critical: 1  # iOS critical notification -- bypasses DND
        volume: 1.0
```

**Wait:** `mobile_app_notification_action` event with action `"LAUNCH_DRONE"`, timeout 120 seconds

**On LAUNCH_DRONE:**
- Log compliance event `"rpic_authorized"` with timestamp
- Transition to LAUNCHING

**On IGNORE_PATROL:**
- Log compliance event `"rpic_declined"` with timestamp
- Close dock lid
- Transition to ABORTED -> IDLE

**On timeout:**
- Log compliance event `"rpic_timeout"`
- Close dock lid
- Transition to ABORTED -> IDLE

**Part 108 mode skips this state entirely.** After DOCK_OPENING, it transitions directly to LAUNCHING with compliance event `"autonomous_launch_authorized"`.

#### LAUNCHING

**Actions (sequential):**
1. `drone_hass.start_stream` (start video feed)
2. `drone_hass.start_recording` (begin evidence capture)
3. `drone_hass.execute_mission` with `mission_id` from the selection step

**Wait:** `sensor.{name}_mission_status` becomes `"executing"`, timeout 30 seconds

**On success:**
- Log compliance event `"mission_started"` with mission_id, weather, battery
- If Part 108: send monitoring notification to FC with ABORT/RTH buttons
- Transition to MISSION_ACTIVE

**On failure (execute_mission raises error or timeout):**
- Log compliance event `"launch_failed"` with error
- `drone_hass.stop_stream`
- Close dock lid
- Notify: "Launch failed: {error}"
- Transition to ABORTED -> IDLE

#### MISSION_ACTIVE

**Monitoring (parallel):**

1. **Mission completion:** Wait for `sensor.{name}_mission_status` == `"completed"`, timeout 10 minutes
2. **FC override (Part 108):** Listen for `mobile_app_notification_action` with `"ABORT_MISSION"` or `"RTH_NOW"`
3. **Link loss:** Watch `binary_sensor.{name}_connected` -- if `off` for > 15 seconds during mission, log event but do NOT take action (ArduPilot handles GCS loss with RTL failsafe)
4. **DAA alert:** Watch `sensor.{name}_daa_threat_level` -- if `"critical"`, log compliance event (avoidance is handled by ArduPilot's AP_Avoidance, not HA)

**On mission completed:**
- Transition to RETURNING

**On FC ABORT:**
- Call `drone_hass.abort_mission`
- Log compliance event `"fc_abort"` with fc_id
- Transition to RETURNING (drone will be hovering; follow with RTH)
- Call `drone_hass.return_to_home`

**On FC RTH:**
- Call `drone_hass.return_to_home`
- Log compliance event `"fc_rth"` with fc_id
- Transition to RETURNING

**On mission error:**
- Log compliance event `"mission_error"` with error from `state/mission -> error`
- ArduPilot will handle the flight safety (RTL/land depending on failsafe config)
- Transition to RETURNING

**On 10-minute timeout:**
- Log compliance event `"mission_timeout"`
- Call `drone_hass.return_to_home`
- Transition to RETURNING

#### RETURNING

**Wait:** `sensor.{name}_flight_state` becomes `"landed"`, timeout 5 minutes

This state covers both the RTL flight and the landing. The drone is autonomously returning.

**On landed:**
- `drone_hass.stop_recording`
- `drone_hass.stop_stream`
- Log compliance event `"landed"` with flight duration, max altitude, battery remaining
- Transition to LANDED

**On timeout (5 min, drone hasn't landed):**
- Log compliance event `"landing_timeout"` -- CRITICAL alert
- Send critical notification: "Drone has not landed after 5 minutes. Check immediately."
- Remain in RETURNING (do not attempt to close dock)
- This requires human intervention

#### LANDED

**Action:** Delay 30 seconds (allow props to fully stop, ESC disarm, cooling)

**Transition to:** DOCK_CLOSING

#### DOCK_CLOSING

**Pre-check:** Verify `binary_sensor.dock_pad_clear` is `off` (pad is occupied = drone is on pad). If pad appears clear (drone not on pad), something is wrong -- do NOT close lid.

**Action:** `cover.close_cover` on `cover.drone_dock_lid`

**Wait:** `binary_sensor.dock_lid_closed` becomes `on`, timeout 30 seconds

**On success:**
- Log compliance event `"patrol_complete"` with full summary
- Transition to COMPLETE -> IDLE

**On timeout / obstruction:**
- Log compliance event `"dock_close_failed"`
- Notify: "Dock lid failed to close. Check for obstruction."
- Transition to DOCK_FAULT (manual intervention needed)

#### COMPLETE

Final compliance log with full mission summary. Reset `input_boolean.drone_patrol_active` to `off`. Return to IDLE.

### HA Helper Entities for State Machine

| Entity | Type | Purpose |
|--------|------|---------|
| `input_boolean.drone_patrol_active` | input_boolean | Prevents re-entrant triggers |
| `input_select.drone_patrol_state` | input_select | Current state machine state (for dashboard display and debugging). Options: `idle`, `safety_check`, `dock_opening`, `awaiting_authorization`, `launching`, `mission_active`, `returning`, `landed`, `dock_closing`, `complete`, `aborted`, `dock_fault` |
| `input_text.drone_patrol_mission` | input_text | Currently selected mission_id |
| `input_text.drone_patrol_trigger` | input_text | What triggered the current patrol (for compliance) |

---

## 5. Config Flow Design

### Step 1: MQTT Connection

**Fields:**

| Field | Type | Default | Validation | Notes |
|-------|------|---------|------------|-------|
| (none -- uses HA's existing MQTT) | -- | -- | -- | The integration checks that `mqtt` integration is loaded. If not, it shows an error: "Please configure the MQTT integration first." |

**Discovery:**
- On entering this step, the integration subscribes to `drone_hass/+/state/connection` for 10 seconds
- Any drone_id that publishes `"online"` during this window is added to a discovered list
- If drones are found, they are presented as a dropdown
- If no drones are found, the user can manually enter a `drone_id`

| Field | Type | Default | Validation |
|-------|------|---------|------------|
| `drone_id` | select (discovered) or text (manual) | first discovered | Non-empty, slug-safe (alphanumeric + underscore) |
| `name` | text | `drone_id` value | Non-empty, used for entity naming |

**Validation:** Attempt to subscribe to `drone_hass/{drone_id}/state/connection`. If bridge is online, proceed. If offline, show warning: "Bridge for this drone is currently offline. You can continue setup, but entities will be unavailable until the bridge comes online."

### Step 2: Media Server (Optional)

| Field | Type | Default | Validation |
|-------|------|---------|------------|
| `media_server_type` | select | `go2rtc` | Options: `go2rtc`, `mediamtx`, `none` |
| `rtsp_source_url` | text | (empty) | Valid RTSP URL if media_server_type is not `none`. Format: `rtsp://host:port/path` |
| `media_server_url` | text | `http://localhost:1984` (go2rtc) or `http://localhost:8888` (mediamtx) | Reachable URL |

**Validation:** If media server configured, attempt HTTP health check on `media_server_url`. Warn (don't block) if unreachable.

**Skip:** If user selects `none`, camera entity is not created. Can be configured later in options flow.

### Step 3: Operational Area

| Field | Type | Default | Validation |
|-------|------|---------|------------|
| `operational_mode` | select | `part_107` | Options: `part_107`, `part_108` |
| `operational_area` | text (file path or pasted GeoJSON) | (empty) | Valid GeoJSON Polygon with altitude_ceiling_m. If empty, a warning is shown that missions cannot be validated. |

**Implementation notes:**
- The GeoJSON can be uploaded as a file via the HA file selector or pasted directly as JSON text
- The integration stores the operational area in `.storage/drone_hass.{entry_id}` alongside the config entry
- The operational area is published to `drone_hass/{drone_id}/config/operational_area` (retained) so the bridge can validate missions
- A map preview showing the polygon on an OpenStreetMap tile would be ideal but requires a custom panel -- for MVP, display the coordinates as text

### Step 4: Legal Acknowledgment

This step presents a series of checkboxes that must ALL be checked to proceed.

| Checkbox | Text |
|----------|------|
| `ack_certification` | "I hold a valid FAA Part 107 Remote Pilot Certificate (or will operate under Part 108 with appropriate organizational authorization)" |
| `ack_registration` | "The aircraft is registered with the FAA" |
| `ack_remote_id` | "The aircraft is equipped with a functioning Remote ID broadcast module" |
| `ack_airspace` | "I have verified the operational area is in Class G (uncontrolled) airspace or I hold appropriate airspace authorization" |
| `ack_insurance` | "I have appropriate drone liability insurance coverage" |
| `ack_responsibility` | "I understand that this software does not replace regulatory compliance. I am solely responsible for safe and legal operation." |

**Validation:** All checkboxes must be `True`. The acknowledgment timestamp is stored in the config entry and logged as a compliance event.

**This is not a legal waiver.** It creates a documented record that the user was informed of requirements.

### Step 5: Validation

Automated checks (informational -- warnings, not blockers):

| Check | Method | Pass / Warn |
|-------|--------|-------------|
| MQTT connection | Subscribe test | Pass if connected, warn if not |
| Bridge heartbeat | Check `state/connection` | Pass if online, warn if offline |
| DAA status | Check `state/daa` | Pass if healthy, warn if unhealthy or unavailable |
| Media server | HTTP health check | Pass if reachable, warn if not (skip if `none`) |
| Operational area published | Check retained message | Pass if published, warn if not |

All warnings are displayed but do not block setup completion. The user can fix issues after setup.

### Options Flow (Post-Setup)

Available via the integration's "Configure" button on the Integrations page.

| Option | Same as Config Flow Step |
|--------|------------------------|
| Media server type / URLs | Step 2 |
| Operational mode (107/108) | Step 3 |
| Operational area (re-upload) | Step 3 |
| Name change | Step 1 |
| Default hover altitude | New -- `float`, default 10.0m |
| Command timeout | New -- `int`, default 10s |
| Telemetry recording | New -- toggle to include/exclude high-frequency telemetry from HA recorder |

### Multiple Drones

Each drone is a separate config entry. The user adds the integration multiple times, selecting a different `drone_id` each time. Each config entry creates its own coordinator, device, and entity set. Entity IDs are differentiated by the `name` field (e.g., `sensor.patrol_north_battery`, `sensor.patrol_south_battery`).

The discovery step in the config flow filters out `drone_id` values that already have a config entry.

---

## 6. Dashboard Design

### Primary View: Drone Monitor

A single Lovelace view with sections layout, designed for a desktop/tablet display. Mobile view uses a simplified subset.

#### Section 1: Status Bar (Top)

**Horizontal stack of badge-style tiles:**

```yaml
type: horizontal-stack
cards:
  - type: tile
    entity: binary_sensor.patrol_connected
    name: Bridge
    vertical: true
  - type: tile
    entity: sensor.patrol_flight_state
    name: Flight
    vertical: true
  - type: tile
    entity: sensor.patrol_battery
    name: Battery
    icon: mdi:battery
    vertical: true
  - type: tile
    entity: sensor.patrol_operational_mode
    name: Mode
    vertical: true
  - type: tile
    entity: binary_sensor.patrol_daa_healthy
    name: DAA
    vertical: true
  - type: tile
    entity: binary_sensor.patrol_fc_on_duty
    name: FC
    vertical: true
```

#### Section 2: Map + Video (Main Area, Side by Side)

**Left: Map card (60% width)**

```yaml
type: map
entities:
  - entity: device_tracker.patrol
    name: Drone
geo_location_sources: []
dark_mode: true
default_zoom: 18
aspect_ratio: 16:9
```

For the operational area overlay and mission corridor visualization, the stock `map` card cannot render GeoJSON polygons. Options:

1. **Stock map card** -- shows drone position as a pin. Functional but no polygon overlay. Use this for MVP.
2. **`auto-entities` + zone entities** -- create HA zones for the operational area corners. Approximate, not a polygon.
3. **Custom card (recommended for v2)** -- a Leaflet.js-based custom card that renders the operational area polygon, mission corridors as polylines, and the drone position as a moving marker. This card would subscribe to the drone's position updates and render in real time. Not needed for MVP but should be on the roadmap.

**Right: Live Video (40% width)**

```yaml
type: picture-entity
entity: camera.patrol_live
camera_view: live
show_state: false
show_name: false
aspect_ratio: 16:9
```

When `go2rtc` is configured, use the `webrtc-camera` custom card for lower latency:

```yaml
type: custom:webrtc-camera
entity: camera.patrol_live
```

#### Section 3: Flight Telemetry

```yaml
type: entities
title: Flight Telemetry
entities:
  - entity: sensor.patrol_altitude
  - entity: sensor.patrol_ground_speed
  - entity: sensor.patrol_heading
  - entity: sensor.patrol_flight_mode
  - entity: sensor.patrol_gps_satellites
  - entity: sensor.patrol_signal_rssi
  - entity: sensor.patrol_mission_status
  - entity: sensor.patrol_mission_progress
```

#### Section 4: DAA Traffic

When there are no ADS-B contacts, show a simple "Airspace Clear" indicator. When contacts exist, show a table.

```yaml
type: conditional
conditions:
  - condition: numeric_state
    entity: sensor.patrol_daa_contacts
    above: 0
card:
  type: markdown
  title: ADS-B Traffic
  content: >
    {{ state_attr('sensor.patrol_daa_contacts', 'traffic_summary') }}
```

The `sensor.patrol_daa_contacts` entity carries a `traffic_summary` attribute with a formatted table of current contacts (ICAO, callsign, distance, altitude, threat level). This is populated by the coordinator from `daa/traffic` messages.

When contacts == 0:
```yaml
type: conditional
conditions:
  - condition: numeric_state
    entity: sensor.patrol_daa_contacts
    below: 1
card:
  type: markdown
  content: |
    ## Airspace Clear
    No ADS-B contacts detected.
```

#### Section 5: Flight Coordinator Controls

```yaml
type: entities
title: Flight Coordinator
entities:
  - entity: binary_sensor.patrol_fc_on_duty
  - entity: sensor.patrol_fc_id
  - type: divider
  - type: buttons
    entities:
      - entity: button.patrol_fc_go_on_duty  # calls drone_hass.set_fc_on_duty
      - entity: button.patrol_fc_go_off_duty
  - type: divider
  - type: section
    label: Emergency Controls
  - type: button
    name: ABORT MISSION
    icon: mdi:alert-octagon
    tap_action:
      action: call-service
      service: drone_hass.abort_mission
      target:
        entity_id: sensor.patrol_flight_state
      confirmation:
        text: "Abort the current mission? Drone will hover in place."
  - type: button
    name: RETURN HOME
    icon: mdi:home-import-outline
    tap_action:
      action: call-service
      service: drone_hass.return_to_home
      target:
        entity_id: sensor.patrol_flight_state
      confirmation:
        text: "Return drone to home position?"
```

Note: The ABORT and RTH buttons use `confirmation` to prevent accidental taps. These are implemented as `button` rows in an `entities` card with `tap_action` overrides, or alternatively as dedicated `button` entities in the integration.

#### Section 6: Dock Status

```yaml
type: entities
title: Dock
entities:
  - entity: cover.drone_dock_lid
  - entity: binary_sensor.dock_pad_clear
  - entity: sensor.dock_temperature
  - entity: sensor.dock_humidity
  - entity: binary_sensor.dock_smoke
  - entity: sensor.dock_wind_speed
  - entity: binary_sensor.dock_rain
  - entity: switch.dock_heater
  - entity: switch.dock_charger_power
  - entity: sensor.dock_power_status
```

#### Section 7: Compliance Status

```yaml
type: entities
title: Compliance
entities:
  - entity: sensor.patrol_operational_mode
  - entity: binary_sensor.patrol_operational_area_valid
  - entity: binary_sensor.patrol_daa_healthy
  - entity: binary_sensor.patrol_fc_on_duty
  - entity: sensor.patrol_fc_id
  - entity: input_select.drone_patrol_state
    name: Patrol State Machine
```

#### Section 8: Battery Health (History)

```yaml
type: statistics-graph
title: Battery Health (30 days)
entities:
  - entity: sensor.patrol_battery
  - entity: sensor.patrol_battery_voltage
stat_types:
  - mean
  - min
  - max
period:
  calendar:
    period: day
days_to_show: 30
```

### Custom Cards Needed

| Need | Stock Card? | Custom Card | Notes |
|------|-------------|-------------|-------|
| Drone position on map | Yes (`map` card) | Not needed for MVP | Stock map works for position |
| Operational area polygon overlay | No | Yes -- custom Leaflet card | v2 feature |
| Mission corridor visualization | No | Yes -- same custom Leaflet card | v2 feature |
| Low-latency video | No (stock `picture-entity` works but higher latency) | `webrtc-camera` (HACS) | Recommended |
| DAA traffic radar display | No | Possibly a custom card showing contacts on polar plot | v3 feature; markdown table sufficient for MVP |

### Mobile View

A simplified subview for the RPIC's phone, optimized for the notification-to-action workflow:

1. Large video feed
2. Battery + flight state badges
3. ABORT / RTH buttons
4. DAA threat level indicator

---

## 7. Recorder / Long-term Statistics Strategy

### The Core Tension

The drone produces high-frequency data (1 Hz position, 0.2 Hz battery) during flights that last 3-5 minutes. Most of the time the drone is landed and idle, producing minimal data. The challenge is:

1. During flight: 1 Hz telemetry = ~300 state changes in a 5-minute flight per sensor. With ~10 high-frequency sensors, that is 3,000 state changes per flight. At a few flights per week, this is manageable.
2. During idle: Retained MQTT states are static. Position doesn't change. Battery changes only during charging. Minimal recorder impact.
3. The real problem is **if someone leaves telemetry recording on during extended operations or testing** -- hours of 1 Hz data would bloat the DB.

### Strategy

#### Entities EXCLUDED from Recorder

These entities change frequently during flight but have no long-term statistical value. The compliance recorder captures this data separately.

```yaml
recorder:
  exclude:
    entities:
      - sensor.patrol_altitude
      - sensor.patrol_ground_speed
      - sensor.patrol_heading
      - sensor.patrol_gps_satellites
      - sensor.patrol_gps_fix
      - sensor.patrol_signal_rssi
      - sensor.patrol_battery_current
      - sensor.patrol_flight_time_remaining
      - sensor.patrol_mission_progress
      - binary_sensor.patrol_recording
      - binary_sensor.patrol_streaming
      - binary_sensor.patrol_gps_lock
```

The integration sets `entity_registry_enabled_default=True` for these but also sets a custom attribute `recorder_exclude=True`. The recommended `recorder:` exclude block is documented in the integration's README and optionally auto-configured.

Better approach: The integration can set `_attr_entity_registry_enabled_default` and also use `should_poll = False` (which it already does as MQTT-driven). For recorder control, the integration can set `_attr_state_class = None` on entities that should not generate long-term statistics, and rely on the user to add recorder excludes for entities that generate too many state changes.

The integration should also document a recommended recorder filter in its README.

#### Entities KEPT in Recorder (with Long-term Statistics)

| Entity | Why Keep | State Class | Statistic Value |
|--------|----------|-------------|-----------------|
| `sensor.patrol_battery` | Battery health degradation over months. "What was the starting charge of each flight?" | `measurement` | Mean/min/max per day shows degradation trend |
| `sensor.patrol_battery_voltage` | Voltage sag under load correlates with cell health | `measurement` | Min voltage during flights reveals cell degradation |
| `sensor.patrol_battery_temperature` | Thermal stress history | `measurement` | Max temp during flights |
| `sensor.patrol_flight_mode` | Flight mode history | None (enum) | State changes show flight patterns |
| `sensor.patrol_mission_status` | Mission success/failure tracking | None (enum) | |
| `sensor.patrol_flight_state` | How often is the drone flying? | None (enum) | State duration analysis |
| `sensor.patrol_daa_contacts` | How much traffic exposure? | None | Max contacts seen per flight |
| `sensor.patrol_daa_threat_level` | Were there ever critical threats? | None (enum) | |
| `sensor.patrol_operational_mode` | Compliance record | None (enum) | |
| `binary_sensor.patrol_connected` | Uptime tracking | None | |
| `binary_sensor.patrol_airborne` | Flight count and duration | None | |
| `binary_sensor.patrol_daa_healthy` | DAA reliability tracking | None | |
| `binary_sensor.patrol_fc_on_duty` | Personnel compliance | None | |
| `device_tracker.patrol` | Position history (0.1 Hz = 6 writes/minute, only during flight) | None | |

#### Device Tracker Update Rate

The position topic publishes at 0.1 Hz (every 10 seconds) specifically for the device tracker. During a 5-minute flight, this produces 30 state changes -- acceptable. When landed, position is static so no state changes are generated (HA only writes to recorder on actual state change).

#### Compliance Data: NOT in HA Recorder

The compliance recorder is a separate system (Section 11 of the architecture). It captures:
- Full-rate telemetry during flight (compressed)
- All DAA contacts and avoidance events
- Weather at go/no-go
- Personnel changes
- Authorization records
- Safety gate check results

This data is written by the bridge to its own append-only, hash-chained log file. It is NOT stored in HA's SQLite database. The bridge publishes compliance records to MQTT topics under `drone_hass/{drone_id}/compliance/` and the integration fires HA events for them (see Section 8), but the authoritative compliance store is the bridge's sidecar.

HA's role is operational awareness and control. The bridge's compliance recorder is the audit trail.

#### Long-term Statistics via HA

For tracking battery degradation and flight metrics over months, the following approach works:

1. **Battery health**: `sensor.patrol_battery` with `state_class: measurement` generates HA long-term statistics automatically. The Statistics card or `statistics-graph` card shows mean/min/max battery percentage per day over months. A declining trend in starting-charge values indicates degradation.

2. **Flight count**: Create a `counter.drone_flight_count` helper, incremented by an automation that triggers on `binary_sensor.patrol_airborne` going `on`. This counter has `state_class: total_increasing` and generates long-term statistics (flights per day/week/month).

3. **Flight hours**: Create a `sensor` template that tracks total airborne time using the `history_stats` integration:
```yaml
sensor:
  - platform: history_stats
    name: Drone Flight Hours Today
    entity_id: binary_sensor.patrol_airborne
    state: "on"
    type: time
    start: "{{ now().replace(hour=0, minute=0, second=0) }}"
    end: "{{ now() }}"
```

4. **Mission success rate**: Track via compliance events. A template sensor could compute `successful_missions / total_missions` from a counter pair.

---

## 8. Event Design

### Event Types

All events are fired on the HA event bus with `event_type` prefixed by `drone_hass_`.

#### `drone_hass_flight_state_changed`

**Fired when:** `state/flight` topic changes value

**Data:**
```json
{
  "drone_id": "patrol",
  "previous_state": "landed",
  "new_state": "airborne",
  "timestamp": "2026-04-14T22:15:30Z"
}
```

**Used by:** Automations that need to react to flight state transitions (start stream on takeoff, close dock after landing). The binary_sensor entities also update, but events are useful for automation triggers that need the transition direction.

#### `drone_hass_mission_state_changed`

**Fired when:** `state/mission -> status` changes

**Data:**
```json
{
  "drone_id": "patrol",
  "previous_status": "idle",
  "new_status": "executing",
  "mission_id": "full_perimeter",
  "progress": 0.0,
  "current_waypoint": 0,
  "total_waypoints": 12,
  "error": null
}
```

**Used by:** State machine automation for patrol workflow transitions.

#### `drone_hass_daa_traffic`

**Fired when:** `daa/traffic` message received (new or updated ADS-B contact)

**Data:**
```json
{
  "drone_id": "patrol",
  "icao": "A12345",
  "callsign": "N12345",
  "lat": 47.610,
  "lon": -122.330,
  "altitude_m": 300,
  "heading": 90,
  "ground_speed_mps": 50,
  "distance_m": 1200,
  "threat_level": "none",
  "timestamp": "2026-04-14T22:15:30Z"
}
```

**Used by:** Informational -- dashboard display, compliance logging. NOT used for avoidance decisions (ArduPilot handles those in firmware). Could trigger notifications if `threat_level` is `"warning"` or `"critical"`.

#### `drone_hass_daa_avoidance`

**Fired when:** `daa/avoidance` message received (drone executed an avoidance maneuver)

**Data:**
```json
{
  "drone_id": "patrol",
  "trigger_icao": "A12345",
  "action": "climb",
  "original_alt": 30.0,
  "new_alt": 45.0,
  "timestamp": "2026-04-14T22:15:30Z"
}
```

**Used by:** Critical notification to FC/RPIC. Compliance logging. This is a significant safety event.

#### `drone_hass_compliance_record`

**Fired when:** Any compliance record is published to `drone_hass/{drone_id}/compliance/#` topics

**Data:**
```json
{
  "drone_id": "patrol",
  "record_type": "flight_log",
  "data": {
    "trigger": "alarm",
    "authorization": "rpic_tap",
    "mission_id": "full_perimeter",
    "takeoff_time": "2026-04-14T22:15:30Z",
    "landing_time": "2026-04-14T22:20:15Z",
    "max_altitude_m": 33.5,
    "max_distance_m": 85.0,
    "outcome": "completed"
  },
  "timestamp": "2026-04-14T22:20:15Z"
}
```

**Used by:** Informational. Could trigger a notification on anomaly reports. The compliance sidecar is the authoritative store; this event is for HA-side awareness.

#### `drone_hass_safety_gate_result`

**Fired when:** The patrol state machine completes its safety check phase

**Data:**
```json
{
  "drone_id": "patrol",
  "passed": true,
  "trigger_source": "alarm_control_panel.home",
  "gates": {
    "bridge_online": true,
    "not_airborne": true,
    "battery_sufficient": true,
    "battery_percent": 82,
    "gps_lock": true,
    "dock_connected": true,
    "no_smoke": true,
    "dock_temp_ok": true,
    "dock_temp_c": 18.5,
    "wind_ok": true,
    "wind_mph": 8.3,
    "no_rain": true,
    "daa_healthy": true,
    "operational_area_valid": true,
    "fc_on_duty": true
  },
  "failed_gate": null,
  "timestamp": "2026-04-14T22:15:25Z"
}
```

**Used by:** Compliance logging. Dashboard display of last safety check result. Debugging automation issues.

#### `drone_hass_fc_override`

**Fired when:** Flight Coordinator issues an ABORT or RTH command (from notification action or dashboard button)

**Data:**
```json
{
  "drone_id": "patrol",
  "action": "abort",
  "fc_id": "fc_alessandro",
  "timestamp": "2026-04-14T22:18:00Z"
}
```

**Used by:** Compliance logging. State machine transition.

#### `drone_hass_bridge_connection_changed`

**Fired when:** Bridge connection state changes (online/offline)

**Data:**
```json
{
  "drone_id": "patrol",
  "previous_state": "online",
  "new_state": "offline",
  "timestamp": "2026-04-14T22:15:30Z"
}
```

**Used by:** Notifications (bridge went offline). Automation guards. Entity availability updates.

### Event Summary

| Event | Frequency | Automation Use | Compliance Use | Dashboard Use |
|-------|-----------|---------------|----------------|---------------|
| `flight_state_changed` | Per flight (4-6 transitions) | Primary | Yes | Yes |
| `mission_state_changed` | Per mission (3-5 transitions) | Primary | Yes | Yes |
| `daa_traffic` | Variable (0 to many per flight) | Optional | Yes | Yes |
| `daa_avoidance` | Rare (0-1 per flight typically) | Notification | Critical | Yes |
| `compliance_record` | Per event type per flight | No | Primary | Optional |
| `safety_gate_result` | Per patrol attempt | Debugging | Yes | Yes |
| `fc_override` | Rare | State machine | Critical | Yes |
| `bridge_connection_changed` | On connect/disconnect | Guard logic | Yes | Yes |

---

## Summary of Key Design Decisions

1. **Custom integration using HA's MQTT component** -- not standalone aiomqtt, not MQTT discovery. This is the right balance of control and integration.

2. **Coordinator is MQTT-subscription-based** -- single wildcard subscription, message routing, push-based entity updates. No polling.

3. **High-frequency telemetry excluded from HA recorder** -- the compliance sidecar is the authoritative flight data store. HA recorder tracks only state-change and statistical entities.

4. **Device tracker at 0.1 Hz** -- a dedicated low-rate position topic prevents recorder bloat while still showing the drone on the map.

5. **Correlation-ID command/response** -- every service call generates a UUID, publishes a command, and awaits the matching response. 10-second default timeout. This is the standard async request/response pattern over MQTT.

6. **Bridge is the compliance authority** -- HA can request flights, but the bridge's ComplianceGate makes the final authorization decision. HA's safety gates are the first line; the bridge is the second.

7. **State machine in AppDaemon recommended over YAML automation** -- the patrol workflow has too many states, error paths, and parallel monitors for a clean YAML automation. AppDaemon (or a `pyscript` implementation) provides proper state machine semantics. A simplified Part 107-only version can work as a YAML automation (as shown in the architecture doc).

8. **Multi-drone via multiple config entries** -- each drone is an independent config entry with its own coordinator, device, and entity namespace. No shared state between drones.

9. **Legal acknowledgment is a record, not a waiver** -- the config flow creates a timestamped record that the user was informed. It does not transfer liability.

10. **Operational area polygon rendering requires a custom Leaflet card** -- stock HA map card cannot render GeoJSON polygons. This is a v2 feature; MVP uses the stock map card for drone position only.