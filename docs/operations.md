# Operations

Operator-facing checklists and procedures for drone_hass. This is an index — deep procedures live in `docs/runbooks/<topic>.md` (TODO; see runbook list at the end).

Cross-references: `architecture.md` (system design), `resolutions-ha.md` (security recommendations), `resolutions-ua.md` (UA/regulatory mitigations), `networking.md` (network topology), `monitoring.md` (alerts), `backups.md` (backup flows).

## 1. Pre-Flight Checklist

Two layers: bridge-enforced (machine-checkable) and RPIC-judgment (laminated card at the dock). Authorize tap (commitment scheme, ATK-HA-02) is the bridge between the two.

### 1.1 Bridge-enforced (ArduPilot pre-arm + ComplianceGate)

| Check | Source | Block on fail? |
|---|---|---|
| Battery ≥ 80 % | MAVLink BATTERY_STATUS | Yes |
| GPS HDOP < 1.5, sats ≥ 12 | MAVLink GPS_RAW_INT | Yes |
| ADS-B receiver healthy | DAA monitor | Yes |
| Geofence loaded, polygon matches operational area | bridge re-uploads if mismatch | Yes |
| MAVLink signing OK on SiK + WiFi | bridge startup self-test | Yes |
| Wind < 15 mph sustained, < 25 mph gust | dock anemometer | Yes |
| No active precipitation | dock rain sensor | Yes |
| Dock pad clear (2-of-3 sensors agree) | ESPHome | Yes |
| Compliance chain verifies cleanly | bridge `verify_chain` on startup | Yes |
| Local clock offset < 250 ms | chrony tracking | Yes |
| Litestream replication lag < 5 s (Part 108 mode only) | bridge metric | Yes (Part 108) |
| Operational area `resurvey_required` flag clear | HA `input_boolean.resurvey_required` | Yes |
| Mission allowlist gate | bridge config | Yes |
| Waypoint altitudes ≤ ceiling − 5 m | ComplianceGate | Yes |
| Authorize tap (Part 107 mode) | commitment scheme cross-verified | Yes |

### 1.2 RPIC-judgment (laminated card)

- Visual aircraft inspection: prop integrity, frame cracks, antenna seating, payload secure
- Visual battery inspection: no swelling, no damage, terminal cleanliness
- RPIC physically present within VLOS of operational area (Part 107)
- Weather observed at altitude (windsock, cloud base, visibility)
- B4UFLY / NOTAM check pulled within last 4 hours (no active TFR, UASFM ceiling unchanged)
- No non-participants in flight path during expected mission duration
- Manual override TX powered, channels healthy
- RPIC has not consumed alcohol within 8 hours / not impaired (§107.27)
- Cross-verification: phone push code == HA card code == dock TFT code → tap LAUNCH

## 2. Periodic Tasks

### 2.1 Annual

| Task | Cadence | Reference |
|---|---|---|
| Tree resurvey + altitude invariant recompute | Pre-leaf-out (Feb-Mar in WA) | architecture.md §11.3; trigger on NWS wind advisory >40 mph, visible canopy change, post-arboriculture work |
| ArduPilot parameter audit (full diff vs canonical) | + on every firmware update | resolutions-ua.md safety params table |
| MAVLink signing key rotation | Annual | resolutions-ua.md ATK-MAV-01; physical USB re-key required |
| SiK Net ID rotation | Annual | resolutions-ua.md ATK-MAV-05 |
| SiK link budget characterisation re-test | Annual + on RF change (antenna swap, dock relocation, new neighbour 915 MHz source) | Part 108 means-of-compliance evidence; archive results in compliance DB |
| Aircraft condition inspection (frame, motor wear, prop cycles, ESC) | Annual + on prop replacement | §107.15 RPIC judgment; ArduPilot `STAT_FLTTIME` |
| Aircraft registration renewal | 3-year cadence on FAA DroneZone ($5) | https://faadronezone.faa.gov/ |
| Insurance renewal | Annual | Per-operator |
| Restore-from-zero drill | Annual | runbooks/restore-from-zero.md (TODO) |
| Part 107 recurrent training | Every 24 calendar months (free online ALC-677) | HA `input_datetime` with 60/30/7-day notifications |
| Part 108 Flight Coordinator currency | TBD pending FAA final rule; provisionally annual recurrent + medical-equivalent | placeholder |
| Remote ID DOC verification | Annual — confirm module still on FAA UAS DOC list | https://uas-doc.faa.gov/ |

