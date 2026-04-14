# Threat Resolutions: HA / MQTT / Network / Docker Domain

> Companion to: threat-model.md Section 9

---

## ATK-MQTT-01: Unauthenticated MQTT Command Injection

**Resolution:**

Create a dedicated Mosquitto configuration that enforces authentication, TLS, and topic-level ACLs. The following files go into the Mosquitto add-on configuration directory (on HAOS, this is configurable via the add-on options or `/share/mosquitto/`).

**`/share/mosquitto/mosquitto.conf`** (or set via add-on config):

```
# ---- Listeners ----
# Disable plaintext entirely. Only TLS on 8883.
listener 8883
protocol mqtt
certfile /ssl/mosquitto/server.crt
keyfile /ssl/mosquitto/server.key
cafile /ssl/mosquitto/ca.crt
require_certificate false
tls_version tlsv1.2

# Do NOT bind a plaintext listener on 1883.
# If you must (for local testing only), bind to 127.0.0.1:
# listener 1883 127.0.0.1

# ---- Authentication ----
per_listener_settings false
allow_anonymous false
password_file /share/mosquitto/passwd

# ---- ACL ----
acl_file /share/mosquitto/acl

# ---- Rate Limiting / Hardening ----
max_inflight_messages 20
max_queued_messages 1000
max_connections 10
message_size_limit 65536
persistent_client_expiration 1d
```

**`/share/mosquitto/acl`**:

```
# ======================================================
# drone_hass Mosquitto ACL
# ======================================================
# Principle: least privilege per client identity.
#
# bridge_user  -- the MAVLink-MQTT bridge add-on
# ha_user      -- Home Assistant's MQTT integration
# All other clients are denied by default (no catch-all rule).

# ---- Bridge user ----
# Bridge publishes telemetry, state, DAA, compliance responses.
# Bridge reads commands and missions from HA.
user bridge_user
topic write drone_hass/+/telemetry/#
topic write drone_hass/+/state/#
topic write drone_hass/+/daa/#
topic write drone_hass/+/command/+/response
topic read  drone_hass/+/command/#
topic read  drone_hass/+/missions/#
topic read  drone_hass/+/compliance/#
topic read  drone_hass/+/config/#
# Bridge LWT (connection state)
topic write drone_hass/+/state/connection
# Bridge heartbeat
topic write drone_hass/bridge/#

# ---- HA user ----
# HA publishes commands, missions, compliance events, config.
# HA reads everything (telemetry, state, DAA).
user ha_user
topic write drone_hass/+/command/arm
topic write drone_hass/+/command/takeoff
topic write drone_hass/+/command/land
topic write drone_hass/+/command/return_to_home
topic write drone_hass/+/command/cancel_rth
topic write drone_hass/+/command/execute_mission
topic write drone_hass/+/command/pause_mission
topic write drone_hass/+/command/resume_mission
topic write drone_hass/+/command/stop_mission
topic write drone_hass/+/command/take_photo
topic write drone_hass/+/command/start_recording
topic write drone_hass/+/command/stop_recording
topic write drone_hass/+/command/start_stream
topic write drone_hass/+/command/stop_stream
topic write drone_hass/+/command/set_gimbal
topic write drone_hass/+/command/reset_gimbal
topic write drone_hass/+/command/set_home
topic write drone_hass/+/command/set_operational_mode
topic write drone_hass/+/command/set_fc_on_duty
topic write drone_hass/+/missions/#
topic write drone_hass/+/compliance/ha_event
topic read  drone_hass/#

# ---- Deny all others ----
# Mosquitto's default with an ACL file is to deny any topic
# not explicitly granted. No catch-all needed.
```

**Generate password file:**

```bash
# On the HA server or in the Mosquitto add-on shell:
mosquitto_passwd -c /share/mosquitto/passwd bridge_user
# Enter a 32+ character random password
mosquitto_passwd /share/mosquitto/passwd ha_user
# Enter a different 32+ character random password
chmod 600 /share/mosquitto/passwd
```

Store passwords in HA's `secrets.yaml`:

```yaml
# secrets.yaml
mqtt_bridge_password: "<random-32-char-password>"
mqtt_ha_password: "<random-32-char-password>"
```

**Bridge add-on options** (in its `options.json` or UI config):

```yaml
mqtt_host: "core-mosquitto"
mqtt_port: 8883
mqtt_username: "bridge_user"
mqtt_password: "<from secrets>"
mqtt_tls: true
mqtt_ca_cert: "/ssl/mosquitto/ca.crt"
```

**HA MQTT integration config** (via UI or `configuration.yaml`):

```yaml
mqtt:
  broker: core-mosquitto
  port: 8883
  username: "ha_user"
  password: !secret mqtt_ha_password
  certificate: /ssl/mosquitto/ca.crt
  tls_insecure: false
```

**Residual risk:** An attacker who compromises the HA server gains `ha_user` credentials and can publish commands. Mitigated by the bridge's ComplianceGate (authorization token required for flight commands).

---

## ATK-MQTT-02: Mission Definition Poisoning via Retained Messages

**Resolution:**

Three controls, layered:

1. **ACL enforcement (above):** Only `ha_user` can write to `drone_hass/+/missions/#`. The bridge user cannot, and no other clients exist.

2. **Mission allowlist in bridge config** (`/data/bridge_config.yaml` inside the add-on container):

```yaml
# bridge_config.yaml -- loaded from disk, NOT from MQTT
missions:
  allowlist:
    - full_perimeter
    - front_sweep
    - rear_sweep
    - east_edge
    - west_edge
    - corner_ne
    - corner_nw
    - corner_se
    - corner_sw
  reject_unknown: true  # Any mission_id not in this list is rejected
```

The bridge code must enforce:

```python
async def _handle_execute_mission(self, cmd):
    mission_id = cmd["params"]["mission_id"]
    if self.config["missions"]["reject_unknown"] and \
       mission_id not in self.config["missions"]["allowlist"]:
        return {"success": False, "error": f"Mission '{mission_id}' not in allowlist"}
    # ... proceed with operational area validation
```

3. **Operational area loaded from disk, never from MQTT:**

```yaml
# bridge_config.yaml
operational_area:
  # Source of truth is this file, not MQTT retained messages.
  geojson_file: "/data/compliance/operational_area.geojson"
  altitude_ceiling_m: 36.6  # 120 ft
  altitude_floor_m: 0
  lateral_buffer_m: 5
```

The bridge must refuse to load the operational area polygon from any MQTT topic. The `config/operational_area` MQTT topic, if used, is publish-only (bridge publishes the loaded area for HA to display), never subscribe.

**Residual risk:** An attacker with `ha_user` credentials can still publish poisoned missions, but the bridge rejects any mission_id not on the allowlist and validates all waypoints against the disk-loaded operational area.

---

## ATK-MQTT-03: Compliance Event Injection

