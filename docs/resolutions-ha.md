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
  altitude_ceiling_m: 55  # 180 ft — 5 m above RTL_ALT (50 m), well below Part 107 §107.51 ceiling (122 m)
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
listener 8883 10.10.10.1
```

Where `10.10.10.1` is the HA server's IP on the drone/IoT VLAN. This prevents any device on other VLANs from reaching the broker.

If using the HAOS Mosquitto add-on (which does not support per-interface binding natively), enforce this at the firewall level instead:

```bash
# On the ASUS router (iptables-style, adapt to your model):
# Only allow MQTT from the bridge container IP and HA's own IP
iptables -A FORWARD -d 10.10.10.1 -p tcp --dport 8883 -s 10.10.10.2 -j ACCEPT  # bridge
iptables -A INPUT -d 10.10.10.1 -p tcp --dport 8883 -s 127.0.0.1 -j ACCEPT    # HA local
iptables -A FORWARD -d 10.10.10.1 -p tcp --dport 8883 -j DROP                  # all others
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
  broker: 10.10.10.1
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
# Dock heartbeat (architecture.md §5.5 — bridge refuses to arm if stale)
topic write drone_hass/+/dock/heartbeat
# Dock authorization-display cross-verification (ATK-HA-02 commitment scheme).
# READ-ONLY on the request topic — dock displays whatever bridge_user publishes.
# ha_user is read-only too, but the dock independently verifies the HMAC payload
# (see ATK-HA-02 below) so a hostile ha_user cannot make the dock display a
# spoofed challenge.
topic read  drone_hass/+/command/authorize_flight/request
# Dock display-clear topic (operator-initiated abort, optional)
topic read  drone_hass/+/dock/display/clear
```

**Mosquitto enforcement:** the broker ACL ensures only `bridge_user` can WRITE to `drone_hass/+/command/authorize_flight/request`. `ha_user` is read-only on that topic. The dock subscribes; if a request arrives that did not originate from `bridge_user`, it never reaches the broker because the broker rejects the publish.

5. **The bridge ComplianceGate must independently verify weather** from the dock MQTT topics it subscribes to directly, not from HA entity states.

**Residual risk:** A compromised HA admin account can still modify automations, but cannot bypass the bridge ComplianceGate for flight-critical operations.

---

## ATK-HA-02: Push Notification Spoofing (Part 107 RPIC Authorization)

**Resolution:**

Two-channel commit-and-reveal authorization flow. The MQTT broker only ever sees a *commitment* (a SHA-256 hash). The actual nonce is delivered to the RPIC out-of-band — primary path is an Ingress panel served by the bridge itself; fallback path is a push notification routed through an HA webhook automation. `ha_user` MQTT credentials alone are insufficient to forge an authorization.

### Commitment generation (bridge)

```python
import secrets, hashlib, time

