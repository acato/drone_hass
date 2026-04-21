# Threat Resolutions: MAVLink / ArduPilot / Flight Controller / Compliance Domain

> Companion to: threat-model.md Section 9

---

## Critical Resolutions (Must-Fix Before Deployment)

### ATK-MAV-01 / ATK-MAV-04: MAVLink Command Injection / Rogue GCS

**Threat Summary:**
- ATK-MAV-01: Attacker within WiFi range sends crafted MAVLink UDP packets to port 14540 or 14550, issuing unauthorized commands (arm, takeoff, mission upload).
- ATK-MAV-04: Rogue GCS connects to FC via MAVLink UDP. ArduPilot accepts multiple GCS connections by default, allowing parameter tampering and mission manipulation.
- **Severity:** Critical

**Resolution: Enable MAVLink v2 message signing**

MAVLink v2 message signing is the primary defense against both command injection and rogue GCS attacks. All MAVLink packets will include SHA-256 HMAC authentication and monotonic timestamp.

#### Implementation Steps

1. **Generate signing key at bridge first install**
   - Use cryptographically secure random generation (Python `secrets.token_bytes(32)`)
   - Store at `/data/compliance/mavlink_signing.key`, permissions `0600` (read-only by bridge process)
   - Protect with file ownership (bridge user, no read permission for others)

2. **Initial key exchange via USB serial (not WiFi)**
   - USB connection is direct, no MITM risk
   - Use pymavlink `setup_signing()` to transfer key to flight controller
   - ArduPilot persists key in EEPROM (non-volatile storage)
   - Verify key acceptance before bringing up WiFi link

3. **Bridge MAVLink Configuration**
   - Use pymavlink `setup_signing(key, allow_unsigned=False)`
   - All subsequent MAVLink messages automatically include:
     - 256-bit SHA-256 HMAC computed over message payload
     - 48-bit monotonically increasing timestamp
   - Configure unsigned packet handling: silently drop without logging (do not leak timing information)

4. **Flight Controller Configuration**
   - Set `SYSID_MYGCS = 245` (bridge system ID) via MAVLink parameter write
   - This restricts certain behaviors to system ID 245 (note: ArduPilot enforcement is partial; network isolation is the primary control)
   - FC only accepts signed messages from SYSID_MYGCS

5. **Network-level Firewall Rules**
   - iptables DROP rule: block inbound UDP 14540/14550 from all sources except bridge container's network namespace
   - Bind MAVSDK connection to specific companion computer IP, never `0.0.0.0`
   - Example iptables rule (pseudocode):
     ```
     iptables -I INPUT -p udp --dport 14540 ! -s <companion_ip> -j DROP
     iptables -I INPUT -p udp --dport 14550 ! -s <companion_ip> -j DROP
     ```

6. **VLAN Isolation**
   - Place drone WiFi on dedicated VLAN with strict firewall rules
   - Enable WiFi client isolation: prevent communication between WiFi clients, only client-to-AP
   - Bridge container is the only allowed host on drone VLAN
   - No other LAN devices can associate with drone VLAN

#### Required ArduPilot Parameters

| Parameter | Value | Purpose |
|-----------|-------|---------|
| `SYSID_MYGCS` | 245 | Bridge system ID — FC restricts command acceptance to this ID |
| `MAV_SYSTEM_ID` | Configured at build time | FC's own system ID (typically 1 for aircraft) |
| (Signing key) | 32-byte key in EEPROM | Generated and persisted via setup_signing(); not exposed as parameter |

#### Code Reference (Bridge Side)

```python
from pymavlink import mavutil

# Generate key on first install
import secrets
signing_key = secrets.token_bytes(32)
with open('/data/compliance/mavlink_signing.key', 'wb') as f:
    f.write(signing_key)
os.chmod('/data/compliance/mavlink_signing.key', 0o600)

# Setup signing on connection
connection = mavutil.mavlink_connection('udp:<companion_ip>:14540', source_system=245)
connection.setup_signing(signing_key, sign_outgoing=True, allow_unsigned_rxcsum=False)

# All subsequent outbound messages are automatically signed
connection.mav.param_set_send(target_system=1, target_component=1,
                              param_id='SYSID_MYGCS', param_value=245,
                              param_type=mavutil.mavlink.MAV_PARAM_TYPE_INT32)
```

#### Defence-in-depth: drop unsigned safety-critical messages