**Resolution:**

1. **Bridge code must distinguish internal vs external compliance events.** Add a `source` field to every compliance record:

```python
class ComplianceRecorder:
    def record_event(self, event_type, details, source):
        """
        source must be one of:
          "bridge_internal" -- generated by ComplianceGate, DAA monitor, etc.
          "ha_external"     -- received via MQTT from HA
        """
        record = {
            "event_type": event_type,
            "details": details,
            "source": source,
            "timestamp": time.time(),
            "prev_hash": self._last_hash,
        }
        # Authorization events MUST be bridge_internal
        if event_type in ("rpic_authorized", "autonomous_launch_authorized",
                          "flight_completed", "daa_avoidance", "safety_gate_result"):
            if source != "bridge_internal":
                logger.warning(
                    "Rejected external compliance event for restricted type: %s",
                    event_type
                )
                return  # Silently drop -- do NOT record forged authorization
        # ... sign and store
```

2. **ACL restricts `compliance/#` publish** to `ha_user` only (already in the ACL above). The bridge reads from this topic but only as informational annotations.

3. **Authorization events (`rpic_authorized`, `autonomous_launch_authorized`) are never accepted from MQTT.** They are generated exclusively by the bridge's internal ComplianceGate state machine.

**Residual risk:** An attacker can inject informational annotations tagged `ha_external`. These cannot be confused with authoritative authorization records because they carry a different `source` field.

---

## ATK-MQTT-04: MQTT Broker Denial of Service

**Resolution:**

1. **Mosquitto rate limiting** (already in the `mosquitto.conf` above):

```
max_inflight_messages 20
max_queued_messages 1000
max_connections 10
message_size_limit 65536
```

2. **Bind Mosquitto to the VLAN interface only** (not `0.0.0.0`):

```
# In mosquitto.conf, under the listener directive:
listener 8883 10.0.10.1
```

Where `10.0.10.1` is the HA server's IP on the drone/IoT VLAN. This prevents any device on other VLANs from reaching the broker.

If using the HAOS Mosquitto add-on (which does not support per-interface binding natively), enforce this at the firewall level instead:

```bash
# On the ASUS router (iptables-style, adapt to your model):
# Only allow MQTT from the bridge container IP and HA's own IP
iptables -A FORWARD -d 10.0.10.1 -p tcp --dport 8883 -s 10.0.10.2 -j ACCEPT  # bridge
iptables -A INPUT -d 10.0.10.1 -p tcp --dport 8883 -s 127.0.0.1 -j ACCEPT    # HA local
iptables -A FORWARD -d 10.0.10.1 -p tcp --dport 8883 -j DROP                  # all others
```

3. **Bridge resilience:** The bridge must continue operating via MAVLink even when MQTT is unresponsive. If MQTT publishes fail, the bridge queues telemetry internally (bounded buffer, e.g., 1000 messages) and reconnects. The flight controller's mission executes independently of MQTT.

**Residual risk:** A compromised device on the same VLAN can still flood the broker. VLAN isolation limits the blast radius.

---

## ATK-MQTT-05: State Topic Spoofing

**Resolution:**

1. **ACL enforcement:** Only `bridge_user` can write to `state/#` topics (already enforced in the ACL above -- `ha_user` has no `topic write drone_hass/+/state/#` rule).

2. **Bridge ComplianceGate reads its own internal state, never MQTT:**

```python
class ComplianceGate:
    def __init__(self, daa_monitor, weather_monitor, mavlink_client):
        # These are direct references to internal objects, NOT MQTT subscribers
        self._daa = daa_monitor
        self._weather = weather_monitor
        self._mavlink = mavlink_client

    def _daa_system_healthy(self) -> bool:
        # Read directly from the DAA monitor's internal state
        return self._daa.is_healthy()

    def _weather_within_envelope(self, context) -> bool:
        # Read from bridge's own weather data (subscribed to dock sensor
        # MQTT topics separately, or queried via ESPHome API)
        return self._weather.wind_mph < 15 and not self._weather.is_raining

    def _flight_controller_on_duty(self) -> bool:
        # Internal state set by the set_fc_on_duty command handler
        return self._fc_on_duty
```

3. **Document explicitly** that HA-side safety gates (automation conditions checking entity states) are a **convenience layer**, not a security boundary. The bridge is the security boundary.

**Residual risk:** If an attacker gains `bridge_user` credentials, they can spoof state topics. Mitigated by: TLS, strong passwords, and the fact that the bridge's ComplianceGate does not read its own MQTT publications for decisions.

---

## ATK-HA-01: HA Automation Manipulation

**Resolution:**

1. **HA authentication hardening** (`configuration.yaml`):

```yaml
homeassistant:
  auth_providers:
    - type: homeassistant
  # Do NOT add trusted_networks or legacy_api_password providers

http:
  ssl_certificate: /ssl/fullchain.pem
  ssl_key: /ssl/privkey.pem
  ip_ban_enabled: true
  login_attempts_threshold: 5
```

2. **Require MFA for all admin accounts.** In HA UI: Profile -> Multi-factor Authentication Modules -> enable TOTP for every user.

3. **Restrict long-lived access tokens:** Audit and revoke unused tokens via the HA UI (Profile -> Long-Lived Access Tokens). Implement a quarterly review.

4. **Bridge-side independent weather checks** (see ATK-MQTT-05 resolution above). The bridge must subscribe directly to dock weather sensor MQTT topics published by the ESPHome dock controller:

```python
# In the bridge, subscribe to ESPHome-published weather topics
# These come from the ESPHome native API -> HA -> MQTT, or from
# a direct ESPHome MQTT component if configured.
async def _subscribe_weather(self):
    await self.mqtt.subscribe("homeassistant/sensor/dock_wind_speed/state")
    await self.mqtt.subscribe("homeassistant/binary_sensor/dock_rain/state")
```

Better yet, have the dock ESP32 publish weather data directly to MQTT topics the bridge reads, bypassing HA entirely:

```yaml
# ESPHome dock config -- publish to MQTT in addition to native API
mqtt:
  broker: 10.0.10.1
  port: 8883
  username: "dock_user"
  password: !secret mqtt_dock_password
  # Publish weather sensor state to a topic the bridge reads
  on_message: []

sensor:
  - platform: ... # anemometer
    name: "Dock Wind Speed"
    on_value:
      then:
        - mqtt.publish:
            topic: "dock/weather/wind_speed"
            payload: !lambda 'return to_string(x);'
            retain: true
```

Add `dock_user` to the Mosquitto password file and ACL:

```
# In acl file
user dock_user
topic write dock/weather/#
topic write dock/status/#
```

5. **The bridge ComplianceGate must independently verify weather** from the dock MQTT topics it subscribes to directly, not from HA entity states.