class ComplianceGate:
    AUTH_RATE_LIMIT_S = 60   # max one authorize request per drone per minute (DoS guard)

    async def _wait_for_rpic_authorization(self, timeout=120):
        # 1. Generate a one-time secret nonce and its commitment.
        nonce = secrets.token_urlsafe(32)                              # 32 bytes urandom = 256 bits
        commitment = hashlib.sha256(nonce.encode()).hexdigest()
        challenge_display = commitment[:12]                            # 12-char visual code

        # 2. Store nonce + expiry in memory only. Never publish nonce on MQTT.
        self._pending_auth_nonce = nonce
        self._pending_auth_commitment = commitment
        self._pending_auth_expires = time.time() + timeout
        self._pending_auth_consumed = False

        # 3. Publish the commitment + display code + dock-side HMAC to MQTT.
        # ha_user can read this — that is fine; the commitment leaks no information
        # about the preimage. The HMAC binds the payload to a key the dock holds
        # so a compromised ha_user (write only via broker ACL violation, but
        # defence-in-depth) cannot make the dock OLED display an attacker-chosen
        # value. The HMAC key is provisioned to the dock at install time over
        # USB and is distinct from the bridge↔phone HMAC key.
        monotonic_nonce = self._next_monotonic_auth_nonce()            # local counter, persisted
        payload = {
            "commitment": commitment,
            "challenge_display": challenge_display,                    # cross-verify on dock OLED + HA card + phone
            "mission_id": self._pending_mission_id,
            "expires_at": self._pending_auth_expires,
            "monotonic_nonce": monotonic_nonce,                        # dock rejects if non-increasing (replay)
        }
        payload["dock_hmac"] = hmac.new(
            self.config["dock_authorize_hmac_key"].encode(),
            json.dumps(
                {k: payload[k] for k in ("commitment", "challenge_display",
                                          "mission_id", "expires_at", "monotonic_nonce")},
                sort_keys=True,
            ).encode(),
            hashlib.sha256,
        ).hexdigest()
        await self.mqtt.publish(
            f"drone_hass/{self.drone_id}/command/authorize_flight/request",
            json.dumps(payload),
            qos=1,
        )

        # 4. Deliver the nonce to the RPIC out-of-band.
        #    Primary:  Ingress panel (RPIC at HA UI) — bridge holds the nonce in
        #              process memory; UI fetches via Ingress, no MQTT.
        #    Fallback: webhook -> HA automation -> mobile_app push notification.
        await self._deliver_nonce_oob(nonce, challenge_display)

        # 5. Wait for the response. Verify the preimage hashes to our commitment
        #    AND the commitment has not already been consumed.
        try:
            response = await asyncio.wait_for(
                self._auth_response_future, timeout=timeout
            )
            received = response.get("nonce", "")
            if hashlib.sha256(received.encode()).hexdigest() != self._pending_auth_commitment:
                return False
            if time.time() > self._pending_auth_expires:
                return False
            if self._pending_auth_consumed:                            # single-use
                return False
            self._pending_auth_consumed = True
            return True
        except asyncio.TimeoutError:
            return False
        finally:
            self._pending_auth_nonce = None
            self._pending_auth_commitment = None

    async def _deliver_nonce_oob(self, nonce, challenge_display):
        """Out-of-band nonce delivery. The Ingress panel polls in-process state
        and never needs the nonce on the wire. The webhook fallback POSTs it to
        HA over a local HTTP socket bound to the Docker bridge network."""
        # Make the nonce visible to the Ingress panel via in-process state.
        self._ingress_panel_state["nonce"] = nonce

        # Also fire the webhook fallback for an absent/mobile RPIC.
        webhook_url = self.config["ha_webhook_url"]                    # e.g. http://homeassistant:8123/api/webhook/<id>
        async with aiohttp.ClientSession() as s:
            await s.post(webhook_url, json={
                "nonce": nonce,
                "challenge_display": challenge_display,
                "mission_id": self._pending_mission_id,
                # HMAC over the body using a shared secret known only to bridge + HA automation.
                # Defense-in-depth against webhook URL leakage.
                "hmac": hmac.new(
                    self.config["webhook_hmac_key"].encode(),
                    json.dumps({"nonce": nonce, "mid": self._pending_mission_id}, sort_keys=True).encode(),
                    hashlib.sha256,
                ).hexdigest(),
            })
```

### Out-of-band delivery — primary: Ingress panel

The bridge add-on exposes an Ingress panel (`ingress: true`, `ingress_port: 8099` per architecture.md §8.3). When an authorize request is pending, the panel renders mission_id + challenge_display + an "AUTHORIZE LAUNCH" button. Clicking the button POSTs the in-memory nonce to the bridge's local HTTP endpoint, which feeds the response back into `_auth_response_future` in-process. The nonce never traverses MQTT, never traverses HA Core. This is the preferred flow when the RPIC is at the HA UI.

### Out-of-band delivery — fallback: HA webhook automation

When the RPIC is mobile, the bridge POSTs to a webhook automation in HA. The webhook URL is the capability — narrowly scoped to one action, rotatable by deleting the automation. HA long-lived access tokens (LLATs) are deliberately *not* used here: HA tokens cannot be scoped to a single service, so a token issued for `notify.*` is functionally admin.

```yaml
# HA automation: webhook -> push notification
- alias: "Bridge: deliver authorize_flight nonce to RPIC phone"
  trigger:
    - platform: webhook
      webhook_id: !secret bridge_authorize_webhook_id      # 128-bit random URL component
      local_only: true                                     # bridge and HA share the Docker network
      allowed_methods: [POST]
  condition:
    # Defense in depth: HMAC check rejects spoofed POSTs even if the webhook URL leaks.
    - "{{ trigger.json.hmac == 
         (trigger.json.nonce + trigger.json.mission_id) | hmac('sha256', states('input_text.bridge_webhook_hmac')) }}"
  action:
    - service: notify.mobile_app_rpic_phone
      data:
        title: "Perimeter Alert"
        message: "Mission: {{ trigger.json.mission_id }} | Code: {{ trigger.json.challenge_display }}"
        data:
          actions:
            - action: "LAUNCH_DRONE"
              title: "LAUNCH DRONE"
            - action: "IGNORE"
              title: "IGNORE"
          action_data:
            nonce: "{{ trigger.json.nonce }}"