### 2.2 Quarterly

| Task | Reference |
|---|---|
| Litestream restore drill (S3 + MinIO replicas, separately) | backups.md (TODO) |
| Compliance chain integrity verification (full Ed25519 + OTS replay end-to-end) | resolutions-ha.md R-08 |
| `cosign verify` of installed image; rotate keyless OIDC identity if expired | resolutions-ha.md R-27 |
| Pixhawk parameter file backup + diff vs canonical | runbooks/ardupilot-params.md (TODO) |
| AWS S3 IAM access key rotation | resolutions-ha.md R-27 |
| Resilience drills (see §3) | runbooks/resilience-drills.md (TODO) |
| B4UFLY / UASFM ceiling refresh for property | https://www.faa.gov/uas/getting_started/b4ufly |
| Accident-reporting procedure drill (§107.9 — 10-day window, $500/serious-injury threshold) | tabletop only |
| Renovate / dependabot PR triage | resolutions-ha.md R-27 |

### 2.3 Monthly

| Task | Reference |
|---|---|
| Battery cycle + capacity test (per cell IR check) | per battery |
| Dock sensor calibration: DS18B20 battery-zone temp probe vs reference | esp32 review of dock thermal |
| ADS-B receiver self-test (compare to known traffic in FlightAware) | per pingRX |
| LAANC / B4UFLY airspace status check | pre-flight; monthly cache refresh |
| Backup verification: random restore from `/volume1/llm_backup/drone_hass/` | backups.md |
| Disk-space audit + GC of expired recordings (30-day retention) | per Synology |
| NTP drift audit (`chronyc tracking` history) | architecture.md §11.6 |

### 2.4 First 30 Days After Deployment

Higher cadence; folds into normal periodic schedule once stable:

- **Daily**: chain verification (`verify_chain.py`), disk-space spot check, log review for unexpected `compliance_gap` markers
- **Weekly**: drift detection (firewall rules, ArduPilot params, ESPHome firmware hash) vs canonical
- **One-shot at day 7**: full restore-from-zero drill (do this once early to catch missed backup paths before they matter)

## 3. Resilience Drills (Quarterly)

| Drill | Procedure | Pass criterion |
|---|---|---|
| WAN down | Pull WAN cable for 20 min during a planned non-flight window | NTP holds locally; chain keeps writing; pre-arm tolerates skew; OTS anchor backlog drains on recovery |
| Ubuntu LLM down | `systemctl stop chronyd mediamtx go2rtc` for 10 min | HAOS systemd-timesyncd takes over NTP within 30 s; video unavailable but bridge unaffected |
| HAOS UPS yank | Pull HAOS power on UPS battery alone | NUT triggers `systemctl stop drone-hass-bridge` after 60 s; SQLite WAL clean checkpoint; on power restore, chain verifies, no gaps |
| MQTT broker restart | `ha addons restart core_mosquitto` | Bridge reconnects within 5 s; LWT fires `offline` then `online`; no compliance writes lost |
| Dock fail-open | Pull PoE cable while bench-flight commanded `airborne=true` retained | Lid opens within 90 s; compliance event logged; auto-reclose at 30 min |
| Litestream S3 unreachable | Block AWS via firewall for 1 hour | Lag metric trips at 5 s in Part 108 mode (pre-arm fail); MinIO secondary keeps replicating; 15-min Part 108 grace per `architecture.md` §14 |
| Bridge add-on update mid-mission risk | Tabletop only — never test in flight | Procedure: bridge add-on updates only between flights; HA Core updates with bridge running OK |

## 4. Per-Incident Response