ArduPilot 4.x AP_Signing accepts certain MAVLink messages **unsigned by default**, including `SYSTEM_TIME` (#2) — to allow clock injection from a fresh GCS that has not yet exchanged the signing key. That default is unsafe for drone_hass: an injector on VLAN 20 can skew the FC RTC, breaking compliance timestamps and MAVLink replay protection. The same exposure exists for several other safety-critical messages.

The bridge enforces signed-only on the full safety-critical set at the MAVLink layer via pymavlink's `signing.allow_unsigned_callback`. Any unsigned packet on the drop list is rejected before it reaches the FC, logged as a compliance event, and incremented on a Prometheus counter so silent drops cannot hide a sustained attack.

```python
# Apply on BOTH the SiK primary and the WiFi secondary connection. SiK trust
# is a defence-in-depth assumption, not a guarantee — Holybro SiK v3 firmware
# has had AES key-recovery CVEs.

UNSIGNED_DROP_MSGIDS = {
    # Time / sync — clock-skew attacks
    mavutil.mavlink.MAVLINK_MSG_ID_SYSTEM_TIME,                  # 2
    mavutil.mavlink.MAVLINK_MSG_ID_TIMESYNC,                     # 111

    # Authentication / signing handshake — never accept unsigned
    mavutil.mavlink.MAVLINK_MSG_ID_AUTH_KEY,                     # 7
    mavutil.mavlink.MAVLINK_MSG_ID_SETUP_SIGNING,                # 256

    # GCS hijack family
    mavutil.mavlink.MAVLINK_MSG_ID_CHANGE_OPERATOR_CONTROL,      # 5
    mavutil.mavlink.MAVLINK_MSG_ID_CHANGE_OPERATOR_CONTROL_ACK,  # 6

    # Parameter writes / reads — pre-empt the param-monitor RTL (ATK-FW-01)
    mavutil.mavlink.MAVLINK_MSG_ID_PARAM_SET,                    # 23
    mavutil.mavlink.MAVLINK_MSG_ID_PARAM_REQUEST_READ,           # 20

    # EKF / home position — silent geofence bypass via origin shift
    mavutil.mavlink.MAVLINK_MSG_ID_SET_GPS_GLOBAL_ORIGIN,        # 48
    mavutil.mavlink.MAVLINK_MSG_ID_SET_HOME_POSITION,            # 179

    # GPS / RTK — corrects EKF position; injection = drift attack
    mavutil.mavlink.MAVLINK_MSG_ID_GPS_RTCM_DATA,                # 233

    # Mission family — bridge owns this path; defence-in-depth
    mavutil.mavlink.MAVLINK_MSG_ID_MISSION_COUNT,                # 44
    mavutil.mavlink.MAVLINK_MSG_ID_MISSION_ITEM,                 # 39
    mavutil.mavlink.MAVLINK_MSG_ID_MISSION_ITEM_INT,             # 73
    mavutil.mavlink.MAVLINK_MSG_ID_MISSION_CLEAR_ALL,            # 45
    mavutil.mavlink.MAVLINK_MSG_ID_MISSION_SET_CURRENT,          # 41

    # Commands — COMMAND_ACK gates execution but unsigned COMMAND_LONG can
    # still flood the queue (DoS) before the bridge sees it
    mavutil.mavlink.MAVLINK_MSG_ID_COMMAND_LONG,                 # 76
    mavutil.mavlink.MAVLINK_MSG_ID_COMMAND_INT,                  # 75

    # Mode / RC override — arming-equivalent
    mavutil.mavlink.MAVLINK_MSG_ID_SET_MODE,                     # 11
    mavutil.mavlink.MAVLINK_MSG_ID_RC_CHANNELS_OVERRIDE,         # 70

    # Telemetry rate control — re-routes streams
    mavutil.mavlink.MAVLINK_MSG_ID_MESSAGE_INTERVAL,             # 511
}

UNSIGNED_DROP_COUNTER = Counter(
    'drone_hass_unsigned_dropped_total',
    'Unsigned safety-critical MAVLink packets dropped',
    ['msgid', 'link'],                                           # link = sik|wifi
)

def install_unsigned_filter(connection, link_name):
    """Reject any unsigned packet whose msgid is on the drop list. Fail-closed
    on parse errors. Returns True to allow, False to drop."""
    def allow_unsigned_callback(self, msgId):
        if msgId in UNSIGNED_DROP_MSGIDS:
            UNSIGNED_DROP_COUNTER.labels(msgid=msgId, link=link_name).inc()
            log.warning("Dropping unsigned safety-critical msgid=%d on link=%s",
                        msgId, link_name)
            emit_compliance_event(
                type='unsigned_msg_dropped',
                msgid=msgId, link=link_name,
                source='bridge_internal',
            )
            return False                                         # drop
        return True                                              # allow non-safety unsigned
    connection.mav.signing.allow_unsigned_callback = allow_unsigned_callback

# Install on both transports.
install_unsigned_filter(sik_connection, link_name='sik')
install_unsigned_filter(wifi_connection, link_name='wifi')
```

**Operational note:** if the FC SYSTEM_TIME is genuinely cold (RTC battery dead, post-reboot at 1980-01-01), the *first* SYSTEM_TIME push from the companion will arrive before MAVLink signing has been mutually established. The bridge handles this by sending the initial SYSTEM_TIME via a direct serial bootstrap on the companion (out-of-band from the broker) before the SiK link is brought up. After signing is live, all SYSTEM_TIME on either link must be signed.

#### Residual Risk

- Physical access to the FC via USB allows re-keying (attacker directly reprograms EEPROM)
- **Controls:** Dock physical lock + tamper sensor + access logs

---

### ATK-COMP-01: Ed25519 Signing Key Extraction

**Threat Summary:**
- Attacker with access to bridge storage (HA backup, compromised machine) extracts the Ed25519 private key
- Used to sign fabricated compliance records with valid signatures
- Records appear authentic in the compliance database
- **Severity:** Critical

**Resolution:** see `resolutions-ha.md` Recommendation R-08 (Ed25519 Key Protection) — authoritative implementation. Earlier revisions of this section described a plaintext-PEM design that accepted "key in HA backups" as residual risk; that design has been superseded.

**Summary of the current design** (full detail in R-08):

- Ed25519 seed material is wrapped with **scrypt + AES-256-GCM** (memory-hard KDF, AEAD with `drone_id` in AAD) before it ever touches disk.
- Two storage modes: `tpm_sealed` (default if TPM 2.0 present) auto-unseals on boot via a TPM-sealed KEK bound to PCR 7; `passphrase_only` prompts via Ingress on every restart.
- Backup blob is always passphrase-wrapped (TPM seal is host-bound, never backed up). Stolen backup faces scrypt N=2^17 — defeats GPU/ASIC bruteforce.
- Operator passphrase enforced via zxcvbn (min 16 chars, score ≥ 3, breach-corpus check); failed-unseal lockout (3 attempts × exponential backoff); compliance events on every unseal success/failure.
- Genesis fingerprint recorded out-of-band (paper, password manager, attorney email) for chain anchor verification.
- Litestream replication to Object-Lock S3 (3-yr COMPLIANCE retention) plus MinIO secondary.
- Chain verification on startup AND daily (Ed25519 + SHA-256 hash chain + OpenTimestamps proof walk).
- Recovery tool `unwrap_signing_key.py` ships standalone for off-bridge restore.

**Residual risk:** the operator controls deployment, so a modified bridge codebase could write false records with valid signatures. Self-hosted compliance is **tamper-evident**, not tamper-proof. Mitigated by Apache 2.0 source auditability, cosign-verified images at install (R-27), opportunistic Remote ID corroboration (contemporaneous RF broadcast that cooperative third-party receivers or DiSCVR law-enforcement access may capture; no routine public flight-history lookup exists), and OpenTimestamps anchoring of the chain to public block-time (a forward-dating attack cannot produce an OTS proof claiming an earlier block-time than the calendar server actually issued).

---

### ATK-MQTT-01: Unauthenticated MQTT Command Injection

**Threat Summary:**
- Default Mosquitto config allows unauthenticated access on port 1883
- Any device on LAN can publish to command topics
- Bridge executes commands without verifying source
- **Severity:** Critical

**Resolution: Enforce authentication, TLS, and topic-level ACLs**

#### Mosquitto Configuration (Reference Implementation)

Ship a production-ready Mosquitto configuration file:

```mosquitto
# /etc/mosquitto/conf.d/drone_hass.conf
# Reference configuration for drone_hass MQTT broker

# Listener: TLS only, no plaintext
listener 8883
protocol mqtt
tls_version tlsv1.3
cafile /etc/mosquitto/certs/ca.crt
certfile /etc/mosquitto/certs/server.crt
keyfile /etc/mosquitto/certs/server.key
require_certificate false

# Disable default listener (plaintext)
listener 1883
protocol mqtt
# Optional: comment out or set to false to disable
# Recommended: disable entirely for production
allow_anonymous false

# Global security settings
allow_anonymous false
password_file /etc/mosquitto/passwd
acl_file /etc/mosquitto/acl.conf

# Rate limiting and resource constraints
max_inflight_messages 20
max_connections 10
message_size_limit 65536

# Logging
log_dest file /var/log/mosquitto/mosquitto.log
log_dest syslog
log_type all
log_timestamp true
```

#### Access Control List (ACL) Configuration

```acl
# /etc/mosquitto/acl.conf
# Topic-level access control for drone_hass

# Bridge user: publishes telemetry, state, DAA, compliance; reads commands and missions
user bridge_user
topic write drone_hass/+/telemetry/#
topic write drone_hass/+/state/#
topic write drone_hass/+/daa/#
topic write drone_hass/+/compliance/#
topic write drone_hass/+/command/+/response
topic read drone_hass/+/command/#
topic read drone_hass/+/missions/#

# HA user: publishes commands and missions; reads all topics
user ha_user
topic write drone_hass/+/command/#
topic write drone_hass/+/missions/#
topic read drone_hass/#

# Deny all others (default: implicit deny)
```

#### Credentials Setup

```bash
# Generate password file with bcrypt hashing
mosquitto_passwd -c -b /etc/mosquitto/passwd bridge_user <bridge_password>
mosquitto_passwd -b /etc/mosquitto/passwd ha_user <ha_password>

# Set strict permissions
chmod 600 /etc/mosquitto/passwd
chmod 600 /etc/mosquitto/acl.conf
```

#### Bridge MQTT Client Configuration

```python
import paho.mqtt.client as mqtt

# Bridge connects with TLS and authentication
client = mqtt.Client(client_id='bridge_drone_hass_01')
client.username_pw_set('bridge_user', password='<bridge_password>')

# TLS configuration
client.tls_set(
    ca_certs='/etc/mosquitto/certs/ca.crt',
    certfile=None,  # Mutual TLS not required, credentials are sufficient
    keyfile=None,
    cert_reqs=mqtt.ssl.CERT_REQUIRED,
    tls_version=mqtt.ssl.PROTOCOL_TLSv1_3,
    ciphers=None
)

# Connect to broker
client.connect('mosquitto.local', 8883, keepalive=60)

# Subscribe to command topics (read-only)
client.subscribe('drone_hass/+/command/#', qos=1)

# Publish telemetry (write-only)
client.publish('drone_hass/drone_01/telemetry/gps', payload, qos=1)
```

#### HA Configuration Example

Home Assistant MQTT integration with authentication:

```yaml
mqtt:
  broker: mosquitto.local
  port: 8883
  protocol: 3.1.1
  username: ha_user
  password: !secret mqtt_ha_password
  tls_insecure: false
  keepalive: 60
```

#### Deployment Verification

Ship a verification script to check Mosquitto configuration:

```bash
#!/bin/bash
# verify_mqtt.sh - Check MQTT broker security configuration

MOSQUITTO_CONF="/etc/mosquitto/conf.d/drone_hass.conf"
PASSWD_FILE="/etc/mosquitto/passwd"
ACL_FILE="/etc/mosquitto/acl.conf"

echo "Verifying Mosquitto configuration..."

# Check TLS listener
if grep -q "listener 8883" "$MOSQUITTO_CONF"; then
    echo "[OK] TLS listener on port 8883"
else
    echo "[FAIL] TLS listener not configured"
    exit 1
fi

# Check plaintext disabled
if grep -q "allow_anonymous false" "$MOSQUITTO_CONF"; then
    echo "[OK] Anonymous access disabled"
else
    echo "[FAIL] Anonymous access is enabled"
    exit 1
fi

# Check password file
if [ -f "$PASSWD_FILE" ]; then
    echo "[OK] Password file exists"
    if [ $(stat -f%A "$PASSWD_FILE" 2>/dev/null || stat -c%a "$PASSWD_FILE") = "600" ]; then
        echo "[OK] Password file permissions: 600"
    else
        echo "[FAIL] Password file permissions too open"
        exit 1
    fi
else
    echo "[FAIL] Password file not found"
    exit 1
fi

# Check ACL file
if [ -f "$ACL_FILE" ]; then
    echo "[OK] ACL file exists"
    if grep -q "user bridge_user" "$ACL_FILE" && grep -q "user ha_user" "$ACL_FILE"; then
        echo "[OK] ACL users defined"
    else
        echo "[FAIL] ACL users not defined"
        exit 1
    fi
else
    echo "[FAIL] ACL file not found"
    exit 1
fi

echo "All checks passed."
```

#### Residual Risk

- ACL enforcement depends on Mosquitto configuration being applied and maintained correctly
- If operator misconfigures ACLs or disables authentication, attacks are possible
- **Control:** Ship and run deployment verification script during setup

---

## High Resolutions (Must-Fix Before Part 108)

### ATK-MAV-02: MAVLink Replay Attack

**Threat Summary:**
- Attacker captures legitimate MAVLink packets (arm, takeoff, mission upload) via WiFi sniffer
- Later replays same packets to trigger same action multiple times
- **Severity:** High

**Resolution:** MAVLink v2 signing with timestamp validation

MAVLink v2 message signing includes a monotonically increasing 48-bit timestamp. The FC rejects messages with older or duplicate timestamps, preventing replay attacks.

#### Implementation Details

The timestamp mechanism in MAVLink v2 signing:
- Each signed message includes a 48-bit timestamp (incrementing)
- FC maintains a record of the last accepted timestamp from each sender
- Incoming message timestamp must be > last accepted timestamp
- Timestamp window: typical implementation accepts ±30 seconds (configurable)
- If timestamp is out of window or goes backwards: message silently dropped

This is automatically enforced by pymavlink `setup_signing()` and ArduPilot firmware. No additional bridge code needed.

#### Verification

Test replay protection:
1. Connect bridge to FC with signing enabled
2. Send valid signed arm command, verify FC arms
3. Replay same packet from WiFi capture: FC rejects silently (no arm occurs)
4. Send new signed arm command: FC accepts (timestamp has advanced)

---

### ATK-MAV-05: SiK 915 MHz Radio Eavesdropping (PRIMARY C2)

**Threat Summary:**
- SiK radios transmit MAVLink in the clear on 915 MHz ISM band by default
- Attacker with SDR ($25-$300) can receive telemetry and, with a transmit-capable SDR, inject commands
- **Severity: HIGH** — after the C2 inversion (architecture.md §6.3), SiK is the *primary* safety link, not a backup. AES-128 + MAVLink v2 signing is mandatory; failure to enable either is a flight-blocker, not a hardening recommendation.

**Resolution:** Enable SiK AES-128 encryption *and* MAVLink v2 signing on the SiK serial endpoint. The bridge refuses to arm if either is unconfigured at startup.

#### SiK Radio Configuration

SiK firmware supports AES-128 encryption and Net ID configuration. Configure via AT commands on both air and ground radios:

```
# AT Command Configuration (SiK firmware v2.x)
# Configure via serial terminal at 57600 baud

# Enable encryption
ATS15=1

# Configure shared encryption key (must be identical on both radios)
# Key format: 32 hex digits (128 bits)
ATS16=0x0102030405060708090A0B0C0D0E0F10

# Change Net ID from default (change ATS11 from default 25 to random value)
ATS11=42

# Verify configuration
ATI7
```

#### Bridge Integration

The SiK ground module is plugged into the bridge host's USB (`/dev/ttyUSB0`). Per architecture.md §6.3 the radio module lives indoors with LMR-400 to an outdoor antenna on the eave. SiK is the primary MAVLink path — there is no failover *to* SiK; the WiFi-secondary path is opportunistic for video and debugging only.

```python
import serial

# Open SiK radio serial link — primary C2.
sik_serial = serial.Serial(
    port='/dev/ttyUSB0',
    baudrate=57600,
    timeout=1.0,
)
sik_connection = mavutil.mavlink_connection(f'serial:{sik_serial.port}:{sik_serial.baudrate}')

# MAVLink v2 signing on the primary path is MANDATORY.
sik_connection.setup_signing(signing_key, sign_outgoing=True, allow_unsigned_rxcsum=False)

# Optional opportunistic WiFi MAVLink for ground-station GUIs only. The bridge
# does not promote this path to safety-critical; ComplianceGate reads SiK
# telemetry only.
wifi_connection = mavutil.mavlink_connection('udp:0.0.0.0:14550')   # opportunistic
wifi_connection.setup_signing(signing_key, sign_outgoing=True, allow_unsigned_rxcsum=False)

active_connection = sik_connection                                  # always SiK for safety path
```

#### Required SiK Parameters

| Parameter | Value | Purpose |
|-----------|-------|---------|
| `ATS15` | 1 | Enable AES-128 encryption |
| `ATS16` | 0x0102... | 128-bit encryption key (must match both radios) |
| `ATS11` | 42 (or other non-default) | Net ID (change from default 25) |

#### Residual Risk

- SiK is the **primary** safety C2 link; WiFi is the secondary video path with no safety responsibility (architecture.md §6.3).
- AES-128 + MAVLink v2 signing raises the eavesdropping/injection bar substantially but does not produce link characterisation evidence. A documented link-budget test (RSSI/SNR vs distance over the operational area, with foliage in leaf and out, and during rain) is required for Part 108 means-of-compliance evidence.
- Future hardening: a Microhard pDDL2450 (~$3-4k) provides AES-256 + characterised throughput and is the upgrade path if SiK's range/throughput envelope or Part 108 final-rule means-of-compliance demands it.

---

### ATK-FW-01: ArduPilot Parameter Tampering

**Threat Summary:**
- Attacker with MAVLink access modifies critical parameters
- Disable geofence: `FENCE_ENABLE=0`
- Disable ADS-B avoidance: `AVD_ENABLE=0`
- Disable GCS failsafe: `FS_GCS_ENABLE=0`
- Change RTL altitude to dangerous value: `RTL_ALT=30000` (300m instead of safe value 50m), or to a value below the 30 m tree canopy
- **Severity:** High

**Resolution:** Continuous parameter monitoring and verification

#### Implementation

Bridge maintains a safety parameter baseline and monitors for unauthorized changes:

```python
# Expected safety parameters (configured at first setup or per deployment)
SAFETY_PARAMETERS = {
    'FENCE_ENABLE': 1,        # Geofence enabled
    'FENCE_TYPE': 7,          # Circle + Polygon boundaries
    'AVD_ENABLE': 1,          # ADS-B avoidance enabled
    'FS_GCS_ENABLE': 2,       # Continue mission to next safe waypoint then RTL.
                              # Tuned for SiK 915 MHz primary C2 (FHSS dwell + retry
                              # variance); FS_GCS_ENABLE=1 was tuned for low-jitter WiFi
                              # primary and false-triggered RTL on normal SiK fades.
    'FS_GCS_TIMEOUT': 15,     # 15 s tolerance — matches SiK link characterisation.
    'RTL_ALT': 50,            # Return to 50m AGL (20 m margin over 30 m tree canopy)
    'FENCE_ALT_MAX': 60,      # Firmware fence ceiling (5 m above operational ceiling)
    'WP_RADIUS': 500,         # Waypoint acceptance radius (cm)
    'FS_EKF_ACTION': 1,       # RTL on EKF failure
    'FS_BATT_ENABLE': 1,      # Battery failsafe enabled
}

class ParameterMonitor:
    def __init__(self, connection, safety_params):
        self.connection = connection
        self.safety_params = safety_params
        self.last_check = {}
        
    def verify_at_startup(self):
        """Read and verify all safety parameters at startup"""
        for param_name, expected_value in self.safety_params.items():
            # Read parameter from FC
            msg = self.connection.recv_match(type='PARAM_VALUE', blocking=True, timeout=5)
            actual_value = msg.param_value
            
            if actual_value != expected_value:
                raise RuntimeError(
                    f"Parameter mismatch at startup: {param_name}="
                    f"{actual_value} (expected {expected_value}). "
                    f"Cannot proceed with flight."
                )
        log.info("All safety parameters verified at startup")
    
    def monitor_continuously(self, interval_sec=30):
        """Periodically re-read parameters; mismatch while airborne triggers RTL"""
        while True:
            time.sleep(interval_sec)
            
            # Check if drone is armed
            try:
                heartbeat = self.connection.recv_match(type='HEARTBEAT', blocking=False)
                is_armed = heartbeat.base_mode & mavutil.mavlink.MAV_MODE_FLAG_ARMED_ARMED
            except:
                continue
            
            # Re-read critical parameters
            for param_name in ['FENCE_ENABLE', 'AVD_ENABLE', 'FS_GCS_ENABLE', 'RTL_ALT', 'FENCE_ALT_MAX']:
                msg = self.connection.recv_match(type='PARAM_VALUE', blocking=False, timeout=2)
                if not msg:
                    continue
                    
                expected = self.safety_params[param_name]
                if msg.param_value != expected:
                    log.critical(
                        f"Parameter tampering detected: {param_name}="
                        f"{msg.param_value} (expected {expected})"
                    )
                    
                    if is_armed:
                        # Trigger RTL immediately via COMMAND_LONG with ACK retry.
                        # Note: pymavlink's MAV_MODE_RTL constant does not exist;
                        # set_mode(MAV_MODE_RTL) would raise AttributeError and
                        # leave the airframe in AUTO. Use MAV_CMD_NAV_RTL.
                        log.critical("Drone armed during tampering. Executing RTL.")
                        self._send_command_with_ack(
                            mavutil.mavlink.MAV_CMD_NAV_RETURN_TO_LAUNCH,
                            0, 0, 0, 0, 0, 0, 0,    # params 1-7 unused
                        )
                    else:
                        # Block launch
                        log.critical("Blocking launch due to parameter tampering.")
                        raise SecurityViolation("Safety parameters compromised")

    def _send_command_with_ack(self, command_id, *params,
                               timeout_s=1.0, retries=3):
        """COMMAND_LONG send with ACK verification and bounded retry.

        Safe to call with blocking=True because the parameter monitor runs in
        its own daemon thread (see thread setup at the bottom of this section).
        Asyncio callers must wrap this in `loop.run_in_executor()`.
        """
        for attempt in range(retries):
            self.connection.mav.command_long_send(
                self.connection.target_system,
                self.connection.target_component,
                command_id,
                attempt,                # confirmation = attempt count
                *params,
            )
            ack = self.connection.recv_match(
                type='COMMAND_ACK', blocking=True, timeout=timeout_s
            )
            if ack and ack.command == command_id:
                if ack.result == mavutil.mavlink.MAV_RESULT_ACCEPTED:
                    return True
                if ack.result != mavutil.mavlink.MAV_RESULT_TEMPORARILY_REJECTED:
                    raise CommandRejected(f"cmd {command_id} -> {ack.result}")
        raise CommandTimeout(f"cmd {command_id} no ACK after {retries} tries")

# Instantiate and run monitor
monitor = ParameterMonitor(mavlink_connection, SAFETY_PARAMETERS)
monitor.verify_at_startup()

# Start continuous monitor in background thread
import threading
monitor_thread = threading.Thread(target=monitor.monitor_continuously, daemon=True)
monitor_thread.start()
```

#### Required ArduPilot Parameters

| Parameter | Min Value | Max Value | Default | Purpose |
|-----------|-----------|-----------|---------|---------|
| `FENCE_ENABLE` | 0 | 1 | 0 (disabled by default) | **Must = 1** to enforce geofence |
| `FENCE_TYPE` | 0 | 7 | 0 | **Should = 7** (circle + polygon boundaries) |
| `AVD_ENABLE` | 0 | 1 | 0 | **Must = 1** to enable ADS-B avoidance |
| `FS_GCS_ENABLE` | 0 | 5 | 0 | **= 2** (continue then RTL) — SiK 915 MHz primary C2 has higher latency variance than WiFi; `=1` (immediate RTL) false-triggers on normal FHSS fades |
| `FS_GCS_TIMEOUT` | 1 | 30 | 5 (s) | **= 15** s — matches SiK link characterisation, prevents nuisance RTL from add-on container scheduling jitter |
| `RTL_ALT` | 0 | 32767 (cm) | 1500 (15m) | **= 5000** (50m AGL — 20 m margin over 30 m tree canopy) |
| `FENCE_ALT_MAX` | 1000 | 32767 (cm) | 10000 (100m) | **= 6000** (60m — 5 m above operational ceiling, see architecture.md §11.3 altitude invariant) |
| `WP_RADIUS` | 0 | 32767 (cm) | 200 (2m) | Waypoint acceptance radius |
| `FS_EKF_ACTION` | 0 | 2 | 0 | **Should = 1** (RTL on EKF failure) |
| `FS_BATT_ENABLE` | 0 | 2 | 0 | **Must = 1 or 2** (battery failsafe) |

#### Startup Checklist

Bridge refuses to arm if any safety parameter is incorrect. Example startup sequence:

```
[Bridge Startup]
[PARAM] Reading safety parameters...
[PARAM] FENCE_ENABLE = 1 ✓
[PARAM] FENCE_TYPE = 7 ✓
[PARAM] AVD_ENABLE = 1 ✓
[PARAM] FS_GCS_ENABLE = 2 ✓
[PARAM] FS_GCS_TIMEOUT = 15 ✓
[PARAM] RTL_ALT = 50 ✓
[PARAM] FENCE_ALT_MAX = 60 ✓
[PARAM] Altitude invariant (tree_max < RTL_ALT < ceiling < FENCE_ALT_MAX): OK
[PARAM] All checks passed
[MONITOR] Starting continuous parameter monitor (interval=30s)
[READY] Ready for flight
```

---

### ATK-FW-02: Firmware Replacement

**Threat Summary:**
- Attacker with MAVLink/physical access flashes modified ArduPilot firmware
- Removes geofence enforcement, disables failsafes, adds backdoor commands
- **Severity:** High

**Resolution:** Firmware integrity verification and comparison

#### Implementation

Bridge reads and logs firmware version at every startup:

```python
def verify_firmware(connection):
    """Read and verify ArduPilot firmware integrity"""
    
    # Request AUTOPILOT_VERSION message
    msg = connection.recv_match(type='AUTOPILOT_VERSION', blocking=True, timeout=5)
    
    # Extract firmware information
    firmware_version = msg.fw_version
    fw_git_hash = msg.flight_sw_git_hash  # Git commit hash
    board_uid = msg.board_uid  # Unique board serial number (128-bit)
    
    # Log as compliance record
    fw_record = {
        'type': 'firmware_verification',
        'timestamp': datetime.utcnow().isoformat(),
        'firmware_version': f"{firmware_version >> 24}.{(firmware_version >> 16) & 0xFF}.{(firmware_version >> 8) & 0xFF}",
        'git_hash': fw_git_hash.hex() if isinstance(fw_git_hash, bytes) else fw_git_hash,
        'board_uid': board_uid.hex() if isinstance(board_uid, bytes) else board_uid,
    }
    
    # Compare against stored baseline
    stored_baseline = db.system_config.find_one({'type': 'firmware_baseline'})
    
    if stored_baseline is None:
        # First run: establish baseline
        log.info(f"Establishing firmware baseline: {fw_record['git_hash']}")
        db.system_config.insert_one({
            'type': 'firmware_baseline',
            'firmware_version': fw_record['firmware_version'],
            'git_hash': fw_record['git_hash'],
            'board_uid': fw_record['board_uid'],
            'established_at': datetime.utcnow().isoformat()
        })
        db.compliance_records.insert_one(fw_record)
    else:
        # Subsequent runs: compare
        if fw_record['git_hash'] != stored_baseline['git_hash']:
            log.critical(
                f"Firmware mismatch detected:\n"
                f"  Expected: {stored_baseline['git_hash']}\n"
                f"  Actual: {fw_record['git_hash']}\n"
                f"  Cannot proceed with flight."
            )
            db.compliance_records.insert_one({
                **fw_record,
                'verification_result': 'FAILED',
                'reason': f"Git hash mismatch (expected {stored_baseline['git_hash']})"
            })
            raise SecurityViolation("Firmware integrity check failed")
        elif fw_record['board_uid'] != stored_baseline['board_uid']:
            log.warning(
                f"Board UID changed. Was the flight controller replaced?\n"
                f"  Previous: {stored_baseline['board_uid']}\n"
                f"  Current: {fw_record['board_uid']}"
            )
            # Update baseline (board replacement is acceptable with operator acknowledgment)
            db.system_config.update_one(
                {'type': 'firmware_baseline'},
                {'$set': {'board_uid': fw_record['board_uid']}}
            )
        
        log.info(f"Firmware verification passed: {fw_record['git_hash']}")
        db.compliance_records.insert_one({**fw_record, 'verification_result': 'OK'})
    
    return fw_record
```

#### ArduPilot Version Information

The `AUTOPILOT_VERSION` MAVLink message provides:

| Field | Type | Purpose |
|-------|------|---------|
| `fw_version` | uint32 | Firmware version (major.minor.patch.type encoded) |
| `flight_sw_git_hash` | uint32 array (4 x uint32) | Git commit hash (128-bit) |
| `board_uid` | uint64 array (2 x uint64) | Unique board serial number (128-bit) |
| `fw_git_hash` | uint32 array (4 x uint32) | Duplicate of flight_sw_git_hash |

#### Companion Computer (RPi) Hardening

Per requirement R-04, harden the RPi running the companion computer:

```bash
#!/bin/bash
# hardening.sh - Harden Raspberry Pi for drone operations

# SSH hardening
echo "Configuring SSH..."
sudo sed -i 's/#PermitRootLogin yes/PermitRootLogin no/' /etc/ssh/sshd_config
sudo sed -i 's/#PubkeyAuthentication yes/PubkeyAuthentication yes/' /etc/ssh/sshd_config
sudo sed -i 's/PasswordAuthentication yes/PasswordAuthentication no/' /etc/ssh/sshd_config
sudo systemctl restart ssh

# Remove default user (pi)
echo "Removing default user..."
sudo userdel -r pi  # WARNING: if you logged in as 'pi', create new user first!

# Minimal services
echo "Disabling unnecessary services..."
sudo systemctl disable bluetooth
sudo systemctl disable avahi-daemon
sudo systemctl disable cups

# Automatic security updates
echo "Setting up unattended-upgrades..."
sudo apt-get install -y unattended-upgrades
sudo dpkg-reconfigure -plow unattended-upgrades

# Firewall
echo "Configuring firewall..."
sudo apt-get install -y ufw
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow 22/tcp  # SSH only
sudo ufw allow from 192.168.100.0/24 to any port 14540  # MAVLink from companion
sudo ufw enable

# Disable internet access for companion computer
# (Implement at network layer via WiFi AP isolation)

echo "RPi hardening complete"
```

#### Startup Verification Sequence

```
[Bridge Startup]
[FC] Requesting AUTOPILOT_VERSION...
[FC] Firmware: ArduCopter 4.4.0 (git: abc123def456)
[FC] Board UID: deadbeefcafebabe0102030405060708
[SECURITY] Comparing against baseline...
[SECURITY] Firmware signature verified ✓
[SECURITY] Board UID matches ✓
[COMPLIANCE] Firmware verification record logged
[READY] Flight controller firmware verified
```

---

### ATK-COMP-02: Compliance Database Deletion

**Threat Summary:**
- Attacker deletes local compliance database to erase flight records
- Bridge has no backup, records are lost permanently
- Attacker covers up unauthorized flights
- **Severity:** High

**Resolution:** Mandatory Litestream replication with immutable storage

#### Implementation

Litestream continuously replicates the compliance SQLite database to off-device storage (S3, GCS, NAS).

1. **Litestream Configuration**

```yaml
# /data/litestream.yml
dbs:
  - path: /data/compliance/compliance.db
    replicas:
      - type: s3
        bucket: drone-hass-compliance-backups
        path: compliance/compliance.db
        region: us-east-1
        access-key-id: $LITESTREAM_S3_KEY_ID
        secret-access-key: $LITESTREAM_S3_SECRET_KEY
        retention: 2160h  # 90 days local, replicate all
        sync-interval: 5s  # Sync every 5 seconds
```

2. **S3 Bucket Configuration (WORM with Object Lock)**

```bash
# Create S3 bucket with Object Lock enabled
aws s3api create-bucket \
  --bucket drone-hass-compliance-backups \
  --region us-east-1 \
  --object-lock-enabled-for-bucket

# Enable COMPLIANCE mode (cannot be overridden by bucket owner)
aws s3api put-object-lock-configuration \
  --bucket drone-hass-compliance-backups \
  --object-lock-configuration '{
    "ObjectLockEnabled": "Enabled",
    "Rule": {
      "DefaultRetention": {
        "Mode": "COMPLIANCE",
        "Years": 5
      }
    }
  }'

# Block public access
aws s3api put-public-access-block \
  --bucket drone-hass-compliance-backups \
  --public-access-block-configuration \
  "BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true"
```

3. **Bridge Startup Verification**

```python
def check_litestream_status():
    """Verify Litestream replication is active"""
    
    if OPERATION_MODE == "PART_108":
        # Part 108 requires active replication
        status = subprocess.run(['litestream', 'status'], capture_output=True, text=True)
        
        if status.returncode != 0:
            raise RuntimeError("Litestream not running. Part 108 mode requires active replication.")
        
        # Check replication status
        if 'Connected' not in status.stdout:
            raise RuntimeError("Litestream replication not connected. Cannot proceed with Part 108.")
        
        log.info("Litestream replication verified")
    elif OPERATION_MODE == "PART_107":
        # Part 107 can run without replication but logs warning
        status = subprocess.run(['litestream', 'status'], capture_output=True, text=True)
        if status.returncode != 0 or 'Connected' not in status.stdout:
            log.warning("Litestream replication not active. Compliance data at risk.")
```

4. **Chain Continuity Check on Startup**

```python
def verify_chain_continuity():
    """
    If local DB is empty but replica has records:
    attacker deleted local DB and we can recover from replica.
    Log critical anomaly and restore.
    """
    
    local_count = db.compliance_records.count_documents({})
    
    # Check replica
    try:
        replica_backup = s3_client.get_object(
            Bucket='drone-hass-compliance-backups',
            Key='compliance/compliance.db'
        )
        import tempfile
        with tempfile.NamedTemporaryFile(suffix='.db') as f:
            f.write(replica_backup['Body'].read())
            f.flush()
            
            replica_db = sqlite3.connect(f.name)
            replica_count = replica_db.execute(
                'SELECT COUNT(*) FROM compliance_records'
            ).fetchone()[0]
            
            if local_count == 0 and replica_count > 0:
                log.critical(
                    f"CHAIN CONTINUITY ALERT: Local DB is empty but replica has "
                    f"{replica_count} records. Possible deletion attack detected. "
                    f"Restoring from replica..."
                )
                # Restore from backup
                shutil.copy(f.name, db_path)
                log.info("Database restored from replica")
                
                # Log anomaly as compliance record
                db.compliance_records.insert_one({
                    'type': 'chain_continuity_check',
                    'status': 'ANOMALY_DETECTED_AND_RECOVERED',
                    'local_records_before_restore': 0,
                    'replica_records': replica_count,
                    'restored_at': datetime.utcnow().isoformat(),
                    'source': 'bridge_internal'
                })
    except Exception as e:
        log.error(f"Chain continuity check failed: {e}")
        if OPERATION_MODE == "PART_108":
            raise RuntimeError("Part 108 requires successful chain continuity check")
```

#### S3 Object Lock Behavior

- **COMPLIANCE mode:** No expiration change allowed, even by bucket owner
- Retention period: 5 years from object creation
- Operator cannot delete records during 5-year window
- Even if operator's AWS credentials are compromised, attacker cannot delete
- Emergency delete requires: write to separate "immutable deletion ledger" + wait for retention period

#### Residual Risk

- Litestream must be configured and running correctly
- S3 credentials must be protected (enable MFA, use IAM roles)
- **Control:** Startup verification + monitoring + automated alerts

---

### ATK-COMP-04: Compliance Record Fabrication

**Threat Summary:**
- Operator (or malicious bridge code) writes false compliance records
- Records are signed with valid key and pass hash chain verification
- False records submitted to FAA for Part 108 authorization
- **Severity:** High

**Resolution:** Distinguish SITL from live records with hardware identifiers

#### Implementation

Every compliance record includes a `flight_source` field indicating whether the flight was real or simulated:

```python
def detect_flight_source(mavlink_connection):
    """
    Detect whether FC is running SITL (simulator) or live hardware.
    SITL: AUTOPILOT_VERSION.uid = 0
    Live: AUTOPILOT_VERSION.uid = non-zero unique board ID
    """
    
    msg = mavlink_connection.recv_match(type='AUTOPILOT_VERSION', blocking=True, timeout=5)
    
    # Extract hardware identifiers
    board_uid = msg.board_uid  # 128-bit unique board ID
    fw_version_str = f"{msg.fw_version >> 24}.{(msg.fw_version >> 16) & 0xFF}"
    
    # SITL has board_uid = 0
    if board_uid == 0 or board_uid is None:
        return 'sitl_simulation'
    
    # Check firmware string for SITL
    if 'SITL' in msg.flight_sw_version:
        return 'sitl_simulation'
    
    # Live flight controller
    return 'live_aircraft'

def add_flight_source_to_record(record, flight_source):
    """Add flight_source field to every compliance record"""
    record['flight_source'] = flight_source  # live_aircraft or sitl_simulation
    return record

# At compliance record creation time
flight_source = detect_flight_source(mavlink_connection)
record = {
    'type': 'flight_record',
    'timestamp': datetime.utcnow().isoformat(),
    'gps_position': gps_position,
    'altitude': altitude,
    'battery_voltage': battery_voltage,
    'flight_source': flight_source,  # <-- NEW
    # ... other fields
}
db.compliance_records.insert_one(record)
```

#### Export Filtering for FAA Submission

When generating compliance data for Part 108 Permit application:

```python
def export_compliance_for_permit(start_date, end_date, flight_source_filter='live_aircraft'):
    """
    Export compliance records for FAA submission.
    Filter to live_aircraft records only (exclude SITL).
    """
    
    query = {
        'timestamp': {'$gte': start_date, '$lte': end_date},
        'flight_source': flight_source_filter,  # live_aircraft only
        'type': {'$in': ['flight_record', 'authorization_record', 'personnel_record']}
    }
    
    records = list(db.compliance_records.find(query).sort('timestamp', 1))
    
    # Verify chain integrity before export
    verify_chain(records)
    
    # Export as JSON with verification summary
    export_data = {
        'export_date': datetime.utcnow().isoformat(),
        'period': {'start': start_date, 'end': end_date},
        'filter': {'flight_source': flight_source_filter},
        'record_count': len(records),
        'records': records,
        'verification_summary': {
            'chain_verified': True,
            'all_signatures_valid': True,
            'sitl_records_excluded': True,
        }
    }
    
    return json.dumps(export_data, indent=2)
```

#### Remote ID Corroboration (opportunistic, not a routine lookup)

Remote ID broadcasts during flight are **contemporaneous RF emissions**. Any receiver in range — FAA-operated infrastructure, cooperative third-party listeners (dronescanner-class apps, amateur observers), or DiSCVR for authorised law enforcement — can log them independently of the bridge. **The FAA does not expose a public flight-history database** that routine operators or third-party auditors can query; DiSCVR is restricted to law enforcement, and the FAA's public DOC system covers equipment declarations (not flight records). So Remote ID corroboration is:

- **Opportunistic** — depends on a receiver being in RF range during the claimed flight window
- **Law-enforcement-accessible** via DiSCVR in the context of a specific investigation
- **NOT a routine audit mechanism** — do not assume an auditor can simply query the FAA for matching tracks

Where Remote ID log data *is* obtainable (via a cooperative receiver network the operator or a third party has deployed, or via law enforcement), the correlation logic below is still useful:

```python
def correlate_with_remote_id(compliance_record, remote_id_track):
    """
    Compare compliance record position against a Remote ID track, when such a
    track is available from an independent receiver. Not a routine FAA lookup.
    Position mismatch indicates possible record falsification.
    """

    compliance_pos = (compliance_record['gps_lat'], compliance_record['gps_lon'])
    remote_id_pos = (remote_id_track['lat'], remote_id_track['lon'])

    distance_m = haversine(compliance_pos, remote_id_pos)

    if distance_m > 50:  # >50m discrepancy is suspicious
        log.warning(
            f"Position mismatch between compliance and Remote ID:\n"
            f"  Compliance: {compliance_pos}\n"
            f"  Remote ID: {remote_id_pos}\n"
            f"  Distance: {distance_m}m\n"
            f"  Possible record falsification detected."
        )
        compliance_record['remote_id_corroboration'] = 'MISMATCH'
    else:
        compliance_record['remote_id_corroboration'] = 'OK'
```

#### Residual Risk

- **Fundamental limitation:** A modified bridge codebase can write false records with valid signatures and correct flight_source
- Operator controls both the signing key and the code
- **Mitigation:**
  - Open-source code is auditable by FAA or third-party experts
  - Git history shows all modifications
  - FAA can require running unmodified tagged releases
  - Remote ID corroboration is opportunistic (receiver-coverage-dependent) or enforcement-specific (DiSCVR for law enforcement). Not a guaranteed audit backstop.
  - Regular audits by compliance officer

---

### ATK-FW-03: GPS Spoofing

**Threat Summary:**
- Attacker broadcasts false GPS signals (GPS spoofing attack)
- FC reports incorrect position, altitude
- Drone navigates to attacker's chosen waypoints
- RTL (return-to-launch) may land at wrong location
- **Severity:** Medium (requires specialized equipment and proximity)

**Resolution:** Multi-constellation GNSS + position sanity checks + dual GPS

#### Implementation

```python
def detect_gps_spoofing():
    """
    Implement multi-layered GPS spoofing detection:
    1. Multi-constellation GNSS (GPS + GLONASS + Galileo + BeiDou)
    2. Bridge-side position sanity checks
    3. Dual GPS receivers if hardware supports
    """
    
    # Layer 1: Multi-constellation configuration
    # Set ArduPilot to use multiple GNSS constellations
    # AUTOPILOT_VERSION tells us if dual GPS is available
    
    # Layer 2: Position sanity checks
    def check_position_sanity(current_gps, operational_area_polygon):
        """
        Verify position is within expected bounds and hasn't jumped
        """
        
        # Check if within operational area
        from shapely.geometry import Point, Polygon
        point = Point(current_gps['lat'], current_gps['lon'])
        if not point.within(operational_area_polygon):
            log.warning(f"Position outside operational area: {current_gps}")
            return False
        
        # Check for sudden jumps
        if hasattr(check_position_sanity, 'last_gps'):
            last_gps = check_position_sanity.last_gps
            
            # Haversine distance between last and current
            dist_m = haversine(
                (last_gps['lat'], last_gps['lon']),
                (current_gps['lat'], current_gps['lon'])
            )
            
            # Maximum possible distance in 1 second @ 25 m/s (max drone speed)
            max_dist_m = 25
            
            if dist_m > max_dist_m:
                log.critical(
                    f"Sudden GPS jump detected: {dist_m}m in 1 second. "
                    f"Possible spoofing attack."
                )
                return False
        
        check_position_sanity.last_gps = current_gps
        return True
    
    # Layer 3: Dual GPS comparison (if supported by hardware)
    def compare_dual_gps(gps1, gps2):
        """
        If dual GPS receivers are available, compare them.
        Large discrepancy indicates spoofing on one receiver.
        """
        
        dist_m = haversine(
            (gps1['lat'], gps1['lon']),
            (gps2['lat'], gps2['lon'])
        )
        
        if dist_m > 50:  # >50m discrepancy is suspicious
            log.warning(
                f"Dual GPS discrepancy detected: {dist_m}m apart. "
                f"Possible spoofing on one receiver."
            )
            return False
        return True
```

#### Required ArduPilot Parameters

| Parameter | Value | Purpose |
|-----------|-------|---------|
| `GPS_GNSS_MODE` | 99 | Enable all GNSS constellations (GPS + GLONASS + Galileo + BeiDou) |
| `GPS_PRIMARY` | 0 | Primary GPS device (0 = first receiver) |
| `GPS_TYPE` | 1 | Auto-detect GPS type |
| `GPS_SAVE_CFG` | 1 | Save GPS configuration to device |

#### Bridge Spoofing Detection Logic

```python
# ArduCopter custom_mode IDs (from libraries/AP_Vehicle/AP_Vehicle.h)
COPTER_MODE_ALT_HOLD = 2
COPTER_MODE_BRAKE = 17
CUSTOM_MODE_ENABLED = mavutil.mavlink.MAV_MODE_FLAG_CUSTOM_MODE_ENABLED  # = 1

def handle_suspected_spoofing(is_armed, operational_area):
    """
    GPS spoofing response. Two-stage degradation:

      Stage 1 — BRAKE (custom_mode 17): halts forward motion within ~2 s using
                EKF position. Bounded drift before the spoof can pull the
                aircraft off property.
      Stage 2 — if EKF innovations remain elevated after 2 s, fall back to
                ALT_HOLD (custom_mode 2): abandons horizontal position control
                entirely and holds altitude on baro + IMU only. ALT_HOLD will
                drift with wind. Under Part 107 the VLOS RPIC takes the sticks;
                under Part 108 this is the documented flyaway-risk path.

      Stage 3 — alert RPIC over the existing MQTT push channel for manual
                recovery. We do not auto-descend: NAV_LAND uses the corrupted
                EKF position and would land somewhere unpredictable.

    pymavlink's MAV_MODE_LAND constant does not exist; set_mode(MAV_MODE_LAND)
    would raise AttributeError. Use MAV_CMD_DO_SET_MODE with a custom_mode.
    """
    if not (suspected_spoofing and is_armed):
        return

    log.critical("GPS spoofing suspected. Stage 1: BRAKE.")
    connection.mav.command_long_send(
        connection.target_system, connection.target_component,
        mavutil.mavlink.MAV_CMD_DO_SET_MODE, 0,
        CUSTOM_MODE_ENABLED, COPTER_MODE_BRAKE,
        0, 0, 0, 0, 0,
    )
    connection.recv_match(type='COMMAND_ACK', blocking=True, timeout=1)

    time.sleep(2.0)
    if ekf_innovations_still_bad():     # bridge already monitors EKF_STATUS_REPORT
        log.critical("EKF still degraded. Stage 2: ALT_HOLD (drift expected).")
        connection.mav.command_long_send(
            connection.target_system, connection.target_component,
            mavutil.mavlink.MAV_CMD_DO_SET_MODE, 0,
            CUSTOM_MODE_ENABLED, COPTER_MODE_ALT_HOLD,
            0, 0, 0, 0, 0,
        )
        connection.recv_match(type='COMMAND_ACK', blocking=True, timeout=1)
        action_taken = 'BRAKE_then_ALT_HOLD'
    else:
        action_taken = 'BRAKE'

    # Stage 3: alert RPIC via the existing bridge MQTT publisher (same channel
    # as authorize_flight push notifications). Do NOT spawn a parallel alert
    # path — fragmenting the compliance log loses correlation.
    publish_rpic_alert(
        severity='critical',
        event='gps_spoofing_suspected',
        action_taken=action_taken,
        note='Manual recovery required; aircraft may drift if in ALT_HOLD',
    )

    db.compliance_records.insert_one({
        'type': 'security_event',
        'event': 'gps_spoofing_suspected',
        'action_taken': action_taken,
        'timestamp': datetime.utcnow().isoformat(),
        'source': 'bridge_internal',
    })
```

#### Residual Risk

- Multi-constellation GNSS makes spoofing harder but not impossible (simultaneous spoofing across multiple constellations is difficult but theoretically possible)
- Dual GPS comparison is effective but requires additional hardware
- Bridge position sanity checks depend on accurate operational area definition
- LAND command is safe but prevents controlled return-to-launch

---

## Medium Resolutions

### ATK-FW-03 Extended: GPS Spoofing Detection (Additional Details)

As referenced in Section 9.3 medium resolutions table:

| Threat | Resolution |
|--------|-----------|
| ATK-FW-03: GPS Spoofing | Multi-constellation GNSS (`GPS_GNSS_MODE=99`). Bridge-side position sanity checks. On suspicion: LAND (not RTL — RTL uses GPS). Dual GPS if hardware supports it. |

This is covered in detail above under High Resolutions section (ATK-FW-03).

---

## Complete ArduPilot Parameter Reference

### Safety-Critical Parameters (Must Verify at Startup)

| Parameter | Type | Min | Max | Default | Drone_HASS Value | Purpose | Threat |
|-----------|------|-----|-----|---------|-------------------|---------|--------|
| `FENCE_ENABLE` | uint8 | 0 | 1 | 0 | **1** | Enable geofence enforcement | ATK-MAV-01, ATK-MAV-04, ATK-FW-01 |
| `FENCE_TYPE` | uint8 | 0 | 7 | 0 | **7** | Circle + Polygon boundaries | ATK-MAV-01 |
| `AVD_ENABLE` | uint8 | 0 | 1 | 0 | **1** | Enable ADS-B avoidance | ATK-MAV-04, ATK-FW-01 |
| `FS_GCS_ENABLE` | uint8 | 0 | 5 | 0 | **2** | Continue then RTL on GCS link loss (tuned for SiK 915 MHz primary C2) | ATK-MAV-03, ATK-FW-01 |
| `FS_GCS_TIMEOUT` | uint16 | 1 | 30 | 5 (s) | **15** | GCS link-loss tolerance (matches SiK link characterisation) | ATK-MAV-03, ATK-FW-01 |
| `FS_EKF_ACTION` | uint8 | 0 | 2 | 0 | **1** | RTL on EKF failure | ATK-FW-01 |
| `FS_BATT_ENABLE` | uint8 | 0 | 2 | 0 | **1** | Battery failsafe enabled | ATK-FW-01 |
| `RTL_ALT` | uint16 | 0 | 32767 (cm) | 1500 | **5000** | Return altitude (50m AGL — 20 m above tree canopy) | ATK-FW-01 |
| `FENCE_ALT_MAX` | uint16 | 1000 | 32767 (cm) | 10000 | **6000** | Firmware fence ceiling (60m — 5 m above operational ceiling) | ATK-FW-01 |
| `WP_RADIUS` | uint16 | 0 | 32767 (cm) | 200 | **500** | Waypoint acceptance radius (5m) | ATK-FW-01 |
| `SYSID_MYGCS` | uint8 | 1 | 255 | 255 | **245** | Bridge system ID | ATK-MAV-01, ATK-MAV-04 |

### GPS / Navigation Parameters

| Parameter | Type | Default | Drone_HASS Value | Purpose |
|-----------|------|---------|-------------------|---------|
| `GPS_GNSS_MODE` | uint8 | 0 | **99** | Multi-constellation (GPS + GLONASS + Galileo + BeiDou) |
| `GPS_TYPE` | uint8 | 1 | **1** | Auto-detect GPS |
| `GPS_PRIMARY` | uint8 | 0 | **0** | Primary GPS device |
| `GPS_SAVE_CFG` | uint8 | 1 | **1** | Save GPS config to device |

### SiK Radio Parameters (via AT Commands)

| AT Command | Value | Purpose |
|-----------|-------|---------|
| `ATS15` | 1 | Enable AES-128 encryption |
| `ATS16` | 0x0102030405060708090A0B0C0D0E0F10 | 128-bit encryption key (example) |
| `ATS11` | 42 | Net ID (change from default 25) |

### MAVLink Signing Configuration (Code-based)

| Setting | Value | Purpose |
|---------|-------|---------|
| `signing_key` | 32-byte random | Generated at first install, stored in `/data/compliance/mavlink_signing.key` |
| `sign_outgoing` | true | Bridge signs all outgoing messages |
| `allow_unsigned_rxcsum` | false | FC rejects unsigned messages |
| `timestamp_mode` | monotonic | 48-bit increasing timestamp prevents replay |

---

## Summary Table: UA-Domain Threat Mitigations

| Threat Code | Threat Name | Resolution | Implemented By | ArduPilot Params | Status |
|-------------|------------|-----------|-----------------|-----------------|--------|
| ATK-MAV-01 | MAVLink Command Injection | MAVLink v2 signing + VLAN | Bridge + Network | SYSID_MYGCS=245 | Critical |
| ATK-MAV-02 | MAVLink Replay Attack | v2 signing timestamp | pymavlink | (automatic) | High |
| ATK-MAV-03 | WiFi Deauth (secondary video link only after C2 inversion) | WPA3-SAE; primary C2 unaffected | Network | n/a — C2 unaffected, video degraded only | Low |
| ATK-MAV-04 | Rogue GCS | MAVLink signing + firewall | Bridge + Network | SYSID_MYGCS=245 | Critical |
| ATK-MAV-05 | SiK Eavesdropping | AES-128 encryption | SiK radio config | (AT commands) | High |
| ATK-COMP-01 | Key Extraction | Key fingerprint + Litestream | Bridge + S3 Object Lock | (N/A) | Critical |
| ATK-COMP-02 | Database Deletion | Litestream WORM storage | S3 Object Lock | (N/A) | High |
| ATK-COMP-04 | Record Fabrication | flight_source detection | Bridge code | (N/A) | High |
| ATK-FW-01 | Parameter Tampering | Continuous monitoring | Bridge code | FENCE_ENABLE, AVD_ENABLE, etc. | High |
| ATK-FW-02 | Firmware Replacement | Version verification | Bridge code | (from AUTOPILOT_VERSION) | High |
| ATK-FW-03 | GPS Spoofing | Multi-constellation + checks | Bridge code | GPS_GNSS_MODE=99 | Medium |

---

## Bridge Startup Checklist (Complete)

```
[Bridge Startup Sequence]

1. [CRYPTO] Initializing Ed25519 signing key
   - Load from /data/compliance/keys/signing_key.pem
   - Verify file permissions 0600 ✓
   - Load public key from /data/compliance/keys/signing_key.pub ✓

2. [MAVLINK] Initializing MAVLink connection
   - Signing key from /data/compliance/mavlink_signing.key ✓
   - Setup signing with FC (USB serial first) ✓
   - Configure SYSID_MYGCS = 245 ✓
   - Verify signed packets accepted ✓

3. [PARAMETERS] Verifying critical safety parameters
   - FENCE_ENABLE = 1 ✓
   - FENCE_TYPE = 7 ✓
   - AVD_ENABLE = 1 ✓
   - FS_GCS_ENABLE = 2 ✓
   - FS_GCS_TIMEOUT = 15 ✓
   - FS_EKF_ACTION = 1 ✓
   - FS_BATT_ENABLE = 1 ✓
   - RTL_ALT = 5000 ✓
   - FENCE_ALT_MAX = 6000 ✓
   - Altitude invariant (tree_max < RTL_ALT < ceiling < FENCE_ALT_MAX): OK ✓
   - SYSID_MYGCS = 245 ✓
   - GPS_GNSS_MODE = 99 ✓
   - All checks passed ✓

4. [FIRMWARE] Verifying flight controller firmware
   - Requesting AUTOPILOT_VERSION ✓
   - Firmware: ArduCopter 4.4.0
   - Git hash: abc123def456 ✓
   - Board UID: deadbeefcafebabe0102030405060708 ✓
   - Comparing against baseline... ✓
   - Firmware signature verified ✓

5. [COMPLIANCE] Verifying compliance database
   - Local record count: 1247 ✓
   - Chain verification: passed ✓
   - All signatures valid ✓
   - SITL records: 0 ✓

6. [LITESTREAM] Verifying off-device replication
   - Litestream running: yes ✓
   - S3 connected: yes ✓
   - Last replication: 2 seconds ago ✓
   - S3 Object Lock enabled: COMPLIANCE mode ✓

7. [RADIO] Initializing SiK backup link
   - Serial connection: /dev/ttyUSB0 ✓
   - Encryption enabled (ATS15=1) ✓
   - Net ID: 42 (non-default) ✓
   - MAVLink signing active on SiK ✓

8. [MONITOR] Starting continuous monitors
   - Parameter monitor (interval=30s) ✓
   - Firmware monitor ✓
   - Position sanity checker ✓

[Bridge Ready]
All security checks passed. Ready for flight.
```

---

*End of UA-domain resolutions. Companion file: `docs/resolutions-ha.md` covers MQTT, HA integration, network, Docker, video, and dock resolutions.*