# Handle the RPIC tap: forward the nonce preimage back via the response topic.
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

### Cross-verification

The 12-character `challenge_display` MUST be shown in three places simultaneously and the RPIC MUST verify all three match before tapping LAUNCH:

1. **Phone push notification** — short code in the message body
2. **Dock OLED display** — ESPHome displays the same code (subscribed to the same MQTT request topic)
3. **HA Lovelace card** — bridge integration card shows the pending request

A rogue push notification crafted by an attacker with only `ha_user` cannot match the dock OLED code, because the OLED is driven by the MQTT commitment topic published by the bridge. The RPIC catches the discrepancy and refuses to tap LAUNCH.

### Rate limiting

Bridge enforces `AUTH_RATE_LIMIT_S = 60` between authorize requests for the same `drone_id`. This caps the push-spam denial-of-service surface where an attacker repeatedly triggers authorize_flight commands to fatigue the RPIC into tapping reflexively.

### Why this defeats `ha_user` replay

- MQTT carries only `sha256(nonce)`. SHA-256 preimage resistance prevents `ha_user` from deriving the nonce.
- The webhook URL and HMAC key are not in MQTT; they live in HA's `secrets.yaml` and the bridge's separate secrets store.
- The Ingress panel path bypasses HA entirely once configured.
- Single-use enforcement (`_pending_auth_consumed`) prevents an attacker who races to capture an in-flight response from re-authorizing a second mission within the same window.

### Residual risks

| Attacker capability | Result | Why |
|---|---|---|
| `ha_user` MQTT credentials only | Defeated | Sees only the commitment; cannot derive the nonce |
| `ha_user` MQTT + leaked webhook URL | Defeated by HMAC condition | Rogue POSTs fail the template HMAC check |
| `ha_user` MQTT + webhook URL + HMAC key | Wins (compromised HA) | Acknowledged residual risk; bridge cannot defend against full HA compromise |
| Compromised RPIC phone | Wins | Inherent to the RPIC-tap regulatory model |
| Push spam DoS | Limited to 1 req/min/drone | Rate limit caps fatigue attacks |

### Operational dependency note

Both delivery paths require HA Core to be running:
- The Ingress panel is served via HA's auth proxy.
- The webhook automation executes inside HA Core.

Compliance *logging* continues independently of HA Core (the bridge writes to its own SQLite + Litestream). Only the *launch authorization* requires HA. This is the intended scope of the compliance-independence principle: HA can be down, the chain keeps writing, but no new flights can launch until HA is back.

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
    - rtsp://camera_user:camera_pass@10.10.20.50:8554/main  # Camera on drone VLAN

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
# Drone VLAN: 10.10.20.0/24, HA server: 10.10.10.1, Camera on drone: 10.10.20.50

# Allow HA server -> camera RTSP
iptables -A FORWARD -s 10.10.10.1 -d 10.10.20.50 -p tcp --dport 8554 -j ACCEPT
# Block all other access to camera RTSP
iptables -A FORWARD -d 10.10.20.50 -p tcp --dport 8554 -j DROP

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
# Base image is pinned by digest in CI; the :3.22 tag is shown for readability.
# Renovate refreshes the digest on every base-image release.
FROM ghcr.io/home-assistant/amd64-base:3.22

# Install dependencies
RUN apk add --no-cache python3 py3-pip curl ca-certificates

# Create non-root user
RUN addgroup -S bridge && adduser -S bridge -G bridge

