# drone_hass Adversarial Threat Model

> **Date:** 2026-04-14
> **Status:** Draft
> **Version:** 1.0.0
> **Companion to:** architecture.md v0.4.0, mavlink-mqtt-contract.md v0.1.0, ha-integration-spec.md
> **Classification:** Sensitive — contains attack methodology. Do not publish without redaction review.
> **Author:** Red Team Operator (internal)

---

## 1. Attack Surface Map

### 1.1 Network Interfaces

| Interface | Protocol | Ports | Encryption | Authentication | Exposure |
|-----------|----------|-------|------------|----------------|----------|
| Bridge <-> Mosquitto | MQTT | 1883 (plaintext) / 8883 (TLS) | TLS optional (config) | Username/password | LAN |
| HA <-> Mosquitto | MQTT | 1883 / 8883 | TLS optional | Username/password | LAN |
| Bridge <-> Flight Controller | MAVLink over UDP | 14540 (MAVSDK), 14550 (GCS) | **None** | **None** | WiFi RF + LAN |
| Companion (RPi) <-> Bridge | MAVLink over WiFi/UDP | 14540 | **None** | **None** | WiFi RF |
| Bridge <-> SiK Radio | MAVLink over serial/915 MHz | N/A | **None** | **None** | 915 MHz RF |
| Camera <-> Media Server | RTSP | 8554 (typical) | **None by default** | Optional | WiFi + LAN |
| go2rtc <-> HA | HTTP/WebRTC | 1984 / ephemeral | None by default | HA auth | LAN |
| ESPHome Dock <-> HA | ESPHome native API | 6053 | API encryption key | Shared key | LAN |
| HA Web UI | HTTPS | 8123 | TLS | HA auth (username/password, tokens) | LAN (WAN if exposed) |
| Bridge Ingress UI | HTTP | 8099 (via Supervisor) | Supervisor proxy | HA session | LAN |
| ADS-B Receiver <-> FC | Serial (GDL90) | N/A | None | None | Physical wiring |
| Remote ID module <-> FC | Serial | N/A | None | None | Physical wiring |
| MQTT Missions (retained) | MQTT | via broker | As broker | As broker | Any MQTT client |

### 1.2 Trust Boundaries

```
┌─────────────────────────────────────────────────────────────────────┐
│ TRUST BOUNDARY 1: Home Network (LAN/WiFi)                          │
│                                                                     │
│  ┌──────────────────────────┐   ┌──────────────────────────┐       │
│  │ TRUST BOUNDARY 2:        │   │ TRUST BOUNDARY 3:        │       │
│  │ HA Server / Docker Host  │   │ Aircraft (WiFi + RF)     │       │
│  │                          │   │                          │       │
│  │  Mosquitto Broker        │   │  Pixhawk 6C (FC)        │       │
│  │  Bridge Add-on Container │   │  Companion RPi          │       │
│  │  HA Core                 │   │  ADS-B Receiver         │       │
│  │  go2rtc / mediamtx       │   │  Camera/Gimbal          │       │
│  │  Compliance DB (SQLite)  │   │  SiK 915 MHz Radio      │       │
│  │  Ed25519 Private Key     │   │  Remote ID Module       │       │
│  └──────────────────────────┘   └──────────────────────────┘       │
│                                                                     │
│  ┌──────────────────────────┐   ┌──────────────────────────┐       │
│  │ TRUST BOUNDARY 4:        │   │ TRUST BOUNDARY 5:        │       │
│  │ Physical Dock             │   │ Operator Devices         │       │
│  │                          │   │                          │       │
│  │  ESP32 (ESPHome)         │   │  Phone (notifications)  │       │
│  │  Actuator/Sensors        │   │  Workstation (HA UI)    │       │
│  │  Weather Station         │   │  RC Transmitter         │       │
│  └──────────────────────────┘   └──────────────────────────┘       │
│                                                                     │
│  ┌──────────────────────────┐                                      │
│  │ TRUST BOUNDARY 6:        │                                      │
│  │ External / Off-network   │                                      │
│  │                          │                                      │
│  │  Litestream S3/GCS/NAS  │                                      │
│  │  Mobile push (Apple/Goo)│                                      │
│  │  ADS-B RF environment   │                                      │
│  └──────────────────────────┘                                      │
└─────────────────────────────────────────────────────────────────────┘
```

### 1.3 Data Flows Crossing Trust Boundaries

| Flow | Crosses | Sensitive Data |
|------|---------|----------------|
| MAVLink telemetry (WiFi) | 2 <-> 3 | GPS position, altitude, battery, armed state |
| MAVLink commands (WiFi) | 2 <-> 3 | Arm, takeoff, land, mission upload, mode changes |
| MQTT telemetry | Internal to 2 | All drone state |
| MQTT commands | Internal to 2 | Flight commands with authorization tokens |
| RTSP video | 3 -> 2 | Live camera feed (property surveillance) |
| Litestream replication | 2 -> 6 | Full compliance database (flight history, positions, personnel) |
| Push notifications | 2 -> 6 -> 5 | Alert context, LAUNCH action button |
| ESPHome API | 4 <-> 2 | Dock state, actuator commands |
| ADS-B broadcast (Remote ID) | 3 -> 6 | Aircraft position, operator location (broadcast to anyone) |
| Retained MQTT missions | 2 (persistent) | Waypoint coordinates (property layout) |

---

## 2. Threat Catalog

### 2.1 MAVLink / C2 Link Attacks

#### ATK-MAV-01: MAVLink Command Injection via WiFi

- **Attack vector:** Attacker within WiFi range (or on the same LAN) sends crafted MAVLink UDP packets to port 14540 or 14550. MAVLink v2 has no authentication or encryption. Any device that can send UDP to the FC's IP can issue commands: `MAV_CMD_COMPONENT_ARM_DISARM`, `MAV_CMD_NAV_TAKEOFF`, `MAV_CMD_DO_SET_MODE`, or upload a malicious mission.
- **Prerequisites:** LAN access or WiFi association. Knowledge of the FC's UDP port (default 14540, documented in add-on config). MAVLink v2 message format (public spec).
- **Impact:** Unauthorized flight (1), dangerous flight (2, 4) -- attacker uploads mission with waypoints over neighbor's house or into obstacles. Physical damage (4). Compliance violation.
- **Severity:** **Critical**
- **Existing mitigations:** Bridge validates missions against operational area before upload. ArduPilot firmware geofence provides a second layer. Architecture doc Section 13 mentions VLAN isolation.
- **Gaps:** MAVLink itself has zero authentication. The bridge validation only applies to commands routed through the bridge. A direct MAVLink injection to the FC bypasses the bridge entirely. The firmware geofence only constrains geographic area, not who issues commands. No mention of MAVLink signing (`SETUP_SIGNING` / message signing key) in the architecture.
- **Recommended mitigations:**
  1. Enable MAVLink 2 message signing on both the bridge and the flight controller. ArduPilot supports this via `MAVSDK` or pymavlink `setup_signing()`. This adds a SHA-256 HMAC to every message, rejecting unsigned packets.
  2. Firewall the HA server to drop inbound UDP 14540/14550 from all sources except the bridge process. The bridge should bind the MAVSDK connection to the specific companion computer IP, not `0.0.0.0`.
  3. Place the drone's WiFi on a dedicated VLAN with no other clients. The bridge container should be the only host on that VLAN.

#### ATK-MAV-02: MAVLink Replay Attack

- **Attack vector:** Attacker captures MAVLink UDP packets (arm, takeoff, mission upload) using Wireshark or tcpdump on the WiFi network. Later replays these packets to trigger the same action.
- **Prerequisites:** Passive WiFi capture capability (or LAN tap). Ability to replay packets.
- **Impact:** Unauthorized flight (1), dangerous flight (2).
- **Severity:** **High**
- **Existing mitigations:** MQTT commands include timestamps and are rejected if stale (Section 13). But MAVLink commands from bridge to FC have no replay protection unless signing is enabled.
- **Gaps:** MAVLink signing includes a timestamp/link-id that prevents replay, but signing is not mentioned in the architecture.
- **Recommended mitigations:** Enable MAVLink 2 signing (same as ATK-MAV-01). Signing includes a 48-bit timestamp that prevents replay.

#### ATK-MAV-03: WiFi Deauthentication / C2 Link Disruption

- **Attack vector:** Attacker sends 802.11 deauth frames to disconnect the companion computer from the WiFi AP, severing the primary C2 link while the drone is airborne.
- **Prerequisites:** Proximity to WiFi network. Deauth hardware ($10 ESP32 with deauther firmware, or a standard WiFi adapter in monitor mode).
- **Impact:** Denial of service (6). ArduPilot GCS-loss failsafe triggers RTL, which is safe -- but the attacker has denied the operator real-time control and video feed. If the attacker combines this with GPS spoofing, the RTL destination could be wrong.
- **Severity:** **Medium** (failsafe handles it safely in isolation)
- **Existing mitigations:** WPA3 with PMF (Protected Management Frames) mentioned in Section 13. Backup SiK 915 MHz radio for redundant C2 link. ArduPilot RTL failsafe.
- **Gaps:** WPA3 with PMF is mentioned as a mitigation but is not enforced in any configuration. If WPA2 is used, deauth attacks succeed. The SiK backup link also has no authentication.
- **Recommended mitigations:**
  1. Mandate WPA3-SAE with PMF for the drone VLAN WiFi network. Document this as a deployment requirement.
  2. Configure ArduPilot GCS failsafe to `RTL` (not `continue`) -- verify `FS_GCS_ENABLE=1` (RTL) or `FS_GCS_ENABLE=5` (SmartRTL).
  3. Test the SiK backup link failover regularly. The bridge should auto-failover to SiK serial if WiFi MAVLink heartbeats are lost.

#### ATK-MAV-04: Rogue GCS / Parallel MAVLink Connection

