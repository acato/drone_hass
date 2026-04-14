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

# All subsequent messages are automatically signed
connection.mav.param_set_send(target_system=1, target_component=1, 
                              param_id='SYSID_MYGCS', param_value=245, 
                              param_type=mavutil.mavlink.MAV_PARAM_TYPE_INT32)
```

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

**Resolution: Defense in depth for key management**

This resolution implements multiple layers of key protection, acknowledging that self-hosted systems cannot be tamper-proof.

#### Implementation Steps

1. **Key Generation and Storage**
   - Generate 32-byte Ed25519 private key on first bridge install: `Ed25519PrivateKey.generate()` (from cryptography library)
   - Store at `/data/compliance/keys/signing_key.pem`, permissions `0600` (readable only by bridge)
   - Store public key separately at `/data/compliance/keys/signing_key.pub`, permissions `0644` (world-readable for verification)
   - Format: PEM (PKCS#8) with no encryption (key material itself is the secret)

2. **Key Fingerprint Registration (Proof of Existence)**
   - Compute fingerprint: SHA-256 hash of public key, first 16 hex characters
   - Log as compliance record #1 at first install with type `key_fingerprint_registration`
   - Display in bridge Ingress UI (HA web interface)
   - **Operator Action:** Instructed to record fingerprint externally:
     - Email to self with timestamp
     - Print and sign
     - Notarize with a timestamp authority
     - This creates an external, independent record that the key existed at install time

3. **Backup Warning**
   - Bridge startup logs warning: `"Ed25519 signing key is included in HA backups. Ensure backups are encrypted."`
   - Document in README: "HA backups contain the compliance signing key. Encrypt and store securely."
   - Recommend separate encryption of backup files (e.g., GPG, age)

4. **Mandatory Litestream for Part 108 Mode**
   - Bridge refuses to start in Part 108 mode without active Litestream replication
   - Ensures compliance data has off-device backup before high-consequence operations
   - Startup check:
     ```python
     if OPERATION_MODE == "PART_108":
         if not litestream_active():
             raise RuntimeError("Part 108 requires active Litestream replication")
     ```

5. **Immutable Off-Device Storage (S3 Object Lock)**
   - Litestream replication target: S3 bucket with Object Lock enabled
   - Lock mode: COMPLIANCE (cannot be bypassed even by bucket owner)
   - Retention period: 5 years (covers FAA record-keeping requirement)
   - Even if attacker deletes local DB and removes the key, S3 Object Lock bucket contains immutable records

6. **Chain Verification on Startup**
   - Bridge startup: walk entire compliance record chain
   - Verify each record's Ed25519 signature using public key
   - Verify SHA-256 hash chain (each record includes hash of previous)
   - If any signature fails or hash breaks: log critical anomaly, prevent Part 108 flight
   - Daily verification job: repeat chain check

#### Code Reference (Bridge Side)

```python
from cryptography.hazmat.primitives.asymmetric import ed25519
from cryptography.hazmat.primitives import serialization
import hashlib

# Generate on first install
private_key = ed25519.Ed25519PrivateKey.generate()
private_pem = private_key.private_bytes(
    encoding=serialization.Encoding.PEM,
    format=serialization.PrivateFormat.PKCS8,
    encryption_algorithm=serialization.NoEncryption()
)
with open('/data/compliance/keys/signing_key.pem', 'wb') as f:
    f.write(private_pem)
os.chmod('/data/compliance/keys/signing_key.pem', 0o600)

public_key = private_key.public_key()
public_pem = public_key.public_bytes(
    encoding=serialization.Encoding.PEM,
    format=serialization.PublicFormat.SubjectPublicKeyInfo
)
with open('/data/compliance/keys/signing_key.pub', 'wb') as f:
    f.write(public_pem)

# Fingerprint registration (record #1)
public_key_hash = hashlib.sha256(public_pem).hexdigest()[:16]
fingerprint_record = {
    'type': 'key_fingerprint_registration',
    'fingerprint': public_key_hash,
    'created_at': datetime.utcnow().isoformat(),
    'operator_action_required': 'Record this fingerprint externally (email, print, notarize)'
}
db.compliance_records.insert(fingerprint_record)

# Sign a record
def sign_record(record, private_key):
    record_json = json.dumps(record, separators=(',', ':'), sort_keys=True)
    signature = private_key.sign(record_json.encode())
    record['signature'] = signature.hex()
    return record

# Verify chain on startup
def verify_chain(db, public_key):
    records = db.compliance_records.find().sort('_id', 1)
    prev_hash = None
    for record in records:
        # Verify signature
        record_copy = dict(record)
        signature_hex = record_copy.pop('signature')
        signature = bytes.fromhex(signature_hex)
        record_json = json.dumps(record_copy, separators=(',', ':'), sort_keys=True)
        try:
            public_key.verify(signature, record_json.encode())
        except Exception as e:
            raise IntegrityError(f"Signature verification failed for record {record['_id']}: {e}")
        
        # Verify hash chain
        record_hash = hashlib.sha256(record_json.encode()).hexdigest()
        if prev_hash and record.get('prev_hash') != prev_hash:
            raise IntegrityError(f"Hash chain broken at record {record['_id']}")
        prev_hash = record_hash
```

#### Residual Risk

- **Fundamental limitation:** Operator controls the signing key and deployment environment
- A modified bridge codebase could write false records with valid signatures
- Self-hosted compliance system provides **tamper-evidence**, not tamper-proof protection
- **Mitigation:** 
  - Open-source code is auditable by FAA or third-party auditors
  - Git history shows all modifications
  - FAA can require running unmodified tagged releases
  - Remote ID broadcasts provide independent, operator-uncontrollable corroboration

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

### ATK-MAV-05: SiK 915 MHz Radio Eavesdropping

**Threat Summary:**
- SiK radios transmit MAVLink in the clear on 915 MHz ISM band
- Attacker with SDR ($25-$300) can receive telemetry and inject commands
- **Severity:** Medium (requires specialized equipment, SiK is backup link only)

**Resolution:** Enable SiK AES-128 encryption

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

Configure SiK serial link in bridge code:

```python
import serial