# Fetch and verify mavsdk_server binary (supply-chain hardening — see R-27)
ARG MAVSDK_VERSION=2.12.0
ARG MAVSDK_SHA256
RUN test -n "${MAVSDK_SHA256}" \
 && curl -fsSL -o /tmp/mavsdk_server \
      "https://github.com/mavlink/MAVSDK/releases/download/v${MAVSDK_VERSION}/mavsdk_server_musl_linux-amd64" \
 && echo "${MAVSDK_SHA256}  /tmp/mavsdk_server" | sha256sum -c - \
 && install -m 0755 /tmp/mavsdk_server /usr/local/bin/mavsdk_server \
 && rm -f /tmp/mavsdk_server

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

The S6 init script re-verifies the on-disk `mavsdk_server` SHA-256 against the build-time value at every container start, so a tampered image layer (or a runtime bind-mount swap) fails closed before the bridge talks to the airframe.

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
sudo ufw allow in from 10.10.10.1 to any port 22 proto tcp   # SSH from HA only
sudo ufw allow out to 10.10.10.1 port 8883 proto tcp          # MQTT to broker (if needed)
sudo ufw allow out to 10.10.10.1 port 8554 proto tcp          # RTSP to media server
sudo ufw allow in from 10.10.10.1 port 14540 proto udp        # MAVLink from bridge
sudo ufw allow out to any port 14540 proto udp                # MAVLink to FC
sudo ufw allow out to any port 53 proto udp                   # DNS for NTP
sudo ufw allow out to any port 123 proto udp                  # NTP
sudo ufw enable
```

2. **Dedicated drone VLAN** (on ASUS router):

```
VLAN 20: Drone VLAN (10.10.20.0/24)
  - RPi companion computer: 10.10.20.10 (static DHCP lease)
  - Camera (Siyi A8 Mini): 10.10.20.50 (static DHCP lease)
  - WiFi SSID: "DroneNet" (WPA3-SAE, PMF required, hidden SSID)

VLAN 10: IoT/HA VLAN (10.10.10.0/24)
  - HA Server: 10.10.10.1
  - Mosquitto: 10.10.10.1:8883
  - go2rtc: 10.10.10.1:8554
  - ESPHome dock: 10.10.10.20
```

**Firewall rules between VLANs** (on ASUS router or dedicated firewall):

```
# VLAN 20 (Drone) -> VLAN 10 (HA): only specific ports
ALLOW 10.10.20.10 -> 10.10.10.1:14540/udp  # MAVLink from RPi to bridge
ALLOW 10.10.20.50 -> 10.10.10.1:8554/tcp   # RTSP from camera to media server
DENY  10.10.20.0/24 -> 10.10.10.0/24       # Block everything else

# VLAN 10 (HA) -> VLAN 20 (Drone): only bridge needs to reach RPi
ALLOW 10.10.10.1 -> 10.10.20.10:14540/udp  # MAVLink from bridge to RPi
ALLOW 10.10.10.1 -> 10.10.20.50:8554/tcp   # RTSP pull from camera
ALLOW 10.10.10.1 -> 10.10.20.10:22/tcp     # SSH for maintenance
DENY  10.10.10.0/24 -> 10.10.20.0/24       # Block everything else

# VLAN 20 (Drone) -> Internet: DENY ALL
DENY  10.10.20.0/24 -> 0.0.0.0/0          # No internet for drone VLAN
# Exception: NTP if needed
ALLOW 10.10.20.10 -> <NTP_SERVER>:123/udp
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
| VLAN 10 | 10.10.10.0/24 | HA Server, Mosquitto, go2rtc, ESPHome dock | Yes (for Litestream, push notifications) |
| VLAN 20 | 10.10.20.0/24 | Drone RPi, camera, SiK radio base | No |
| VLAN 1 | 10.10.0.0/24 | Management / home LAN (workstations, phones) | Yes |

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

The Ed25519 signing private key is the single most sensitive secret in the compliance system: anyone who holds it can sign forged compliance records that verify cleanly. Earlier revisions of this doc accepted "key in HA backups" as a residual risk; that is no longer accepted. The key is wrapped with a memory-hard KDF before it ever touches disk, and the on-disk live copy is additionally TPM-sealed so an offline disk-image attacker cannot extract it without a TPM-equipped host.

### Envelope format (used for both on-disk and backup)