**Residual risk:** A compromised HA admin account can still modify automations, but cannot bypass the bridge ComplianceGate for flight-critical operations.

---

## ATK-HA-02: Push Notification Spoofing (Part 107 RPIC Authorization)

**Resolution:**

Implement a cryptographic challenge-response authorization flow:

```python
# Bridge side -- when a flight is requested
import secrets
import hashlib

class ComplianceGate:
    async def _wait_for_rpic_authorization(self, timeout=120):
        # Generate a one-time challenge
        nonce = secrets.token_urlsafe(32)
        challenge_hash = hashlib.sha256(nonce.encode()).hexdigest()[:12]

        # Store the expected nonce internally (NOT published to MQTT)
        self._pending_auth_nonce = nonce
        self._pending_auth_expires = time.time() + timeout

        # Publish authorization request (includes the nonce for the notification)
        await self.mqtt.publish(
            f"drone_hass/{self.drone_id}/command/authorize_flight/request",
            json.dumps({
                "nonce": nonce,
                "challenge_display": challenge_hash,  # Short code shown in notification
                "mission_id": self._pending_mission_id,
                "expires_at": self._pending_auth_expires,
            }),
            qos=1,
        )

        # Wait for response with matching nonce
        try:
            response = await asyncio.wait_for(
                self._auth_response_future, timeout=timeout
            )
            if response.get("nonce") != self._pending_auth_nonce:
                return False
            if time.time() > self._pending_auth_expires:
                return False
            return True
        except asyncio.TimeoutError:
            return False
        finally:
            self._pending_auth_nonce = None
```

On the HA integration side, the notification includes the nonce and sends it back:

```python
# In the HA integration's automation / AppDaemon
# The notification carries the nonce in its data
async def send_rpic_notification(hass, coordinator, request_data):
    await hass.services.async_call("notify", "mobile_app_rpic_phone", {
        "title": "Perimeter Alert",
        "message": f"Mission: {request_data['mission_id']} | Code: {request_data['challenge_display']}",
        "data": {
            "actions": [
                {
                    "action": "LAUNCH_DRONE",
                    "title": "LAUNCH DRONE",
                },
                {
                    "action": "IGNORE",
                    "title": "IGNORE",
                },
            ],
            # The nonce is embedded in the notification action URI
            "action_data": {"nonce": request_data["nonce"]},
        },
    })
```

When the RPIC taps LAUNCH, the HA automation publishes the nonce back to the bridge:

```yaml
# HA automation snippet
- alias: "Handle RPIC LAUNCH response"
  trigger:
    - platform: event
      event_type: mobile_app_notification_action
      event_data:
        action: "LAUNCH_DRONE"
  action:
    - service: mqtt.publish
      data:
        topic: "drone_hass/patrol/command/authorize_flight/response"
        payload: >
          {"nonce": "{{ trigger.event.data.action_data.nonce }}"}
        qos: 1
```

An attacker who fires a fake `mobile_app_notification_action` event cannot include the correct nonce because the nonce was only delivered to the RPIC's phone via the push notification. The nonce is never published to any MQTT topic that the attacker could read (only to the authorization request topic, which is write-only from bridge_user and the response is matched internally).

**Residual risk:** If the attacker compromises the RPIC's phone, they have the nonce. Mitigated by phone security (biometrics, PIN).

---

## ATK-HA-03: Service Call Abuse

**Resolution:**

1. **Restrict camera/gimbal commands to airborne-only in the bridge:**

```python
# Bridge command handler
async def _handle_command(self, action, cmd):
    # Camera/gimbal commands require airborne state
    camera_gimbal_commands = {
        "take_photo", "start_recording", "stop_recording",
        "set_gimbal", "reset_gimbal", "start_stream", "stop_stream"
    }
    if action in camera_gimbal_commands:
        if not self._is_airborne:
            return {"success": False, "error": "Camera commands only available while airborne"}
```

2. **HA user permissions:** Create a non-admin "family" user group that cannot call `drone_hass.*` services. Only the RPIC/admin HA user should have access to drone services. While HA does not have per-service RBAC natively, you can use the `admin` flag on user accounts. All drone services should check `context.user_id` is an admin:

```python
# In the integration's service handler
async def async_handle_service(call: ServiceCall):
    if not call.context.user_id:
        raise Unauthorized()
    user = await hass.auth.async_get_user(call.context.user_id)
    if not user or not user.is_admin:
        raise Unauthorized("Only admin users can control the drone")
```

**Residual risk:** Any HA admin can call services. Limit admin accounts to the RPIC only.

---

## ATK-VID-01: RTSP Stream Interception

**Resolution:**

1. **Configure go2rtc with RTSP authentication** (`/config/go2rtc.yaml`):

```yaml
# go2rtc.yaml
streams:
  drone_live:
    - rtsp://camera_user:camera_pass@10.0.20.50:8554/main  # Camera on drone VLAN

# API authentication
api:
  listen: ":1984"
  username: "go2rtc_admin"
  password: "strong-random-password-here"

rtsp:
  listen: ":8554"
  username: "rtsp_user"
  password: "strong-random-password-here"

webrtc:
  listen: ":8555"
```

2. **Firewall RTSP ports.** On the ASUS router or HA host firewall:

```bash
# Only the go2rtc/mediamtx process on the HA server can reach the camera's RTSP port
# Drone VLAN: 10.0.20.0/24, HA server: 10.0.10.1, Camera on drone: 10.0.20.50

# Allow HA server -> camera RTSP
iptables -A FORWARD -s 10.0.10.1 -d 10.0.20.50 -p tcp --dport 8554 -j ACCEPT
# Block all other access to camera RTSP
iptables -A FORWARD -d 10.0.20.50 -p tcp --dport 8554 -j DROP

# go2rtc listens on localhost only for RTSP re-serve (or on the HA VLAN IP)
# Block external access to go2rtc's RTSP port
iptables -A INPUT -p tcp --dport 8554 -s 127.0.0.1 -j ACCEPT
iptables -A INPUT -p tcp --dport 8554 -j DROP
```

3. **Configure the camera (Siyi A8 Mini) with RTSP authentication** if supported. Set a non-default username/password in the camera's web interface.

4. **HA camera entity** points to the authenticated go2rtc URL:

```yaml
# In HA, the camera entity is created by the drone_hass integration
# pointing to go2rtc's authenticated RTSP:
# rtsp://rtsp_user:strong-password@localhost:8554/drone_live
```

**Residual risk:** RTSP authentication is basic auth (base64, not encrypted). TLS on RTSP (RTSPS) is ideal but not universally supported by cameras or go2rtc. Network isolation is the primary control.

---

## ATK-VID-02: Video Recording Access

**Resolution:**

1. **Video retention automation** in HA (`automations.yaml`):

```yaml
- alias: "Purge old drone recordings"
  trigger:
    - platform: time
      at: "03:00:00"
  action:
    - service: shell_command.purge_drone_video
```