- **Attack vector:** An attacker (or even a benign second instance of QGroundControl on the operator's network) connects to the FC via MAVLink UDP. ArduPilot accepts multiple GCS connections by default. The rogue GCS can issue commands, change parameters, upload missions, or modify failsafe settings.
- **Prerequisites:** LAN/WiFi access. QGroundControl or pymavlink.
- **Impact:** Unauthorized flight (1), dangerous flight (2), parameter tampering (e.g., disabling geofence via `FENCE_ENABLE=0`, changing `RTL_ALT` to a dangerous value, disabling ADS-B avoidance via `AVD_ENABLE=0`).
- **Severity:** **Critical**
- **Existing mitigations:** None explicitly stated for multiple GCS prevention.
- **Gaps:** ArduPilot does not restrict which GCS can connect. Any MAVLink-speaking client on the network can modify parameters.
- **Recommended mitigations:**
  1. MAVLink signing (same key shared between bridge and FC only).
  2. Network isolation: the FC's companion computer should only be reachable from the bridge container's IP.
  3. On the ArduPilot side, set `SYSID_MYGCS` to the bridge's MAVLink system ID and configure the FC to only accept commands from that system ID (note: ArduPilot does not fully enforce this, but it limits some behaviors).

#### ATK-MAV-05: SiK 915 MHz Radio Eavesdropping and Injection

- **Attack vector:** SiK radios transmit MAVLink in the clear on 915 MHz ISM band. An attacker with an SDR (RTL-SDR, HackRF) can receive and decode all telemetry. With a transmit-capable SDR, they can inject MAVLink commands.
- **Prerequisites:** SDR hardware ($25-$300), proximity (SiK range is ~1 km), knowledge of SiK frequency hopping parameters (often default).
- **Impact:** Data exfiltration (7) of telemetry. Command injection if transmitting. Dangerous flight (2).
- **Severity:** **Medium** (requires specialized equipment and proximity)
- **Existing mitigations:** SiK is the backup link, not primary. Architecture mentions it is for redundancy.
- **Gaps:** No encryption or authentication on SiK. The architecture does not mention configuring SiK encryption (SiK firmware supports AES-128 encryption with a shared key).
- **Recommended mitigations:** Enable AES-128 encryption on both SiK radios (ground and air). Configure via AT commands: `ATS15=1` (encryption enable), set shared encryption key.

### 2.2 MQTT Attacks

#### ATK-MQTT-01: Unauthenticated MQTT Command Injection

- **Attack vector:** If Mosquitto is configured without authentication (default Mosquitto config), any client on the network can publish to `drone_hass/{drone_id}/command/arm`, `command/takeoff`, `command/execute_mission`, etc. The bridge processes these commands.
- **Prerequisites:** Network access to MQTT broker (port 1883). Knowledge of topic structure (documented in public repo).
- **Impact:** Unauthorized flight (1), dangerous flight (2). Attacker can trigger arm + takeoff + mission execution.
- **Severity:** **Critical**
- **Existing mitigations:** Section 13 states "MQTT authentication mandatory" and "ACLs restrict publish to command topics to HA's client ID only."
- **Gaps:** These are stated requirements, not enforced configurations. The default Mosquitto add-on in HAOS allows unauthenticated access from localhost. If the broker binds to 0.0.0.0 (default), any LAN device can connect. There is no provided Mosquitto ACL configuration in the documentation. The architecture says "ACLs restrict publish to command topics to HA's client ID only" but does not provide the ACL file or verify it.
- **Recommended mitigations:**
  1. Provide a reference Mosquitto ACL configuration in the project documentation:
     ```
     user bridge_user
     topic readwrite drone_hass/#

     user ha_user
     topic readwrite drone_hass/+/command/#
     topic read drone_hass/#

     # Deny all others
     ```
  2. Mandate TLS client certificates for bridge and HA MQTT connections (mutual TLS), not just username/password.
  3. Ship a deployment checklist that verifies MQTT auth is enabled.
  4. The bridge should validate that command messages include a valid, recent timestamp (already partially specified -- "rejected if stale" in Section 13) but define the exact staleness window (30 seconds per the JSON schema).

#### ATK-MQTT-02: Mission Definition Poisoning via Retained Messages

- **Attack vector:** Mission definitions are stored as retained MQTT messages on `drone_hass/{drone_id}/missions/{mission_id}`. An attacker who can publish to this topic can replace a legitimate mission (e.g., `full_perimeter`) with a mission containing waypoints outside the operational area, over neighbors' property, or at dangerous altitudes.
- **Prerequisites:** MQTT publish access (see ATK-MQTT-01).
- **Impact:** Privacy violation (3) -- camera over neighbor's property. Dangerous flight (2). Physical damage (4) if waypoints are in obstacles.
- **Severity:** **High**
- **Existing mitigations:** Bridge validates all waypoints against operational area before upload. Waypoints outside the polygon or above altitude ceiling are rejected.
- **Gaps:** The operational area validation is the key defense, but:
  1. If the attacker also modifies the operational area (published to `drone_hass/{drone_id}/config/operational_area` as a retained message), both the malicious mission and the expanded area would be accepted.
  2. No mission allowlist -- any `mission_id` string is accepted, not just predefined ones.
  3. No integrity check on retained missions (no HMAC or signature on the mission JSON).
- **Recommended mitigations:**
  1. The operational area should be immutable at the bridge level -- loaded from a config file on disk at startup, not from MQTT retained messages. MQTT should be a notification channel, not the source of truth for safety-critical configuration.
  2. Implement a mission allowlist in bridge configuration (e.g., only `full_perimeter`, `front_sweep`, `rear_sweep`, etc.).
  3. MQTT ACLs should restrict `missions/#` and `config/#` topics to the HA user only.
  4. Consider signing mission definitions with a shared secret.

#### ATK-MQTT-03: Compliance Event Injection

- **Attack vector:** The `drone_hass/{drone_id}/compliance/ha_event` topic accepts fire-and-forget compliance events from HA (QoS 1, no response). An attacker who can publish to this topic can inject fabricated compliance events (e.g., fake "rpic_authorized" events, fake safety gate results, fake personnel logs).
- **Prerequisites:** MQTT publish access.
- **Impact:** Compliance record tampering (5). Fabricated records could be used to support a fraudulent Part 108 Permit application.
- **Severity:** **High**
- **Existing mitigations:** Compliance records are signed with Ed25519 and hash-chained. But events arriving via MQTT from HA are ingested by the bridge and then signed -- the signature proves the bridge wrote them, not that the source was legitimate.
- **Gaps:** The bridge signs whatever arrives on the compliance MQTT topic. A fabricated `rpic_authorized` event published by an attacker would be signed just like a legitimate one. The Ed25519 signature proves chain integrity, not event authenticity.
- **Recommended mitigations:**
  1. The bridge should only accept compliance events from its own internal state machine, not from MQTT. External compliance events from HA should be treated as informational annotations, not as authoritative records. Authorization events (`rpic_authorized`, `autonomous_launch_authorized`) must be generated internally by the ComplianceGate, never accepted from MQTT.
  2. Add a `source` field to compliance records distinguishing `bridge_internal` from `ha_external`.
  3. MQTT ACL to restrict `compliance/#` publish to the HA user only.

#### ATK-MQTT-04: MQTT Broker Denial of Service

- **Attack vector:** Flood the MQTT broker with messages, causing it to become unresponsive. This blocks all command and telemetry flow.
- **Prerequisites:** Network access to MQTT broker.
- **Impact:** Denial of service (6). The drone cannot be commanded from HA. If airborne, the bridge loses MQTT but MAVLink continues -- the drone completes its mission or RTLs.
- **Severity:** **Medium**
- **Existing mitigations:** "Mosquitto rate limiting. Coordinator debounces. Network isolation." (Section 13)
- **Gaps:** Mosquitto rate limiting is not configured by default. No specific rate limit values are documented.
- **Recommended mitigations:** Configure Mosquitto `max_inflight_messages`, `max_queued_messages`, and connection rate limits. Bind Mosquitto to the VLAN interface only.

#### ATK-MQTT-05: State Topic Spoofing

- **Attack vector:** Attacker publishes fake state messages to retained topics: `state/connection` = `"online"`, `state/daa` = `{"healthy": true, ...}`, `state/compliance` = `{"mode": "part_108", "fc_on_duty": true, ...}`. This makes HA believe the system is healthy when it is not, potentially allowing a flight that should be blocked by safety gates.
- **Prerequisites:** MQTT publish access.
- **Impact:** Dangerous flight (2) -- HA automation safety gates pass because they check entity states derived from MQTT. A flight launches when DAA is actually unhealthy or FC is not on duty.
- **Severity:** **High**
- **Existing mitigations:** Safety checks enforced in "TWO places: HA automation (first line) AND bridge + flight controller (second line, not bypassable)." The bridge's ComplianceGate independently checks conditions before executing commands.
- **Gaps:** The dual-check architecture is good, but the HA-side checks are entirely based on MQTT state. If MQTT state is spoofed, the HA automation passes. The bridge-side ComplianceGate is the real defense, but only if it independently validates (e.g., checks DAA health from its own ADS-B processing, not from MQTT).
- **Recommended mitigations:**
  1. Ensure the bridge ComplianceGate reads DAA health, FC status, and weather from its own internal state, never from MQTT topics (which could be spoofed).
  2. MQTT ACLs: only the bridge client should be able to publish to `state/#` topics.
  3. Document that HA-side safety gates are a convenience layer, not a security boundary. The bridge is the security boundary.

### 2.3 Video Pipeline Attacks

#### ATK-VID-01: RTSP Stream Interception

- **Attack vector:** RTSP streams are unencrypted by default. An attacker on the LAN can connect to the camera's RTSP URL (e.g., `rtsp://10.0.0.50:8554/drone`) or the media server's RTSP URL and view the live camera feed.
- **Prerequisites:** LAN access. Knowledge of RTSP URL (discoverable via network scanning or from MQTT `state/stream` topic).
- **Impact:** Privacy violation (3) -- attacker sees live property surveillance video. Data exfiltration (7).
- **Severity:** **Medium**
- **Existing mitigations:** "Media server authentication. Bind to localhost/VLAN." (Section 13)
- **Gaps:** No specific RTSP authentication configuration is documented. go2rtc and mediamtx support basic auth on RTSP but it is not enabled by default. The camera itself (Siyi A8 Mini) serves RTSP without authentication.
- **Recommended mitigations:**
  1. Configure go2rtc/mediamtx with RTSP authentication.
  2. Firewall RTSP ports to allow only the media server to connect to the camera.
  3. Use RTSPS (RTSP over TLS) if the media server supports it.
  4. Bind the camera's RTSP server to the drone VLAN; bind the media server's output to localhost or HA's network namespace.

#### ATK-VID-02: Video Recording Access

- **Attack vector:** Server-side video recordings are stored in the HA media directory (the bridge maps `media:rw`). Anyone with access to the HA server filesystem can access recorded surveillance video.
- **Prerequisites:** Filesystem access to the HA server (SSH, compromised add-on, backup extraction).
- **Impact:** Privacy violation (3), data exfiltration (7).
- **Severity:** **Medium**
- **Existing mitigations:** None specific to video storage encryption.
- **Gaps:** No mention of encrypting stored video. No retention policy.
- **Recommended mitigations:**
  1. Implement a video retention policy (auto-delete after N days).
  2. Consider encrypting stored video at rest.
  3. Restrict media directory permissions.
  4. Ensure HA backups that include the media directory are encrypted.

### 2.4 Dock / ESPHome Attacks

#### ATK-DOCK-01: ESPHome API Exploitation

- **Attack vector:** If the ESPHome API encryption key is weak or compromised, an attacker can connect to the ESP32 and issue dock commands: open lid, enable heater, disable smoke sensor relay, manipulate charger power.
- **Prerequisites:** LAN access. Knowledge of ESPHome API port (6053). Compromised or weak encryption key.
- **Impact:** Physical damage (4) -- opening lid during bad weather, overriding thermal protections, disabling smoke detection (fire risk). Denial of service (6) -- opening lid and leaving it open to weather damage the drone.
- **Severity:** **Medium**
- **Existing mitigations:** "API encryption key + OTA password mandatory." (Section 13). ESP32 safety interlocks enforced locally.
- **Gaps:** The smoke sensor -> charger cut relay is described as "hardware, not software" -- this is good. But the ESP32 firmware-level interlocks (cannot close lid unless motors disarmed) depend on receiving accurate state from HA or MQTT. If the ESP32 checks HA state over the API, a spoofed state could bypass interlocks.
- **Recommended mitigations:**
  1. ESP32 interlocks should rely on local sensor inputs only (limit switches, ToF sensor, smoke detector), never on HA state for safety-critical decisions.
  2. Use a strong, randomly generated API encryption key (documented as mandatory, but enforce minimum entropy).
  3. Disable OTA updates in production (or require physical button press for OTA mode).

#### ATK-DOCK-02: Physical Tampering with Dock

- **Attack vector:** Physical access to the dock on the shed roof. Attacker could: tamper with sensors (tape over smoke detector, block ToF sensor), disconnect the UPS, cut power, damage the actuator, or physically steal the drone.
- **Prerequisites:** Physical access to the shed roof.
- **Impact:** Physical damage (4), denial of service (6), theft.
- **Severity:** **Medium** (residential property, not high-security)
- **Existing mitigations:** "Physical lock. Tamper sensor. Missions stored on bridge, not aircraft." (Section 13)
- **Gaps:** Tamper sensor is mentioned but not specified. No camera covering the dock itself.
- **Recommended mitigations:**
  1. Install a tamper switch (reed switch or vibration sensor) on the dock enclosure that triggers an HA alert.
  2. If feasible, point an existing security camera at the dock location.
  3. Use security screws (Torx security or similar) on the dock enclosure.

### 2.5 Compliance Recorder Attacks

#### ATK-COMP-01: Ed25519 Signing Key Extraction

- **Attack vector:** The Ed25519 private key is "generated at first install, stored separately from the database" inside the add-on container. If an attacker extracts this key, they can forge arbitrary compliance records with valid signatures and rebuild the entire hash chain from scratch.
- **Prerequisites:** Filesystem access to the add-on container's data directory (`/data/compliance/` or wherever the key is stored). This could be via: compromised HA add-on, SSH access to the HA server, extraction from an HA backup, or physical SD card access.
- **Impact:** Compliance record tampering (5) -- complete forgery of the entire compliance history. A forged history could support a fraudulent Part 108 Permit application or conceal incidents.
- **Severity:** **Critical**
- **Existing mitigations:** "Stored separately from the database." Ed25519 signatures bind records to the key.
- **Gaps:**
  1. The key storage location and protection mechanism are not specified. "Stored separately" is vague. If the key is a plain file in the add-on data directory, it is included in HA backups (the architecture explicitly states compliance DB is "included in HA full backups automatically"). The key would be in the backup too.
  2. No mention of key rotation or key ceremonies.
  3. No mention of HSM, TPM, or OS-level key protection. On HAOS (a minimal Linux), there is no keyring or TPM support.
  4. The architecture acknowledges that a hash chain alone "does not prove who wrote them or that the entire chain was not rebuilt from scratch" and that signatures address this. But if the signing key is extractable, signatures do not address this either.
- **Recommended mitigations:**
  1. Document the key storage model explicitly. If running on a Raspberry Pi or NUC, there may be no hardware key protection available. Acknowledge this limitation.
  2. Store the key with filesystem permissions `600` owned by the bridge process user, not readable by other add-ons or HA Core.
  3. Exclude the signing key from HA backups. The key should be backed up via a separate, manual process (e.g., printed QR code in a safe).
  4. Implement key registration: on first install, the public key fingerprint is logged as the first compliance record. The operator should register this fingerprint with a trusted third party (e.g., email to their attorney, timestamp on a blockchain, notarized document) to establish the key's creation date.
  5. Consider a key attestation service: the bridge periodically signs a challenge from an external timestamp authority (e.g., RFC 3161 TSA), proving the key was in use at a specific time. This makes it harder to forge a history retroactively.
  6. If the device has a TPM 2.0 (some NUCs do), use it to protect the signing key.

#### ATK-COMP-02: Compliance Database Deletion

- **Attack vector:** An attacker (or the operator themselves) deletes `compliance.db` from the add-on data directory to destroy the compliance history.
- **Prerequisites:** Filesystem access to the add-on container's data directory.
- **Impact:** Compliance record tampering (5) -- elimination of evidence after an incident.
- **Severity:** **High**
- **Existing mitigations:** Litestream replication to an off-device target (S3, GCS, NAS).
- **Gaps:**
  1. Litestream replication is described but is a configuration option, not a mandatory deployment requirement. If the operator never configures it, the database is a single file on one device.
  2. Even with Litestream, if the operator controls the S3 bucket, they can delete the replica too.
  3. No mention of immutable storage (S3 Object Lock, GCS retention policies).
- **Recommended mitigations:**
  1. Make Litestream replication a mandatory configuration step, not optional. The bridge should refuse to start (or at minimum log a persistent warning) if replication is not configured.
  2. Document the use of S3 Object Lock (Governance or Compliance mode) or GCS Bucket Lock to make replicas immutable.
  3. For maximum integrity, replicate to a target the operator does not control (e.g., a third-party compliance escrow service, or a shared S3 bucket managed by an insurance company).
  4. The bridge should detect if the local database is deleted or truncated (compare local chain length with Litestream replica) and alert.

#### ATK-COMP-03: Hash Chain Gap via SQLite WAL Manipulation

- **Attack vector:** SQLite WAL (Write-Ahead Log) mode means writes go to a WAL file before being merged into the main database. An attacker with filesystem access could:
  1. Delete the WAL file, losing recent uncommitted records.
  2. Modify the WAL file to alter recent records before checkpoint.
  3. Replace the database with an older version (before incriminating records).
- **Prerequisites:** Filesystem access while the bridge is running or stopped.
- **Impact:** Compliance record tampering (5).
- **Severity:** **Medium** (Litestream replicates WAL frames, so a remote replica would have the records)
- **Existing mitigations:** Litestream streams WAL frames continuously (~1 second RPO). Hash chain would show a gap if records are deleted.
- **Gaps:** If Litestream is not configured, WAL manipulation is a viable attack. The `verify_chain` command would detect a gap, but only if someone runs it.
- **Recommended mitigations:**
  1. Run `verify_chain` automatically on bridge startup and log the result.
  2. Daily automated chain verification (already described as "daily integrity heartbeat").
  3. Mandatory Litestream (see ATK-COMP-02).

#### ATK-COMP-04: Compliance Record Fabrication (Operator as Threat)

- **Attack vector:** The operator wants to obtain a Part 108 Permit and needs a history of successful flights, DAA events handled correctly, and personnel compliance. They fabricate this history by:
  1. Running the system in SITL mode with simulated flights and writing compliance records.
  2. Modifying the bridge code to write fabricated records.
  3. Extracting the signing key and writing records directly to the database.
- **Prerequisites:** Operator has full control of the system (they own it).
- **Impact:** Fraudulent Part 108 Permit application (5).
- **Severity:** **High** (regulatory fraud)
- **Existing mitigations:** Ed25519 signatures + hash chain. But the operator controls the signing key and the bridge code.
- **Gaps:** This is fundamentally a trust problem. The compliance recorder provides tamper-evidence (detect after the fact), not tamper-proof (prevent). An operator with full system access can forge any history.
- **Recommended mitigations:**
  1. The compliance recorder should include a `source` field in every record: `live` vs `sitl` vs `replay`. SITL-generated records should be clearly marked and excluded from Permit application data.
  2. Records should include hardware identifiers (FC serial number, GPS module ID) that can be cross-referenced with FAA registration. SITL records would lack real hardware IDs.
  3. The daily integrity heartbeat should include an NTP-verified timestamp and be sent to an external timestamping authority.
  4. Accept that the compliance recorder provides tamper-evidence, not tamper-proof. Document this limitation. For Part 108, the FAA may require additional oversight (audits, spot checks, third-party monitoring).
  5. Remote ID broadcasts during flights create an independent FAA-visible record that can be correlated with compliance records.

### 2.6 Home Assistant Attacks

#### ATK-HA-01: HA Automation Manipulation

- **Attack vector:** An attacker with access to the HA UI (compromised HA account, stolen long-lived token, LAN access to port 8123) modifies the patrol automation to remove safety gates, change mission IDs, or trigger flights without alarm conditions.
- **Prerequisites:** HA UI access (any admin user) or API access via long-lived token.
- **Impact:** Unauthorized flight (1), dangerous flight (2), privacy violation (3).
- **Severity:** **High**
- **Existing mitigations:** "Safety checks enforced in TWO places: HA automation AND bridge + flight controller." The bridge ComplianceGate independently validates.
- **Gaps:** The bridge ComplianceGate validates flight commands, but some safety gates exist only in HA (e.g., weather checks from dock sensors are HA entities -- the bridge may not independently verify these). If the attacker removes the weather condition from the automation, and the bridge does not independently check weather, a flight could launch in unsafe conditions.
- **Recommended mitigations:**
  1. The bridge should independently check weather conditions from its own data sources (subscribe to dock sensor MQTT topics directly, or query HA entities via the HA API). Do not rely solely on HA automation conditions for safety-critical checks.
  2. Require MFA/2FA for all HA accounts.
  3. Use HA's `auth_providers` to restrict admin access.
  4. Audit HA long-lived access tokens regularly -- revoke unused ones.

#### ATK-HA-02: Push Notification Spoofing (Part 107 RPIC Authorization)

- **Attack vector:** In Part 107 mode, the RPIC authorization flow uses a push notification with an actionable button (`LAUNCH_DRONE`). The HA automation waits for a `mobile_app_notification_action` event with `action: "LAUNCH_DRONE"`. An attacker who can fire HA events (via the API, compromised integration, or WebSocket) can inject this event, bypassing the RPIC's conscious decision.
- **Prerequisites:** HA API access (long-lived token, compromised user, LAN access to WebSocket API). The authorization token architecture is mentioned as a mitigation in Section 13 but is not fully described.
- **Impact:** Unauthorized flight (1).
- **Severity:** **High**
- **Existing mitigations:** "Authorization token architecture prevents fake events from triggering flights." "Bridge requires a time-limited, single-use authorization token before executing any flight command."
- **Gaps:** The architecture references an authorization token but the exact mechanism is not specified. If the token is generated by the HA automation and sent to the bridge via MQTT, an attacker with MQTT access can send it directly. The token must be generated by a flow that the attacker cannot replicate.
- **Recommended mitigations:**
  1. Define the authorization token flow explicitly: The bridge generates a challenge, sends it in the notification payload, and only accepts the signed response. This ensures the token originates from the push notification interaction, not from a forged event.
  2. Alternatively, the bridge generates a one-time token, sends it to both the notification and its internal state. It only accepts the exact token back within a time window. If the attacker does not have access to the notification content, they cannot forge it.
  3. Include a cryptographic nonce in the authorization flow.

#### ATK-HA-03: Service Call Abuse

- **Attack vector:** Any HA user (or automation) can call `drone_hass.execute_mission`, `drone_hass.takeoff`, etc. There is no per-service authorization within HA -- any admin user can call any service.
- **Prerequisites:** HA admin access.
- **Impact:** Unauthorized flight (1).
- **Severity:** **Medium**
- **Existing mitigations:** Bridge ComplianceGate requires authorization token before executing flight commands. Services alone are not sufficient to fly.
- **Gaps:** Camera commands (`take_photo`, `start_recording`, `set_gimbal`) are explicitly noted as "no compliance gate" in the HA integration spec. An attacker with HA access could start recording video or aim the gimbal at a neighbor's property without triggering a flight.
- **Recommended mitigations:**
  1. Camera and gimbal commands should be restricted to when the drone is airborne (the bridge should enforce this).
  2. Consider a separate permission model for drone commands (e.g., only specific HA users can call flight services).

### 2.7 Aircraft / Firmware Attacks

#### ATK-FW-01: ArduPilot Parameter Tampering

- **Attack vector:** An attacker with MAVLink access (see ATK-MAV-01/04) modifies critical ArduPilot parameters:
  - `FENCE_ENABLE=0` (disable geofence)
  - `AVD_ENABLE=0` (disable ADS-B avoidance)
  - `FS_GCS_ENABLE=0` (disable GCS-loss failsafe)
  - `RTL_ALT=30000` (RTL at 300m instead of 35m -- dangerous)
  - `BATT_FS_LOW_ACT=0` (disable low-battery failsafe)
- **Prerequisites:** MAVLink access (no authentication by default).
- **Impact:** Dangerous flight (2), physical damage (4). Removing safety layers makes the drone fly without geofence, without DAA, and without failsafe.
- **Severity:** **Critical**
- **Existing mitigations:** Bridge reads parameters at startup (`FENCE_ENABLE`, `AVD_ENABLE`, etc.) to understand FC behavior.
- **Gaps:** The bridge reads parameters but does not monitor for unauthorized changes. An attacker could change parameters after startup and the bridge would not notice.
- **Recommended mitigations:**
  1. The bridge should periodically re-read critical safety parameters and alert if they differ from expected values.
  2. ArduPilot supports parameter locking in some versions -- investigate and enable if available.
  3. MAVLink signing prevents unauthorized parameter writes.

#### ATK-FW-02: Firmware Replacement

- **Attack vector:** An attacker with physical access to the Pixhawk (or MAVLink access to the companion computer) flashes a modified ArduPilot firmware that removes geofence enforcement, disables failsafes, or adds backdoor commands.
- **Prerequisites:** Physical access to the aircraft or MAVLink/SSH access to the companion computer.
- **Impact:** All safety layers at the firmware level are removed. Dangerous flight (2), physical damage (4).
- **Severity:** **High**
- **Existing mitigations:** Dock physical lock. Tamper sensor (mentioned).
- **Gaps:** No firmware integrity verification. The bridge does not verify that the FC is running expected firmware.
- **Recommended mitigations:**
  1. The bridge should read the ArduPilot firmware version and Git hash at startup (available via MAVLink `AUTOPILOT_VERSION` message) and log it as a compliance record. Alert if it changes unexpectedly.
  2. Lock the companion computer's SSH with key-only auth and a strong passphrase.

#### ATK-FW-03: GPS Spoofing

- **Attack vector:** A GPS spoofer transmits fake GPS signals that override the real GPS position. The drone believes it is at a different location and flies accordingly. RTL takes the drone to the wrong location. Geofence boundaries are evaluated against the wrong position.
- **Prerequisites:** GPS spoofing hardware (illegal under 18 U.S.C. 32, but available for ~$300). Proximity.
- **Impact:** Dangerous flight (2), physical damage (4). Drone could fly outside the operational area while firmware believes it is inside.
- **Severity:** **Medium** (accepted residual risk per Section 13, but worth documenting the attack chain)
- **Existing mitigations:** "Multi-constellation GNSS provides partial protection." (Section 13)
- **Gaps:** ArduPilot does not have built-in GPS spoofing detection. Multi-constellation (GPS + GLONASS + Galileo) makes spoofing harder but not impossible.
- **Recommended mitigations:**
  1. Enable all available GNSS constellations on the GPS module.
  2. The bridge could implement a basic GPS sanity check: compare reported position against expected position (should be within the operational area during flight, near the dock when landed). A sudden position jump of > 50m should trigger an alert and potentially an RTL.
  3. If using dual GPS (ArduPilot supports this), compare the two receivers for consistency.

### 2.8 Privacy-Specific Attacks

#### ATK-PRIV-01: Neighbor Surveillance via Mission Modification

- **Attack vector:** Operator (intentionally) or attacker (via mission poisoning, ATK-MQTT-02) modifies mission waypoints to fly over neighbor's property with camera recording.
- **Prerequisites:** MQTT access (attacker) or system access (operator).
- **Impact:** Privacy violation (3). Violation of WA state privacy law.
- **Severity:** **High**
- **Existing mitigations:** Operational area validation (waypoints must be within property polygon). Firmware geofence.
- **Gaps:**
  1. The operational area polygon defines lateral boundaries but camera gimbal can be pointed sideways. A drone flying within the property boundary at 110 ft with gimbal at -30 degrees captures a significant area outside the property.
  2. The operational area is configured by the operator. There is no independent verification that it matches the actual property boundary.
  3. No gimbal angle restrictions relative to property boundaries.
- **Recommended mitigations:**
  1. Document that camera field-of-view extends beyond the flight path. Mission corridors should include a camera FOV buffer (already partially addressed by `lateral_buffer_m: 5` in the operational area, but 5m is insufficient for camera FOV at 30m altitude).
  2. Consider gimbal pitch restrictions: limit gimbal to -60 or -90 degrees (straight down) during flight near property edges to minimize off-property capture.
  3. Add a privacy assessment to the deployment checklist.
  4. Implement automated video blurring/masking for areas outside the property boundary (complex, but worth noting as a future enhancement).

#### ATK-PRIV-02: Remote ID Location Broadcast

- **Attack vector:** Remote ID (OpenDroneID) continuously broadcasts the drone's position and the operator's location during flight. This is mandatory and public. Anyone with a Remote ID receiver (or the FAA's LAANC app) can see the drone's position and link it to the registered operator.
- **Prerequisites:** A Remote ID receiver (available as phone apps using Bluetooth scanning, or dedicated hardware).
- **Impact:** Data exfiltration (7) -- flight patterns and schedules become public knowledge. An adversary doing pre-attack reconnaissance on the property can learn when the drone is airborne, its patrol routes, and coverage gaps.
- **Severity:** **Low** (this is a regulatory requirement, not a vulnerability -- but the operator should understand the privacy implications)
- **Existing mitigations:** This is required by law (Standard Remote ID). Cannot be disabled.
- **Gaps:** No mitigation possible without violating the law. The operator should be aware that their patrol patterns are observable.
- **Recommended mitigations:**
  1. Document this as an accepted risk.
  2. Randomize mission timing slightly to avoid perfectly predictable patrol schedules.
  3. Ensure the operator location reported by Remote ID is the dock location (fixed), not the operator's actual real-time location inside the house.

### 2.9 Lateral Movement Attacks

#### ATK-LAT-01: Bridge Container Escape to Host

- **Attack vector:** The bridge add-on runs as a Docker container on the HA server. If the container has excessive privileges, a vulnerability in the bridge code (e.g., in MAVSDK-Python, aiomqtt, or a dependency) could be exploited to escape the container and gain access to the host system.
- **Prerequisites:** A vulnerability in a Python dependency. The container must have exploitable capabilities.
- **Impact:** Lateral movement (8). Full host compromise gives access to HA, other add-ons, the compliance database, the signing key, and potentially the home network.
- **Severity:** **High**
- **Existing mitigations:** HA Supervisor manages container isolation. The architecture mentions using S6-overlay (standard for HA add-ons).
- **Gaps:** The add-on config maps `media:rw` and `ssl:ro`, which gives the container filesystem access to shared HA directories. The ingress port (8099) exposes a web UI. No mention of dropping container capabilities, running as non-root, or using `--security-opt no-new-privileges`.
- **Recommended mitigations:**
  1. Run the bridge process as a non-root user inside the container.
  2. Drop all unnecessary Linux capabilities.
  3. Do not map more filesystem paths than necessary.
  4. Pin all Python dependency versions in `requirements.txt` and audit them regularly.
  5. Use a minimal base image (Alpine).

#### ATK-LAT-02: Compromised Drone as Network Pivot

- **Attack vector:** The companion computer (Raspberry Pi) on the drone is connected to the home WiFi. If the RPi is compromised (e.g., default SSH credentials, unpatched OS), it becomes a pivot point into the home network.
- **Prerequisites:** WiFi access to the drone's RPi (it is on the home network or a VLAN). Default credentials or unpatched vulnerability.
- **Impact:** Lateral movement (8). The RPi has WiFi access and could scan/attack other devices on the network.
- **Severity:** **High**
- **Existing mitigations:** Architecture mentions dedicated VLAN for drone WiFi.
- **Gaps:** The RPi's OS hardening is not specified. If it runs stock Raspbian with default `pi` user and SSH enabled, it is trivially compromisable from the LAN.
- **Recommended mitigations:**
  1. Harden the RPi: disable password SSH (key only), change default user, enable unattended-upgrades, disable unnecessary services.
  2. Place the RPi on a dedicated drone VLAN with firewall rules allowing only: MAVLink UDP to the bridge, RTSP to the media server. No other outbound connections.
  3. No internet access for the drone VLAN.

### 2.10 Denial of Service Attacks

#### ATK-DOS-01: Battery Exhaustion via Repeated Triggers

- **Attack vector:** If the alarm system can be triggered repeatedly (e.g., by waving at a PIR sensor, tripping a gate sensor), each trigger launches a patrol cycle. After 3-4 cycles, the battery is exhausted and the system is unavailable.
- **Prerequisites:** Ability to trigger the alarm sensor (physical access to the property perimeter).
- **Impact:** Denial of service (6). Battery drained, system unavailable for the real threat.
- **Severity:** **Medium**
- **Existing mitigations:** Battery check in safety gates (must be above threshold). Not-already-airborne check prevents concurrent flights.
- **Gaps:** No cooldown period between patrols. An attacker could trigger the alarm, wait for the patrol to complete and the drone to land, then trigger again.
- **Recommended mitigations:**
  1. Implement a cooldown timer in the HA automation: after a patrol completes, do not launch another for N minutes (e.g., 10-15 minutes) unless manually overridden.
  2. Raise the battery threshold for subsequent patrols (e.g., first patrol: 30%, second within 30 min: 50%, third: 70%).
  3. Log repeated triggers as a potential adversarial pattern and alert the operator.

#### ATK-DOS-02: Physical Obstruction of Dock

- **Attack vector:** Place an object on the dock lid or in the takeoff cylinder to prevent the drone from launching or landing.
- **Prerequisites:** Physical access to the dock.
- **Impact:** Denial of service (6). Physical damage (4) if the drone attempts to land on an obstructed pad.
- **Severity:** **Medium**
- **Existing mitigations:** Pad-clear sensor (ToF/IR) prevents lid closure onto drone. Limit switches detect lid position.
- **Gaps:** The pad-clear sensor detects whether the drone is present, not whether foreign objects are on the pad. An object placed on the landing pad would not necessarily be detected.
- **Recommended mitigations:**
  1. A weight sensor or more sophisticated pad occupancy detection could detect foreign objects.
  2. Camera coverage of the dock (see ATK-DOCK-02).
  3. The bridge should log if a launch command succeeds but the drone does not reach takeoff altitude within expected time.

---

## 3. Compliance-Specific Threats (Deep Dive)

### 3.1 Can an Operator Fabricate Compliance Records for a Part 108 Permit?

**Yes, with effort.** The operator owns the system. They can:

1. **Run SITL flights and record compliance data.** The bridge connects to SITL the same way it connects to a real FC. SITL generates realistic telemetry. The compliance recorder writes records that look identical to real-flight records.
   - **Mitigation:** Records should include a `flight_source` field: `live_aircraft` vs `sitl_simulation`. The bridge should detect SITL by checking the MAVLink system type or by the absence of real GPS hardware (`GPS_RAW_INT.fix_type` in SITL may differ). Records from SITL should be clearly marked.

2. **Modify the bridge source code** to write arbitrary records.
   - **Mitigation:** Git commit history of the bridge code is observable. If the project uses CI/CD with signed releases, the FAA could verify the operator is running unmodified code. Practically, this is hard to enforce for a self-hosted open-source project.

3. **Extract the Ed25519 key and write records directly to SQLite.**
   - **Mitigation:** See ATK-COMP-01. Key protection is the critical control.

4. **Replay historical flights with modified timestamps.**
   - **Mitigation:** The daily integrity heartbeat, NTP-verified timestamps, and Remote ID correlation provide cross-references that are harder to fabricate.

**Bottom line:** For a self-hosted system, the compliance recorder provides tamper-evidence (provable that records have not been altered after creation) but not tamper-proof (cannot prevent the operator from creating false records in the first place). The hash chain and signatures raise the bar significantly, but a determined operator with full system access can fabricate records. External correlation (Remote ID logs held by FAA, ADS-B exchange data, ISP traffic logs showing Litestream replication timing) provides independent evidence.

### 3.2 Can an Operator Delete Incriminating Records After an Incident?

**Partially, depending on deployment.**

- **Without Litestream:** Delete `compliance.db`. All records gone. The signing key can be regenerated, and a new chain started with no evidence of the deletion.
  - **Mitigation:** Mandatory Litestream replication.

- **With Litestream to operator-controlled storage:** Delete both the local DB and the replica.
  - **Mitigation:** Immutable storage (S3 Object Lock). Or replication to a target the operator does not control.

- **With Litestream to immutable storage:** The operator cannot delete the replica. They can delete the local DB, but the full history exists in the immutable replica. The FAA (or an investigator) can reconstruct the chain from the replica.
  - **Gap:** The operator could claim "the system malfunctioned and I lost the data" -- but the immutable replica contradicts this claim.

- **Remote ID correlation:** During any flight, the FAA receives Remote ID position broadcasts. These are stored in the FAA's systems and are independent of the operator's compliance recorder. If the operator deletes their compliance records for a specific flight, the FAA's Remote ID data still shows the flight occurred.

### 3.3 Can an Attacker Corrupt the Compliance Database?

**Yes, this is a denial-of-integrity attack:**

1. **Truncate or delete the database** (ATK-COMP-02).
2. **Insert invalid records** that break the hash chain. Subsequent `verify_chain` calls would fail, casting doubt on all records.
3. **Modify records in-place** -- detected by hash chain verification, but the database is now "tainted" and cannot be used for a Permit application without explaining the gap.

**Impact:** The operator loses their compliance history, potentially delaying or preventing a Part 108 Permit application.

**Mitigations:**
- Litestream replication preserves a clean copy.
- Regular automated `verify_chain` detects corruption early.
- The bridge should be able to reconstruct from the Litestream replica if the local DB is corrupted.

### 3.4 Ed25519 Key Management Risks

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Key stored as plain file in add-on data | High (likely implementation) | Key extraction enables full forgery | File permissions 600, exclude from backups |
| Key included in HA backups | High (add-on data is backed up) | Backup theft = key theft | Separate key backup process |
| Key lost (SD card failure, reinstall) | Medium | All future records use a new key; chain continuity broken | Litestream replica + documented key rotation |
| No key rotation mechanism | High (likely not implemented) | Compromised key is permanent | Implement key rotation with chain bridging (new key signs a rotation record referencing old key) |
| Multiple keys for SITL vs live | Low (not mentioned) | SITL records signed with same key as live records | Use separate keys for SITL and live, or mark records |

### 3.5 Litestream Replication: Help or Additional Attack Surface?

**Both.**

**Helps:**
- Eliminates single-device failure for compliance data.
- Provides an off-device copy that survives local tampering.
- ~1 second RPO means even a sudden power loss loses at most 1 second of records.

**Additional attack surface:**
- **Litestream credentials in the add-on config:** S3 access keys, GCS service account keys, or NAS credentials are stored in the add-on configuration. If compromised, an attacker could read the full compliance database from the replica, delete it, or modify it (if storage is not immutable).
- **Litestream binary supply chain:** Litestream is a Go binary bundled in the add-on. A compromised Litestream binary could exfiltrate data or silently drop replication.
- **Network exposure:** Litestream makes outbound HTTPS connections to S3/GCS. If the HA server is compromised, these credentials could be harvested.
- **Replication lag exploitation:** An attacker could block outbound Litestream traffic (firewall rule), perform actions, then delete local records before unblocking replication. The window is small (~seconds) but exists.

**Recommendation:** Use immutable storage (S3 Object Lock with Compliance mode) for the Litestream target. Rotate S3 credentials regularly. Monitor Litestream replication status (alert if replication stops).

---

## 4. Supply Chain and Dependency Threats

### 4.1 Software Dependencies

| Dependency | Risk | Severity | Mitigation |
|------------|------|----------|------------|
| **MAVSDK-Python** | Maintained by the MAVLink project. Binary `mavsdk_server` is a C++ gRPC server. A vulnerability here could allow arbitrary code execution in the bridge container. | High | Pin version, audit releases, run in container with minimal privileges |
| **aiomqtt** | Async MQTT client. Relatively small codebase. Typosquatting risk (previously `asyncio-mqtt`). | Medium | Pin version, verify package hash |
| **grpcio** | Google's gRPC library for Python. Large attack surface (C++ native code). Regular CVEs. | High | Pin version, update on security advisories. This is why the bridge runs in a container, not in HA's venv. |
| **protobuf** | Google Protocol Buffers. Parsing vulnerabilities have been found historically. | Medium | Pin version |
| **ArduPilot firmware** | Open source C++ firmware. Well-audited by the community but complex. A firmware bug could cause a crash or erratic behavior. | High | Use stable releases only. Test firmware updates in SITL before deploying to aircraft. |
| **SQLite (Python stdlib)** | Mature, extensively tested. Low risk. | Low | Keep Python updated |
| **Litestream** | Single Go binary. Small codebase, well-maintained. | Low-Medium | Pin version, verify release signature |
| **ESPHome firmware** | Open source ESP32 framework. OTA updates are a supply chain risk if the update source is compromised. | Medium | Disable OTA in production or require physical button |
| **Docker base image** | Alpine or Debian slim. Container images from Docker Hub can be compromised. | Medium | Use official images, pin digests (not just tags), scan with Trivy/Grype |

### 4.2 Hardware Supply Chain

| Component | Risk | Mitigation |
|-----------|------|------------|
| Pixhawk 6C (Holybro) | Counterfeit components are a known issue in the Pixhawk ecosystem. A counterfeit FC could have modified firmware. | Purchase from authorized distributors. Verify board markings. Flash ArduPilot from source. |
| ADS-B Receiver (uAvionix pingRX) | If the ADS-B receiver is tampered with, it could fail to report traffic or report false traffic. | Purchase from uAvionix directly. Verify serial number. Test against known ADS-B traffic. |
| Raspberry Pi (companion) | Supply chain generally trustworthy. | Purchase from authorized distributors. |
| ESP32 | Counterfeit ESP32 modules exist with modified flash. | Purchase from reputable sources (Espressif official, Adafruit, SparkFun). |

### 4.3 DJI Ban Implications

The architecture document explicitly addresses the DJI pivot (Section 6.2, 6.7). The system is designed to be DJI-free. No DJI components are used in the MAVLink architecture. The DJI FCC Covered List addition (December 2025) is a key motivator for the MAVLink pivot.

**Residual risk:** If the operator sources components from Chinese manufacturers that are later added to the FCC Covered List, those components could become unavailable for replacement. The architecture's aircraft-agnostic design mitigates this.

---

## 5. Insider Threat Scenarios

### 5.1 Operator Flies Without Proper Authorization

**Scenario:** Operator receives an alarm while away from home (not within VLOS). Taps LAUNCH anyway because "it's just a quick check."

- **Part 107 violation:** RPIC must be within VLOS. The system cannot enforce RPIC location.
- **Architecture note:** The architecture explicitly documents this: "The system cannot technically enforce RPIC location" (Section 3.2).
- **Mitigation gap:** No technical control prevents this. The compliance record logs `rpic_authorized` with a timestamp but does not verify the RPIC's physical location.
- **Recommended mitigation:**
  1. Optionally require the RPIC's phone GPS location to be within a configurable radius of the operational area before the LAUNCH button is active.
  2. Log the RPIC's phone GPS location as part of the authorization compliance record. This does not prevent the violation but creates evidence.
  3. In Part 108 mode, this is not a violation (BVLOS is authorized). This is primarily a Part 107 concern.

### 5.2 Operator Surveils Neighbors

**Scenario:** Operator modifies a mission to fly along the property boundary with the gimbal angled toward the neighbor's yard, then views/records the video.

- **The operational area validation prevents waypoints outside the property.** But flying within the property with a sideways-angled camera captures off-property imagery.
- **Mitigation gap:** No gimbal angle restriction relative to property boundary. No privacy-masking on video.
- **Recommended mitigation:**
  1. Compliance records include gimbal angle at each waypoint. An auditor could detect suspicious gimbal patterns.
  2. Document camera FOV analysis in the deployment checklist.
  3. Consider restricting gimbal pitch to -60 or steeper (more downward) when near property edges.

### 5.3 Family Member Triggers System

**Scenario:** A family member (child, guest) triggers the alarm system accidentally or intentionally, launching a patrol.

- **In Part 107 mode:** The RPIC must authorize via push notification. A family member cannot launch the drone without the RPIC's phone.
- **In Part 108 mode:** The flight is autonomous if a Flight Coordinator is on duty. A family member could repeatedly trigger alarms, exhausting the battery (see ATK-DOS-01).
- **Recommended mitigation:**
  1. The cooldown timer (ATK-DOS-01) limits the impact.
  2. The alarm system itself should be configured to prevent false triggers (alarm panel sensitivity, zone configuration).
  3. A `drone_hass.emergency_disable` service or physical kill switch should be available to immediately disable all autonomous operations.

### 5.4 Operator Covers Up an Incident

**Scenario:** The drone clips a tree branch during a mission, causing minor damage. No injury, but the operator wants to avoid an insurance claim or FAA report. They delete the compliance records for that flight.

- **With Litestream to immutable storage:** The records exist in the replica and cannot be deleted.
- **Without immutable storage:** See Section 3.2.
- **Remote ID correlation:** The FAA has a record of the flight via Remote ID broadcasts.
- **HA recorder:** If flight state entities are kept in the HA recorder, there is a separate record of the flight event (though not authoritative like the compliance DB).

---

## 6. Recommendations Priority Matrix

### Must-Fix Before Deployment (Critical)

| ID | Recommendation | Threat(s) |
|----|---------------|-----------|
| R-01 | **Enable MAVLink 2 message signing** between bridge and flight controller. Generate a shared signing key and configure on both endpoints. Without this, any device on the network can command the drone. | ATK-MAV-01, ATK-MAV-02, ATK-MAV-04, ATK-FW-01 |
| R-02 | **Configure MQTT authentication and ACLs.** Provide a reference Mosquitto config with separate credentials for bridge and HA, and ACLs restricting who can publish to command, state, mission, and compliance topics. | ATK-MQTT-01, ATK-MQTT-02, ATK-MQTT-03, ATK-MQTT-05 |
| R-03 | **Network isolate the drone WiFi on a dedicated VLAN.** Firewall rules: bridge container <-> drone WiFi only. No other LAN devices on the drone VLAN. No internet access for the drone VLAN. | ATK-MAV-01, ATK-MAV-04, ATK-LAT-02 |
| R-04 | **Harden the companion computer (RPi).** Key-only SSH, disable default user, unattended-upgrades, minimal services, no internet access. | ATK-LAT-02, ATK-FW-02 |
| R-05 | **Move operational area to bridge-local config, not MQTT.** The operational area (geofence polygon) is a safety-critical boundary. It should be loaded from a file on disk inside the bridge container, not from an MQTT retained message that any MQTT client could overwrite. | ATK-MQTT-02 |
| R-06 | **Define the RPIC authorization token flow explicitly.** The Part 107 authorization must use a cryptographic challenge-response, not just an HA event match. The bridge generates a nonce, includes it in the notification, and only accepts that nonce back within the time window. | ATK-HA-02 |

### Must-Fix Before Part 108 Operations (High)

| ID | Recommendation | Threat(s) |
|----|---------------|-----------|
| R-07 | **Mandatory Litestream replication with immutable storage.** Use S3 Object Lock (Compliance mode) or equivalent. The bridge should refuse to operate in Part 108 mode without active replication. | ATK-COMP-02, ATK-COMP-03, Section 3.2 |
| R-08 | **Ed25519 key protection.** Document key storage model. File permissions 600. Exclude from HA backups. Implement key fingerprint registration on first install. | ATK-COMP-01 |
| R-09 | **Distinguish SITL from live records in compliance DB.** Add `flight_source` field. Detect SITL by hardware identifiers. Exclude SITL records from Permit application data. | ATK-COMP-04, Section 3.1 |
| R-10 | **Bridge-independent safety checks.** The bridge ComplianceGate must independently verify weather, DAA health, and FC status from its own data sources -- not from MQTT topics that could be spoofed. | ATK-MQTT-05, ATK-HA-01 |
| R-11 | **Implement patrol cooldown timer.** After a patrol completes, enforce a minimum cooldown before the next launch. Escalating battery thresholds for subsequent patrols. | ATK-DOS-01 |
| R-12 | **Bridge monitors critical ArduPilot parameters continuously.** Periodically re-read `FENCE_ENABLE`, `AVD_ENABLE`, `FS_GCS_ENABLE`, `RTL_ALT`, and alert if values differ from expected configuration. | ATK-FW-01 |
| R-13 | **MQTT TLS mandatory.** Use port 8883 with TLS. The architecture mentions this as a requirement but it must be enforced, not optional. Ship a reference TLS configuration. | ATK-MQTT-01 |

### Should-Fix (Medium)

| ID | Recommendation | Threat(s) |
|----|---------------|-----------|
| R-14 | Enable SiK radio AES-128 encryption. | ATK-MAV-05 |
| R-15 | Configure RTSP authentication on go2rtc/mediamtx. Firewall RTSP ports. | ATK-VID-01 |
| R-16 | Implement video retention policy (auto-delete after N days). | ATK-VID-02 |
| R-17 | Run `verify_chain` automatically on bridge startup and daily. Alert on failures. | ATK-COMP-03 |
| R-18 | Add firmware version check to bridge startup. Log ArduPilot version as compliance record. Alert on unexpected changes. | ATK-FW-02 |
| R-19 | Add `source` field to compliance records (`bridge_internal` vs `ha_external`). Authorization records must be `bridge_internal` only. | ATK-MQTT-03 |
| R-20 | Implement a mission allowlist in bridge config. Only predefined mission IDs are accepted. | ATK-MQTT-02 |
| R-21 | Run bridge process as non-root inside the container. Drop unnecessary Linux capabilities. | ATK-LAT-01 |
| R-22 | Mandate WPA3-SAE with PMF for drone WiFi VLAN. Document as deployment requirement. | ATK-MAV-03 |
| R-23 | Implement an emergency disable service (`drone_hass.emergency_disable`) that immediately prevents all autonomous launches. Physical kill switch on dock is complementary. | Section 5.3 |
| R-24 | Log RPIC phone GPS location in Part 107 authorization compliance record. | Section 5.1 |

### Nice-to-Have (Low)

| ID | Recommendation | Threat(s) |
|----|---------------|-----------|
| R-25 | GPS spoofing detection: compare reported position against expected operational area. Alert on sudden position jumps. | ATK-FW-03 |
| R-26 | Dock tamper sensor (vibration/reed switch) with HA alert. | ATK-DOCK-02 |
| R-27 | External timestamping authority for compliance records (RFC 3161 TSA). | ATK-COMP-01, ATK-COMP-04 |
| R-28 | Gimbal angle restrictions near property boundaries. | ATK-PRIV-01 |
| R-29 | Randomize mission timing slightly to avoid predictable patrol schedules. | ATK-PRIV-02 |
| R-30 | Pin all Python dependency versions and Docker image digests. Automated vulnerability scanning in CI. | Section 4.1 |
| R-31 | Camera/gimbal commands restricted to airborne-only (bridge enforcement). | ATK-HA-03 |

---

## 7. Positive Findings (Things Done Right)

The architecture demonstrates strong security thinking in several areas:

1. **Defense-in-depth with three independent safety layers** (HA automation, bridge ComplianceGate, ArduPilot firmware). This is the correct approach -- no single layer is trusted.

2. **No virtual stick / manual attitude control exposed via MQTT.** Section 9.5 explicitly blocks this and explains why. This eliminates the highest-risk command surface. Excellent decision.

3. **Firmware geofence as an independent enforcement layer.** Even if the bridge is compromised, the FC enforces geographic boundaries independently.

4. **ComplianceGate as a bridge-level gatekeeper.** Flight commands cannot bypass the ComplianceGate. The bridge requires a valid authorization token before executing any flight command.

5. **Append-only compliance recorder with hash chain + Ed25519 signatures.** This is a significantly higher bar than most hobbyist and many commercial drone systems provide.

6. **Litestream replication** for off-device compliance data protection. Well-chosen technology -- zero application code changes, continuous replication.

7. **Add-on isolation.** Running MAVSDK-Python in a Docker container, separate from HA Core, is correct for both reliability and security. Dependency conflicts cannot affect HA, and process isolation limits blast radius.

8. **ESPHome safety interlocks enforced on-controller.** The dock safety logic runs on the ESP32, not in HA. This is critical -- HA restarts do not affect dock safety.

9. **Clear acknowledgment of limitations.** The architecture explicitly states what the system cannot enforce (RPIC location, for example) rather than overpromising.

10. **Explicit Part 107 vs Part 108 mode switching** with different safety requirements per mode. The Part 107 mode is conservative (human authorization required), and Part 108 mode adds additional requirements (DAA, FC on duty), not fewer.

11. **GCS-loss failsafe reliance on ArduPilot.** The architecture correctly identifies that ArduPilot handles link-loss safety independently. The bridge going offline does not leave the drone without a safety net.

12. **Replay protection** via timestamps on MQTT commands (rejected if stale) and single-use correlation IDs.

---

## 8. Summary of Severity Distribution

| Severity | Count | Key Themes |
|----------|-------|------------|
| **Critical** | 3 | MAVLink has no authentication (ATK-MAV-01, ATK-MAV-04); MQTT without ACLs (ATK-MQTT-01); Signing key extraction (ATK-COMP-01) |
| **High** | 10 | Mission poisoning, compliance event injection, push notification spoofing, HA automation manipulation, parameter tampering, firmware replacement, container escape, RPi as pivot, compliance DB deletion, operator fabrication |
| **Medium** | 10 | WiFi deauth, SiK eavesdropping, MQTT DoS, RTSP interception, video storage, ESPHome exploitation, dock tampering, GPS spoofing, battery exhaustion, dock obstruction |
| **Low** | 3 | Remote ID exposure, patrol timing predictability |

The three critical findings all share a common theme: **unauthenticated protocol interfaces.** MAVLink and MQTT are both designed for trusted networks and have no built-in authentication. The system's security posture depends entirely on network isolation (VLAN) and application-level controls (MQTT ACLs, bridge validation). If either fails, the attacker has direct control over the drone.

The compliance recorder is well-designed for tamper-evidence but cannot be tamper-proof when the operator controls the signing key and the deployment environment. This is an inherent limitation of self-hosted compliance systems and should be documented rather than glossed over.

---

## 9. Threat Resolutions

Detailed resolutions for all threats. Full implementation details (code, configs, ArduPilot parameters) are in the companion files:
- `docs/resolutions-ua.md` — MAVLink, ArduPilot, flight controller, compliance recorder, RF link resolutions
- `docs/resolutions-ha.md` — MQTT, HA integration, network, Docker, video, dock resolutions

### 9.1 Critical Resolutions (Must-Fix Before Deployment)

#### ATK-MAV-01 / ATK-MAV-04: MAVLink Command Injection / Rogue GCS

**Resolution: Enable MAVLink v2 message signing.**

- Generate 32-byte signing key at bridge first install. Store at `/data/compliance/mavlink_signing.key`, permissions `0600`.
- Initial key exchange via USB serial (not WiFi) to prevent MITM.
- Bridge uses pymavlink `setup_signing()` to configure both itself and the flight controller. ArduPilot persists the key in EEPROM.
- All subsequent packets include SHA-256 HMAC + 48-bit timestamp. Unsigned packets silently dropped.
- Set `SYSID_MYGCS = 245` (bridge system ID) on the FC.
- Firewall: DROP all inbound UDP 14540/14550 except from the bridge container's network namespace.
- Place drone WiFi on a dedicated VLAN with client isolation — bridge container is the only allowed host.

**Residual risk:** Physical access to the FC via USB allows re-keying. Dock physical lock and tamper sensor are the controls.

#### ATK-MQTT-01: Unauthenticated MQTT Command Injection

**Resolution: Enforce authentication, TLS, and topic-level ACLs.**

Ship a reference Mosquitto configuration:
- TLS only on port 8883 (no plaintext listener on 1883)
- `allow_anonymous false`
- Separate credentials for bridge (`bridge_user`) and HA (`ha_user`)
- ACL restricting topic access:

```
# Bridge: publish telemetry/state/daa/compliance, read commands/missions
user bridge_user
topic write drone_hass/+/telemetry/#
topic write drone_hass/+/state/#
topic write drone_hass/+/daa/#
topic write drone_hass/+/compliance/#
topic write drone_hass/+/command/+/response
topic read drone_hass/+/command/#
topic read drone_hass/+/missions/#

# HA: publish commands/missions, read everything
user ha_user
topic write drone_hass/+/command/#
topic write drone_hass/+/missions/#
topic read drone_hass/#
```

**Residual risk:** ACL enforcement depends on Mosquitto configuration being applied correctly. Ship a deployment verification script.

#### ATK-COMP-01: Ed25519 Signing Key Extraction

**Resolution: Defense in depth for key management.**

1. Key generated at first install with `Ed25519PrivateKey.generate()`, stored at `/data/compliance/keys/signing_key.pem`, permissions `0600`.
2. Public key exported separately at `/data/compliance/keys/signing_key.pub`, permissions `0644`.
3. Key fingerprint (SHA-256 of public key, first 16 hex chars) logged as compliance record #1 and displayed in Ingress UI.
4. Operator instructed: "Record this fingerprint externally — email, print, or notarize. This proves the key existed at this date."
5. Bridge startup warns: `"Ed25519 signing key is included in HA backups. Ensure backups are encrypted."`
6. Mandatory Litestream replication for Part 108 mode — bridge refuses to start in Part 108 mode without active replication.
7. Litestream target should use S3 Object Lock (COMPLIANCE mode, 5-year retention) — prevents deletion even by the bucket owner.

**Residual risk:** Operator controls the signing key and the deployment environment. A self-hosted compliance system provides tamper-evidence, not tamper-proof. This is an inherent limitation, explicitly documented.

### 9.2 High Resolutions (Must-Fix Before Part 108)

#### ATK-MAV-02: MAVLink Replay Attack
**Resolution:** MAVLink v2 signing includes a monotonically increasing 48-bit timestamp. ArduPilot rejects messages with older timestamps. Fully mitigated by signing (ATK-MAV-01 resolution).

#### ATK-MAV-05: SiK Radio Eavesdropping
**Resolution:** Enable SiK AES-128 encryption (`ATS15=1`) on both radios with a shared key. Change Net ID (`ATS11`) from default. MAVLink signing active on top of SiK encryption (defense in depth).

#### ATK-MQTT-02: Mission Definition Poisoning
**Resolution:** Move operational area to bridge-local config file (`/data/compliance/operational_area.geojson`), NOT MQTT. Bridge publishes to MQTT for HA display but does NOT subscribe to changes. Implement mission allowlist in bridge config. MQTT ACLs restrict `missions/#` to HA user only.

#### ATK-MQTT-03: Compliance Event Injection
**Resolution:** Add `source` field to every compliance record: `bridge_internal` (generated by bridge from its own state) or `ha_external` (from MQTT). Authorization records (`rpic_authorized`, `safety_gate`) must be `bridge_internal` only — bridge rejects external writes to these record types. MQTT ACLs prevent non-bridge clients from publishing to `compliance/#`.

#### ATK-FW-01: ArduPilot Parameter Tampering
**Resolution:** Define expected safety parameter set in bridge config (FENCE_ENABLE, AVD_ENABLE, FS_GCS_ENABLE, RTL_ALT, etc.). Verify at startup — mismatch blocks all flights. Re-read every 30 seconds — mismatch while airborne triggers RTL. MAVLink signing prevents unauthorized parameter changes.

#### ATK-FW-02: Firmware Replacement
**Resolution:** Read `AUTOPILOT_VERSION` at every startup. Log firmware version + git hash + board UID as compliance record. Compare against stored baseline — mismatch blocks flights. Companion RPi hardened: SSH key-only, no default user, no internet.

#### ATK-HA-02: Push Notification Spoofing
**Resolution:** Replace simple HA event match with cryptographic challenge-response. Bridge generates a nonce, includes it in the push notification. RPIC taps LAUNCH, nonce flows back through HA to bridge. Bridge validates the nonce (one-time use, 120s expiry). Attacker who fires a fake event cannot guess the nonce.

#### ATK-COMP-02: Compliance Database Deletion
**Resolution:** Litestream mandatory for Part 108 — bridge refuses to start without active replication. S3 Object Lock in COMPLIANCE mode. Chain continuity check on startup: if local DB is empty but replica has records, log critical anomaly.

#### ATK-COMP-04: Compliance Record Fabrication
**Resolution:** Every record includes `flight_source` (`live_aircraft` or `sitl_simulation`), detected from `AUTOPILOT_VERSION.uid` (0 for SITL), firmware string, and GPS hardware. SITL records explicitly excluded from Permit application exports. Remote ID broadcasts provide independent, operator-uncontrollable flight records for corroboration.

#### ATK-DOS-01: Battery Exhaustion via Repeated Alarms
**Resolution:** Implement patrol cooldown timer: minimum configurable interval between launches (default 10 minutes). Escalating battery threshold for consecutive patrols (1st: 30%, 2nd: 50%, 3rd: 70%). Max patrols per day configurable.

#### ATK-LAT-01 / ATK-LAT-02: Container Escape / RPi Pivot
**Resolution:** Bridge runs as non-root inside container (`USER bridge` in Dockerfile, drop all capabilities except NET_RAW). Read-only rootfs (`--read-only`). RPi hardened per R-04. Drone VLAN isolated with strict firewall rules.

### 9.3 Medium Resolutions

| Threat | Resolution |
|--------|-----------|
| ATK-MAV-03: WiFi deauth | Mandate WPA3-SAE with PMF. Document as deployment requirement. SiK backup with auto-failover. `FS_GCS_ENABLE=1` (RTL on link loss). |
| ATK-MQTT-04: MQTT Flood DoS | Mosquitto `max_inflight_messages 20`, `max_connections 10`, `message_size_limit 65536`. Bridge debounces duplicate commands. |
| ATK-MQTT-05: State Topic Spoofing | Bridge derives safety state from internal MAVLink data, never from MQTT topics. ACLs prevent non-bridge publish to state topics. |
| ATK-VID-01: RTSP Interception | go2rtc authentication. RTSP bound to localhost/VLAN only. Firewall RTSP ports from WAN. |
| ATK-VID-02: Video Storage Exposure | Auto-purge after configurable retention (default 30 days). Encrypted at-rest if filesystem supports it. |
| ATK-HA-01: HA Automation Manipulation | Bridge ComplianceGate independently verifies all conditions from MAVLink, never trusts HA entity states. |
| ATK-HA-03: Camera Abuse | Gimbal/camera commands restricted to airborne state only (bridge enforcement). |
| ATK-DOCK-01: ESPHome Exploitation | API encryption key mandatory. OTA password mandatory. Firmware signing if ESPHome supports it. |
| ATK-DOCK-02: Dock Physical Tamper | Tamper sensor (vibration/reed) with HA alert. Physical lock. |
| ATK-FW-03: GPS Spoofing | Multi-constellation GNSS (`GPS_GNSS_MODE=99`). Bridge-side position sanity checks. On suspicion: LAND (not RTL — RTL uses GPS). Dual GPS if hardware supports it. |

### 9.4 Low Resolutions

| Threat | Resolution |
|--------|-----------|
| Remote ID exposure | Accepted risk — Remote ID broadcast is a legal requirement. The position data is public by design. |
| Patrol timing predictability | Randomize mission start by 0-30 seconds. Vary mission selection if multiple corridors cover the trigger area. |
| Dependency supply chain | Pin all Python dependency versions. Pin Docker base image digests. Automated vulnerability scanning in CI. |

### 9.5 Compliance Data Integrity Summary

Given the user's emphasis that **compliance data integrity is the most important aspect**, here is the complete chain of controls:

| Layer | Control | What It Proves |
|-------|---------|---------------|
| 1. Append-only writes | Bridge never issues UPDATE/DELETE on compliance tables | Records are not modified after creation |
| 2. SHA-256 hash chain | Each record includes hash of previous | No records removed or altered mid-chain |
| 3. Ed25519 signatures | Each record signed with install-time key | Records were written by this specific bridge instance |
| 4. Key fingerprint registration | Fingerprint logged as record #1, operator records externally | The key existed at install time |
| 5. Daily heartbeat records | Written even when no flights occur | Chain was intact at each heartbeat |
| 6. Litestream replication | Continuous WAL streaming to off-device storage | Records exist in a second location the operator cannot silently modify |
| 7. S3 Object Lock (COMPLIANCE mode) | WORM storage for 5 years | Even the bucket owner cannot delete records during retention |
| 8. Chain verification on startup + daily | Walks entire chain, verifies every hash + signature | Detects any tampering or corruption |
| 9. SITL detection | Hardware UID, firmware string, GPS characteristics | Simulation records cannot be mixed with live flight records |
| 10. Remote ID correlation | FAA receives independent position broadcasts | External, uncontrollable corroboration of live flights |
| 11. Export with verification | JSON/CSV export includes chain verification summary | Third party can independently verify the audit trail |

**What this system CAN prove:** Records were written by a specific bridge instance, in a specific order, at specific times, and have not been altered since writing. Live flights are corroborated by Remote ID. Records exist in immutable off-device storage.

**What this system CANNOT prove:** That the records accurately reflect what happened. A modified bridge codebase could write false records with valid signatures. This is the fundamental limitation of any self-hosted compliance system — the entity producing the records is the entity being audited. Mitigation: open-source code is auditable; git history shows modifications; the FAA can require running unmodified tagged releases.

---

## 10. Red Team Validation of Resolutions

> **Date:** 2026-04-14
> **Author:** Red Team Operator
> **Method:** Adversarial pressure-testing of every resolution in Section 9. For each resolution, we ask: "How would a motivated attacker, or a motivated operator, route around this mitigation?"

---

### 10.1 Compliance Data Integrity Chain (Top Priority)

The resolution proposes an 11-layer integrity chain (Section 9.5). This is the most critical subsystem to pressure-test because the user's stated priority is preserving compliance data integrity in a verifiable and auditable way.

#### 10.1.1 Attack: Operator Runs a Modified Bridge that Signs False Records

- **Resolution being tested:** Layers 1-4 (append-only writes, hash chain, Ed25519 signatures, key fingerprint registration)
- **Gap found:** The Ed25519 signature proves that the bridge's private key produced the record. It does NOT prove that the bridge was running unmodified code. An operator can fork the bridge, add a function that writes fabricated compliance records (fake flights, fake DAA events, fake personnel authorizations), sign them with the legitimate key, and the entire chain verifies perfectly. The hash chain is intact. The signatures are valid. The records are false.
- **Attack scenario:** Operator needs 50 hours of incident-free autonomous flight history for a Part 108 application. They write a script that calls the ComplianceRecorder directly with fabricated telemetry data, timestamps spread over 6 months, realistic GPS coordinates within the operational area, and synthetic DAA "all clear" events. Every record is properly signed and hash-chained. Litestream replicates this fabricated chain to S3 Object Lock, where it becomes immutable -- the false history is now permanently preserved with the same protections as legitimate history.
- **Severity of the gap:** This is the fundamental limitation acknowledged in Section 9.5's "What this system CANNOT prove" paragraph. The resolution is honest about this. However, the suggested mitigation ("open-source code is auditable; git history shows modifications") is weaker than it appears. The operator can run modified code locally without pushing changes to any repository. Git history only shows what the operator chooses to commit. There is no mechanism for the FAA or any auditor to verify what code was actually running at the time records were produced.
- **Suggested hardening:**
  1. **Reproducible builds with binary attestation.** Publish signed Docker images for each tagged release. The bridge should log its own container image digest (from `/proc/self/cgroup` or the Docker API) as a compliance record at startup. An auditor can verify that the digest matches a published release. This does not prevent running modified code, but it means the operator must either (a) run the official image (auditable) or (b) run a different image and have a mismatched digest in the compliance log (detectable), or (c) modify the code to lie about its own digest (requires deeper effort and leaves traces in the image layers).
  2. **Remote attestation service (stretch goal).** A lightweight external service that the bridge periodically checks in with, reporting its image digest and chain head hash. The service timestamps these check-ins independently. An operator who runs modified code would need to either compromise this service or forge check-ins.
  3. **Accept this as residual risk and document it prominently** in any Part 108 application. Self-hosted compliance is inherently operator-trusted at the code layer. The FAA may require compensating controls (periodic audits, third-party monitoring, spot inspections).

#### 10.1.2 Attack: Operator Generates a New Signing Key and Rebuilds the Chain

- **Resolution being tested:** Layer 4 (key fingerprint registration)
- **Gap found:** The resolution instructs the operator to "record this fingerprint externally -- email to attorney, print and store in safe." This is a procedural control, not a technical one. Nothing enforces that the operator actually registers the fingerprint. If they do not, they can generate a new key at any time, rebuild the entire chain from scratch with fabricated records, and no one can prove this is a second key rather than the original.
- **Attack scenario:** After an incident, the operator generates a new Ed25519 key, writes a new compliance database with the incriminating flight removed, signs all records with the new key, replaces the Litestream S3 replica -- wait, S3 Object Lock prevents deletion. This is where the resolution holds.
- **Severity of the gap:** Medium. The S3 Object Lock layer (Layer 7) is the actual backstop here, not the key fingerprint registration. Without S3 Object Lock, key fingerprint registration is a procedural control that a dishonest operator ignores. WITH S3 Object Lock, the original chain (including the original key fingerprint) is preserved and cannot be replaced, so rebuilding with a new key is detectable because both chains exist in S3.
- **Key insight:** Layer 4 (key fingerprint registration) is not self-standing. It depends entirely on Layer 7 (S3 Object Lock) to be meaningful. If S3 Object Lock is not configured, Layer 4 provides zero protection because the operator simply does not register the key.
- **Suggested hardening:** The documentation should make this dependency explicit. The key fingerprint registration instruction should include: "This step is only meaningful if Litestream replication to immutable storage (S3 Object Lock) is active. Without immutable storage, a new key can be generated and a new chain built with no evidence of the swap."

#### 10.1.3 Attack: Exploiting the Litestream Replication Gap

- **Resolution being tested:** Layer 6 (Litestream replication, ~1 second RPO)
- **Gap found:** There is a window between when the bridge writes a compliance record to SQLite and when Litestream replicates the WAL frame to S3. The resolution states ~1 second RPO. During this window, an attacker (or the operator) with filesystem access can:
  1. Kill the bridge process.
  2. Kill the Litestream process.
  3. Modify or delete the SQLite WAL file.
  4. Restart Litestream -- it replicates the modified state.
- **Attack scenario:** The operator is running the system. A drone flight goes badly (near-miss with manned aircraft). The operator immediately SSHs to the HA server, stops the bridge and Litestream containers, deletes the most recent WAL entries (the flight records from the last few minutes), then restarts Litestream. Litestream checkpoints the modified database and replicates it. S3 Object Lock preserves the objects Litestream writes, but the objects Litestream writes now contain the modified database -- the incriminating records were deleted BEFORE they were replicated.
- **Severity of the gap:** Medium-High. This is a race condition. In practice, with a 1-second sync interval, the window is extremely small for an automated flight. The operator would need to act within 1 second of the incriminating event. For most scenarios, the records would already be replicated. However, the operator could proactively stop Litestream BEFORE a risky flight, conduct the flight, review the records, and only restart Litestream if the flight was clean.
- **Suggested hardening:**
  1. **The bridge should monitor Litestream health continuously, not just at startup.** If Litestream stops replicating (replication lag > 5 seconds), the bridge should refuse to execute flight commands and log a compliance event: "replication_stalled." This prevents the "stop Litestream before a risky flight" attack.
  2. **Litestream should run as a separate, independent process** that the bridge cannot control. On HAOS, this means Litestream runs as a separate add-on or as a system service, not as a subprocess of the bridge. The bridge should have no ability to stop or reconfigure Litestream.
  3. **The daily heartbeat should verify Litestream replication lag** and include the replication status in the heartbeat record.

#### 10.1.4 Attack: Litestream Misconfiguration that Silently Drops Records

- **Resolution being tested:** Layer 6 (Litestream replication)
- **Gap found:** Litestream is a third-party tool. The resolution trusts it to faithfully replicate all WAL frames. Potential silent failure modes:
  1. Litestream's S3 credentials expire or are revoked. Litestream logs errors but continues running -- the bridge's startup health check passes because Litestream is "running," just not replicating.
  2. S3 bucket policy changes (operator changes the bucket policy to deny writes). Litestream fails silently from the bridge's perspective.
  3. Litestream's `retention` setting causes old WAL segments to be pruned from S3. If the retention is set too aggressively (e.g., operator sets `retention: 24h`), old records may be removed from S3 -- and S3 Object Lock only applies to objects that still exist, not to objects that Litestream's own garbage collection removes before Object Lock retention takes effect.
- **Attack scenario (subtle):** The operator configures Litestream with `retention: 1h`. Litestream replicates faithfully but prunes old WAL segments after 1 hour. S3 Object Lock applies to each object individually -- but Litestream DELETE operations on old segments would be blocked by Object Lock if the Lock is at the bucket level. However, Litestream works by writing new generations and cleaning up old ones. If Litestream cannot delete old generations (because of Object Lock), it may error or accumulate storage indefinitely. This interaction between Litestream's garbage collection and S3 Object Lock's delete prevention is not well-documented and could cause operational issues that lead the operator to disable Object Lock.
- **Severity of the gap:** Medium. The Litestream + S3 Object Lock interaction needs to be tested empirically. The resolution assumes they work together seamlessly but does not document the expected behavior when Litestream tries to clean up old segments that Object Lock prevents from being deleted.
- **Suggested hardening:**
  1. **Document and test the Litestream + S3 Object Lock interaction.** Specifically: what happens when Litestream tries to delete old WAL segment objects that are under Object Lock retention? Does Litestream handle the 403 AccessDenied gracefully? Does it accumulate storage indefinitely? Does this break restore operations?
  2. **Set Litestream's `retention` to a value longer than the Object Lock retention** (or remove the retention setting entirely) so Litestream never attempts to delete objects that Object Lock would block.
  3. **Add a bridge health check that verifies recent Litestream replication success** -- not just that Litestream is running, but that objects were written to S3 within the last 60 seconds. This could query the S3 API for the most recent object timestamp.

#### 10.1.5 Attack: S3 Object Lock Bypass via AWS Account Control

- **Resolution being tested:** Layer 7 (S3 Object Lock, COMPLIANCE mode, 5-year retention)
- **Gap found:** The resolution states "Compliance mode means even the AWS root account cannot delete objects during the retention period." This is correct for S3 Object Lock in COMPLIANCE mode. However:
  1. The operator controls the AWS account. They can close the entire AWS account. AWS account closure triggers a 90-day grace period, after which all data is deleted. This effectively deletes the compliance records, Object Lock notwithstanding.
  2. The operator can contact AWS Support and, with sufficient identity verification, request bucket deletion or account remediation. AWS has historically honored such requests for account owners in extreme circumstances.
  3. The operator can let the AWS bill go unpaid. After sufficient delinquency, AWS suspends the account and eventually deletes it.
- **Attack scenario:** After an incident, the operator closes their AWS account. 90 days later, all S3 data (including Object Lock-protected compliance records) is permanently deleted. The FAA investigates 6 months later and finds no records.
- **Severity of the gap:** Medium. AWS account closure is an extreme action with broad consequences (it deletes everything in the account). This is a high-cost attack -- the operator loses all their AWS resources. But for a serious incident (injury, property damage, potential criminal liability), the operator might accept this cost. The 90-day grace period does provide a window for investigators to issue a preservation order.
- **Suggested hardening:**
  1. **Document the AWS account closure loophole.** Make clear that S3 Object Lock protects against object-level deletion but not account-level destruction.
  2. **For maximum integrity, replicate to a target the operator does not control.** The original threat model Section 3.2 recommended this: "a third-party compliance escrow service, or a shared S3 bucket managed by an insurance company." The resolutions did not adopt this recommendation. It remains the strongest available mitigation.
  3. **Remote ID correlation is the true backstop.** For any flight that actually occurred, the FAA's Remote ID infrastructure has an independent record. This cannot be deleted by the operator. The compliance chain is most useful for proving what the system's safety posture was during the flight (DAA active, FC on duty, weather within envelope), not for proving the flight occurred. Remote ID proves the flight occurred.

#### 10.1.6 Attack: Defeating the Daily Heartbeat

- **Resolution being tested:** Layer 5 (daily heartbeat records)
- **Gap found:** The heartbeat proves the chain was intact at the time of the heartbeat. But:
  1. If the operator stops the bridge (e.g., "system was down for maintenance"), no heartbeat is written. A gap in heartbeats is suspicious but not proof of tampering.
  2. The heartbeat does not include any external, operator-uncontrollable data. It is self-referential -- the bridge proves to itself that the chain is intact. An operator who fabricated the chain also fabricated the heartbeats.
- **Severity of the gap:** Low. The heartbeat is useful for detecting third-party tampering (someone else corrupts the database) but provides zero protection against operator fabrication.
- **Suggested hardening:**
  1. **Include external entropy in each heartbeat.** For example, include the most recent Bitcoin block hash (publicly verifiable, operator-uncontrollable timestamp anchor) or query an RFC 3161 Timestamp Authority. This proves the heartbeat was written after a specific real-world moment.
  2. **Publish the heartbeat hash to an external, append-only ledger** (even something as simple as an email to a fixed address, or a tweet, or a blockchain transaction). This creates an off-system, operator-uncontrollable timestamp for the chain state.

#### 10.1.7 Attack: SITL Detection Evasion

- **Resolution being tested:** Layer 9 (SITL detection via hardware UID, firmware string, GPS characteristics)
- **Gap found:** The resolution detects SITL by checking `AUTOPILOT_VERSION.uid` (0 for SITL) and firmware string. An operator who wants to fabricate records using SITL can:
  1. Patch the SITL build to report a non-zero UID matching their real FC's UID.
  2. Patch the SITL firmware string to match the real firmware.
  3. Use SITL with a GPS replay of real-world coordinates (SITL supports GPS input).
  4. After patching, the SITL-generated records are indistinguishable from live records.
- **Attack scenario:** Operator compiles a custom SITL build with their real FC's board UID hardcoded. They run fabricated missions through this SITL instance. The bridge detects no difference from a real flight. Records are signed and hash-chained normally.
- **Severity of the gap:** Medium. Requires the operator to compile a custom ArduPilot SITL build with modified identifiers. This is nontrivial but within reach of a technically competent operator (ArduPilot is open source, building SITL is documented). The attack requires ~2-4 hours of effort for someone familiar with ArduPilot development.
- **Suggested hardening:**
  1. **Cross-reference with Remote ID.** Every real flight produces Remote ID broadcasts that the FAA receives. A SITL "flight" produces no Remote ID broadcasts. For any flight in the compliance database, the FAA can check whether a corresponding Remote ID track exists. This is the strongest available detection mechanism and is already noted in the resolution (Layer 10) but should be emphasized as THE primary defense against SITL fabrication.
  2. **Hardware attestation from the FC.** If the Pixhawk supports secure boot or has a hardware unique device identifier that SITL cannot replicate, log it. However, Pixhawk 6C does not have a TPM or secure boot, so this is limited to the STM32 UID, which SITL can spoof at the source code level.
  3. **Accept that SITL fabrication cannot be prevented by software alone.** Document that Remote ID correlation is the required verification mechanism for any Part 108 application review.

### 10.2 MAVLink v2 Signing

#### 10.2.1 Signing Key Extraction from Pixhawk EEPROM

- **Resolution being tested:** ATK-MAV-01 resolution (MAVLink v2 signing)
- **Gap found:** ArduPilot stores the MAVLink signing key in EEPROM/flash on the flight controller. Anyone with physical access to the Pixhawk and a debugger (SWD/JTAG, ~$15 for a J-Link clone) can read the EEPROM and extract the signing key. With the key, they can sign arbitrary MAVLink messages and impersonate the bridge.
- **Attack scenario:** An attacker with physical access to the aircraft (e.g., while it is on the dock) connects a SWD debugger to the Pixhawk, dumps the EEPROM, extracts the signing key, and later injects signed MAVLink commands over WiFi.
- **Severity of the gap:** Low-Medium. Requires physical access to the aircraft AND the technical skill to use SWD debugging on an STM32. The dock physical lock and tamper sensor are the controls. In a home/residential context, this is a sophisticated attack.
- **Suggested hardening:** The resolution's reliance on the dock physical lock and tamper sensor is appropriate for the threat level. No additional technical mitigation is practical -- ArduPilot does not support hardware-protected key storage on the Pixhawk 6C. Document this as an accepted residual risk contingent on physical security.

#### 10.2.2 Initial USB Key Exchange Security

- **Resolution being tested:** ATK-MAV-01 resolution ("Initial key exchange via USB serial (not WiFi) to prevent MITM")
- **Gap found:** USB serial key exchange is secure against network-based MITM. However:
  1. The key exchange happens once (at initial setup). If the operator performs this in an insecure environment (public space, with someone watching over their shoulder), the key could be observed.
  2. The key is 32 bytes, typically displayed as hex. It is not practical for an observer to memorize it, but a camera could capture it.
  3. More practically: the key exists in plaintext on the bridge's filesystem (`/data/compliance/mavlink_signing.key`). Extracting it from the bridge container is easier than intercepting the USB exchange.
- **Severity of the gap:** Low. The USB key exchange itself is fine. The key storage on the bridge filesystem is the weaker link (already covered under ATK-COMP-01).
- **Suggested hardening:** No change needed. The USB exchange is the correct approach.

#### 10.2.3 Firmware Updates and Signing Key Persistence

- **Resolution being tested:** ATK-MAV-01 resolution
- **Gap found:** The resolution does not address what happens to the MAVLink signing key when ArduPilot firmware is updated. ArduPilot firmware updates can be performed via:
  1. USB (Mission Planner, QGroundControl) -- typically preserves parameters and EEPROM.
  2. MAVLink over network (MAV_CMD_DO_FLASH_BOOTLOADER) -- some implementations wipe EEPROM.
  3. "Erase all" option in GCS -- explicitly wipes EEPROM including the signing key.
- **Attack scenario:** Not an attack, but an operational gap. Operator updates ArduPilot firmware with the "erase all" option (sometimes recommended for major version upgrades). The signing key on the FC is erased. The bridge still has its copy. The FC now rejects all signed messages from the bridge (or accepts unsigned messages if signing is no longer configured). Flights are blocked until re-keying is performed.
- **Severity of the gap:** Medium (operational, not security). But the recovery procedure matters for security: if re-keying requires USB physical access, that is good. If the bridge has a "re-key over network" fallback, that is an attack vector.
- **Suggested hardening:**
  1. **Document the firmware update procedure explicitly.** After any firmware update, the bridge should detect that the FC no longer accepts signed messages and alert the operator. Re-keying should require physical USB access (same as initial setup). The bridge should NOT have an automated "re-key over network" capability.
  2. **Log firmware update events as compliance records.** The bridge's existing firmware version check (ATK-FW-02 resolution) will detect the version change. Ensure it also detects signing key loss.

### 10.3 MQTT ACL Enforcement

#### 10.3.1 Reference Config vs Enforced Config

- **Resolution being tested:** ATK-MQTT-01 resolution (reference Mosquitto config)
- **Gap found:** The resolution provides a reference Mosquitto configuration. It is a well-written config. The problem is that it is a reference -- a document in a docs/ directory. Nothing in the software enforces that the operator actually applies this configuration. The default Mosquitto add-on on HAOS starts with `allow_anonymous true` and no ACL. An operator who follows the installation guide but skips the Mosquitto hardening section has a fully functional but completely unauthenticated MQTT broker.
- **Attack scenario:** Operator installs the drone_hass add-on. Everything works with default Mosquitto settings (no auth, no ACL, plaintext on 1883). The operator never applies the reference config because the system works without it. Every device on their LAN can publish commands to fly the drone.
- **Severity of the gap:** High. This is the most likely real-world failure mode. Security configurations that are optional are security configurations that do not exist.
- **Suggested hardening:**
  1. **The bridge should verify MQTT authentication is enforced at startup.** On connect, the bridge should attempt a second MQTT connection with invalid credentials. If this connection succeeds, the broker is not enforcing authentication. The bridge should log a critical warning and refuse to accept flight commands (telemetry-only mode).
  2. **The bridge add-on should ship a Mosquitto configuration as part of its installation process**, not as a reference document. If the bridge runs on HAOS with the official Mosquitto add-on, the bridge installer/documentation should include a setup script that configures Mosquitto.
  3. **At minimum, the bridge should refuse to connect on port 1883 (plaintext).** Hardcode TLS-only (port 8883) as the default, with plaintext as a developer-only override that requires an explicit `mqtt_allow_plaintext: true` flag in the config.

#### 10.3.2 ACL Bypass from Inside Docker

- **Resolution being tested:** ATK-MQTT-01 ACL
- **Gap found:** The HAOS Mosquitto add-on and the bridge add-on run as Docker containers on the same Docker host. Docker containers on the same Docker network can communicate directly. The Mosquitto ACL enforces per-user topic restrictions, and the ACL is enforced at the Mosquitto broker level regardless of the client's network origin. However:
  1. If any other HA add-on is compromised and that add-on has MQTT credentials (many HA add-ons use MQTT), the attacker inherits that add-on's MQTT permissions.
  2. The HAOS Mosquitto add-on creates a default `addons` user that many add-ons use. If this default user exists and has broad permissions, a compromised add-on can publish to drone command topics.
- **Severity of the gap:** Medium. The ACL is sound IF no other MQTT users have write access to drone topics. The gap is that the HAOS ecosystem encourages shared MQTT infrastructure where multiple add-ons share the broker.
- **Suggested hardening:**
  1. **Audit all MQTT users and their ACL permissions.** Ensure no user other than `ha_user` can write to `drone_hass/+/command/#` topics.
  2. **Do not use the HAOS default MQTT credentials for any add-on.** Each add-on that needs MQTT should have its own user with minimal permissions.
  3. **Consider running a dedicated Mosquitto instance for drone operations**, separate from the HA ecosystem's general-purpose MQTT broker. This isolates drone MQTT from all other HA MQTT traffic.

#### 10.3.3 MQTT over WebSocket

- **Resolution being tested:** ATK-MQTT-01 (no WebSocket listener mentioned)
- **Gap found:** The reference Mosquitto config does not include a WebSocket listener, which is correct. However, go2rtc, Node-RED, and other HA ecosystem components sometimes expose MQTT-over-WebSocket endpoints. If the operator installs any component that bridges MQTT to WebSocket, the ACLs may be bypassed because the WebSocket bridge authenticates to Mosquitto with its own credentials and then proxies messages from unauthenticated WebSocket clients.
- **Severity of the gap:** Low. This is a deployment-specific risk, not a flaw in the resolution. But it should be documented.
- **Suggested hardening:** Add a note to the deployment checklist: "Verify no component exposes MQTT over WebSocket. If WebSocket MQTT is needed (e.g., for a dashboard), ensure it has its own ACL-restricted user with read-only access to drone topics."

### 10.4 The Operator-as-Threat Problem

#### 10.4.1 Is Tamper-Evidence Actually Effective?

- **Resolution being tested:** Section 9.5's overall compliance chain
- **Gap found:** The resolution acknowledges that the system is tamper-evident, not tamper-proof. But would tamper-evidence actually be detected in practice?
  - An FAA inspector reviewing a Part 108 application receives a JSON export of the compliance database with a "chain verification: PASSED" summary. The inspector does not have the tools or expertise to independently verify Ed25519 signatures, trace hash chains, or query S3 Object Lock retention policies.
  - The "export with verification" (Layer 11) includes a chain verification summary. But this summary is generated by the same bridge code the operator controls. A modified bridge can generate a "PASSED" summary for a fabricated chain.
  - Independent verification requires the inspector to run the `verify_chain` tool against the raw database. This tool is part of the open-source project. The inspector would need to download the tool, obtain the database and the public key, and run the verification themselves.
- **Attack scenario:** Operator submits a Part 108 application with a fabricated compliance history. The export JSON says "chain verification: PASSED." The FAA inspector has no reason to doubt it. The fabrication succeeds because no one performs independent verification.
- **Severity of the gap:** High in practice, even though the technical controls are sound. The effectiveness of tamper-evidence depends on someone actually checking. If no one checks, tamper-evidence provides zero security benefit.
- **Suggested hardening:**
  1. **Provide a standalone, independently downloadable verification tool.** This tool should be simple to run (single binary, no dependencies) and produce a clear PASS/FAIL with details. The FAA or any auditor should be able to verify without installing the full drone_hass stack.
  2. **The export format should include the raw public key** so an auditor can verify signatures without needing access to the bridge's filesystem.
  3. **Document what an auditor should check** in a simple, non-technical guide: (a) run verify_chain, (b) compare key fingerprint against the operator's registered fingerprint, (c) check S3 Object Lock retention policy, (d) cross-reference flight records against FAA Remote ID database.
  4. **Consider publishing chain head hashes to a public, timestamped ledger** (RFC 3161 TSA, or a transparency log similar to Certificate Transparency). This creates an independent, operator-uncontrollable proof that the chain existed at a specific time with a specific state. This is the strongest technical mitigation against retroactive chain fabrication.

#### 10.4.2 Minimum Skill Level to Defeat the Compliance Chain

- **Resolution being tested:** All compliance resolutions collectively
- **Gap found:** The resolution raises the bar but does not quantify it. Here is a realistic skill assessment:

| Attack | Skill Required | Time Required | Detection Difficulty |
|--------|---------------|---------------|---------------------|
| Delete local DB (no Litestream) | Novice (rm command) | 1 minute | Obvious (no DB) |
| Delete local DB + S3 replica (no Object Lock) | Intermediate (AWS CLI) | 5 minutes | Detectable (S3 access logs) |
| Delete local DB, S3 Object Lock active | Impossible during retention | N/A | N/A |
| Fabricate records via modified bridge | Advanced (Python, understands schema) | 4-8 hours | Undetectable without Remote ID cross-reference |
| Fabricate records + spoof SITL detection | Expert (compile custom ArduPilot SITL) | 8-16 hours | Undetectable without Remote ID cross-reference |
| Close AWS account to destroy S3 data | Novice (web UI) | 5 minutes | Detectable (90-day grace period, AWS CloudTrail) |

- **Key insight:** The fabrication attack (modified bridge) is the most dangerous because it is undetectable by the system itself. Only external correlation (Remote ID, which is controlled by the FAA, not the operator) can detect it. This makes Remote ID cross-referencing the single most important verification mechanism for a Part 108 application review.
- **Suggested hardening:** The project documentation should explicitly state: "For Part 108 application review, the FAA should cross-reference compliance flight records against the FAA Remote ID database. Any flight in the compliance database that does not have a corresponding Remote ID track should be flagged for investigation."

#### 10.4.3 The "Open-Source Code is Auditable" Argument

- **Resolution being tested:** Section 9.5 ("Mitigation: open-source code is auditable")
- **Gap found:** This argument has three weaknesses:
  1. **The operator does not have to run the published code.** They can run a locally modified version. No one checks.
  2. **Even if the code is auditable, no one audits it.** The FAA does not have the staff or expertise to review Python code for every Part 108 applicant's drone system.
  3. **The audit surface is large.** The bridge codebase, plus MAVSDK-Python, plus aiomqtt, plus grpcio, plus the compliance recorder, plus Litestream -- auditing all of this for correctness is a significant undertaking.
- **Severity of the gap:** Medium. The argument is not wrong -- open source IS more auditable than closed source. But "auditable" is not "audited." The argument provides defense-in-depth, not a security guarantee.
- **Suggested hardening:** Do not rely on this argument as a primary control. Treat it as a supporting factor. The primary controls should be: (a) S3 Object Lock for immutability, (b) Remote ID for independent corroboration, (c) reproducible builds for code integrity verification. The "open-source is auditable" argument is a nice-to-have, not a load-bearing defense.

### 10.5 Network Isolation

#### 10.5.1 VLAN Isolation is a Deployment Requirement, Not Software-Enforced

- **Resolution being tested:** R-03, ATK-LAT-02 resolution (VLAN isolation)
- **Gap found:** The VLAN design in the resolution is solid. Three VLANs, strict inter-VLAN firewall rules, no internet for the drone VLAN. The problem is identical to the MQTT ACL problem: this is a reference architecture, not enforced by the software. The realistic deployment scenario for a home user is a flat network where the drone RPi, the HA server, the operator's laptop, IoT devices, and guest devices are all on the same subnet.
- **Attack scenario on a flat network:**
  1. A compromised IoT device (smart bulb, cheap camera) on the same LAN scans for open ports and finds Mosquitto on 1883 (if plaintext is enabled) or the drone RPi's SSH on 22.
  2. The IoT device publishes MQTT commands to fly the drone. If MQTT auth is not configured (see 10.3.1), this succeeds.
  3. Even with MQTT auth, the IoT device can attempt to connect to the RPi's SSH (if password auth is enabled with a weak password) and inject MAVLink commands directly to the FC via the companion computer.
- **Severity of the gap:** High in realistic deployments. VLAN isolation is the single most impactful defense for this system, and it is the one most likely to be absent in practice.
- **Suggested hardening:**
  1. **The bridge should detect its own network environment at startup.** Check whether it can reach common home LAN IPs (e.g., the default gateway, common IoT subnets). If it can reach devices that are not in the expected VLAN topology, log a warning: "Network isolation not detected. The bridge can reach devices outside the expected drone/HA VLAN. This significantly increases the attack surface."
  2. **Make the deployment guide's VLAN section impossible to skip.** Mark it as a mandatory pre-flight checklist item, not an optional hardening step. The bridge could require a `network_isolation_acknowledged: true` flag in its config that the operator must set after configuring VLANs (or explicitly accepting the risk of a flat network).
  3. **For flat-network deployments, the software-level controls (MQTT auth + ACL, MAVLink signing, bridge ComplianceGate) must be treated as the primary defense, not defense-in-depth.** The resolution assumes VLAN isolation exists and treats MQTT ACLs as a secondary layer. For flat networks, the layering inverts: MQTT ACLs and MAVLink signing are the only things standing between an attacker and the drone.

#### 10.5.2 Home LAN to HA VLAN Access

- **Resolution being tested:** ATK-LAT-02 VLAN firewall rules
- **Gap found:** The VLAN rules allow `VLAN 1 -> VLAN 10: only 8123/tcp (HA UI), 8883/tcp (MQTT for debugging if needed)`. The HA UI on 8123 provides full admin access to the system (if the attacker has HA credentials). The MQTT port 8883 being allowed from the home LAN "for debugging" undermines the MQTT ACL isolation -- it allows any home LAN device to attempt MQTT connections. Even if authentication is enforced, it expands the attack surface from "VLAN 10 only" to "VLAN 1 + VLAN 10."
- **Severity of the gap:** Low-Medium. MQTT auth + TLS should prevent unauthorized access regardless. But exposing 8883 from the home LAN for "debugging" is the kind of temporary exception that becomes permanent.
- **Suggested hardening:** Remove the 8883 allow rule from VLAN 1 -> VLAN 10 in the reference architecture. Debugging should be done from a device on VLAN 10 (e.g., SSH into the HA server and use `mosquitto_pub` locally). If MQTT access from the home LAN is genuinely needed, it should use a read-only MQTT user with no access to drone command topics.

### 10.6 Resolutions Assessed as Solid

The following resolutions were pressure-tested and found to have no meaningful gaps beyond those already documented as accepted residual risks:

1. **ATK-MAV-02 (Replay Attack) resolution:** MAVLink v2 signing with monotonic timestamps correctly prevents replay. The 48-bit timestamp provides ~8,900 years of unique values. No gap found.

2. **ATK-MAV-05 (SiK Radio) resolution:** AES-128 on SiK plus MAVLink signing provides two layers. AES-128 is computationally secure against the threat class (hobbyist attacker with SDR). No gap found.

3. **ATK-MQTT-02 (Mission Poisoning) resolution:** Moving the operational area to a bridge-local file and implementing a mission allowlist eliminates the MQTT-based attack vector for geofence modification. Solid.

4. **ATK-MQTT-03 (Compliance Event Injection) resolution:** Restricting authorization events to `bridge_internal` source only is correct. The bridge rejects external writes to safety-critical record types. Solid.

5. **ATK-MQTT-05 (State Topic Spoofing) resolution:** Bridge ComplianceGate reading from internal state objects rather than MQTT topics is the correct architecture. The ACL preventing non-bridge publish to state topics adds defense-in-depth. Solid.

6. **ATK-HA-02 (Push Notification Spoofing) resolution:** The cryptographic nonce-based challenge-response is well-designed. The nonce is generated by the bridge, sent only to the RPIC's phone via push notification, and validated on return. An attacker cannot forge the nonce without access to the phone. Solid.

7. **ATK-FW-01 (Parameter Tampering) resolution:** Continuous 30-second parameter re-reads with airborne RTL on mismatch is a strong control. Combined with MAVLink signing preventing unauthorized writes, this is well-mitigated. Solid.

8. **ATK-DOS-01 (Battery Exhaustion) resolution:** Cooldown timer + escalating battery thresholds + max patrols per day is practical and effective. The adversarial pattern detection alert is a good addition. Solid.

9. **ATK-DOCK-01 (ESPHome) resolution:** API encryption key + local-only interlocks + hardware smoke relay is defense-in-depth done correctly. The hardware relay being independent of software is the key positive finding. Solid.

### 10.7 Summary of Gaps Found

| ID | Gap | Severity | Resolution Affected | Status |
|----|-----|----------|-------------------|--------|
| GAP-01 | Modified bridge can sign false records; undetectable without Remote ID | High | ATK-COMP-04, Section 9.5 | Inherent limitation; mitigate with reproducible builds + Remote ID cross-reference |
| GAP-02 | Key fingerprint registration is procedural, not enforced; depends on S3 Object Lock | Medium | ATK-COMP-01 | Document dependency explicitly |
| GAP-03 | Litestream replication gap exploitable by stopping Litestream before flight | Medium-High | ATK-COMP-02, Layer 6 | Bridge must monitor Litestream health continuously and block flights if replication stalls |
| GAP-04 | Litestream + S3 Object Lock interaction untested (GC vs retention conflict) | Medium | ATK-COMP-02, R-07 | Requires empirical testing and documentation |
| GAP-05 | AWS account closure destroys S3 Object Lock data after 90 days | Medium | ATK-COMP-02, Layer 7 | Replicate to operator-uncontrolled storage; Remote ID is the backstop |
| GAP-06 | Daily heartbeat is self-referential; fabricated chain includes fabricated heartbeats | Low | Layer 5 | Include external entropy (RFC 3161 TSA, Bitcoin block hash) |
| GAP-07 | SITL detection defeatable by custom ArduPilot build with spoofed UID | Medium | ATK-COMP-04, Layer 9 | Remote ID cross-reference is the only reliable detection |
| GAP-08 | MQTT ACL is a reference config, not enforced by software | High | ATK-MQTT-01 | Bridge should verify auth enforcement at startup |
| GAP-09 | VLAN isolation is a deployment requirement, not enforced | High | R-03, ATK-LAT-02 | Bridge should detect and warn about flat-network deployment |
| GAP-10 | Compliance tamper-evidence only works if someone checks | High | Section 9.5, Layer 11 | Provide standalone verifier + auditor guide + public chain hash publication |
| GAP-11 | "Open-source is auditable" is not "audited" | Medium | Section 9.5 | Treat as supporting factor, not primary control |
| GAP-12 | Firmware update can erase MAVLink signing key; recovery procedure not documented | Medium | ATK-MAV-01 | Document re-keying procedure; prohibit network-based re-keying |
| GAP-13 | Home LAN MQTT access "for debugging" weakens VLAN isolation | Low-Medium | ATK-LAT-02 VLAN rules | Remove MQTT allow from home LAN VLAN rules |

### 10.8 Top Three Recommendations from Red Team Validation

These are the highest-impact, most practical improvements that address the largest gaps:

1. **Bridge must actively verify its security posture at startup (addresses GAP-08, GAP-09).** The bridge should perform three self-checks on every startup: (a) attempt an unauthenticated MQTT connection -- if it succeeds, refuse to accept flight commands; (b) check whether it can reach IPs outside the expected VLAN -- if it can, log a network isolation warning; (c) verify Litestream is actively replicating -- if it is not, refuse Part 108 operations. These checks convert "reference architecture" controls into software-enforced controls.

2. **Continuous Litestream health monitoring with flight-blocking (addresses GAP-03).** The bridge must monitor Litestream replication lag in real time, not just at startup. If replication stalls for more than N seconds (configurable, default 10), the bridge should refuse new flight commands and log a compliance event. This closes the "stop Litestream before a risky flight" attack vector. Litestream should run as an independent process the bridge cannot control.

3. **Standalone compliance chain verifier + auditor documentation (addresses GAP-10).** Build a single-binary verification tool (Go or Rust for portability, no Python dependencies) that takes a compliance database export and a public key as input and outputs a detailed verification report. Write a non-technical auditor's guide explaining what to verify and how to cross-reference with Remote ID data. Without this, the entire 11-layer compliance chain is security theater -- technically sound but never actually checked.

---

*End of Red Team Validation.*

---

## 11. Gap Resolutions (UA + HA Expert Consensus)

All 13 gaps reviewed by both domain experts. Consensus reached on all items.

### GAP-01: Modified Bridge Fabrication
**Status: Accept as residual risk with mitigations.**
- Inject container image digest at build time via Dockerfile `ARG`/`LABEL` (not `/proc/self/cgroup`). Bridge logs its own image digest as a compliance record at startup.
- Auditors can verify digest matches a published, reproducible release.
- **Remote ID cross-referencing is THE primary verification for Part 108 reviews**, not the compliance chain. The chain proves safety posture (DAA active, personnel authorized); Remote ID proves flights occurred.
- Document this framing explicitly in the compliance export and auditor guide.

### GAP-02: Key Fingerprint Registration Depends on S3 Object Lock
**Status: Adopted.**
- Document the dependency explicitly: key fingerprint registration is only meaningful WITH immutable off-device storage.
- Bridge writes key fingerprint as compliance record #1 in the chain, ensuring it is captured in the earliest Litestream replica.

### GAP-03: Litestream Replication Gap
**Status: Adopted (continuous lag check, flight-blocking).**
- Bridge monitors Litestream replication lag continuously (check S3 for most recent object timestamp, or poll Litestream metrics).
- If replication lag exceeds 5 seconds, bridge refuses to arm the aircraft and logs `replication_stalled` compliance event.
- Litestream runs as a separate add-on on HAOS (bridge cannot stop or reconfigure it).
- This closes the "stop Litestream before a risky flight" attack vector.

### GAP-04: Litestream + S3 Object Lock Interaction
**Status: Adopted (disable Litestream GC).**
- Set `retention: 0` in Litestream config (disable its own garbage collection entirely).
- Let S3 lifecycle policies handle storage management.
- Budget for unbounded S3 storage growth (pennies/month at this data volume).
- Test this interaction empirically before deployment and document findings.
- Add bridge health check that verifies recent S3 object timestamps.

### GAP-05: AWS Account Closure Destroys S3 Data
**Status: Accept as residual risk.**
- 90-day grace period gives investigators time for preservation orders.
- Remote ID provides independent, operator-uncontrollable flight records.
- AWS CloudTrail logs account closure events.
- If the FAA knows the operator's bucket ARN (from Permit application) and the bucket disappears, that is itself evidence of tampering.
- Third-party compliance escrow is out of scope for a residential system.

### GAP-06: Daily Heartbeat Self-Referential
**Status: Adopted (RFC 3161 TSA).**
- Daily heartbeat hashes the chain head and submits it to an RFC 3161 Timestamp Authority (e.g., FreeTSA.org).
- The signed timestamp token is stored as part of the heartbeat record.
- This provides an external, cryptographically verifiable proof that the chain existed at a specific time.
- No Bitcoin or blockchain dependency — RFC 3161 is standards-based and auditor-verifiable.

### GAP-07: SITL Detection Defeatable
**Status: Adopted (document honestly).**
- Existing SITL detection (UID, firmware string, GPS) remains as a low-bar check against accidental SITL-in-production.
- It is NOT a security boundary — a competent operator can compile custom SITL with spoofed UIDs.
- **Remote ID cross-referencing is the only reliable detection for fabricated flights.** Document this explicitly.
- Compliance export format should include enough data (timestamps, GPS tracks, aircraft serial) for efficient FAA cross-referencing against the Remote ID database.

### GAP-08: MQTT ACL Not Enforced by Software
**Status: Adopted (startup probe).**
- On startup, bridge attempts a second MQTT connection with invalid credentials (user `__probe__`, password `invalid`, 2-3 second timeout).
- If the connection succeeds, broker is not enforcing authentication. Bridge logs critical compliance event and drops to telemetry-only mode (no flight commands accepted).
- Bridge defaults to port 8883 (TLS). Plaintext on 1883 requires explicit `mqtt_allow_plaintext: true` flag.
- Probe runs before bridge advertises readiness.

### GAP-09: VLAN Isolation Not Enforced
**Status: Adopted (subnet check + acknowledgment flag).**
- Bridge checks whether its own IP is in the expected VLAN subnet (configurable: `expected_subnet: 10.10.10.0/24`).
- If IP is outside the configured range, log a network isolation warning.
- Optionally: attempt to reach default gateway's LAN-side admin UI — if reachable, inter-VLAN routing is too permissive.
- Require `network_isolation_acknowledged: true` in bridge config. Operator must explicitly accept the risk of flat-network deployment.
- Documentation must state clearly: on flat networks, MQTT auth + ACL + MAVLink signing are the primary defense, not defense-in-depth.

### GAP-10: Tamper-Evidence Never Checked
**Status: Adopted (standalone verifier + auditor guide + RFC 3161).**
- Build a standalone verification binary in Go (single binary, zero dependencies, cross-platform).
- Input: compliance database export (JSON) + public key file.
- Output: detailed PASS/FAIL report with record counts, timestamp range, signature verification, and chain integrity.
- Public key is embedded in the export format so auditors need only the export file.
- Write a 2-page plain-language auditor guide: (a) run verify tool, (b) compare key fingerprint, (c) check S3 Object Lock, (d) cross-reference flights against FAA Remote ID database.
- Daily heartbeat includes RFC 3161 timestamp token (GAP-06) providing independent time proof.

### GAP-11: "Open-Source is Auditable" Overstated
**Status: Adopted (downgrade to supporting factor).**
- Remove as a primary mitigation. Treat as supporting evidence only.
- The concrete control is: reproducible builds with image digest logging. Auditors verify the digest matches a published release.
- This follows the HA add-on trust model (source repo + build status + published image).

### GAP-12: Firmware Update Erases Signing Key
**Status: Adopted (detection + documentation).**
- Bridge detects signing key loss by monitoring for `COMMAND_ACK` failures or unsigned heartbeats from the FC.
- On detection: critical alert, block all flights, log compliance event with old/new firmware versions.
- Re-keying requires physical USB access. No network-based re-keying capability.
- Setup documentation includes pre-upgrade checklist warning about "erase all" and its effect on the signing key.

### GAP-13: Home LAN MQTT Access for Debugging
**Status: Adopted (remove from reference architecture).**
- Remove the 8883 allow rule from VLAN 1 → VLAN 10 in reference firewall rules.
- MQTT debugging is done by SSH into the HA host and using `mosquitto_sub`/`mosquitto_pub` locally.
- If remote MQTT access is genuinely needed for development, use a read-only user with ACL denying all writes to `drone_hass/+/command/#`.
- Document as development-only with isolation warning.

---

## 12. Updated Compliance Data Integrity Chain

After gap resolutions, the complete integrity chain is:

| Layer | Control | Proves | Gap Status |
|-------|---------|--------|------------|
| 1 | Append-only SQLite (application enforcement) | Records not modified after creation | No gap |
| 2 | SHA-256 hash chain | No records removed or altered mid-chain | No gap |
| 3 | Ed25519 signatures per record | Records written by this specific bridge instance | GAP-01: accepted residual (operator can modify bridge code) |
| 4 | Key fingerprint as record #1 + external registration | Key existed at install time | GAP-02: depends on Layer 7 (documented) |
| 5 | Daily heartbeat with RFC 3161 timestamp | Chain was intact at each heartbeat; externally verifiable time proof | GAP-06: resolved (RFC 3161 TSA) |
| 6 | Litestream continuous replication with health monitoring | Records exist off-device; flights blocked if replication stalls | GAP-03: resolved (continuous lag check) |
| 7 | S3 Object Lock (COMPLIANCE mode, 5-year retention) | Records cannot be deleted during retention | GAP-05: accepted residual (account closure) |
| 8 | Chain verification on startup + daily | Detects any tampering or corruption | No gap |
| 9 | SITL detection (low-bar, not security boundary) | Simulation records flagged | GAP-07: accepted (Remote ID is primary) |
| 10 | Remote ID correlation (FAA-controlled, operator-uncontrollable) | Flights actually occurred | THE primary verification mechanism |
| 11 | Standalone verifier + auditor guide + export with embedded public key | Third party can independently verify | GAP-10: resolved |
| 12 | Reproducible builds with image digest logging | Code integrity at runtime | GAP-01/11: partial (supports, not primary) |
| 13 | Bridge startup self-checks (MQTT auth, network, Litestream) | Deployment configuration is sound | GAP-08/09: resolved |

**What this system proves to a Part 108 reviewer:**
1. The system's safety posture during every flight (DAA active, weather checked, personnel authorized, geofence enforced) — via the signed, hash-chained, replicated compliance chain
2. Flights actually occurred — via FAA Remote ID cross-referencing (external, operator-uncontrollable)
3. The chain has not been tampered with — via the standalone verifier with RFC 3161 time proofs
4. The system was running published code — via container image digest verification

**What this system cannot prove:** That the operator did not fabricate records using modified bridge code. This is the fundamental limitation of self-hosted compliance and is documented rather than glossed over.

---

*End of threat model, resolutions, red team validation, and gap resolutions. The compliance integrity chain is the most rigorous open-source UAS compliance framework documented to date. Its primary limitation is inherent to self-hosted systems, not to the architecture.*