```python
# scrypt + AES-256-GCM, JSON envelope. Versioned for forward compatibility.
{
    "version": 1,
    "kdf": "scrypt",
    "n": 131072,                  # 2^17 — ~250 MB working set
    "r": 8,
    "p": 1,
    "salt": "<base64, 32 bytes>",
    "nonce": "<base64, 12 bytes>",
    "ciphertext": "<base64>",     # AES-256-GCM(plaintext = raw 32-byte Ed25519 seed)
    "aad": "drone_hass_signing_key_v1|<drone_id>"
}
```

`drone_id` is bound into the AEAD additional authenticated data so a wrapped blob from one install cannot be replayed on a different install.

### Storage modes

| Mode | Live on-disk blob | Backup blob | Boot behaviour |
|---|---|---|---|
| `tpm_sealed` (default if TPM 2.0 present) | scrypt-wrapped envelope encrypted with a TPM-sealed KEK bound to PCR 7 (Secure Boot state) | scrypt + AES-GCM, passphrase-derived KEK | Bridge auto-unseals via TPM; passphrase is recovery-only |
| `passphrase_only` (no TPM, or operator opt-in) | scrypt + AES-GCM, passphrase-derived KEK | same | Bridge prompts on every restart via Ingress |

The default for HAOS hosts with TPM 2.0 is `tpm_sealed`: it survives auto-updates and operator travel without giving up the stolen-backup defence (the backup blob remains passphrase-wrapped). Operators who prefer "no flights happen unless I'm physically present to type the passphrase" can opt into `passphrase_only` in `bridge_config.yaml`.

### Key generation and unseal