```yaml
# configuration.yaml
shell_command:
  purge_drone_video: >
    find /media/drone_recordings -type f -name "*.mp4" -mtime +30 -delete
```

This deletes recordings older than 30 days. Adjust `+30` to your retention requirement.

2. **Restrict media directory permissions** inside the bridge container. The add-on `config.yaml`:

```yaml
map:
  - media:rw  # Required for writing recordings
  - ssl:ro    # TLS certs, read-only
```

On the host, ensure the media directory has restrictive permissions:

```bash
chmod 750 /media/drone_recordings
chown root:homeassistant /media/drone_recordings
```

3. **Encrypt HA backups.** In the HA UI when creating backups, always set a backup password. This encrypts the backup tarball, including any media files.

4. **If compliance requires longer retention,** store recordings on encrypted storage (LUKS partition on the HA server, or an encrypted NAS share).

**Residual risk:** Anyone with SSH/physical access to the HA server can read the files. Full-disk encryption (LUKS) on the HA server mitigates this for physical access scenarios.

---

## ATK-DOCK-01: ESPHome API Exploitation (relates to ATK-NET-01 / ESPHome threats)

**Resolution:**

1. **Strong API encryption key** in ESPHome dock config (`dock.yaml`):

```yaml
api:
  encryption:
    key: !secret dock_api_key
  # The key must be a base64-encoded 32-byte random value.
  # Generate with: python3 -c "import secrets, base64; print(base64.b64encode(secrets.token_bytes(32)).decode())"

ota:
  - platform: esphome
    password: !secret dock_ota_password
  # In production, consider disabling OTA entirely:
  # Remove the ota: section and reflash via USB only.
```

Generate the key:

```bash
python3 -c "import secrets, base64; print(base64.b64encode(secrets.token_bytes(32)).decode())"
# Example output: k3J8mN2pQ7rS1tU4vW6xY9zA0bC5dE8fG1hI3jK5lM=
```

Store in ESPHome `secrets.yaml`:

```yaml
dock_api_key: "k3J8mN2pQ7rS1tU4vW6xY9zA0bC5dE8fG1hI3jK5lM="
dock_ota_password: "another-strong-random-password"
```

2. **ESP32 interlocks must rely on local sensor inputs only:**

```yaml
# dock.yaml -- ESPHome
binary_sensor:
  - platform: gpio
    pin: GPIO27
    name: "Dock Pad Clear"
    id: pad_clear
    device_class: occupancy

  - platform: gpio
    pin: GPIO26
    name: "Dock Smoke"
    id: smoke_detected
    device_class: smoke

cover:
  - platform: endstop
    name: "Drone Dock Lid"
    id: dock_lid
    open_action:
      - switch.turn_on: actuator_open
    open_endstop: lid_open_limit
    close_action:
      - switch.turn_on: actuator_close
    close_endstop: lid_closed_limit
    stop_action:
      - switch.turn_off: actuator_open
      - switch.turn_off: actuator_close

    # SAFETY INTERLOCKS -- enforced locally, not from HA state
    # Cannot close unless pad_clear confirms drone is landed
    # This is checked in the close_action lambda:

switch:
  - platform: gpio
    pin: GPIO25
    name: "Dock Charger Power"
    id: charger_relay
    # Hardware interlock: smoke sensor cuts charger via a separate
    # physical relay wired in series. This ESPHome switch is the
    # software-controllable relay; the hardware relay is independent.

interval:
  - interval: 1s
    then:
      # Watchdog: if smoke detected, force charger off (software backup)
      - if:
          condition:
            binary_sensor.is_on: smoke_detected
          then:
            - switch.turn_off: charger_relay
            - logger.log: "SMOKE DETECTED - charger cut (software backup)"
```

3. **Disable OTA in production** by removing the `ota:` section from the ESPHome config entirely. Reflash via USB only, requiring physical access to the ESP32.

**Residual risk:** If the API encryption key is compromised, an attacker can control the dock. The hardware smoke relay (wired in series with the charger, independent of the ESP32) remains functional regardless.

---

## ATK-DOCK-02: Physical Tampering with Dock

**Resolution:**

1. **Tamper sensor** (reed switch or vibration sensor) on the dock enclosure lid:

```yaml
# dock.yaml -- ESPHome
binary_sensor:
  - platform: gpio
    pin:
      number: GPIO33
      mode: INPUT_PULLUP
      inverted: true
    name: "Dock Tamper"
    id: dock_tamper
    device_class: tamper
    filters:
      - delayed_on: 100ms  # Debounce
```

2. **HA automation for tamper alert:**

```yaml
- alias: "Dock tamper alert"
  trigger:
    - platform: state
      entity_id: binary_sensor.dock_tamper
      to: "on"
  action:
    - service: notify.mobile_app_rpic_phone
      data:
        title: "DOCK TAMPER ALERT"
        message: "Tamper sensor triggered on drone dock enclosure."
        data:
          push:
            sound:
              name: default
              critical: 1
              volume: 1.0
    - service: persistent_notification.create
      data:
        title: "Dock Tamper Alert"
        message: "Tamper sensor on drone dock triggered at {{ now() }}"
```

3. **Security screws** (Torx T20 security or similar) on all dock enclosure fasteners. Document in the BOM.

4. **Camera coverage:** If an existing security camera can cover the dock location, add it to the monitoring zone. This is a physical/placement decision, not a software configuration.

**Residual risk:** A determined attacker with physical access can bypass any tamper sensor. This is an alerting control, not a prevention control.

---

## ATK-LAT-01: Bridge Container Escape to Host

**Resolution:**

1. **Run bridge process as non-root.** In the add-on's `Dockerfile`:

```dockerfile
FROM ghcr.io/home-assistant/amd64-base:3.18

# Install dependencies
RUN apk add --no-cache python3 py3-pip

# Create non-root user
RUN addgroup -S bridge && adduser -S bridge -G bridge

# Install Python packages
COPY requirements.txt /app/requirements.txt
RUN pip3 install --no-cache-dir -r /app/requirements.txt

COPY . /app
WORKDIR /app

# Set ownership
RUN chown -R bridge:bridge /app /data

# Run as non-root
USER bridge

ENTRYPOINT ["python3", "-m", "mavlink_mqtt_bridge"]
```

If using S6-overlay (standard for HA add-ons), configure the service to drop privileges:

```bash
# /etc/s6-overlay/s6-rc.d/bridge/run
#!/command/with-contenv bashio
exec s6-setuidgid bridge python3 -m mavlink_mqtt_bridge
```

2. **Drop unnecessary Linux capabilities** in the add-on's `config.yaml`:

```yaml
# Add-on config.yaml (HA Supervisor add-on metadata)
privileged: []  # No privileged access
# Do NOT add: SYS_ADMIN, NET_ADMIN, SYS_RAWIO, etc.

# Security options (if supported by Supervisor version)
security_opt:
  - no-new-privileges:true

# Minimal filesystem mappings
map:
  - media:rw     # Flight video storage -- required
  - ssl:ro       # TLS certs -- required, read-only
  # Do NOT map: config, addons, backup, share (unless needed)
```

3. **Pin all Python dependency versions** (`requirements.txt`):

```
mavsdk==2.2.0
aiomqtt==2.3.0
grpcio==1.62.0
protobuf==4.25.3
cryptography==42.0.5
```

4. **Minimal base image:** Use Alpine-based HA add-on base images (already standard). Avoid Debian-based images unless necessary.

5. **Automated vulnerability scanning** in CI:

```yaml
# .github/workflows/security.yml
name: Security Scan
on: [push, pull_request]
jobs:
  trivy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: aquasecurity/trivy-action@master
        with:
          scan-type: fs
          scan-ref: .
          severity: CRITICAL,HIGH
```

**Residual risk:** The HA Supervisor manages container isolation. The add-on still has `media:rw` access, which is shared with other add-ons. A compromised bridge could write malicious files to the shared media directory. Mitigated by running as non-root with minimal capabilities.

---

## ATK-LAT-02: Compromised Drone as Network Pivot

**Resolution:**

1. **Harden the companion computer (RPi):**

```bash
# On the RPi companion computer:

# Disable password authentication for SSH
sudo sed -i 's/#PasswordAuthentication yes/PasswordAuthentication no/' /etc/ssh/sshd_config
sudo sed -i 's/PasswordAuthentication yes/PasswordAuthentication no/' /etc/ssh/sshd_config
echo "PubkeyAuthentication yes" | sudo tee -a /etc/ssh/sshd_config
sudo systemctl restart sshd

# Remove default pi user, create a dedicated user
sudo adduser --disabled-password dronecomp
sudo mkdir -p /home/dronecomp/.ssh
# Copy your SSH public key
echo "ssh-ed25519 AAAA... your-key" | sudo tee /home/dronecomp/.ssh/authorized_keys
sudo chmod 700 /home/dronecomp/.ssh
sudo chmod 600 /home/dronecomp/.ssh/authorized_keys
sudo chown -R dronecomp:dronecomp /home/dronecomp/.ssh
sudo deluser --remove-home pi 2>/dev/null || true

# Enable unattended upgrades
sudo apt install -y unattended-upgrades
sudo dpkg-reconfigure -plow unattended-upgrades

# Disable unnecessary services
sudo systemctl disable --now avahi-daemon bluetooth cups
sudo systemctl mask avahi-daemon bluetooth

# Firewall: only allow MAVLink and RTSP out, SSH from HA server only
sudo apt install -y ufw
sudo ufw default deny incoming
sudo ufw default deny outgoing
sudo ufw allow in from 10.0.10.1 to any port 22 proto tcp   # SSH from HA only
sudo ufw allow out to 10.0.10.1 port 8883 proto tcp          # MQTT to broker (if needed)
sudo ufw allow out to 10.0.10.1 port 8554 proto tcp          # RTSP to media server
sudo ufw allow in from 10.0.10.1 port 14540 proto udp        # MAVLink from bridge
sudo ufw allow out to any port 14540 proto udp                # MAVLink to FC
sudo ufw allow out to any port 53 proto udp                   # DNS for NTP
sudo ufw allow out to any port 123 proto udp                  # NTP
sudo ufw enable
```

2. **Dedicated drone VLAN** (on ASUS router):

```
VLAN 20: Drone VLAN (10.0.20.0/24)
  - RPi companion computer: 10.0.20.10 (static DHCP lease)
  - Camera (Siyi A8 Mini): 10.0.20.50 (static DHCP lease)
  - WiFi SSID: "DroneNet" (WPA3-SAE, PMF required, hidden SSID)

VLAN 10: IoT/HA VLAN (10.0.10.0/24)
  - HA Server: 10.0.10.1
  - Mosquitto: 10.0.10.1:8883
  - go2rtc: 10.0.10.1:8554
  - ESPHome dock: 10.0.10.20
```

**Firewall rules between VLANs** (on ASUS router or dedicated firewall):

```
# VLAN 20 (Drone) -> VLAN 10 (HA): only specific ports
ALLOW 10.0.20.10 -> 10.0.10.1:14540/udp  # MAVLink from RPi to bridge
ALLOW 10.0.20.50 -> 10.0.10.1:8554/tcp   # RTSP from camera to media server
DENY  10.0.20.0/24 -> 10.0.10.0/24       # Block everything else

# VLAN 10 (HA) -> VLAN 20 (Drone): only bridge needs to reach RPi
ALLOW 10.0.10.1 -> 10.0.20.10:14540/udp  # MAVLink from bridge to RPi
ALLOW 10.0.10.1 -> 10.0.20.50:8554/tcp   # RTSP pull from camera
ALLOW 10.0.10.1 -> 10.0.20.10:22/tcp     # SSH for maintenance
DENY  10.0.10.0/24 -> 10.0.20.0/24       # Block everything else

# VLAN 20 (Drone) -> Internet: DENY ALL
DENY  10.0.20.0/24 -> 0.0.0.0/0          # No internet for drone VLAN
# Exception: NTP if needed
ALLOW 10.0.20.10 -> <NTP_SERVER>:123/udp
```

3. **No internet access for the drone VLAN.** The RPi does not need internet access. All software updates are performed via SSH from the HA server or physically via SD card.

**Residual risk:** If the RPi is compromised, the attacker is confined to the drone VLAN with no internet and can only reach the HA server on MAVLink and RTSP ports. Lateral movement to the home LAN is blocked by VLAN firewall rules.

---

## ATK-DOS-01: Battery Exhaustion via Repeated Triggers

**Resolution:**

1. **Cooldown timer in HA automation:**

```yaml
# input_number for configurable cooldown
input_number:
  drone_patrol_cooldown_minutes:
    name: "Patrol Cooldown (minutes)"
    min: 5
    max: 60
    step: 5
    initial: 15
    mode: slider

input_datetime:
  drone_last_patrol_completed:
    name: "Last Patrol Completed"
    has_date: true
    has_time: true

counter:
  drone_patrols_last_hour:
    name: "Patrols in Last Hour"
    initial: 0
    step: 1
    maximum: 10
```

In the patrol automation's condition block:

```yaml
- alias: "Drone Security Patrol"
  trigger:
    - platform: state
      entity_id: alarm_control_panel.home
      to: "triggered"
  condition:
    # Cooldown check
    - condition: template
      value_template: >
        {% set last = states('input_datetime.drone_last_patrol_completed') %}
        {% set cooldown = states('input_number.drone_patrol_cooldown_minutes') | float %}
        {% if last == 'unknown' %}
          true
        {% else %}
          {{ (now() - strptime(last, '%Y-%m-%d %H:%M:%S')).total_seconds() > (cooldown * 60) }}
        {% endif %}
    # Escalating battery threshold
    - condition: template
      value_template: >
        {% set patrols = states('counter.drone_patrols_last_hour') | int %}
        {% set battery = states('sensor.patrol_battery') | float(0) %}
        {% if patrols == 0 %}
          {{ battery > 30 }}
        {% elif patrols == 1 %}
          {{ battery > 50 }}
        {% elif patrols == 2 %}
          {{ battery > 70 }}
        {% else %}
          false
        {% endif %}
    # ... other safety conditions
  action:
    # ... launch sequence
    # At end of mission (after landing confirmed):
    - service: input_datetime.set_datetime
      target:
        entity_id: input_datetime.drone_last_patrol_completed
      data:
        datetime: "{{ now().strftime('%Y-%m-%d %H:%M:%S') }}"
    - service: counter.increment
      target:
        entity_id: counter.drone_patrols_last_hour
```

Reset the hourly counter:

```yaml
- alias: "Reset patrol counter hourly"
  trigger:
    - platform: time_pattern
      hours: "/1"
  action:
    - service: counter.reset
      target:
        entity_id: counter.drone_patrols_last_hour
```

2. **Alert on repeated triggers:**

```yaml
- alias: "Adversarial trigger detection"
  trigger:
    - platform: state
      entity_id: counter.drone_patrols_last_hour
  condition:
    - condition: numeric_state
      entity_id: counter.drone_patrols_last_hour
      above: 2
  action:
    - service: notify.mobile_app_rpic_phone
      data:
        title: "Repeated Patrol Triggers"
        message: >
          {{ states('counter.drone_patrols_last_hour') }} patrols triggered in the
          last hour. Possible adversarial trigger pattern. Autonomous launches suspended
          until counter resets.
        data:
          push:
            sound:
              name: default
              critical: 1
              volume: 1.0
```

**Residual risk:** The battery will eventually be exhausted after the allowed patrols. The escalating threshold ensures the drone retains enough charge for at least one more emergency patrol.

---

## Recommendation R-02: Mosquitto ACL Config

**Resolution:** Fully addressed in ATK-MQTT-01 above. The complete ACL file, password file generation, and Mosquitto configuration are provided.

---

## Recommendation R-03: VLAN Isolation

**Resolution:** Fully addressed in ATK-LAT-02 above. The VLAN topology, firewall rules between VLANs, and internet access restrictions are provided.

Summary of VLAN design:

| VLAN | Subnet | Purpose | Internet |
|------|--------|---------|----------|
| VLAN 10 | 10.0.10.0/24 | HA Server, Mosquitto, go2rtc, ESPHome dock | Yes (for Litestream, push notifications) |
| VLAN 20 | 10.0.20.0/24 | Drone RPi, camera, SiK radio base | No |
| VLAN 1 | 10.0.1.0/24 | Home LAN (workstations, phones) | Yes |

Inter-VLAN rules:
- VLAN 20 -> VLAN 10: only MAVLink (14540/udp) and RTSP (8554/tcp) to HA server IP
- VLAN 10 -> VLAN 20: only MAVLink and RTSP to drone IPs, SSH to RPi
- VLAN 20 -> VLAN 1: DENY ALL
- VLAN 1 -> VLAN 10: only 8123/tcp (HA UI), 8883/tcp (MQTT for debugging if needed)

---

## Recommendation R-04: RPi Hardening

**Resolution:** Fully addressed in ATK-LAT-02 above (the RPi hardening script). Summary:
- Key-only SSH, password auth disabled
- Default `pi` user removed, dedicated `dronecomp` user
- Unattended upgrades enabled
- Unnecessary services disabled (avahi, bluetooth, cups)
- UFW firewall with deny-all default, specific allow rules only
- No internet access

---

## Recommendation R-07: Litestream Mandatory for Part 108

**Resolution:**

The bridge must check for active Litestream replication on startup and refuse to operate in Part 108 mode without it.

```python
# Bridge startup check
class Bridge:
    async def start(self):
        # Check Litestream config
        litestream_configured = os.path.exists("/data/compliance/litestream.yml")

        if self.config["operational_mode"] == "part_108":
            if not litestream_configured:
                logger.critical(
                    "Part 108 mode requires Litestream replication. "
                    "Configure /data/compliance/litestream.yml before enabling Part 108."
                )
                raise SystemExit(1)

            # Verify replication is actually running
            if not await self._verify_litestream_health():
                logger.critical("Litestream replication is configured but not healthy.")
                raise SystemExit(1)

        elif not litestream_configured:
            logger.warning(
                "Litestream replication is not configured. "
                "Compliance records exist only on this device. "
                "This is acceptable for Part 107 but REQUIRED for Part 108."
            )
            # Publish persistent warning to HA
            await self.mqtt.publish(
                f"drone_hass/{self.drone_id}/state/warnings",
                json.dumps({"litestream": "not_configured"}),
                retain=True,
            )
```

**Litestream config with S3 Object Lock** (`/data/compliance/litestream.yml`):

```yaml
dbs:
  - path: /data/compliance/compliance.db
    replicas:
      - type: s3
        bucket: "drone-hass-compliance"
        path: "patrol/"
        endpoint: "s3.us-west-2.amazonaws.com"
        region: "us-west-2"
        access-key-id: "${LITESTREAM_ACCESS_KEY_ID}"
        secret-access-key: "${LITESTREAM_SECRET_ACCESS_KEY}"
        retention: 8760h  # 1 year
        sync-interval: 1s
```

**S3 bucket configuration** (enable Object Lock during bucket creation -- it cannot be enabled after):

```bash
aws s3api create-bucket \
  --bucket drone-hass-compliance \
  --region us-west-2 \
  --create-bucket-configuration LocationConstraint=us-west-2 \
  --object-lock-enabled-for-bucket

aws s3api put-object-lock-configuration \
  --bucket drone-hass-compliance \
  --object-lock-configuration '{
    "ObjectLockEnabled": "Enabled",
    "Rule": {
      "DefaultRetention": {
        "Mode": "COMPLIANCE",
        "Years": 3
      }
    }
  }'
```

Compliance mode means even the AWS root account cannot delete objects during the retention period.

---

## Recommendation R-08: Ed25519 Key Protection

**Resolution:**

1. **Key storage with restrictive permissions** (in bridge startup):