| Incident | Immediate action | Follow-up |
|---|---|---|
| Dock fail-open engaged | Acknowledge critical push; investigate WiFi/PoE/MQTT loss | Compliance event auto-logged; manually close lid after aircraft secured; 30-min auto-reclose if not |
| GPS spoofing alert (ATK-FW-03) | RPIC takes manual control; aircraft will be in BRAKE then ALT_HOLD | Review compliance event; check for nearby SDR-capable transmitters; report to FAA if persistent |
| MAVLink signing failure | Bridge refuses to arm; verify signing key on disk; if mismatch, re-key via USB | Investigate possible key extraction; rotate immediately if any concern |
| Compliance chain verification failure | Pre-arm fails; bridge stops accepting writes; investigate via `verify_chain.py --verbose` | Restore from Litestream replica; if chain confirmed broken, write new genesis with link to last-good hash + OTS proof (R-08 chain restart) |
| Passphrase wrong-attempts threshold | Bridge sealed after 3 attempts × 60 s | Wait for backoff; if forgotten passphrase, follow R-08 chain restart procedure |
| Unsigned safety-critical message dropped (ATK-MAV-01 filter) | Compliance event logged; Prometheus counter increments; alert fires on >0 in 5 min window | Investigate VLAN 20 — check for rogue MAVLink injector |

## 5. Secrets & Key Rotation Calendar

| Secret | Cadence | Procedure | Verification |
|---|---|---|---|
| MQTT TLS server cert | Annual | runbooks/mqtt-cert.md (TODO) | `openssl s_client -connect mosquitto:8883` shows new cert |
| MAVLink signing key | Annual | resolutions-ua.md ATK-MAV-01 — physical USB re-key on FC | bridge startup self-test passes |
| SiK Net ID + AES-128 key | Annual | runbooks/sik-rotation.md (TODO) — both ends, AT commands | telemetry resumes on both radios |
| Ed25519 compliance signing key | On suspected compromise OR every 5 years | R-08 chain restart procedure | new genesis + link to prior chain hash |
| AWS S3 IAM access key | Quarterly | runbooks/aws-iam-rotation.md (TODO) | Litestream resumes replication |
| cosign keyless / YubiHSM identity | YubiHSM annual; keyless OIDC every 90 days when GHA token rotates | R-27 | `cosign verify` succeeds on next image |
| HA mobile_app push tokens | Per device replacement | re-pair device via HA UI | test push notification round-trip |
| Bridge↔phone HMAC (ATK-HA-02) | Per RPIC change | re-provision via Ingress UI | test commitment-flow round-trip |
| Bridge↔dock HMAC (display verification) | Per dock firmware reflash | re-provision via dock USB | test challenge cross-verification |
| HA secrets.yaml backup encryption passphrase | Per operator personnel change | rotate; re-encrypt all backups | manual test restore |

## 6. Audit-Logging Policy

Operations actions that affect safety go into the compliance chain with `actor=sysop, ops_event=true`:

- Firmware flash (Pixhawk, ESPHome dock)
- Geofence / operational-area change
- Signing key rotation (any of the three: MAVLink, Ed25519 compliance, dock HMAC)
- ComplianceGate mode change (Part 107 ↔ Part 108)
- Forced lid open via physical button or fail-open trigger
- Restore from backup
- HAOS bare-metal reinstall

Routine ops are NOT logged into the compliance chain (would dilute audit signal):
- HA Core update
- Add-on update (other than bridge add-on)
- Log rotation
- TLS cert renewal (logged in TLS audit only)

## 7. Runbook Index (TODO)

Deep procedures split per topic. Each runbook is independently versioned. To create:

- `runbooks/restore-from-zero.md` — bare-metal HAOS rebuild + bridge reinstall + Litestream restore + chain validation
- `runbooks/ardupilot-params.md` — parameter backup, diff, restore, post-flash verification
- `runbooks/sik-rotation.md` — SiK Net ID + AES key rotation, both radios
- `runbooks/aws-iam-rotation.md` — Litestream IAM access key rotation
- `runbooks/mqtt-cert.md` — Mosquitto TLS cert renewal (LE / internal CA path)
- `runbooks/resilience-drills.md` — exact commands for each drill in §3
- `runbooks/firmware-update-bridge.md` — bridge add-on update procedure (between-flights only; cosign verify required)
- `runbooks/firmware-update-dock.md` — ESPHome OTA via physical USB (per ATK-DOCK-01)
- `runbooks/firmware-update-ardupilot.md` — manual `.apj` flash + GPG verify + parameter restore
- `runbooks/passphrase-recovery.md` — chain restart procedure when Ed25519 passphrase is lost