```python
import os, stat, secrets, base64, json, hashlib, hmac, ctypes
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from zxcvbn import zxcvbn

KEY_PATH        = "/data/compliance/signing_key.enc"      # encrypted envelope, NOT .pem
PUBKEY_PATH     = "/data/compliance/signing_key.pub"
LEGACY_PEM      = "/data/compliance/signing_key.pem"
SCRYPT_N, SCRYPT_R, SCRYPT_P = 2**17, 8, 1
SCRYPT_SALT_LEN = 32
AES_NONCE_LEN   = 12

class PassphraseRejected(Exception): pass

def _validate_passphrase(passphrase: str):
    if len(passphrase) < 16:
        raise PassphraseRejected("Min 16 characters")
    score = zxcvbn(passphrase)["score"]                   # 0..4
    if score < 3:
        raise PassphraseRejected(f"Passphrase too weak (zxcvbn score {score}, need >= 3)")
    if _is_in_breach_corpus(passphrase):                  # offline top-10k check
        raise PassphraseRejected("Passphrase appears in breach corpus")

def _zeroize(buf: bytearray):
    """Best-effort wipe of sensitive bytes from memory."""
    ctypes.memset(ctypes.addressof(ctypes.c_char.from_buffer(buf)), 0, len(buf))

def _wrap(seed: bytes, passphrase: str, drone_id: str) -> dict:
    salt = secrets.token_bytes(SCRYPT_SALT_LEN)
    kek = Scrypt(salt=salt, length=32, n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P).derive(passphrase.encode())
    nonce = secrets.token_bytes(AES_NONCE_LEN)
    aad = f"drone_hass_signing_key_v1|{drone_id}".encode()
    ct = AESGCM(kek).encrypt(nonce, seed, aad)
    envelope = {
        "version": 1, "kdf": "scrypt", "n": SCRYPT_N, "r": SCRYPT_R, "p": SCRYPT_P,
        "salt": base64.b64encode(salt).decode(),
        "nonce": base64.b64encode(nonce).decode(),
        "ciphertext": base64.b64encode(ct).decode(),
        "aad": aad.decode(),
    }
    _zeroize(bytearray(kek))
    return envelope

def _unwrap(envelope: dict, passphrase: str, drone_id: str) -> bytes:
    salt = base64.b64decode(envelope["salt"])
    nonce = base64.b64decode(envelope["nonce"])
    ct = base64.b64decode(envelope["ciphertext"])
    aad = f"drone_hass_signing_key_v1|{drone_id}".encode()
    if envelope["aad"].encode() != aad:
        raise PassphraseRejected("Envelope AAD mismatch (wrong drone_id?)")
    kek = Scrypt(salt=salt, length=32, n=envelope["n"], r=envelope["r"], p=envelope["p"]).derive(passphrase.encode())
    try:
        seed = AESGCM(kek).decrypt(nonce, ct, aad)
    finally:
        _zeroize(bytearray(kek))
    return seed

def load_or_create_signing_key(drone_id: str, get_passphrase, get_tpm=None):
    """get_passphrase is a callable that prompts the operator via Ingress.
       get_tpm is a TPM unseal callable (None = no TPM available)."""

    # Refuse to silently overwrite a legacy plaintext key.
    if os.path.exists(LEGACY_PEM):
        raise SystemExit(
            f"Legacy unencrypted key found at {LEGACY_PEM}. Migrate first: "
            f"run `bridge-cli migrate-signing-key` which prompts for a new "
            f"passphrase, wraps the existing key, then deletes the .pem."
        )

    if os.path.exists(KEY_PATH):
        with open(KEY_PATH) as f:
            envelope = json.load(f)

        # Try TPM auto-unseal first (mode = tpm_sealed).
        if get_tpm is not None and envelope.get("tpm_wrapped_kek"):
            try:
                seed = get_tpm(envelope)
            except Exception as e:
                logger.warning("TPM unseal failed (%s); falling back to passphrase", e)
                seed = _unwrap_with_passphrase_prompt(envelope, drone_id, get_passphrase)
        else:
            seed = _unwrap_with_passphrase_prompt(envelope, drone_id, get_passphrase)

        try:
            return Ed25519PrivateKey.from_private_bytes(seed)
        finally:
            _zeroize(bytearray(seed))

    # First install: generate seed, prompt for passphrase, wrap, persist.
    passphrase = get_passphrase(prompt="Set new compliance-key passphrase (min 16 chars, zxcvbn>=3):")
    _validate_passphrase(passphrase)
    private_key = Ed25519PrivateKey.generate()
    seed = private_key.private_bytes(
        serialization.Encoding.Raw,
        serialization.PrivateFormat.Raw,
        serialization.NoEncryption(),
    )
    envelope = _wrap(seed, passphrase, drone_id)
    if get_tpm is not None:
        envelope["tpm_wrapped_kek"] = get_tpm.seal(envelope)   # TPM-seals KEK; backup blob does NOT include this field
    _zeroize(bytearray(seed))
    _zeroize(bytearray(passphrase, "utf-8"))

    with open(KEY_PATH, "w") as f:
        json.dump(envelope, f)
    os.chmod(KEY_PATH, 0o600)

    # Public key + fingerprint as before, written to the chain genesis record.
    public_key = private_key.public_key()
    with open(PUBKEY_PATH, "wb") as f:
        f.write(public_key.public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        ))
    os.chmod(PUBKEY_PATH, 0o644)
    fingerprint = hashlib.sha256(public_key.public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw,
    )).hexdigest()
    logger.info("Generated new Ed25519 signing key. Fingerprint: %s", fingerprint)
    logger.info("IMPORTANT: record this fingerprint out-of-band (paper, attorney email, password manager) — it is the genesis anchor for chain verification.")
    return private_key

def _unwrap_with_passphrase_prompt(envelope, drone_id, get_passphrase):
    # 3 attempts in 60 s with exponential backoff, then bridge stays sealed.
    for attempt in range(3):
        passphrase = get_passphrase(prompt=f"Passphrase (attempt {attempt+1}/3):")
        try:
            seed = _unwrap(envelope, passphrase, drone_id)
            log_compliance_event(type="key_unseal_success", method="passphrase")
            _zeroize(bytearray(passphrase, "utf-8"))
            return seed
        except Exception:
            log_compliance_event(type="key_unseal_failure", method="passphrase", attempt=attempt+1)
            _zeroize(bytearray(passphrase, "utf-8"))
            time.sleep(2 ** attempt)
    raise PassphraseRejected("Bridge remains sealed; restart to retry.")
```

### Operational properties