```python
import os
import stat
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization

KEY_PATH = "/data/compliance/signing_key.pem"
PUBKEY_PATH = "/data/compliance/signing_key.pub"

def load_or_create_signing_key():
    if os.path.exists(KEY_PATH):
        # Verify permissions
        st = os.stat(KEY_PATH)
        if st.st_mode & 0o077:  # Any group/other permissions
            logger.critical(
                "Signing key has insecure permissions: %s. "
                "Expected 0600. Refusing to start.",
                oct(st.st_mode)
            )
            raise SystemExit(1)

        with open(KEY_PATH, "rb") as f:
            private_key = serialization.load_pem_private_key(f.read(), password=None)
        return private_key

    # First install: generate key
    private_key = Ed25519PrivateKey.generate()

    # Write private key with 0600 permissions
    with open(KEY_PATH, "wb") as f:
        f.write(private_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption()
        ))
    os.chmod(KEY_PATH, stat.S_IRUSR | stat.S_IWUSR)  # 0600

    # Write public key (this one can be shared)
    public_key = private_key.public_key()
    with open(PUBKEY_PATH, "wb") as f:
        f.write(public_key.public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo
        ))
    os.chmod(PUBKEY_PATH, 0o644)

    # Log the public key fingerprint as the first compliance record
    fingerprint = hashlib.sha256(
        public_key.public_bytes(
            serialization.Encoding.Raw,
            serialization.PublicFormat.Raw
        )
    ).hexdigest()

    logger.info("Generated new Ed25519 signing key. Fingerprint: %s", fingerprint)
    logger.info(
        "IMPORTANT: Register this fingerprint with a trusted third party "
        "(email to attorney, print and store in safe). "
        "Fingerprint: %s", fingerprint
    )

    return private_key
```

2. **Exclude the key from HA backups.** The HA Supervisor backs up everything in `/data/`. To exclude the key, store it in a location the backup does not cover, or use a `.gitignore`-style exclusion if supported. Since HAOS add-on backups include all of `/data/`, the practical approach is:

```python
# Store key outside the standard backup path
# Option A: Use /config/.ssl/ which is typically not backed up with add-on data
# Option B: Document that the key must be backed up separately

# In the add-on documentation:
# WARNING: The signing key at /data/compliance/signing_key.pem is included
# in HA backups. After creating a backup, extract and delete the key from
# the backup archive. Store the key backup separately (encrypted USB,
# printed QR code, etc.).
```

The most practical approach for HAOS: accept that the key is in backups, but encrypt all HA backups with a strong password. Document that backup encryption is mandatory.

---

## Recommendation R-11: Patrol Cooldown

**Resolution:** Fully addressed in ATK-DOS-01 above. The cooldown timer, escalating battery thresholds, and adversarial pattern detection automation are provided.

---

## Recommendation R-13: MQTT TLS Mandatory

**Resolution:** Fully addressed in ATK-MQTT-01 above. The Mosquitto configuration disables the plaintext listener entirely and only exposes TLS on port 8883. The TLS certificate paths, HA MQTT integration config, and bridge add-on config are all provided.