# Open SiK radio serial link
sik_serial = serial.Serial(
    port='/dev/ttyUSB0',  # Companion computer serial port
    baudrate=57600,
    timeout=1.0
)

# Create MAVLink connection over SiK
sik_connection = mavutil.mavlink_connection(f'serial:{sik_serial.port}:{sik_serial.baudrate}')

# Setup signing on SiK link (same key as WiFi)
sik_connection.setup_signing(signing_key, sign_outgoing=True, allow_unsigned_rxcsum=False)

# Failover logic: if WiFi MAVLink heartbeats are lost for >5 seconds, switch to SiK
last_wifi_heartbeat = time.time()
while True:
    # Check WiFi connection health
    wifi_msg = wifi_connection.recv_match(type='HEARTBEAT', blocking=False)
    if wifi_msg:
        last_wifi_heartbeat = time.time()
    
    # Failover to SiK if WiFi is down
    if time.time() - last_wifi_heartbeat > 5.0:
        active_connection = sik_connection
        log.warning("WiFi link lost, switched to SiK radio")
    else:
        active_connection = wifi_connection
```

#### Required SiK Parameters

| Parameter | Value | Purpose |
|-----------|-------|---------|
| `ATS15` | 1 | Enable AES-128 encryption |
| `ATS16` | 0x0102... | 128-bit encryption key (must match both radios) |
| `ATS11` | 42 (or other non-default) | Net ID (change from default 25) |

#### Residual Risk

- SiK link is backup only; primary link is WiFi with signing enabled
- Encryption + MAVLink signing provides defense in depth

---

### ATK-FW-01: ArduPilot Parameter Tampering

**Threat Summary:**
- Attacker with MAVLink access modifies critical parameters
- Disable geofence: `FENCE_ENABLE=0`
- Disable ADS-B avoidance: `AVD_ENABLE=0`
- Disable GCS failsafe: `FS_GCS_ENABLE=0`
- Change RTL altitude to dangerous value: `RTL_ALT=30000` (300m instead of default 35m)
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
    'FS_GCS_ENABLE': 1,       # RTL on GCS link loss
    'RTL_ALT': 35,            # Return to 35m AGL
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
            for param_name in ['FENCE_ENABLE', 'AVD_ENABLE', 'FS_GCS_ENABLE', 'RTL_ALT']:
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
                        # Trigger RTL immediately
                        log.critical("Drone armed during tampering. Executing RTL.")
                        self.connection.set_mode(mavutil.mavlink.MAV_MODE_RTL)
                    else:
                        # Block launch
                        log.critical("Blocking launch due to parameter tampering.")
                        raise SecurityViolation("Safety parameters compromised")

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
| `FS_GCS_ENABLE` | 0 | 5 | 0 | **Must = 1 or 5** (RTL on link loss) |
| `RTL_ALT` | 0 | 32767 (cm) | 1500 (15m) | **Typical = 3500** (35m AGL, safe height) |
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
[PARAM] FS_GCS_ENABLE = 1 ✓
[PARAM] RTL_ALT = 35 ✓
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

#### Remote ID Corroboration

Remote ID broadcasts independently record flight positions outside of bridge control:

```python
def correlate_with_remote_id(compliance_record, remote_id_track):
    """
    Compare compliance record position against Remote ID track.
    Remote ID is received by third parties and forwarded to FAA.
    Position mismatch indicates record falsification.
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
  - Remote ID provides independent, operator-uncontrollable corroboration
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
def handle_suspected_spoofing(is_armed, operational_area):
    """
    If spoofing is suspected while airborne:
    LAND (not RTL) because RTL uses GPS which may be spoofed.
    """
    
    if suspected_spoofing and is_armed:
        log.critical("GPS spoofing suspected. Executing LAND (not RTL).")
        
        # Send LAND command instead of RTL
        # RTL relies on GPS for return position, so if GPS is spoofed, RTL is unsafe
        connection.set_mode(mavutil.mavlink.MAV_MODE_LAND)
        
        # Log as compliance/security event
        db.compliance_records.insert_one({
            'type': 'security_event',
            'event': 'gps_spoofing_suspected',
            'action_taken': 'LAND',
            'timestamp': datetime.utcnow().isoformat(),
            'source': 'bridge_internal'
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
| `FS_GCS_ENABLE` | uint8 | 0 | 5 | 0 | **1** | RTL on GCS link loss | ATK-MAV-03, ATK-FW-01 |
| `FS_EKF_ACTION` | uint8 | 0 | 2 | 0 | **1** | RTL on EKF failure | ATK-FW-01 |
| `FS_BATT_ENABLE` | uint8 | 0 | 2 | 0 | **1** | Battery failsafe enabled | ATK-FW-01 |
| `RTL_ALT` | uint16 | 0 | 32767 (cm) | 1500 | **3500** | Return altitude (35m AGL) | ATK-FW-01 |
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
| ATK-MAV-03 | WiFi Deauth | WPA3-SAE + SiK backup | Network + Firmware | FS_GCS_ENABLE=1 | Medium |
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
   - FS_GCS_ENABLE = 1 ✓
   - FS_EKF_ACTION = 1 ✓
   - FS_BATT_ENABLE = 1 ✓
   - RTL_ALT = 3500 ✓
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