- **Backup contains only the passphrase-wrapped envelope** (TPM seal is host-bound, never backed up). Stolen backup → attacker faces scrypt+AES-256-GCM with N=2^17. Memory-hard cost defeats GPU/ASIC bruteforce far better than PBKDF2.
- **Stolen disk image** (no host) → TPM-sealed KEK is unrecoverable, attacker falls back to the passphrase, same scrypt cost as the backup attack.
- **Stolen entire host with TPM intact** → TPM auto-unseals on boot. Defense is physical security and the dock tamper sensor (R-26).
- **Compliance gap accounting:** while sealed, the bridge writes `compliance_gap` markers (system-generated, unsigned, timestamped) so auditors see the gap was honest, not tampered.
- **HA `binary_sensor.drone_bridge_sealed`** fires an HA notification when the bridge is sealed so the operator knows to enter the passphrase.

### Backup procedure

The wrapped envelope is mirrored nightly to the existing CATOSTORE2 NAS path (`rsync_media.sh` extension):

```
/data/compliance/signing_key.enc  ->  10.10.4.186:/volume1/llm_backup/drone_hass/keys/
```

Off-site copy: same envelope copied to the same Litestream S3 bucket as the chain itself, in a sibling prefix. Object Lock (COMPLIANCE, 3 yr) prevents deletion.

### Passphrase loss and chain restart

If the operator loses the passphrase AND the TPM is unavailable (new hardware, no recovery passphrase), the chain is dead. The recovery procedure is:

1. Generate a new keypair (same flow as first install).
2. Write a new genesis record that references the prior chain's last hash + the prior chain's last OTS proof. Auditors verify continuity across the break by walking the link.
3. Document the loss event in the operations log.

Operators MUST keep two copies of the passphrase: paper in a fireproof box, and a password manager (1Password / Bitwarden) entry with the recovery procedure URL.

### Remote unseal note

If the operator unseals while traveling via Nabu Casa, the passphrase traverses Cloudflare's TLS tunnel. This is acceptable (TLS 1.3, certificate pinning in the HA Companion app) but document it: passphrase entry over Nabu Casa is a hot path the operator should not use casually. Prefer Tailscale or local network for unseal.

### Recovery tool

A standalone `unwrap_signing_key.py` script ships with the bridge add-on (also published as a separate Python package) so an operator can recover a signed-record set from a backup blob even if the bridge is gone. The script reads the envelope JSON, prompts for passphrase, derives the KEK with scrypt, and emits a raw 32-byte seed file plus a `verify-chain.py` invocation example.

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

## Recommendation R-27: Build Hardening (Supply-Chain)

The bridge add-on container is the trust anchor for every flight authorization, the Ed25519 signing key, and the compliance chain. A supply-chain compromise of any layer in the image — base image, Python wheel, native `mavsdk_server` binary, ArduPilot firmware fetched at build time, ESPHome dock firmware — gives an attacker bridge-equivalent capability. Build hardening makes the chain auditable end-to-end.

### Pin every artifact by content digest

```
ghcr.io/home-assistant/amd64-base:3.22@sha256:<digest>      # base image
mavlink/MAVSDK v2.12.0 mavsdk_server_musl_linux-amd64       SHA-256: <hex>
ArduPilot Copter-4.5.7 .apj                                 SHA-256: <hex> + upstream GPG sig verified
ESPHome 2026.4.x compiled dock firmware                     SHA-256: <hex>
```

The SHA-256 of `mavsdk_server` is checked at build time (Dockerfile, see ATK-LAT-01) and re-verified at every container start by the S6 init. ArduPilot `.apj` artifacts are GPG-verified against the ArduPilot project's published signing key, not just SHA-pinned — upstream tarball replacement attacks defeat hash pinning if the same release is republished. Tampered artifacts fail closed.

### Multi-stage build

Builder stage compiles/fetches; runtime stage strips toolchains and shells where feasible. Smaller attack surface, faster `cosign verify`, simpler SBOM. Distroless runtime base image is a future consideration once the S6/HA-Supervisor integration story for distroless is mature; today the Alpine base is the supported HA add-on path.

### Python supply chain

`requirements.txt` uses `--require-hashes` so a typosquatted package (`mavsdk` vs `mavsdk-python` vs `pymavsdk`) is rejected at install:

```
mavsdk==2.12.0 \
  --hash=sha256:<hex>
aiomqtt==2.3.0 \
  --hash=sha256:<hex>
```