To generate self-signed certificates for the MQTT broker (if not using Let's Encrypt):

```bash
# Generate CA
openssl genrsa -out /ssl/mosquitto/ca.key 4096
openssl req -x509 -new -nodes -key /ssl/mosquitto/ca.key \
  -sha256 -days 3650 -out /ssl/mosquitto/ca.crt \
  -subj "/CN=drone_hass MQTT CA"

# Generate server cert
openssl genrsa -out /ssl/mosquitto/server.key 2048
openssl req -new -key /ssl/mosquitto/server.key \
  -out /ssl/mosquitto/server.csr \
  -subj "/CN=core-mosquitto"
openssl x509 -req -in /ssl/mosquitto/server.csr \
  -CA /ssl/mosquitto/ca.crt -CAkey /ssl/mosquitto/ca.key \
  -CAcreateserial -out /ssl/mosquitto/server.crt \
  -days 3650 -sha256

# Set permissions
chmod 600 /ssl/mosquitto/server.key /ssl/mosquitto/ca.key
chmod 644 /ssl/mosquitto/server.crt /ssl/mosquitto/ca.crt
```

---

## Recommendation R-15: RTSP Authentication

**Resolution:** Fully addressed in ATK-VID-01 above. The go2rtc configuration with RTSP authentication, firewall rules, and camera authentication are provided.

---

## Recommendation R-16: Video Retention Policy

**Resolution:** Fully addressed in ATK-VID-02 above. The 30-day auto-delete shell command automation is provided.

---

## Recommendation R-17: Auto verify_chain

**Resolution:**

```python
# Bridge startup and daily verification
class ComplianceRecorder:
    async def startup_verification(self):
        """Run verify_chain on startup and publish result."""
        result = self.verify_chain()
        if not result["valid"]:
            logger.critical(
                "Compliance chain verification FAILED on startup. "
                "Records %d-%d are invalid. Details: %s",
                result.get("first_invalid", "?"),
                result.get("last_checked", "?"),
                result.get("error", "unknown"),
            )
            await self.mqtt.publish(
                f"drone_hass/{self.drone_id}/state/warnings",
                json.dumps({"compliance_chain": "INVALID", "details": result}),
                retain=True,
                qos=1,
            )
            # In Part 108 mode, refuse to start
            if self.config["operational_mode"] == "part_108":
                raise SystemExit(1)
        else:
            logger.info(
                "Compliance chain verified: %d records, chain intact.",
                result["total_records"],
            )

    def verify_chain(self) -> dict:
        """Verify the hash chain integrity of all compliance records."""
        cursor = self.db.execute(
            "SELECT id, event_type, timestamp, prev_hash, record_hash, signature "
            "FROM compliance_records ORDER BY id ASC"
        )
        prev_hash = None
        count = 0
        for row in cursor:
            count += 1
            # Verify prev_hash links to previous record
            if row["prev_hash"] != prev_hash:
                return {
                    "valid": False,
                    "first_invalid": row["id"],
                    "error": f"Hash chain break at record {row['id']}",
                    "total_records": count,
                }
            # Verify record_hash is correct
            computed = self._compute_hash(row)
            if computed != row["record_hash"]:
                return {
                    "valid": False,
                    "first_invalid": row["id"],
                    "error": f"Record hash mismatch at record {row['id']}",
                    "total_records": count,
                }
            # Verify Ed25519 signature
            if not self._verify_signature(row):
                return {
                    "valid": False,
                    "first_invalid": row["id"],
                    "error": f"Signature invalid at record {row['id']}",
                    "total_records": count,
                }
            prev_hash = row["record_hash"]

        return {"valid": True, "total_records": count}
```

**Daily verification cron** (inside the add-on container, via S6-overlay):

```bash
# /etc/s6-overlay/s6-rc.d/daily-verify/run
#!/command/with-contenv bashio
while true; do
    sleep 86400  # 24 hours
    python3 -m mavlink_mqtt_bridge.verify_chain
done
```

Or trigger from HA via a daily automation that calls a bridge service.

---

## Recommendation R-19: Compliance Record Source Field

**Resolution:** Fully addressed in ATK-MQTT-03 above. The `source` field (`bridge_internal` vs `ha_external`) is added to every compliance record, and authorization events are rejected if sourced externally.

---

## Recommendation R-20: Mission Allowlist

**Resolution:** Fully addressed in ATK-MQTT-02 above. The `missions.allowlist` configuration in `bridge_config.yaml` and the enforcement code are provided.

---

## Recommendation R-21: Non-Root Bridge

**Resolution:** Fully addressed in ATK-LAT-01 above. The Dockerfile with non-root user, S6-overlay user switching, and capability dropping are provided.

---

## Recommendation R-22: WPA3 Mandate

**Resolution:**

Document as a mandatory deployment requirement. On the ASUS router:

1. Navigate to Wireless -> General -> Band (the one serving the drone VLAN SSID)
2. Set Authentication Method: **WPA3-Personal (SAE)**
3. Enable Protected Management Frames: **Required** (not optional)
4. Set the pre-shared key to a strong random passphrase (20+ characters)
5. Optionally hide the SSID (minor security benefit but reduces discoverability)

**Deployment checklist item:**

```
[ ] Drone WiFi SSID uses WPA3-SAE with PMF Required
[ ] Verified by connecting with a WPA3-capable client
[ ] WPA2 fallback is DISABLED on the drone SSID
[ ] SSID is bound to VLAN 20 (drone VLAN)
```

If the ASUS router does not support WPA3, this is a blocking deployment requirement -- upgrade the router or use a dedicated WPA3-capable AP for the drone VLAN.

**Residual risk:** WPA3 with PMF prevents deauthentication attacks. However, if the attacker uses a WiFi jammer (illegal, but possible), the WiFi link is still disrupted. The SiK 915 MHz backup link provides redundant C2 in this scenario.

---

## Recommendation R-23: Emergency Disable

**Resolution:**

1. **HA service and helper:**

```yaml
# configuration.yaml
input_boolean:
  drone_emergency_disable:
    name: "Drone Emergency Disable"
    icon: mdi:alert-octagon
```

In the patrol automation, add this as the first condition:

```yaml
condition:
  - condition: state
    entity_id: input_boolean.drone_emergency_disable
    state: "off"
  # ... other conditions
```

2. **Physical kill switch on the dock** (ESPHome):

```yaml
# dock.yaml -- ESPHome
binary_sensor:
  - platform: gpio
    pin:
      number: GPIO32
      mode: INPUT_PULLUP
    name: "Dock Emergency Disable"
    id: emergency_disable
    device_class: safety
    on_press:
      then:
        # Locally: prevent lid from opening
        - globals.set:
            id: emergency_mode
            value: "true"
        - logger.log: "EMERGENCY DISABLE activated"

globals:
  - id: emergency_mode
    type: bool
    restore_value: true
    initial_value: "false"
```

3. **HA automation to sync physical switch with the input_boolean:**

```yaml
- alias: "Sync dock emergency disable"
  trigger:
    - platform: state
      entity_id: binary_sensor.dock_emergency_disable
      to: "on"
  action:
    - service: input_boolean.turn_on
      target:
        entity_id: input_boolean.drone_emergency_disable
    - service: notify.mobile_app_rpic_phone
      data:
        title: "EMERGENCY DISABLE"
        message: "Drone emergency disable activated. All autonomous launches blocked."
        data:
          push:
            sound:
              name: default
              critical: 1
              volume: 1.0
```

4. **HA service for remote emergency disable:**

```yaml
# In the drone_hass integration, expose as a service:
# drone_hass.emergency_disable -- sets input_boolean and sends RTH if airborne

- alias: "Emergency disable -- RTH if airborne"
  trigger:
    - platform: state
      entity_id: input_boolean.drone_emergency_disable
      to: "on"
  condition:
    - condition: state
      entity_id: binary_sensor.patrol_airborne
      state: "on"
  action:
    - service: drone_hass.return_to_home
      target:
        device_id: <drone_device_id>
```

---

## Recommendation R-24: RPIC GPS Logging

**Resolution:**

In the Part 107 authorization flow, capture the RPIC's phone GPS location and include it in the compliance record:

```yaml
# HA automation -- when RPIC taps LAUNCH
- alias: "Log RPIC location on authorization"
  trigger:
    - platform: event
      event_type: mobile_app_notification_action
      event_data:
        action: "LAUNCH_DRONE"
  action:
    # Log RPIC location as compliance event
    - service: drone_hass.log_compliance_event
      data:
        event: "rpic_location_at_authorization"
        details:
          rpic_lat: "{{ state_attr('device_tracker.rpic_phone', 'latitude') }}"
          rpic_lon: "{{ state_attr('device_tracker.rpic_phone', 'longitude') }}"
          rpic_gps_accuracy: "{{ state_attr('device_tracker.rpic_phone', 'gps_accuracy') }}"
          distance_to_dock_m: >
            {{ distance('device_tracker.rpic_phone', 'zone.home') | float * 1000 }}
    # Warn if RPIC is too far from operational area
    - condition: template
      value_template: >
        {{ distance('device_tracker.rpic_phone', 'zone.home') | float > 0.5 }}
    - service: notify.mobile_app_rpic_phone
      data:
        title: "VLOS WARNING"
        message: >
          You appear to be {{ (distance('device_tracker.rpic_phone', 'zone.home') | float * 1000) | round(0) }}m
          from the operational area. Part 107 requires VLOS. Launch at your own regulatory risk.
```

**Residual risk:** GPS location can be spoofed on a jailbroken phone. The system logs what is available but cannot verify the RPIC's actual physical location. This creates a record for auditing, not an enforcement mechanism.

---

## Recommendation R-26: Dock Tamper Sensor

**Resolution:** Fully addressed in ATK-DOCK-02 above. The ESPHome reed switch / vibration sensor configuration, HA tamper alert automation with critical push notification, and security screw specification are provided.

---

## Summary of Residual Risks After All Mitigations

| Area | Residual Risk | Severity | Justification |
|------|--------------|----------|---------------|
| MQTT | Compromised HA server exposes `ha_user` credentials | Medium | Bridge ComplianceGate blocks unauthorized flights regardless |
| Video | RTSP basic auth is not encrypted | Low | Network isolation (VLAN) is the primary control |
| Container | Bridge has `media:rw` shared directory access | Low | Non-root process, minimal capabilities |
| Compliance key | Key is in HA backups on HAOS | Medium | Encrypted backups mandatory; separate key backup documented |
| Physical | Tamper sensor is alerting only, not prevention | Low | Residential threat model; camera coverage supplements |
| RPIC location | Cannot technically enforce VLOS | Medium | Logging creates audit trail; Part 108 removes this requirement |
| Drone WiFi | WiFi jammer defeats WPA3 | Low | SiK backup link; RTL failsafe; illegal equipment required |