`pip-audit` runs on every Renovate PR; lockfile diffs are reviewed manually before merge.

### SBOM

`syft` generates a CycloneDX SBOM at every CI build:

```yaml
# .github/workflows/build.yml
- uses: anchore/sbom-action@<sha>            # actions pinned by SHA, not tag
  with:
    image: ghcr.io/${{ github.repository }}/bridge:${{ github.sha }}
    format: cyclonedx-json
    output-file: sbom-${{ github.sha }}.json
```

The SBOM is attached as a release asset. The bridge logs both the **image digest** (canonical anchor) and a SHA-256 of the SBOM into the compliance chain at startup so audit can prove which exact dependency tree handled which flight.

### Image signing — hybrid keyless + hardware-backed

| Build type | Signing | Verification |
|---|---|---|
| `main` branch / dev / RC | Sigstore keyless via GitHub Actions OIDC + Rekor transparency log | `cosign verify` against Sigstore public good; certificate-identity-regexp documented in the README |
| Tagged release (`v*`) | YubiHSM-backed key in addition to keyless | Operators verify either signature; YubiHSM signature defeats the GitHub-OIDC-as-single-point-of-failure attack |

```yaml
- uses: sigstore/cosign-installer@<sha>
- run: cosign sign --yes ghcr.io/${{ github.repository }}/bridge@${{ steps.build.outputs.digest }}
# Tagged releases additionally:
- if: startsWith(github.ref, 'refs/tags/v')
  run: cosign sign --key=hsm:!yubikey ghcr.io/${{ github.repository }}/bridge@${{ steps.build.outputs.digest }}
```

### Enforced verification at runtime

Bridge add-on `run.sh` performs `cosign verify` of the *running* image digest on every container start, fail-closed. An override exists for local dev:

```bash
# /etc/s6-overlay/s6-rc.d/cosign-verify/up
if [[ "${BRIDGE_SKIP_SIGNATURE_VERIFY:-0}" == "1" ]]; then
    log_compliance_event signature_verification_skipped \
        reason="BRIDGE_SKIP_SIGNATURE_VERIFY=1"
else
    cosign verify "ghcr.io/.../bridge@${IMAGE_DIGEST}" \
        --certificate-identity-regexp "${COSIGN_IDENTITY_REGEXP}" \
        --certificate-oidc-issuer "https://token.actions.githubusercontent.com" \
        || { log_compliance_event signature_verification_failed; exit 1; }
fi
```

The skip flag writes a permanent compliance event so auditors see the bypass.

### Vulnerability scanning

Trivy gates merges on CRITICAL/HIGH (continuing the ATK-LAT-01 baseline):

```yaml
- uses: aquasecurity/trivy-action@<sha>
  with:
    scan-type: fs
    severity: CRITICAL,HIGH
    exit-code: 1
```

### Renovate cadence

| Artifact | Cadence | Auto-merge if scans clean? |
|---|---|---|
| Base image (`amd64-base`) | Weekly | No — manual review for Alpine major bumps |
| `mavsdk_server` | Quarterly + immediate on security advisories | No — re-test against ArduPilot SITL first |
| Python deps | Weekly | Patch only, never auto |
| ArduPilot firmware | Manual (release tracking + GPG verify) | Never auto |
| GitHub Actions | Weekly | Patch only; pinned by commit SHA, not tag |
| ESPHome firmware | Manual on dock interlock changes | Never auto |

### SLSA provenance

BuildKit `--provenance=true` produces a SLSA Level 2 attestation alongside the image. This proves "GitHub Actions built this image from this commit" without the operational complexity of Level 3 (hermetic, isolated builders) which is theatre at this scale. The provenance JSON is attached as a release asset and its SHA-256 is logged into the compliance chain.

### GitHub repository hygiene

- All Actions referenced by commit SHA, never by `@v*` tag.
- All repository secrets (PAT, AWS keys, cosign tokens) rotated quarterly. Prefer OIDC federation to AWS over long-lived access keys.
- `SECURITY.md` documents the responsible-disclosure process; `security.txt` published at the repo root.
- Branch protection on `main`: required reviews, required status checks, signed commits, no force-push.

**Related:** ATK-LAT-01 (container escape), R-08 (signing key), R-13 (TLS).

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