# drone_hass System Architecture

> **Date:** 2026-04-14
> **Status:** Proposal
> **Version:** 0.4.0

---

## 1. Executive Summary

**drone_hass** is an open-source Home Assistant integration that enables autonomous aerial perimeter inspection using MAVLink-compatible drones.

The system is **designed for Part 108 BVLOS operations from day one**. Part 107 human-in-the-loop is the current operating mode — a stepping stone, not the target. When the Part 108 final rule is published, the architecture is ready to switch to fully autonomous alarm-triggered flight within a pre-approved operational area, with a Flight Coordinator monitoring rather than a pilot authorizing each launch.

The system is split into two software packages (add-on + integration) following the proven Frigate/Zigbee2MQTT pattern, plus physical infrastructure:

1. **Bridge Add-on** — HA add-on (Docker container) running the MAVLink-MQTT bridge, DAA monitor, ComplianceGate, and compliance recorder (SQLite). Connects to the drone via MAVSDK-Python, publishes/subscribes MQTT. Runs independently of HA Core — survives HA restarts, keeps logging mid-flight. Also deployable as a standalone Docker container or systemd service for HA Container/Core users.
2. **HA Integration** — `custom_components/drone_hass/`, consuming MQTT via `homeassistant.components.mqtt`. Entities, services, config flow, dashboard. No heavy dependencies — pure MQTT consumer.
3. **Physical Dock** — weatherproof enclosure with ESPHome ESP32 controller, keeps drone staged and batteries ready
4. **Weather Station** — local anemometer and rain gauge at the dock site for automated go/no-go

The add-on and integration communicate **exclusively via MQTT**. The integration does not know or care whether the MQTT messages come from the add-on, a Docker container, or a systemd service on a remote SBC.

The add-on bundles:
- MAVLink-MQTT bridge (MAVSDK-Python + aiomqtt)
- DAA monitor (ADS-B traffic processing, threat assessment)
- ComplianceGate (Part 107/108 mode enforcement)
- Compliance recorder (append-only SQLite with cryptographic hash chain)
- Mission manager (operational area validation, mission upload)
- Operational area definition (GeoJSON volume validated on every mission)

**Design principles:**
- Aircraft-agnostic: the dock, MQTT topics, and HA integration do not depend on a specific drone
- Protocol-first: MAVLink is the aircraft interface, MQTT is the HA interface — both are open standards
- Dual-mode: Part 107 (human authorization) and Part 108 (autonomous with monitoring) selectable via configuration
- Safety in firmware: flight controller geofence, ESPHome interlocks, and DAA run independently of HA
- Add-on isolation: the bridge, compliance recorder, and DAA processing run in their own container, independent of HA Core lifecycle. MAVSDK-Python/gRPC dependencies never touch HA's Python environment
- Compliance independence: the compliance recorder keeps logging even when HA Core is restarting

---

## 2. Legal Prerequisites

Before any flight operation, the following are **mandatory** — not optional, not future work.

### For Part 107 Operations (Current)

| Requirement | Detail |
|-------------|--------|
| FAA Part 107 Remote Pilot Certificate | RPIC must hold this before any flight |
| FAA drone registration | Aircraft must be registered with FAA |
| Remote ID broadcast module | Required since September 2023. ArduPilot supports OpenDroneID; external module (e.g., uAvionix ping Remote ID) required if firmware lacks it |
| Anti-collision strobe | Required for night operations. Must be visible for 3 statute miles. Mount on aircraft, account for weight/CG impact |
| Class G airspace verification | Confirm property is in unrestricted airspace. Use FAA B4UFLY or sectional charts |
| VLOS confirmation | RPIC must be able to see the aircraft with unaided vision at all times (corrective lenses OK, binoculars not). The live video feed does NOT satisfy VLOS |
| RPIC physical presence | The RPIC must be on or near the property — within visual range of the aircraft — before authorizing launch. Tapping LAUNCH from an office while watching a phone stream is a Part 107 violation |

### For Part 108 Operations (Target)

| Requirement | Detail |
|-------------|--------|
| Operating Permit or Certificate | Application to FAA for approved operational area |
| Cooperative DAA (ADS-B In) | Aircraft must detect and yield right-of-way to ADS-B-broadcasting traffic. Mandatory for all Part 108 operations |
| Standard Remote ID | Continuous position broadcast during operations |
| Airworthiness Acceptance | Aircraft must have a Declaration of Compliance from manufacturer (see Section 6.6) |
| Operations Supervisor designation | Person responsible for safe operation of all flights |
| Flight Coordinator designation | Person with tactical oversight during flight; must be able to intervene |
| Compliance records | Flight logs, DAA events, weather, personnel — see Section 11 |
| Defined operational area | Pre-approved geographic volume for BVLOS operations |

### For All Deployments

| Requirement | Detail |
|-------------|--------|
| Insurance | Homeowner's policy likely excludes commercial UAS. Obtain drone-specific commercial liability coverage ($500-1,500/year for Part 107; expect higher for Part 108 autonomous operations) |
| WA state privacy | Mission corridors must avoid areas where neighbors have a reasonable expectation of privacy (yards, windows). This constraint is stronger for autonomous operations where no human is making real-time judgment calls |
| Property overflight | Perimeter patrol must stay within own property airspace |
| Multi-drone limitation | One drone airborne at a time per qualified person. Under Part 107, one RPIC cannot maintain VLOS on two aircraft simultaneously (14 CFR 107.35(a)). Under Part 108, Flight Coordinator oversight limits apply |

### HA Config Flow Acknowledgment

The HA integration config flow includes an explicit acknowledgment step where the user confirms they hold the required certifications and have verified airspace classification. This is not legally bulletproof but creates a record that the user was informed of requirements.

---

## 3. Regulatory Framework

> **Reading guide:** this section mixes layers of invariance. US Part 107/108 detail is **Level 5** (national specialisation); concepts like risk-based categorisation, VLOS/BVLOS step-change, Remote ID, and insurance are **Level 2** (risk-based regulation family, shared across FAA/EASA/TC/CASA/…). See `regulatory-layered-model.md` for the full invariance model. Each subsection below is tagged with its layer for navigation.

### 3.1 Applicable Law *(Level 5: US-specific)*

Drone operation in the U.S. is governed by federal law (FAA), not state law. This use case — property security triggered by an alarm — is **commercial/operational**, meaning **14 CFR Part 107** applies today and **14 CFR Part 108** will apply when finalized.

### 3.2 Part 107: Current Operating Mode *(Level 5: US-specific)*

Part 107 governs all flight operations until a Part 108 Permit is obtained.

| Requirement | Status |
|-------------|--------|
| FAA Part 107 certificate (RPIC) | Required |
| FAA registration | Required |
| Remote ID broadcast | Required (OpenDroneID module) |
| Anti-collision strobe for night ops | Required (visible 3 statute miles) |
| Visual Line of Sight (VLOS) | Required — RPIC or visual observer must see drone with unaided vision |
| Fly under 400 ft AGL | Yes (missions at 80-120 ft) |
| Unrestricted (Class G) airspace | Yes (property is in Class G) |
| Airspace authorization (LAANC) | Not needed for Class G |

**The human-in-the-loop constraint:** Under Part 107, a Remote Pilot in Command must be responsible for the flight, be able to intervene immediately, and explicitly authorize takeoff. The system satisfies this with a single-tap authorization step — the same compliance pattern used commercially by DJI Dock, Skydio Dock, and Percepto.

**VLOS realities for this property:**
- The property is ~300 ft x 150 ft, flat, 1 acre. VLOS is maintainable for daylight operations on all planned mission corridors.
- "Maintainable" is not the same as "maintained" — the RPIC must actually be watching the aircraft, not the HA dashboard. The live video feed is for situational awareness and evidence capture, not for satisfying VLOS.
- Night operations: the anti-collision strobe must be visible for 3 statute miles. At 80-110 ft on a 1-acre property, VLOS via strobe is achievable, but the RPIC must be outdoors watching the aircraft.
- The RPIC must be physically present on or near the property before tapping LAUNCH. The system cannot technically enforce RPIC location, but this document places the burden explicitly on the operator: **do not authorize flight unless you are within visual range of the planned flight corridor.**
- The "person detected while no one is home" scenario is NOT a valid Part 107 use case unless a visual observer (14 CFR 107.33) is on-site. Under Part 108, this constraint is removed.

### 3.3 Part 108: Target Operating Mode *(Level 5: US-specific)*

Part 108 is the target regulatory framework. The NPRM was published August 7, 2025. The final rule has not been published as of April 2026. Expected timeline: final rule summer 2026, implementation 6-12 months after publication.

**What Part 108 changes:**

| Part 107 Constraint | Part 108 Replacement |
|---------------------|---------------------|
| RPIC must authorize each flight | Operations Supervisor + Flight Coordinator roles; no per-flight authorization required |
| RPIC must hold Part 107 certificate | No individual pilot certification; organizational responsibility model |
| VLOS required | BVLOS authorized within approved operational area |
| Per-flight waivers for BVLOS | Operational area pre-approved; routine flights within it without per-flight permission |
| Human is a gatekeeper | Human is a monitor — Flight Coordinator can intervene but does not pre-authorize |

**Two authorization tiers (from NPRM):**
1. **Operating Permit** — lower-risk operations, less FAA oversight. Available for operations in population density Categories 1-3. Residential suburban (Seattle Eastside) is likely Category 2-3, within Permit pathway.
2. **Operating Certificate** — higher-risk/complexity operations, greater organizational obligations.

**DAA requirements for Class G, Category 2-3 (this property):**
- Cooperative DAA mandatory: detect aircraft broadcasting ADS-B (1090 MHz and UAT/978 MHz)
- Non-cooperative detection (radar, optical) NOT required for this category
- Aircraft must determine collision risk and execute avoidance maneuvers autonomously

**Compliance workflow under Part 108:**

```
Alarm → Automated safety checks (weather, DAA health, airspace, battery, dock)
    → Operational area validated
    → Flight Coordinator on duty confirmed
    → Autonomous launch
    → Flight Coordinator notified (monitoring, can ABORT/RTH)
    → Mission executes
    → RTL → dock closes
    → Compliance record written
```

The per-flight human tap disappears. The Flight Coordinator is a monitor with override capability, not a gatekeeper.

### 3.4 Dual-Mode Architecture *(Level 1: project architecture, specialised at Level 5)*

The system operates in one of two modes, selectable via configuration:

```
Part 107 mode (default):
  Alarm → Safety checks → RPIC notification → Human tap required → Launch

Part 108 mode:
  Alarm → Safety checks + DAA health + FC on duty → Autonomous launch → FC notified
```

Part 107 mode is a strict subset of Part 108 mode — everything Part 108 requires (DAA, logging, weather checks, operational area validation), Part 107 operations also benefit from. The only difference is whether a human tap is required before launch.

### 3.5 Washington State Specifics *(Level 6: site-specific within US)*

WA adds minimal flight restrictions beyond FAA:
- Privacy: avoid surveillance where people have reasonable expectation of privacy (neighbor yards/windows)
- Property overflight: perimeter patrol must avoid crossing into neighbors' airspace
- State parks require permission; private residential land is fine

### 3.6 Non-Operator Deployments *(Level 1: project policy)*

This is a public open-source project. Operators deploying it are responsible for their own regulatory compliance. The system includes:
- Explicit prerequisites in this document (Section 2)
- Acknowledgment step in HA config flow
- Operational mode requires manual configuration (Part 108 mode is not the default)
- Geofence and operational area validation cannot be bypassed from HA

These measures do not transfer legal responsibility from the operator but create a documented record that requirements were communicated.

### 3.7 EU — Design Considerations (Pressure Test) *(Level 3–5: SORA, EU framework, national specialisations)*

The primary target jurisdiction is the US (Part 107/108 — Level 5). A separate pressure-test analysis against EU Regulation 2019/947 + 2019/945 (Level 4) covers the EU as a whole, with three national specialisations (Level 5):

- `regulatory-eu.md` — pan-EU framework (direct-effect regulations, SORA methodology, GDPR baseline, EU-wide one-way-doors, per-country architecture abstractions).
- `regulatory-eu-it.md` — Italy specialisation. Full worked scenario for a ~1-acre coastal property in Lavagna, Liguria. ENAC + Garante + D-Flight. Complete cost breakdown, SORA process walkthrough, 27-item deliverables checklist.
- `regulatory-eu-fr.md` — France specialisation (seed). DGAC/DSAC + AlphaTango + CNIL. Flagged as partial — CNIL-aligned DPIA overlay is the single biggest completion item.
- `regulatory-eu-de.md` — Germany specialisation (seed). LBA + 16 Länder + DIPUL + Länder DPAs. Flagged as partial — Länder fragmentation is the structural problem.

Headline conclusions:

- The operation falls in the **Specific category**, realistic target **SAIL II** via national operational authorisation with SORA methodology. Timeline 2–7 months depending on country, cost €2.5–5k self-prepared fees + 150–300 engineer-hours. STS/PDRA are blocked by the self-built ArduPilot's lack of C-class marking — EU-wide.
- **EU Specific operational authorisation ≈ US Part 108 operational permit** — the software shape is the same (pre-approved volume, human monitors without gating, mandatory logging). Compliance-store and privacy semantics differ.
- The biggest non-aviation gap is **GDPR / the national DPA** on the camera payload. CNIL (FR) is the hardest surface; Länder DPAs (DE) are heterogeneous; Garante (IT) is most lenient. This drives the two-tier compliance recorder design (see `compliance-recorder-two-tier.md`), worth adopting in US mode too.
- **~65% of the regulatory content is MS-neutral; ~25% swaps cleanly; ~10% needs rewriting** (principally the DPA layer). Porting from IT to FR is weeks; IT to DE is months, dominated by Länder fragmentation.

Rather than build EU support now, the design makes **cheap hedges** on decisions that are hard or expensive to reverse later — primarily in hardware selection. Real commitments (parachute, FLARM, D-Flight registration, SORA submission, DPIA lawyer) are deferred until EU deployment is actually on the roadmap.

**One-way-door decisions being hedged now:**

| Area | US-only naive default | Hedged default | Why it matters |
|---|---|---|---|
| Primary C2 radio | RFD900x (915 MHz, 1 W) | **RFD868x (868 MHz, 25 mW) or dual-band variant** | 915 MHz is not usable at ISM power levels in the EU. Same vendor, similar price. Swapping later requires re-pairing both ends. |
| Remote ID module | FAA-certified only | **Dual-certified: FAA + ASD-STAN EN 4709-002 / Delegated Reg (EU) 2020/1058** | Dronetag / BlueMark modules carry both declarations. Minimal premium. |
| Autopilot firmware | ArduPilot 4.4 | **ArduPilot 4.5+** | Multi-fence required for asymmetric sector-dependent altitude caps under SORA. Parameter cascade if upgraded later. |
| Airframe payload margin | Sized to camera + comms only | **Headroom for parachute (200–500 g) + FLARM (~50 g) + independent FTS MCU (~30 g) + LTE modem (~100 g)** | Adding ~1 kg of reserve at airframe selection avoids a full rebuild later. |
| Independent FTS MCU footprint | Not present | **Reserve PCB / chassis space + a UART or relay line** on an autopilot-external MCU (ESP32/STM32 with own power rail) | FTS must fire even if autopilot hangs. Retrofitting into a finished airframe is painful. |
| Camera focal length | Whatever the use case wants | **Default wide-angle (≤30 mm equiv)** | GDPR identifiability argument depends on this. Telephoto payload changes the DPIA calculus. |
| Gimbal | Any | **Real-time queryable attitude (MAVLink-native / SBUS)** | Geospatial / FOV-sector privacy masking requires per-frame gimbal state. Closed-API gimbals foreclose the privacy mask. |
| Autopilot UART budget | Consume as needed | **Reserve 1 UART for FLARM, 1 for LTE C2** | Pixhawk 6C has 7 serial ports. Budget them at design time rather than fighting cable runs later. |
| Compliance recorder schema | Single-tier chain + inline blobs | **Two-tier: immutable metadata chain + deletable blob tier** (see `compliance-recorder-two-tier.md`) | Retrofitting tier-2 later means migrating the chain. Biggest software one-way-door. |
| Privacy masking | Post-hoc in HA or absent | **Pre-record in the RTSP pipeline (go2rtc/mediamtx)** | If frames are recorded unmasked, the raw exists and is GDPR-scoped. Architectural. |
| `OperationalMode` enum | `PART_107`, `PART_108` only (`mavlink_mqtt_bridge/compliance.py`) | Extensible; no `assert mode in (…)` patterns in callers | `EU_OPEN_A3` / `EU_SPECIFIC_SORA` drop in cleanly. Current shape is already extensible; just keep it that way. |
| Operator ID schema | FAA-only implicit | **Tagged union: `{faa_op_id \| eu_df_operator_number}`** | Data-model change is cheap now, painful after shipping. |
| Geofence representation | Single polygon inset | **Three nested polygons (operational, contingency, GRB) with per-edge setback values** | Populate trivially in US mode; required under SORA OSO #24. |
| Flight log regulator field | Not present | Add `country` / `regulator` columns to `flight_log` | Makes regulator-scoped queries trivial later. |

**Accepted one-way-doors (closing knowingly):**

- **No C-class marking possible for self-built ArduPilot.** EU deployment will be SORA-operational-authorisation only, never STS/PDRA. Reopening requires replacing the flight stack with a certified commercial UAS.
- **No ANSI/CTA 2063 serial number flow for STS.** Same root cause.

See `regulatory-eu.md` for the pan-EU framework and `regulatory-eu-it.md` for the worked Lavagna scenario — site geometry, GRB math, SAIL / OSO derivation, ENAC SORA process walkthrough, cost breakdown, 27-item deliverables checklist. France and Germany seeds (`regulatory-eu-fr.md`, `regulatory-eu-de.md`) cover the cross-country findings and open items.

---

## 4. Operational Concept

### 4.1 The Alarm Response Workflow

<p align="center"><img src="https://raw.githubusercontent.com/acato/drone_hass/main/docs/diagrams/alarm-workflow.svg" alt="Alarm Response Workflow"></p>

**Part 108 mode** follows the same flow, except the actionable notification is replaced by:
- Autonomous launch after all safety gates pass
- Flight Coordinator receives monitoring notification with ABORT/RTH override buttons
- Compliance record includes autonomous authorization justification

**Target timeline: alarm → airborne in ~15-30 seconds** (Part 108, no human tap) or ~30-60 seconds (Part 107, with RPIC authorization).

### 4.2 Mission Design for This Property

With 50+ trees (some >100 ft), missions are **constrained corridor sweeps**, not a simple perimeter orbit.

| Mission | Description | Altitude |
|---------|-------------|----------|
| `front_sweep` | Driveway + front edge | 80 ft (clear corridor) |
| `rear_sweep` | Back fence line | 80 ft |
| `east_edge` | East property boundary | 110 ft (taller trees) |
| `west_edge` | West property boundary | 80 ft |
| `full_perimeter` | All 4 edges sequentially | Variable per segment |
| `corner_ne` / `nw` / `se` / `sw` | Quick corner investigation | 80-110 ft |

Altitude is a **safety spec** (tree clearance + margin), not a fixed number. Camera angle compensates: gimbal at -30 to -45 degrees provides border coverage from higher altitudes.

All missions must stay within the defined operational area (Section 11.3).

---

## 5. Physical Dock Design

### 5.1 Purpose

The dock provides: environmental survivability, deterministic staging, battery readiness, and a motorized lid controlled by Home Assistant.

The dock is **aircraft-agnostic by design**. It does not know or care what drone is sitting on it. Landing pad alignment guides are adjustable for different airframe footprints.

### 5.2 Enclosure Specification

| Component | Material | Rationale |
|-----------|----------|-----------|
| Outer enclosure | NEMA 4X polycarbonate or stainless cabinet | Weatherproof, corrosion-resistant |
| Lid panel | Aluminum sheet with internal ribs + drip edge | Strong, lightweight, rain shedding |
| Inner liner | Cement board + steel tray under drone bay | Noncombustible (LiPo fire mitigation) |
| Fasteners | Stainless steel (isolated from aluminum) | Galvanic corrosion prevention |
| Seals | EPDM gasket + compression latch | Weathertight, UV-resistant |
| Insulation | Polyisocyanurate (foil-faced), isolated from battery bay | Thermal management |

### 5.3 Environmental Control

Seattle Eastside climate: mild but wet. Condensation is a bigger threat than rain.

| System | Purpose | Implementation |
|--------|---------|----------------|
| Heating | Keep batteries 10-30 C | PTC heater pad (reptile heater class), NOT direct battery contact |
| Ventilation | Condensation/humidity control | 12V fan + filtered intake, dew-point logic |
| Temperature sensing | Interior + battery zone + ambient | DS18B20 or BME280 sensors |
| Humidity sensing | Dew point management | BME280 |
| Smoke/heat detection | LiPo fire early warning | Smoke detector in lid void |
| Drain | Prevent water pooling | Weep holes with insect mesh |

### 5.4 Lid Mechanism

| Component | Spec |
|-----------|------|
| Actuator | 12-24V DC linear actuator, clevis mount |
| Limit switches | Redundant open + closed microswitches |
| Pad clear sensor | ToF or IR beam — prevents closing onto drone |
| Manual override | Physical button + emergency stop |

### 5.5 ESPHome Dock Controller

The dock runs on an **ESP32 with ESPHome**, exposing entities to Home Assistant. Safety interlocks are enforced **locally on the controller**, not in HA — HA sends intents, the ESP32 enforces conditions.

**State machine (firmware-level):**
```
CLOSED → OPENING → OPEN → CLOSING → CLOSED
```

**Safety interlocks (on-controller, not in HA):**
- Cannot open unless power is healthy
- Cannot close unless motors disarmed AND pad-clear sensor confirms landed
- Auto-close timeout with abort on obstruction
- Charger power relay cut on smoke/overtemp (hardware, not software)
- Motion timeout: if actuator runs too long, stop and flag fault
- Watchdog timer: if ESP32 firmware hangs, fail to safe state (lid closed, charger off)
- **Fail-open override**: if MQTT lost > 60 s while aircraft is airborne, lid opens regardless of other state — see "Connectivity and fail-open lid policy" below

#### Connectivity (PoE primary, WiFi fallback)

The dock's connectivity is **wired Cat6 PoE++ from the house switch to the dock**, not WiFi-primary. WiFi-only had a fatal failure mode: WiFi drops mid-flight → dock cannot receive `cmd/lid/open` → drone has no landing target. Wired Ethernet eliminates this single point of failure.

| Hardware | Spec |
|---|---|
| House switch port | **PoE++ 802.3bt Type 3 (60 W)** on managed switch with VLAN 10 untagged. PoE+ (30 W) was originally specified but the budget — ESP32 + W5500 + TFT (~5 W) + lid motor peak (15 W) + heater (25 W steady) + charger contactor coil — peaks at ~50 W; PoE+ would brown out. |
| In-conduit cable | Cat6 (or Cat6A if >50 m), pulled in the same trench/conduit as existing dock power |
| Surge protection | Ubiquiti ETH-SP-G2 surge arrestor at **both** ends of the Cat6 run (~$25 each). WA outdoor runs see lightning-induced transients. |
| At-dock splitter | PoE-Texas GBT-12V60W (PoE++ in, 12 V DC out + Ethernet out) |
| Dock controller | ESP32-WROOM-32U + W5500 SPI Ethernet (hardware TCP/IP offload, rock-solid ESPHome support) |
| WiFi fallback | Same ESP32-WROOM-32U external antenna; only used if Ethernet link down |

ESPHome YAML must declare `ethernet:` block **before** `wifi:` so the dock comes up wired-first and only attempts WiFi on Ethernet link-loss:

```yaml
ethernet:
  type: W5500
  clk_pin: GPIO18
  mosi_pin: GPIO23
  miso_pin: GPIO19
  cs_pin: GPIO5
  interrupt_pin: GPIO4
  reset_pin: GPIO2
  manual_ip:
    static_ip: 10.10.10.20
    gateway: 10.10.10.1
    subnet: 255.255.255.0

wifi:                     # fallback only — dock prefers Ethernet
  ssid: !secret dock_wifi_ssid
  password: !secret dock_wifi_password
  fast_connect: true
  power_save_mode: none
```

#### Fail-open lid policy (mandatory firmware behaviour)

The dock **opens the lid** if either condition holds while the dock has been disconnected from MQTT for more than 60 s:

1. **Live-airborne**: bridge's last `state/airborne` (retained) was `true` AND that retained value is less than 90 s old (60 s connectivity loss + 30 s telemetry stale margin).
2. **Recently-closed bootstrap**: lid was commanded closed within the last 20 minutes (covers the "launched then comms died before the dock saw `airborne=true`" case where the retained-message latch never reached the dock).

An open lid in weather is recoverable. A closed lid blocking an emergency landing is not. The weather-precipitation interlock that gates *normal* lid opens is **bypassed** for the live-airborne fail-open case — a wet dock interior is an acceptable cost. Precipitation interlock *does* apply to the recently-closed bootstrap path: if the drone was already on the ground at takeoff but the dock missed `airborne=true`, opening into a downpour for no reason is silly.

**Bridge-side requirement** (added to `mavlink-mqtt-contract.md`):

```yaml
# drone_hass/{drone_id}/state/airborne — retained, QoS 1
# Bridge publishes on every state change.
# "airborne" = armed AND (relative_altitude_m > 2.0 OR EKF in_air flag set).
# NOT raw MAV_STATE_ACTIVE — that fires during armed-on-ground.
```

**Compliance event** logged on every fail-open engage AND recovery:

```json
{
  "type": "dock_fail_open_engaged",
  "mqtt_last_seen_ts": "...",
  "airborne_retained_ts": "...",
  "lid_last_closed_ts": "...",
  "trigger": "live_airborne" | "recently_closed_bootstrap",
  "last_known_position": {...},
  "last_known_battery_pct": 47,
  "weather_at_engage": {...},
  "lid_open_ts": "..."
}
```

**Operator notifications** — critical-priority push (not silent), on both engage and recovery:
- Engage: "DOCK FAIL-OPEN ENGAGED — investigate. Aircraft last seen [position, battery]."
- Recovery: "Dock lid manually closed by [operator] at [time]."

**Auto-reclose timeout**: 30 minutes. Prevents indefinite open state once MQTT recovers.

**Audible / visual alarm at the dock during fail-open**: piezo buzzer continuous tone + the TFT switches to a red "FAIL-OPEN — DRONE LANDING — STAND CLEAR" full-screen indicator.

**Physical FORCE OPEN button** — hardware pull-up to a debounced GPIO that drives the lid motor through a firmware path that **bypasses MQTT entirely**. RPIC last-resort recovery if all comms are dead. Mounted next to the dock, mushroom-head, weatherproof, ~$3 part. Pressing FORCE OPEN also fires the same compliance event with `trigger: "physical_button"`.

**Part 108 CONOPS:** the fail-open behaviour must be documented in the operational means-of-compliance (lost-link contingency mitigation). Verify ArduPilot RTL altitude (per §11.3 altitude invariant) clears the open lid mechanism with margin, otherwise the drone could descend into a partially-open lid mid-cycle.

**Entities exposed to HA:**

| Entity | Type | Notes |
|--------|------|-------|
| `cover.drone_dock_lid` | Cover | Open/close/stop |
| `sensor.dock_temperature` | Temperature | Interior |
| `sensor.dock_battery_zone_temp` | Temperature | Near battery/drone |
| `sensor.dock_humidity` | Humidity | Interior |
| `binary_sensor.dock_lid_open` | Binary sensor | Limit switch |
| `binary_sensor.dock_lid_closed` | Binary sensor | Limit switch |
| `binary_sensor.dock_pad_clear` | Binary sensor | ToF/IR |
| `binary_sensor.dock_smoke` | Binary sensor | Smoke detector |
| `switch.dock_heater` | Switch | PTC heater relay |
| `switch.dock_fan` | Switch | Ventilation fan relay |
| `switch.dock_charger_power` | Switch | Smart outlet / relay for charger |
| `sensor.dock_power_status` | Sensor | Mains/UPS status |
| `sensor.dock_authorize_display` | Sensor | Current `challenge_display` shown on the dock TFT (or `IDLE` / `EXPIRED` / `INVALID_HMAC`) — exposed for HA dashboard correlation |

#### Authorization cross-verification display

For the commit-and-reveal authorization flow (resolutions-ha.md ATK-HA-02), the dock displays the bridge's `challenge_display` on a small outdoor-readable screen so the RPIC can cross-verify against (a) the phone push notification and (b) the HA Lovelace card. Mismatch on any of the three sources = REFUSE TO AUTHORIZE. This is the property that defeats a `ha_user` who tries to inject a rogue push notification — the OLED still shows the bridge's real value.

| Hardware | Spec | Why |
|---|---|---|
| Display | ST7789 240×240 IPS TFT, SPI, ~$8 | Daylight-readable behind polycarbonate (SSD1306 OLED washes out in direct sun). LDR on ADC drives PWM backlight for night auto-dim. |
| Mount | Dock exterior face oriented toward typical RPIC standing zone, ~1.2 m off ground, angled ~15° upward, with anti-reflective polycarbonate window | Operator must not have to look down into a horizontal surface in bright light |
| Audible alert | Piezo buzzer on `output: ledc` (RTTTL) | Two short beeps on challenge appearance, one long on expiry. Operators are not always staring at the dock. |

**Default display state** (most of the time): "VERIFY MODE INACTIVE — DO NOT AUTHORIZE" in large text. The OLED only switches to the challenge view when a *valid signed request* arrives within the last 30 s. Missing display is an explicit REFUSE signal, not an ambiguous one — operator habituation to "OLED is glitchy, ignore it" is the failure mode this defeats.

**Trust hardening (all three required, none of these are pick-one):**

1. **Mosquitto ACL** — only the `bridge_user` clientid can publish to `drone_hass/+/command/authorize_flight/request`. `ha_user` is read-only on that topic. Already in resolutions-ha.md ATK-MQTT-01 ACL; verify the dock subscriber is gated to bridge-publishes-only.
2. **HMAC-SHA256** over `challenge_display + commitment + expires_at + monotonic_nonce`, signed with a key provisioned to the dock at install time (separate from the bridge↔phone HMAC key). Dock refuses to display unsigned or replayed payloads (monotonic nonce check).
3. **Loud failure UI** — see "Default display state" above.

**Clear logic** (in priority order, applied in firmware):
1. Bridge publishes `authorize_flight/response` (success or deny) — clear immediately.
2. Local timer reaches `expires_at` — clear immediately. **The local timer is the safety net; never trust the bridge to always send a clear.**
3. Explicit `drone_hass/{drone_id}/dock/display/clear` topic for operator abort.

**Heartbeat:** the dock publishes `drone_hass/{drone_id}/dock/heartbeat` at 1 Hz. The bridge refuses to arm if dock heartbeat is stale (no silent third-source loss).

**Compliance log:** all three verification sources (phone notification ack, HA card render, dock display confirm) are logged into the compliance DB with the `challenge_display` value each one observed. Auditors verify all three values match for any approved authorization.

**ESPHome YAML sketch** (full file in `dock/esphome/dock_controller.yaml`):

```yaml
spi:
  clk_pin: GPIO18
  mosi_pin: GPIO23

display:
  - platform: st7789v
    cs_pin: GPIO5
    dc_pin: GPIO16
    reset_pin: GPIO17
    update_interval: 250ms       # responsive countdown
    lambda: |-
      if (id(auth_pending) && id(auth_hmac_valid) && (id(now_secs) < id(expires_at))) {
        it.printf(0,   0, id(font_small), "MISSION");
        it.printf(0,  18, id(font_med),   "%s", id(mission_id).c_str());
        it.printf(0,  60, id(font_small), "VERIFY CODE");
        it.printf(0,  78, id(font_xl),    "%s", id(challenge_display).c_str());
        it.printf(0, 200, id(font_small), "Expires in %ds",
                  id(expires_at) - id(now_secs));
      } else {
        it.fill(COLOR_RED);                 // loud-failure default
        it.printf(0,  60, id(font_med), "VERIFY MODE");
        it.printf(0,  90, id(font_med), "INACTIVE");
        it.printf(0, 140, id(font_small), "DO NOT AUTHORIZE");
      }
```

### 5.6 Placement

On the shed roof. Requirements:
- Clear vertical column above (no overhanging branches)
- Clear lateral clearance ~30-50 ft for takeoff/landing
- Clear approach lane for return-to-home (no branches in the direction of final approach)
- Power from shed below
- WiFi coverage from house network
- Local weather station mounted nearby (anemometer, rain gauge)

### 5.7 Power Architecture

<p align="center"><img src="https://raw.githubusercontent.com/acato/drone_hass/main/docs/diagrams/power-architecture.svg" alt="Power Architecture"></p>

UPS is important: brownouts during storms are common — exactly when you want the system most.

### 5.8 Ground Infrastructure

| Component | Purpose | Part 108 Relevance |
|-----------|---------|-------------------|
| Local weather station (anemometer + rain gauge) | Automated go/no-go with measured data | Operational safety documentation; not API-derived |
| ADS-B ground receiver (FlightAware PiAware or similar) | Extended traffic awareness beyond airborne receiver | Supplements onboard DAA, earlier warning |
| SiK 915 MHz telemetry radio (PRIMARY C2) | Bounded-latency MAVLink command + telemetry between bridge and Pixhawk | Part 108 emphasizes a *characterised* C2 link; SiK + FHSS + AES-128 + MAVLink v2 signing has a known link budget. WiFi as primary fails this characterisation under multipath, foliage, and DFS evictions. |
| WiFi 5 GHz on dedicated drone SSID (SECONDARY) | High-bandwidth path for RTSP video and opportunistic MAVLink TCP | Non-safety-critical; degrades gracefully. Mission continues on SiK alone. |
| RC transmitter (always-on manual override) | RPIC takes the sticks anytime regardless of bridge state | RC failsafe → RTL via firmware |

### 5.9 RF Channel Plan

The aircraft, dock, RC, and house networks share three crowded ISM bands. Without a documented plan, ELRS desenses SiK, drone WiFi DFS-evicts mid-flight, and ESPHome dock loses MQTT during takeoff. This section pins channels, powers, and coexistence rules.

| Band | User | Power / mode | WA-relevant constraints | Coexistence notes |
|---|---|---|---|---|
| 1090 MHz | ADS-B In RX (uAvionix pingRX Pro) | RX only | passive | no emissions; never a coexistence source |
| 978 MHz | UAT ADS-B RX | RX only | passive | as above |
| 915 MHz ISM (902-928 MHz) | SiK primary C2, FHSS, AES-128 + MAVLink v2 signing | up to 30 dBm conducted per FCC Part 15.247 (1 W). Holybro/mRobotics SiK is 100 mW (20 dBm) at antenna port; with LMR-400 (~2 dB run loss) + 6 dBi outdoor antenna ≈ 24 dBm EIRP | **Do not use Crossfire 915 MHz for RC** — desenses the SiK receiver even with FHSS separation. Z-Wave 908.42 MHz sits 6.5 MHz below the SiK band edge and coexists in practice — call it out so future Z-Wave additions are reviewed. |
| 2.4 GHz channel 1 (2401-2423 MHz) | ESPHome dock WiFi (ESP32 fixed channel) | 14 dBm (default) | n/a | Channel 1 chosen for slight isolation from BLE adv channel 39 (2480) used by OpenDroneID. Dock WiFi is fallback only — PoE Ethernet is primary (per §5.5 dock connectivity). |
| 2.4 GHz, hopping 2400-2480 | ELRS RC manual override | up to 1 W (30 dBm) per Part 15.247 FHSS; typically 250 mW for line-of-sight ops within VLOS | Push house WiFi off 2.4 GHz entirely (or guest-only). ELRS will degrade 2.4 GHz WiFi during flight; that is expected and acceptable since the dock has PoE primary. |
| 2.4 GHz Bluetooth + WiFi MAC layer | OpenDroneID Remote ID broadcast | per FAA Part 89 broadcast Remote ID rule | declared via ArduPilot OpenDroneID native support (4.4+) | **Standard Remote ID strongly recommended for Part 108; Broadcast Module operationally insufficient for BVLOS** (control-station location not reliably transmitted by broadcast modules; most USS/UTM acceptance criteria assume Standard RID). Broadcast Module remains legal under Part 89 for Part 107 ops today. |
| 5 GHz channels 149/153/157/161 (UNII-3) | Drone WiFi SSID, video only, dedicated AP | up to 30 dBm | **Non-DFS** — chosen to prevent radar evictions interrupting video mid-flight | Lock channel statically (no auto-selection); do not allow band steering. House WiFi pinned away from these channels. PolyPhaser N-type DC-block lightning arrestor (~$60) on the outdoor 5 GHz feed alongside the 915 MHz arrestor — WA convergence-zone storm season is real. |
| 5 GHz channels 36-48, 100-144 | House WiFi (UNII-1, UNII-2A, UNII-2C with DFS) | 23-30 dBm | DFS allowed for house, not for drone | Separate physical AP from drone SSID. |
| 6 GHz LPI / Standard Power with AFC | Future upgrade path for drone video | per FCC 6 GHz rules; WA allows Standard Power outdoor with AFC | Clean spectrum, no coexistence with current load. ESP32-C6 is the SBC-class 6 GHz path. Defer until video uplink demands it. |

#### Aircraft antenna placement

- **915 MHz SiK** and **2.4 GHz ELRS RX** antennas separated by **≥50 cm** on the aircraft. Bands are ~1.5 GHz apart so no fundamental conflict, but near-field coupling at <50 cm desenses both.
- **5 GHz video antenna** mounted at least 30 cm from the GPS module — 5 GHz harmonics can pollute the GPS L1 receiver if antennas are co-located.
- **Remote ID broadcast antenna** (BLE/WiFi) is integrated into the OpenDroneID transmitter module; mount the module on the airframe top to avoid attenuation by frame and battery.

#### Channel selection procedure

Static assignment. If the operator brings up a new neighbour AP that takes channel 149, the manual fallback is 153 → 157 → 161; document the choice in the operations log. No automatic channel selection on the drone SSID — automation introduces non-determinism the safety case cannot accept.

#### Dock-specific RF guidance

- **Disable Bluetooth on the dock ESP32** (`CONFIG_BT_ENABLED=n` if custom; ESPHome `bluetooth_proxy` off). The dock has no BT use case and active BT scanning/advertising collides with OpenDroneID BLE broadcasts at close range during takeoff/landing.
- Route the dock's IPEX antenna feed away from PoE magnetics and any switching supplies; ferrite on the PoE cable entry to the enclosure.
- ESPHome YAML must declare `ethernet:` block **before** `wifi:` so the dock comes up wired-first and only attempts WiFi as fallback.

---

## 6. Platform Strategy

### 6.1 Why MAVLink

MAVLink is the lingua franca of open drone platforms. It is:
- **Platform-agnostic**: ArduPilot, PX4, Parrot, Skydio (X10D) all speak it
- **Stable**: MAVLink v2 has been stable for years. The investment does not rot.
- **Well-documented**: Full message spec at mavlink.io, mature Python libraries
- **IP-reachable**: UDP/TCP/serial — no proprietary SDK, no Android device, no RC controller in the software loop
- **Directly mappable**: The MQTT topic design maps nearly 1:1 to MAVLink messages

### 6.2 What MAVLink Replaces

The previous architecture used a DJI-specific Android bridge: a dedicated Android device running DJI Mobile SDK v4, translating proprietary DJI protocols to MQTT/RTMP. This approach had fundamental limitations:

- Required a physical Android device + RC controller permanently connected
- DJI Mobile SDK v4 is in maintenance mode — no bug fixes expected
- DJI is on the FCC Covered List (December 2025) — new models cannot receive FCC authorization
- Mavic 2 batteries, parts, and SDK support are degrading
- No path to Part 108 compliance (no DAA, no ADS-B, no UTM integration)
- The drone does not output any standard streaming protocol — a 4-stage proprietary video chain was required

MAVLink eliminates the entire proprietary translation layer. The bridge becomes a Python process connecting directly to the flight controller over IP.

### 6.3 Reference Aircraft Build

**Holybro X500 V2 + Pixhawk 6C + Raspberry Pi companion computer**

| Component | Specific Part | Approx. Cost |
|-----------|---------------|-------------|
| Frame + motors + ESCs + props | Holybro X500 V2 ARF kit | $280-$350 |
| Flight controller | Pixhawk 6C or CubePilot Cube Orange+ | $200-$400 |
| GPS (primary) | Holybro M10 or Here3 (RTK-capable) | $50-$150 |
| Telemetry radio (PRIMARY C2) | SiK 915 MHz pair (mRobotics or Holybro), with MAVLink v2 signing + AES-128 (`ATS15=1`); ground module installed indoors with LMR-400 to outdoor antenna on the eave (avoids weatherproofing the bridge host) | $80 |
| Telemetry antenna (outdoor, ground side) | 915 MHz vertical dipole (Comet GP-3 or similar), N-female bulkhead through eave; PolyPhaser IS-50UX-C2 lightning arrestor between antenna and feedline entry | $60 |
| Spare SiK pair (safety-critical hardware) | One bench unit on the shelf; air and ground modules are the safety C2 path | $80 |
| Companion computer | Raspberry Pi 5 (4GB+) | $60-$100 |
| Camera + gimbal | Siyi A8 Mini (3-axis, 4K, RTSP native) | $300-$400 |
| Batteries | 4S 5200mAh LiPo x3 | $120-$200 |
| Anti-collision strobe | Firehouse Technology ARC II or uAvionix | $30-$80 |
| Remote ID module | uAvionix ping Remote ID | $100-$150 |
| ADS-B In receiver | uAvionix pingRX Pro | $250-$350 |
| WiFi adapter (companion) — secondary, video-only | Alfa AWUS036ACS, 5 GHz non-DFS only (149/153/157/161 in WA) | $40-$80 |
| RC transmitter (manual override) | RadioMaster TX16S + ELRS 2.4 GHz receiver. **Do not use Crossfire 915 MHz** — collides with SiK 915 MHz primary C2 even with FHSS separation. | $150-$250 |
| Dock connectivity (PoE) | TP-Link TL-PoE10R splitter (12 V DC out) + Cat6 from house switch to dock through existing power conduit. Wired Ethernet is the dock's primary link; WiFi is fallback only. Eliminates the "dock cannot open lid for emergency landing" failure mode that pure WiFi creates. | $30 + cable |
| Misc (wiring, connectors, weatherproofing) | — | $100-$200 |
| **Total** | | **$1,700-$2,750** |

### 6.4 Platform Characteristics

| Attribute | Assessment |
|-----------|-----------|
| MAVLink support | Native — ArduPilot IS MAVLink |
| Waypoint missions | Up to 718 mission items. Spline waypoints, DO commands for camera/gimbal |
| Live streaming | Companion computer + camera → RTSP. Or Siyi A8 Mini serves RTSP directly |
| DAA capability | ADS-B In via pingRX + ArduPilot AP_Avoidance library |
| Remote ID | OpenDroneID supported in ArduPilot firmware |
| Firmware geofence | Polygon + altitude ceiling, enforced in flight controller firmware |
| Failsafe stack | GCS loss → RTL, low battery → RTL/land, geofence breach → RTL/land, EKF failure → land |
| Weather resistance | Open-frame dev kit, no IP rating. Requires significant weatherproofing — see Section 6.8 |
| Obstacle avoidance | None out of box. Add rangefinders (TF-Luna) for terrain following, forward LIDAR (Lightware LW20/C) for basic proximity |
| Battery life | ~18-22 minutes depending on payload |
| Flight time for 1-acre mission | 3-5 minutes — well within margin |

### 6.5 Alternative Platforms

| Platform | MAVLink | DAA Path | Blue UAS | Price | Verdict |
|----------|---------|----------|----------|-------|---------|
| Parrot ANAFI Ai | No (Olympe Python SDK — proprietary but open-source) | Possible with external ADS-B | ANAFI USA variant is listed | $4,000-$5,000 | Strong contender; Python SDK; RTSP native; less control than ArduPilot |
| Parrot ANAFI USA | No (Olympe) | Possible | Yes | $7,000-$8,000 | Blue UAS listed; otherwise same as ANAFI Ai |
| Skydio X10 | Yes (X10D variant) | Built-in | Yes (X10D) | $15,000-$25,000 | Enterprise-priced; productized version of this use case; overkill for residential |
| Custom ArduPilot (this design) | Native | Yes (pingRX + AP_Avoidance) | N/A (NDAA-compliant by construction) | $1,700-$2,750 | Maximum control, maximum learning, best Part 108 sensor integration |

### 6.6 The Airworthiness Question (Part 108)

The Part 108 NPRM's airworthiness acceptance framework is built around **manufacturers** issuing Declarations of Compliance. A homebuild ArduPilot quad does not have a "manufacturer" in the regulatory sense.

**Current uncertainty:** The NPRM does not clearly accommodate DIY/homebuilt UAS. The 3,000+ NPRM comments likely included pushback on this point, and the final rule may create a homebuilder pathway. As of today, a DIY build may not qualify for Part 108 operations.

**Mitigations:**
1. Use a commercial ArduPilot-based airframe (Holybro, CubePilot) from a vendor likely to pursue Declaration of Compliance
2. The ArduPilot project may pursue a means of compliance for the firmware itself
3. The software stack is airframe-agnostic — if Part 108 requires a specific manufacturer's DoC, swap the drone and keep the entire ground system intact
4. Monitor the final rule; if the homebuilder pathway is closed, Parrot ANAFI (Olympe SDK, Blue UAS) becomes the flight hardware with this open-source ground system

**Strategy:** Build on a commercial ArduPilot frame from a recognized manufacturer. Design the software to be airframe-agnostic. Wait for the final rule before committing to a specific compliance path.

### 6.7 What Is Lost by Leaving DJI

| Capability | DJI Mavic 2 | ArduPilot X500 V2 | Impact |
|-----------|-------------|-------------------|--------|
| Obstacle avoidance | Omnidirectional vision | None (add rangefinders for basic proximity) | Mitigate with altitude margins, conservative speed, well-planned corridors |
| Camera quality | Hasselblad 1" sensor, 3-axis gimbal, 4K HDR | Siyi A8 Mini or similar — good for security, not DJI-class optics | Sufficient for "is there a person in the driveway" at 80-120 ft |
| Flight time | 31 minutes | 18-22 minutes | 1-acre mission takes 3-5 minutes; margin is thinner but adequate |
| Consumer polish | Flies perfectly out of box | Requires assembly, PID tuning, vibration isolation | First 20 hours involve more tinkering; comparable reliability after tuning |
| Folding/portability | Folds to ~354mm diagonal | Fixed 500mm frame | Dock sizing increases. Not a showstopper |
| Part 108 path | None (no DAA, no ADS-B, aging SDK) | Full (ADS-B In, firmware geofence, OpenDroneID, configurable failsafe) | This is why we pivot |

### 6.8 Aircraft Weatherproofing

The X500 V2's weather resistance assessment ("open-frame dev kit, no IP rating, requires conformal coating") is the most operationally significant risk in this design. The dock's environmental controls (heating, ventilation, humidity management) protect the drone while staged, but do not address:

- **Condensation cycles:** A drone sitting on a shed roof in Seattle will experience daily dew-point crossings, especially in spring/fall. Moisture condenses on cold metal, wicks into connectors, and corrodes exposed PCBs — even inside a closed dock.
- **Rain during flight:** The alarm-response use case means flying in weather that triggered the alarm. Pacific Northwest drizzle is persistent and wind-driven.
- **Motor winding exposure:** Brushless motors on the X500 V2 are open-can designs. Water in the stator windings causes bearing corrosion and eventual motor failure.
- **ESC connector corrosion:** XT60/XT90 connectors and bullet connectors are not sealed. Moisture + current = galvanic corrosion at contact surfaces.

**This is not a software problem, but it can kill the entire project operationally.**

#### Required Weatherproofing (Before Outdoor Deployment)

| Component | Treatment | Detail |
|-----------|-----------|--------|
| Flight controller (Pixhawk 6C) | Silicone-sealed enclosure | Aftermarket waterproof Pixhawk case, or seal stock case with RTV silicone at seams. Vent with Gore-Tex membrane for pressure equalization without water ingress. |
| ESCs | Conformal coat + heat shrink | Apply MG Chemicals 422B or similar acrylic conformal coat to ESC PCBs. Heat-shrink over the entire ESC body. |
| Power distribution board | Conformal coat | Same acrylic conformal coat. Cover both sides. |
| Companion computer (RPi) | Sealed enclosure | Small IP65 ABS enclosure with cable glands for USB, serial, and antenna pigtails. |
| Motor windings | Corrosion-X or ACF-50 | Apply anti-corrosion lubricant to stator windings and bearings. Reapply quarterly. Does not make motors waterproof but dramatically slows corrosion. |
| All connectors (XT60, JST, servo) | Dielectric grease + silicone boot | Apply dielectric grease to contact surfaces before mating. Silicone boot or heat-shrink over mated connectors to prevent water pooling. |
| GPS module | Sealed or potted | GPS must remain RF-transparent — use conformal coat, not a metal enclosure. Some GPS modules (Here3) come with sealed housings. |
| ADS-B receiver (pingRX) | Conformal coat + mount in semi-enclosed bay | The antenna must remain exposed; the PCB must not. |
| Antenna connections (SMA, u.FL) | Silicone seal + self-amalgamating tape | Wrap all antenna connector joints to prevent water wicking into coax. |
| Wire harness | Split loom + drip loops | All wiring routed through split-loom conduit. Drip loops at entry points so water runs off rather than following wires into enclosures. |
| Frame joints | Thread-lock + silicone | Arm-to-body joints can loosen from vibration and admit water. Apply thread-lock to bolts, silicone bead at seams. |

#### Operational Weatherproofing (Dock + Aircraft Together)

| Measure | Purpose |
|---------|---------|
| Dock dew-point ventilation | Activate fan when interior humidity approaches dew point. Prevent condensation from forming on the drone at all. |
| Dock heating in cold weather | Keep interior above ambient dew point. PTC heater + BME280 sensor drive this automatically. |
| Dock drain channels | Direct any condensation away from the drone — tilt the landing pad slightly so water flows to weep holes, not pools under the drone. |
| Pre-flight condensation check | If dock humidity sensor shows recent dew-point crossing, delay launch until ventilation clears moisture. Automation gate, not just a recommendation. |
| Quarterly corrosion inspection | Visual inspection of motor bearings, connector surfaces, PCB coatings. Part of the battery rotation maintenance cycle. |
| Motor replacement budget | Budget for annual motor replacement. Open-can brushless motors in wet environments have ~12-18 month useful life even with treatment. Include in cost estimate. |

#### Alternative: IP-Rated Frame

If weatherproofing the X500 V2 proves too fragile in practice, the fallback is an IP-rated frame designed for wet environments:

| Frame | IP Rating | Compatibility | Price | Notes |
|-------|-----------|---------------|-------|-------|
| Holybro X500 V2 (weatherproofed) | None (DIY) | Pixhawk 6C native | $280-$350 + $100-$200 sealing materials | Reference build; requires all treatments above |
| ModalAI Sentinel | IP44 | PX4 native, MAVLink | ~$5,000-$8,000 | Purpose-built for outdoor persistent deployment; significantly higher cost |
| Custom carbon fiber enclosed frame | DIY IP43-54 | Pixhawk compatible | $500-$1,200 | Enclosed electronics bay with sealed motor mounts; more build effort |

The software stack is airframe-agnostic — switching frames requires mechanical work, not code changes.

---

## 7. Battery Lifecycle Management

### 7.1 The Core Problem

LiPo batteries degrade quickly when stored at high charge. They self-discharge (generating heat), bloat after relatively few cycles, and are designed for intermittent recreational use — not persistent readiness.

**Design mindset: batteries are consumables.** Plan for annual replacement.

### 7.2 Charge Strategy

| Role | SOC Target | Location | Rotation |
|------|------------|----------|----------|
| Hot standby (installed in drone) | 80-85% | In dock | Rotated weekly |
| Ready spare | 55-65% (storage band) | In charging area inside dock | Promoted to standby weekly |
| Charging / cooling | Cycling | Charging area | As needed |

**Inventory:** 3 batteries minimum.

### 7.3 Automated Maintenance (via HA)

| Automation | Trigger | Action |
|------------|---------|--------|
| Weekly rotation reminder | Schedule (Sunday AM) | Notify operator to swap batteries |
| Charge maintenance | Standby drops below 75% | Enable charger power outlet for bounded window |
| Thermal gating | Dock temp outside 5-40 C | Disable charger power |
| Quarterly deep cycle | Schedule (quarterly) | Remind operator to full cycle all packs |
| Swelling/degradation check | Every rotation | Visual inspection checklist notification |

**Note:** Monitor standby battery SOC more frequently than weekly — LiPo self-discharge may drop below the 75% threshold before weekly rotation, especially in warmer conditions.

### 7.4 What NOT To Attempt

- Permanent powered drone in dock
- DIY charging contacts on the aircraft
- Robotic battery swapping
- Unattended overnight charging cycles
- Third-party batteries in a dock scenario (highest failure item in unattended deployments)

---

## 8. Software Architecture

### 8.1 Deployment Model: Add-on + Integration

The system follows the same pattern as Frigate, Zigbee2MQTT, and Z-Wave JS: a **dedicated add-on** for the heavy backend, a **custom integration** for the HA glue. They communicate exclusively via MQTT.

**Why this split is necessary (not optional):**

1. **Compliance independence.** The compliance recorder must keep logging during HA Core restarts (which are routine — config changes, updates, add-on installs). The add-on container starts before HA Core and keeps running through HA restarts.
2. **Dependency isolation.** MAVSDK-Python depends on `grpcio`, `protobuf`, and a native `mavsdk_server` binary. These cannot be installed into HA's Python venv on HAOS, and `grpcio` version conflicts with HA Core are a known pain point. The add-on container isolates all of this.
3. **Process isolation.** A gRPC stall or MAVSDK memory leak cannot block HA's event loop or bring down other integrations.

**Deployment targets:**

| Environment | Bridge deployment | Integration deployment |
|-------------|------------------|----------------------|
| HAOS (primary target) | HA add-on (Supervisor-managed Docker container) | HACS custom integration |
| HA Container | Standalone Docker container (`docker-compose.yml` provided) | HACS custom integration |
| HA Core | systemd service or Docker container | Manual `custom_components/` install |

The MQTT contract is the interface — the integration works identically regardless of how the bridge is deployed.

### 8.1.1 Reference Deployment

The property runs a multi-host home infrastructure. The drone_hass components are mapped to the existing hosts to honour the compliance-independence principle (recorder cannot share a fate with HA Core) and to avoid forcing infrastructure relocation. All cross-host flows are catalogued in `docs/networking.md`.

**Subnet layout** (correct as of 2026-04; see `docs/networking.md` for the authoritative VLAN map):

| VLAN | Subnet | Role |
|---|---|---|
| 1 | 10.10.0.0/24 | Management (router 10.10.0.1) |
| 2 | 10.10.2.0/24 | Ubuntu LLM server (10.10.2.222) — Ollama, Plex, go2rtc, mediamtx, chronyd |
| 4 | 10.10.4.0/24 | Synology DS1819+ (10.10.4.186) — NAS, MinIO |
| 7 | 10.10.7.0/24 | IoT (e.g., generator monitor at 10.10.7.209) |
| 10 | 10.10.10.0/24 | HAOS host + drone integration components + ESPHome dock |
| 20 | 10.10.20.0/24 | Drone-side: companion RPi, Pixhawk telemetry — firewalled off the internet |

**Component placement:**

| Component | Host | Process / Container | Lifecycle | Backup target | Fail mode |
|---|---|---|---|---|---|
| Bridge add-on (`mavlink_mqtt_bridge` + ComplianceGate + compliance recorder + Litestream + OpenTimestamps client) | HAOS host (VLAN 10) | Docker via HA Supervisor | Auto-start before HA Core; survives HA restarts | Wrapped Ed25519 envelope to NAS `/volume1/llm_backup/drone_hass/keys/` (R-08); compliance DB to S3 + MinIO via Litestream | **fail-closed** — bridge down = no flights, no compliance writes |
| HA Integration (`custom_components/drone_hass`) | HAOS host (VLAN 10) | HA Core process | Tied to HA Core | HA snapshot covers `.storage/core.config_entries` | **fail-closed for new authorizations**; entities go unavailable; bridge keeps logging |
| Mosquitto broker | HAOS host (VLAN 10), `host_network: true` so it binds 10.10.10.x | Add-on | Supervisor-managed | passwd + ACL + persistence to NAS `/volume1/llm_backup/drone_hass/mosquitto/` | **fail-closed** — broker down = bridge ↔ HA blind |
| go2rtc (RTSP → WebRTC remux) | Ubuntu LLM (10.10.2.222) | systemd unit (existing media stack) | Independent | Config in repo | fail-open for live video; recordings continue via mediamtx |
| mediamtx (RTSP recording, 30-day rolling) | Ubuntu LLM (10.10.2.222) | systemd unit | Independent | NFS-mounted to NAS `/volume1/Movies/drone_recordings/` | fail-open for recording; live stream continues |
| chronyd stratum-2 (NTS upstream, serves VLAN 10 + 20) | Ubuntu LLM (10.10.2.222) | systemd unit | Independent | Config in repo | fail-degraded — HAOS systemd-timesyncd takes over for VLAN 10; VLAN 20 holds local crystal until restored |
| HAOS host NTP client (and Synology NTP client) | respective hosts | systemd-timesyncd / chronyc | with host | n/a | fail-degraded — hold local crystal, ~36 ms/hour drift |
| Litestream replication (live in bridge container) | Inside bridge add-on | Sidecar process | with bridge | n/a (it IS the backup) | fail-degraded — chain still writes locally; pre-arm fails after `litestream_replication_lag_s > 5` in Part 108 mode (R-07) |
| Litestream primary replica target | S3 us-west-2 with Object Lock COMPLIANCE 3 yr | AWS managed | independent | n/a | fail-degraded — bridge falls back to MinIO replica until S3 reachable |
| Litestream secondary replica target | MinIO on Synology (10.10.4.186) | DSM Docker container | DSM | DSM snapshot | fail-degraded — S3 still primary |
| Litestream S3 IAM credentials | HA Supervisor secrets, env-mounted into bridge add-on | n/a | with bridge | password manager + paper backup of IAM access key + secret | fail-closed for replication; rotate quarterly |
| OpenTimestamps client (chain anchor) | Inside bridge add-on container | Scheduled task (hourly) | with bridge | n/a; proofs land in compliance DB and replicate via Litestream | fail-open — anchor latency increases, chain integrity unaffected |
| ESPHome dock controller | Dock ESP32 (VLAN 10) | ESP-IDF firmware | independent of HAOS | source repo + secrets vault; OTA password rotated per build | **fail-safe** — interlocks enforced in firmware regardless of HA/bridge state (R-26 hardware smoke-relay; lid current-sense end-stop) |
| Pixhawk 6C flight controller | Airframe | ArduPilot firmware | independent | parameter `.parm` file backup pre/post each tuning session, mirrored to NAS | **fail-safe** — firmware geofence + AP_Avoidance + RTL/ALT_HOLD failsafes operate without bridge or HA |
| Companion RPi (MAVLink router, gpsd refclock for chronyd, RTSP source) | Airframe (VLAN 20) | systemd units | independent | image clone after first config; mirrored to NAS | fail-degraded — bridge loses telemetry/video but Pixhawk continues autonomously to RTL |

**Cross-VLAN traffic note:** Synology and Ubuntu LLM serve other tenants (NAS shares, LLM/Plex) and are not relocated to VLAN 10. The cross-VLAN flows (HAOS↔Ubuntu for go2rtc/chronyd, HAOS↔Synology for MinIO/NFS) cross the ASUS router at wire speed (~0.2 ms added latency). AiProtection and adaptive QoS are disabled on the inter-VLAN paths between 10.10.10.x ↔ 10.10.2.x and 10.10.10.x ↔ 10.10.4.x to avoid CPU bottlenecks. Service discovery uses IP literals or split-horizon DNS (`mosquitto.drone.lan`, `chrony.drone.lan`) — no `.local` mDNS dependency. ASUS DNS-rebind protection has explicit exceptions for the local zone.

### 8.2 High-Level Overview

<p align="center"><img src="https://raw.githubusercontent.com/acato/drone_hass/main/docs/diagrams/system-overview.svg" alt="System Architecture"></p>

### 8.3 Bridge Add-on

**Purpose:** Owns the drone. Translates between MAVLink and MQTT. Records compliance data. Enforces the ComplianceGate. Runs independently of HA Core.

**Technology:** Python 3.12+, MAVSDK-Python (async), aiomqtt, SQLite (compliance DB)

**Container:** Docker, managed by HA Supervisor on HAOS. Uses S6-overlay init system. Multi-arch (amd64, aarch64). Bundles the `mavsdk_server` native binary per architecture. armv7 is not supported: no upstream `mavsdk_server` prebuilt exists for 32-bit ARM, and source builds are out of scope for the pipeline. aarch64 covers Raspberry Pi 4/5 with a 64-bit OS, which is the realistic SBC target.

**Add-on metadata:**

```yaml
name: "drone_hass MAVLink Bridge"
slug: "drone_hass_bridge"
startup: system          # Starts before HA Core
boot: auto               # Auto-starts on HA boot
arch: [amd64, aarch64]
ports:
  14540/udp: 14540       # MAVLink UDP (MAVSDK default)
  14550/udp: 14550       # MAVLink UDP (GCS)
map:
  - media:rw             # Flight video storage
  - ssl:ro               # MQTT TLS certs
ingress: true            # Web UI for compliance log browsing
ingress_port: 8099
panel_icon: "mdi:drone"
options:
  mavlink_connection: "udp://:14540"
  mqtt_host: "core-mosquitto"
  mqtt_port: 1883
  drone_id: "patrol"
  operational_mode: "part_107"
```

**Key lifecycle behavior:**
- Starts before HA Core — bridge is ready when the integration loads
- Keeps running when HA Core restarts (config changes, updates)
- Supervisor auto-restarts on crash
- Compliance SQLite DB in `/data/compliance/` — persists across add-on updates, included in HA backups

**Responsibilities:**
- Connect to flight controller via MAVSDK-Python (UDP/TCP/serial)
- Publish telemetry to MQTT (downsampled from MAVLink rates to 1 Hz; burst during missions)
- Subscribe to MQTT command topics, translate to MAVLink commands, publish responses
- Upload and monitor missions (MAVLink mission protocol)
- Monitor ADS-B traffic (ADSB_VEHICLE messages), publish to MQTT, log DAA events
- Enforce ComplianceGate (Part 107 or Part 108 mode)
- Write compliance records to SQLite (append-only, hash-chained)
- Validate missions against operational area before upload
- Monitor flight controller heartbeat; publish connection state
- Publish add-on health to `drone_hass/bridge/{instance_id}/status`
- MQTT Last Will and Testament: `"offline"` on disconnect

### 8.4 HA Integration

**Purpose:** Owns the HA experience. Entities, services, config flow, dashboard. Pure MQTT consumer — no heavy dependencies.

**Technology:** Python 3.12+, `homeassistant.components.mqtt` (HA's managed MQTT client)

**Uses HA's built-in MQTT component** (`mqtt.async_subscribe`, `mqtt.async_publish`), NOT a standalone aiomqtt client. This means:
- Single MQTT connection (HA's existing broker config)
- No duplicate credentials
- Reconnection and TLS handled by HA's MQTT component
- Requires HA's MQTT integration to be configured (reasonable prerequisite)

**Responsibilities:**
- Config flow (drone discovery via MQTT, legal acknowledgment, media server URL)
- DroneMqttCoordinator (subscribes to `drone_hass/{drone_id}/#`, maintains state dict, pushes entity updates)
- All entity platforms (sensor, binary_sensor, camera, device_tracker)
- Service handlers (publish MQTT commands, await correlation-ID responses)
- HA event firing (alarm response, DAA alerts, compliance events)

### 8.5 User Installation

1. Add GitHub repository as custom add-on repository in HA
2. Install "drone_hass MAVLink Bridge" add-on, configure MAVLink connection + drone ID
3. Start the add-on
4. Install `drone_hass` integration via HACS
5. Add integration — config flow discovers the drone (already publishing on MQTT from the running add-on)

### 8.6 Video Pipeline

The MAVLink pivot eliminates the proprietary DJI video chain entirely.

**Previous (DJI):** Aircraft → OcuSync RF (proprietary) → RC (proprietary USB) → Android SDK decode → RTMP re-encode → media server. Four stages, three protocol translations, all proprietary.

**Current (MAVLink):** Aircraft camera serves RTSP over IP → media server pulls RTSP → done.

| Implementation | How |
|---------------|-----|
| Siyi A8 Mini (or similar IP camera payload) | Camera serves RTSP directly on its own IP address |
| RPi companion + USB/CSI camera | GStreamer pipeline encodes H.264, serves RTSP via `gst-rtsp-server` or mediamtx |

The media server (go2rtc or mediamtx) **pulls** the RTSP stream. go2rtc handles this natively. The HA camera entity points at the media server — unchanged from previous design.

**Live stream specs:**

| Parameter | Value |
|-----------|-------|
| Protocol | RTSP (native from camera or companion computer) |
| Codec | H.264 |
| Resolution | Up to 4K (depends on camera hardware; not limited to 720p like DJI live stream) |
| Latency | 100-300ms glass-to-glass (vs 500-1500ms with DJI chain) |
| Recording | Server-side from RTSP stream (mediamtx native recording or FFmpeg sidecar) AND optionally onboard on companion computer |

**Recording advantage:** No more "retrieve SD card after flight" — video is recorded server-side from the stream and optionally onboard. Both copies are available immediately after landing.

### 8.7 ComplianceGate

The bridge includes a mode-switching compliance gate:

```python
class OperationalMode(Enum):
    PART_107 = "part_107"    # Human authorization required
    PART_108 = "part_108"    # Autonomous with Flight Coordinator monitoring

class ComplianceGate:
    # Margin between max waypoint altitude and the operational ceiling, in metres.
    # Tuned to baro-noise + thermal lift on warm days so a benign mission does not
    # nuisance-trip the firmware fence at apex. See §11.3 altitude invariant.
    WAYPOINT_CEILING_MARGIN_M = 5.0

    async def authorize_flight(self, mission, context):
        # Common gates (both modes)
        if not await self._safety_checks_pass(context):
            return False
        if not self._mission_within_operational_area(mission):
            return False
        if not self._mission_waypoints_under_ceiling(mission):
            return False                                            # added per task #12
        if not self._weather_within_envelope(context):
            return False

        if self.mode == OperationalMode.PART_107:
            return await self._wait_for_rpic_authorization(timeout=120)

        elif self.mode == OperationalMode.PART_108:
            if not self._daa_system_healthy():
                return False
            if not self._flight_coordinator_on_duty():
                return False
            await self._log_autonomous_authorization(mission, context)
            await self._notify_flight_coordinator(mission)
            return True

    def _mission_waypoints_under_ceiling(self, mission):
        """Reject missions whose tallest waypoint sits within WAYPOINT_CEILING_MARGIN_M
        of the operational ceiling. Baro noise + thermal lift can push the actual
        flown altitude above the planned waypoint by 1-3 m on a warm day; without
        the margin the firmware fence at FENCE_ALT_MAX trips at apex."""
        ceiling = self.config.operational_area.altitude_ceiling_m   # 55 m today
        max_wp_alt = max(wp.alt_m for wp in mission.waypoints)
        if max_wp_alt > ceiling - self.WAYPOINT_CEILING_MARGIN_M:
            self._reject(
                code='waypoint_too_high',
                detail=f"max waypoint altitude {max_wp_alt:.1f} m exceeds "
                       f"ceiling {ceiling} m minus {self.WAYPOINT_CEILING_MARGIN_M} m margin",
                mission_id=mission.id,
            )
            return False
        # Also enforce floor — landing approaches shouldn't plan below 0 m AGL.
        min_wp_alt = min(wp.alt_m for wp in mission.waypoints if wp.alt_m is not None)
        floor = self.config.operational_area.altitude_floor_m       # 0 m today
        if min_wp_alt < floor:
            self._reject(code='waypoint_too_low',
                         detail=f"waypoint altitude {min_wp_alt:.1f} m below floor {floor} m",
                         mission_id=mission.id)
            return False
        return True
```

The check is applied at three points in the mission lifecycle:

1. **Mission upload** — bridge runs `_mission_waypoints_under_ceiling()` before forwarding any `MISSION_ITEM_INT` to the FC. Reject = log compliance event + return error to HA.
2. **Pre-arm** — runs again immediately before issuing arm-and-takeoff. Catches a mission that was uploaded valid but became invalid after an operational-area config change.
3. **Mid-flight ceiling watchdog** — bridge subscribes to telemetry and triggers an RTL via `MAV_CMD_NAV_RETURN_TO_LAUNCH` if `relative_alt_m > altitude_ceiling_m - WAYPOINT_CEILING_MARGIN_M`. ArduPilot's own `FENCE_ALT_MAX` is the firmware backstop; this is the bridge's earlier-warning watchdog.

The rejection is logged into the compliance chain with the mission ID, the rejected waypoint altitude, and the operative ceiling, so audit can confirm the gate ran on every attempt.

---

## 9. MQTT Topic Design

### 9.1 Topic Namespace

All topics under `drone_hass/{drone_id}/` where `drone_id` is the aircraft identifier.

### 9.2 Telemetry (Bridge → HA)

QoS 0 for high-frequency data, QoS 1 for state changes.

```
drone_hass/{drone_id}/telemetry/flight        (1 Hz; from GLOBAL_POSITION_INT + GPS_RAW_INT + HEARTBEAT)
{
  "lat": 47.6062, "lon": -122.3321,
  "alt": 45.2,                    // meters relative to takeoff
  "heading": 127.5,               // degrees
  "speed_x": 2.1, "speed_y": -0.5, "speed_z": 0.0,
  "ground_speed": 2.16,           // m/s
  "flight_mode": "AUTO",          // ArduPilot modes: GUIDED, LOITER, AUTO, STABILIZE, RTL, LAND
  "armed": true, "is_flying": true,
  "gps_fix": 3,                   // 0=no, 2=2D, 3=3D
  "satellite_count": 14,
  "timestamp": 1739980800
}

drone_hass/{drone_id}/telemetry/battery       (0.2 Hz; from BATTERY_STATUS)
{
  "charge_percent": 78,
  "voltage_mv": 15200, "current_ma": -2100,
  "temperature_c": 32,
  "remaining_mah": 2800, "full_charge_mah": 3600,
  "flight_time_remaining_s": 1200,
  "timestamp": 1739980800
}

drone_hass/{drone_id}/telemetry/gimbal        (1 Hz; from GIMBAL_DEVICE_ATTITUDE_STATUS)
{ "pitch": -45.0, "roll": 0.2, "yaw": 127.5, "mode": "YAW_FOLLOW" }

drone_hass/{drone_id}/telemetry/camera        (on change; from CAMERA_CAPTURE_STATUS)
{
  "is_recording": true, "recording_time_s": 45,
  "storage_remaining_mb": 28500
}

drone_hass/{drone_id}/telemetry/signal        (1 Hz; from RADIO_STATUS or WiFi RSSI)
{ "rssi": -62, "remote_rssi": -68, "noise": 40 }

drone_hass/{drone_id}/telemetry/position      (0.1 Hz; for device tracker — reduces HA recorder churn)
{ "lat": 47.6062, "lon": -122.3321, "alt": 45.2 }
```

### 9.3 DAA Traffic (Bridge → HA)

```
drone_hass/{drone_id}/daa/traffic             (on detection; from ADSB_VEHICLE)
{
  "icao": "A12345",
  "callsign": "N12345",
  "lat": 47.610, "lon": -122.330,
  "altitude_m": 300,
  "heading": 90,
  "ground_speed_mps": 50,
  "distance_m": 1200,
  "threat_level": "none",         // none, advisory, warning, critical
  "timestamp": 1739980800
}

drone_hass/{drone_id}/daa/avoidance           (on avoidance maneuver)
{
  "trigger_icao": "A12345",
  "action": "climb",              // climb, descend, lateral, hold
  "original_alt": 30.0,
  "new_alt": 45.0,
  "timestamp": 1739980800
}
```

### 9.4 State (Bridge → HA)

QoS 1, `retain: true`.

```
drone_hass/{drone_id}/state/connection     "online" | "offline"  (LWT = "offline")
drone_hass/{drone_id}/state/flight         "landed" | "airborne" | "returning_home" | "landing"
drone_hass/{drone_id}/state/mission        { "status": "idle|uploading|executing|paused|completed|error",
                                             "mission_id": null, "progress": 0.0,
                                             "current_waypoint": 0, "total_waypoints": 0, "error": null }
drone_hass/{drone_id}/state/stream         { "is_streaming": true, "rtsp_url": "rtsp://...",
                                             "resolution": "1080p", "bitrate_kbps": 5000 }
drone_hass/{drone_id}/state/daa            { "healthy": true, "contacts": 0, "last_check": 1739980800 }
drone_hass/{drone_id}/state/compliance     { "mode": "part_107", "fc_on_duty": true,
                                             "operational_area_valid": true }
```

### 9.5 Commands (HA → Bridge)

QoS 1. Request/response pattern with correlation IDs.

```
drone_hass/{drone_id}/command/{action}
  { "id": "uuid", "params": { ... } }

drone_hass/{drone_id}/command/{action}/response
  { "id": "uuid", "success": true, "error": null, "data": { ... } }
```

**Available commands:**

| Category | Commands |
|----------|----------|
| Flight | `arm`, `takeoff`, `land`, `return_to_home`, `cancel_rth` |
| Mission | `execute_mission` (params: `mission_id`), `pause_mission`, `resume_mission`, `stop_mission` |
| Camera | `take_photo`, `start_recording`, `stop_recording` |
| Gimbal | `set_gimbal` (params: `pitch`, `mode`), `reset_gimbal` |
| Stream | `start_stream`, `stop_stream` |
| System | `set_home` (params: `lat`, `lon`) |
| Compliance | `set_operational_mode` (params: `mode`), `set_fc_on_duty` (params: `on_duty`, `fc_id`) |

**Virtual stick / manual attitude control is intentionally NOT exposed as an HA service.** It bypasses all mission-level safety validation — geofence, altitude ceiling, speed limits, operational area. The security model (Section 13) is built around mission-level commands with validation layers. Raw attitude control at 50 Hz with no waypoint validation, accessible from any HA automation or compromised instance, is an unacceptable risk. Manual control is available only via the RC transmitter (hardware backup), not through software.

### 9.6 Mission Definitions (HA → Bridge)

Retained MQTT messages cached by the bridge:

```
drone_hass/{drone_id}/missions/{mission_id}   (retained)
{
  "id": "full_perimeter",
  "name": "Full Perimeter Sweep",
  "speed_mps": 5.0,
  "finish_action": "RTL",
  "heading_mode": "AUTO",
  "flight_path_mode": "SPLINE",
  "waypoints": [
    { "lat": 47.6062, "lon": -122.3321, "alt": 24.4,
      "speed_mps": 5.0, "gimbal_pitch": -45.0,
      "stay_ms": 2000, "actions": ["TAKE_PHOTO"] },
    { "lat": 47.6065, "lon": -122.3318, "alt": 33.5,
      "speed_mps": 3.0, "gimbal_pitch": -90.0,
      "stay_ms": 0, "actions": ["START_RECORD"] }
  ]
}
```

The bridge translates this JSON format to MAVLink mission items: each waypoint becomes `MAV_CMD_NAV_WAYPOINT`, camera/gimbal actions become DO commands between waypoints, `finish_action: RTL` becomes a final `MAV_CMD_NAV_RETURN_TO_LAUNCH`.

All missions are validated against the operational area (Section 11.3) before upload. Waypoints outside the operational area polygon or above the altitude ceiling are rejected.

---

## 10. HA Integration Design

### 10.1 Entities

#### Sensors

| Entity ID | Device Class | Unit | Source |
|-----------|-------------|------|--------|
| `sensor.{name}_battery` | `battery` | `%` | `telemetry/battery → charge_percent` |
| `sensor.{name}_altitude` | `distance` | `m` | `telemetry/flight → alt` |
| `sensor.{name}_ground_speed` | `speed` | `m/s` | `telemetry/flight → ground_speed` |
| `sensor.{name}_gps_satellites` | — | — | `telemetry/flight → satellite_count` |
| `sensor.{name}_signal_rssi` | `signal_strength` | `dBm` | `telemetry/signal → rssi` |
| `sensor.{name}_battery_temperature` | `temperature` | `°C` | `telemetry/battery → temperature_c` |
| `sensor.{name}_flight_mode` | — | — | `telemetry/flight → flight_mode` |
| `sensor.{name}_heading` | — | `°` | `telemetry/flight → heading` |
| `sensor.{name}_flight_time_remaining` | `duration` | `s` | `telemetry/battery → flight_time_remaining_s` |
| `sensor.{name}_mission_status` | — | — | `state/mission → status` |
| `sensor.{name}_daa_contacts` | — | — | `state/daa → contacts` |
| `sensor.{name}_operational_mode` | — | — | `state/compliance → mode` |

#### Binary Sensors

| Entity ID | Device Class | Source |
|-----------|-------------|--------|
| `binary_sensor.{name}_connected` | `connectivity` | `state/connection` |
| `binary_sensor.{name}_airborne` | — | `state/flight ∈ {airborne, returning_home}` |
| `binary_sensor.{name}_armed` | — | `telemetry/flight → armed` |
| `binary_sensor.{name}_recording` | — | `telemetry/camera → is_recording` |
| `binary_sensor.{name}_streaming` | — | `state/stream → is_streaming` |
| `binary_sensor.{name}_daa_healthy` | — | `state/daa → healthy` |
| `binary_sensor.{name}_fc_on_duty` | — | `state/compliance → fc_on_duty` |

#### Camera

| Entity ID | Source |
|-----------|--------|
| `camera.{name}_live` | Media server stream URL (RTSP → WebRTC via go2rtc) |

#### Device Tracker

| Entity ID | Source |
|-----------|--------|
| `device_tracker.{name}` | `telemetry/position → lat, lon` (0.1 Hz — reduces recorder churn) |

### 10.2 Services

| Service | Description | Fields |
|---------|-------------|--------|
| `drone_hass.execute_mission` | Upload and execute waypoint mission | `mission_id` (required) |
| `drone_hass.return_to_home` | Command RTL | — |
| `drone_hass.takeoff` | Arm and take off to hover altitude | — |
| `drone_hass.land` | Land at current position | — |
| `drone_hass.take_photo` | Capture single photo | — |
| `drone_hass.start_recording` | Begin video recording | — |
| `drone_hass.stop_recording` | Stop video recording | — |
| `drone_hass.start_stream` | Start RTSP live stream relay | — |
| `drone_hass.stop_stream` | Stop live stream | — |
| `drone_hass.set_gimbal` | Set gimbal pitch angle | `pitch` (-90 to +30) |
| `drone_hass.pause_mission` | Pause executing mission (hold position) | — |
| `drone_hass.resume_mission` | Resume paused mission | — |
| `drone_hass.stop_mission` | Abort mission (hover in place) | — |
| `drone_hass.set_fc_on_duty` | Toggle Flight Coordinator on-duty status | `on_duty` (bool), `fc_id` (string) |
| `drone_hass.log_compliance_event` | Write a compliance record | `event` (string), `details` (dict) |

### 10.3 Coordinator Design

The coordinator is **MQTT-subscription based** (not polling). It uses `homeassistant.components.mqtt` — HA's managed MQTT client — not a standalone aiomqtt connection.

```python
from homeassistant.components import mqtt

class DroneMqttCoordinator:
    """Subscribes to MQTT topics and maintains drone state.

    Uses HA's built-in MQTT component (single shared broker connection,
    no duplicate credentials, reconnection handled by HA).
    """

    def __init__(self, hass, entry):
        self.hass = hass
        self.data = {
            "connection": "offline",
            "flight": {}, "battery": {}, "gimbal": {},
            "camera": {}, "signal": {}, "mission": {},
            "stream": {}, "daa": {}, "compliance": {},
        }
        self._listeners = []
        self._unsubscribe = None
        self._drone_id = entry.data["drone_id"]

    async def async_start(self):
        """Subscribe to all drone topics via HA's MQTT integration."""
        self._unsubscribe = await mqtt.async_subscribe(
            self.hass,
            f"drone_hass/{self._drone_id}/#",
            self._on_message,
            qos=1,
        )

    async def _on_message(self, msg):
        """Route MQTT messages to data buckets, notify entity listeners."""

    async def async_send_command(self, action, params=None):
        """Publish command via HA MQTT, wait for correlation-ID response (10s timeout)."""
        await mqtt.async_publish(
            self.hass,
            f"drone_hass/{self._drone_id}/command/{action}",
            payload=json.dumps({"id": str(uuid4()), "params": params or {}}),
            qos=1,
        )
```

The integration does not manage its own MQTT connection. It relies on HA's MQTT integration being configured (a prerequisite checked in the config flow).

### 10.4 Config Flow

<p align="center"><img src="https://raw.githubusercontent.com/acato/drone_hass/main/docs/diagrams/config-flow.svg" alt="Config Flow"></p>

### 10.5 Alarm-Triggered Automation

**Part 107 mode:**

```yaml
automation:
  - alias: "Drone Security Patrol — Part 107"
    trigger:
      - platform: state
        entity_id: alarm_control_panel.home
        to: "triggered"
    condition:
      - condition: state
        entity_id: sensor.drone_operational_mode
        state: "part_107"
      # Safety gates
      - condition: state
        entity_id: binary_sensor.drone_connected
        state: "on"
      - condition: numeric_state
        entity_id: sensor.drone_battery
        above: 30
      - condition: state
        entity_id: binary_sensor.drone_airborne
        state: "off"
      - condition: state
        entity_id: binary_sensor.dock_smoke
        state: "off"
      - condition: numeric_state
        entity_id: sensor.dock_temperature
        above: 5
        below: 40
      - condition: state
        entity_id: binary_sensor.drone_daa_healthy
        state: "on"
      # Weather checks (local instruments)
      - condition: numeric_state
        entity_id: sensor.dock_wind_speed
        below: 15
      - condition: state
        entity_id: binary_sensor.dock_rain
        state: "off"
    action:
      - service: drone_hass.log_compliance_event
        data:
          event: "patrol_initiated"
          details:
            trigger: "alarm"
            mode: "part_107"
            weather: "{{ states('sensor.dock_wind_speed') }} mph wind"
            battery: "{{ states('sensor.drone_battery') }}%"

      - service: cover.open_cover
        entity_id: cover.drone_dock_lid
      - wait_for_trigger:
          - platform: state
            entity_id: binary_sensor.dock_lid_open
            to: "on"
        timeout: "00:00:30"

      # RPIC authorization (Part 107 compliance step)
      - service: notify.mobile_app_pilot_phone
        data:
          title: "Perimeter Alert"
          message: >
            Alarm triggered. Battery {{ states('sensor.drone_battery') }}%.
            Wind {{ states('sensor.dock_wind_speed') }} mph.
            DAA healthy. Dock open. Mission: full_perimeter.
          data:
            actions:
              - action: "LAUNCH_DRONE"
                title: "LAUNCH DRONE"
              - action: "IGNORE"
                title: "Ignore"

      - wait_for_trigger:
          - platform: event
            event_type: mobile_app_notification_action
            event_data:
              action: "LAUNCH_DRONE"
        timeout: "00:02:00"
        continue_on_timeout: false

      - service: drone_hass.log_compliance_event
        data:
          event: "rpic_authorized"
          details:
            authorization_time: "{{ now().isoformat() }}"

      - service: drone_hass.start_stream
      - service: drone_hass.execute_mission
        data:
          mission_id: "full_perimeter"

      - wait_for_trigger:
          - platform: state
            entity_id: sensor.drone_mission_status
            to: "completed"
        timeout: "00:10:00"

      - service: drone_hass.stop_stream
      - delay: "00:00:30"
      - service: cover.close_cover
        entity_id: cover.drone_dock_lid
```

**Part 108 mode:**

```yaml
automation:
  - alias: "Drone Security Patrol — Part 108 Autonomous"
    trigger:
      - platform: state
        entity_id: alarm_control_panel.home
        to: "triggered"
    condition:
      - condition: state
        entity_id: sensor.drone_operational_mode
        state: "part_108"
      # All Part 107 safety gates PLUS:
      - condition: state
        entity_id: binary_sensor.drone_fc_on_duty
        state: "on"
      - condition: state
        entity_id: binary_sensor.drone_daa_healthy
        state: "on"
      # Same weather, battery, dock conditions as Part 107
    action:
      - service: drone_hass.log_compliance_event
        data:
          event: "autonomous_launch_initiated"
          details:
            trigger: "alarm"
            mode: "part_108"
            coordinator: "{{ states('sensor.flight_coordinator_id') }}"
            weather: "{{ states('sensor.dock_wind_speed') }} mph wind"

      # NO human tap — autonomous launch
      - service: cover.open_cover
        entity_id: cover.drone_dock_lid
      - wait_for_trigger:
          - platform: state
            entity_id: binary_sensor.dock_lid_open
            to: "on"
        timeout: "00:00:30"

      - service: drone_hass.start_stream
      - service: drone_hass.execute_mission
        data:
          mission_id: "full_perimeter"

      # Notify Flight Coordinator (monitoring, not gating)
      - service: notify.mobile_app_pilot_phone
        data:
          title: "Autonomous Mission Launched"
          message: >
            Full perimeter sweep in progress.
            Battery {{ states('sensor.drone_battery') }}%.
            Tap to override.
          data:
            actions:
              - action: "ABORT_MISSION"
                title: "ABORT"
              - action: "RTH_NOW"
                title: "RETURN HOME"

      - wait_for_trigger:
          - platform: state
            entity_id: sensor.drone_mission_status
            to: "completed"
        timeout: "00:10:00"

      - service: drone_hass.stop_stream
      - delay: "00:00:30"
      - service: cover.close_cover
        entity_id: cover.drone_dock_lid
```

---

## 11. Compliance Framework

> **Layers:** the compliance framework spans Levels 1 (project architecture, including the two-tier recorder primitive), 2 (risk-based regulatory concepts: occurrence reporting, audit chain, insurance validation) and 5 (per-jurisdiction ComplianceGate mode, retention classes, DPIA overlay). See `regulatory-layered-model.md`.

### 11.1 Purpose

Part 108 requires flight data recording, quality assurance, and auditability. This framework is implemented from day one — it makes Part 107 operations better now and becomes the evidence base for the Part 108 Permit application. The same framework serves EU Specific-category operational authorisations (SORA, Level 3) via the per-country ComplianceGate modes — see `regulatory-eu.md` and the two-tier recorder spec in `compliance-recorder-two-tier.md`.

### 11.2 Compliance Recorder

A module within the bridge add-on that writes structured, append-only records to a SQLite database. NOT stored in HA's recorder database — a dedicated, independent store with audit trail properties.

**Storage:** SQLite database at `/data/compliance/compliance.db` inside the add-on container. This path maps to the Supervisor's persistent add-on data directory on HAOS. Survives add-on updates, HA Core updates, and HA OS updates. Included in HA full backups automatically.

**Why SQLite:**
- Full SQL query capability for Permit applications (`SELECT COUNT(*) FROM flights WHERE date BETWEEN ? AND ?`)
- Single file — easy to back up, export, copy for FAA submissions
- WAL mode provides concurrent read access while the bridge is writing
- Zero external dependencies (`sqlite3` is in Python's standard library)
- Append-only enforcement at the application layer (bridge never issues UPDATE or DELETE)

**Properties:**
- Append-only (no record modification after write)
- Timestamped (UTC, ISO 8601)
- **Ed25519 signed**: each record is signed with a private key generated at first install, stored separately from the database. The public key is exportable — an FAA inspector or anyone can independently verify the chain without access to the application
- **Hash-chained**: each record stores `SHA-256(prev_hash + record_type + timestamp + payload)` linking it to the previous record. Proves no records were removed or altered mid-chain
- Queryable via SQL for aggregate statistics
- Exportable to JSON/CSV/PDF via add-on Ingress web UI or service call (for FAA Permit applications)
- **Replicated off-device** via Litestream (continuous WAL streaming to S3, GCS, NAS, or local path). Eliminates single-device failure as a compliance data loss scenario

**Why signatures, not just hashes:** A bare hash chain proves records were not altered *after insertion*, but does not prove *who wrote them* or that the entire chain was not rebuilt from scratch with fabricated data. Ed25519 signatures bind each record to the signing key generated at install. For an NTSB investigation or civil litigation, this is the difference between "there is a hash chain" and "there is a cryptographically signed audit trail with an independently verifiable public key."

**Why Litestream replication:** One SQLite file on one device (potentially an SD card on a Pi) is a single point of failure. Litestream is a single Go binary (~15 MB) bundled in the add-on that continuously replicates WAL frames to a configured target. ~1 second recovery point objective. Zero changes to SQLite application code.

**Storage requirements:** For compliance operations, use SSD or NVMe storage, not an SD card. Enable Litestream replication to an off-device target. SD cards have poor `fsync()` behavior and limited write endurance.

**Schema (with versioning):**

```sql
-- Version tracking (checked and migrated on startup)
CREATE TABLE schema_version (
    version INTEGER NOT NULL
);

CREATE TABLE compliance_records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    record_type TEXT NOT NULL,
    drone_id TEXT NOT NULL,
    timestamp_utc TEXT NOT NULL,
    payload TEXT NOT NULL,          -- JSON blob
    prev_hash TEXT NOT NULL,
    record_hash TEXT NOT NULL,
    signature TEXT NOT NULL,        -- Ed25519 signature (base64)
    signing_key_id TEXT NOT NULL    -- fingerprint of the signing key
);

CREATE INDEX idx_records_type ON compliance_records(record_type);
CREATE INDEX idx_records_drone ON compliance_records(drone_id);
CREATE INDEX idx_records_timestamp ON compliance_records(timestamp_utc);

CREATE TABLE telemetry_archive (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    flight_id TEXT NOT NULL,
    drone_id TEXT NOT NULL,
    timestamp_utc TEXT NOT NULL,
    telemetry_json TEXT NOT NULL
);

CREATE INDEX idx_telemetry_flight ON telemetry_archive(flight_id);
```

**Schema migration policy:**
- Hand-written migration functions (`migrate_v1_to_v2()`, etc.) — no ORM, no Alembic. Small schema = auditable raw SQL
- Never delete or rename columns (append-only schema, like append-only data)
- New fields as nullable columns with defaults
- New record types are new values in `record_type` — no schema change needed
- Migrations are idempotent and run on startup

**Export formats:**
- **CSV** — one file per record type (flights.csv, daa_events.csv, etc.). Universal, importable into any tool.
- **JSON** — machine-readable archive with full payload structure and hash chain for verification
- **PDF report** — human-readable summary for a date range (flight count, hours, DAA encounters, anomalies). Attachment for Permit application narratives.
- All exports include a chain verification summary: "Chain verified, N records, first/last timestamps, no gaps detected"

**Decentralized timestamps (OpenTimestamps):** After each flight, the bridge hashes the compliance record and submits it to the OpenTimestamps network. The `.ots` proof file is stored alongside the record. Anyone can independently verify the proof — without the operator's cooperation, without any account, permanently.

This replaces RFC 3161 Timestamp Authorities as the external time-proof mechanism. Unlike a TSA (which can go offline or be compromised), OpenTimestamps is decentralized and does not depend on any single entity's continued existence. Unlike S3 Object Lock (which can be destroyed by closing the AWS account), an OpenTimestamps anchor exists independently of any operator-controlled infrastructure.

```
Flight completes
  → Compliance record written to SQLite (signed, hash-chained)
  → Litestream replicates to S3 (existing)
  → Bridge submits record hash to OpenTimestamps calendar servers
  → .ots proof stored in compliance DB (initially "pending")
  → ~1-3 hours later: proof confirmed (immutable)
  → Bridge updates proof to "confirmed"
  → Export includes .ots proofs — auditor verifies independently
```

Cost: free. OpenTimestamps batches thousands of hashes into single operations. Dependency: `opentimestamps-client` Python package.

**Daily integrity heartbeat:** The recorder writes a heartbeat record once per day, even if no flights occur. The heartbeat hashes the chain head and submits it to OpenTimestamps. This proves the chain was intact at each heartbeat — not self-asserted by the bridge, but independently anchored.

**Verification:** A standalone verification tool (Go binary, zero dependencies, cross-platform) takes a compliance database export and a public key as input and outputs a detailed PASS/FAIL report. The tool also verifies OpenTimestamps proofs independently. The public key is embedded in the export format so auditors need only the export file. A 2-page plain-language auditor guide documents: (a) run the verifier, (b) compare key fingerprint against operator's registered fingerprint, (c) verify OpenTimestamps proofs, (d) cross-reference flight records against FAA Remote ID database.

**Bridge startup self-checks:** On every startup, the bridge verifies its own deployment security:
1. Attempts an unauthenticated MQTT connection — if it succeeds, drops to telemetry-only mode (no flight commands)
2. Checks its own IP against the expected VLAN subnet — logs warning if outside expected range
3. Verifies Litestream is actively replicating — refuses Part 108 mode if replication is not active
4. Logs container image digest as a compliance record (for reproducible build verification)

**Continuous Litestream health monitoring:** The bridge monitors replication lag in real time. If lag exceeds 5 seconds, the bridge refuses to arm the aircraft and logs a `replication_stalled` compliance event. Litestream runs as a separate add-on that the bridge cannot stop or reconfigure. This closes the "stop replication before a risky flight" attack vector.

### 11.5 Compliance Data Integrity Model

Five independent mechanisms, each proving a different property:

| Mechanism | What it proves | Who controls it |
|-----------|---------------|-----------------|
| **Ed25519 signatures** | Who wrote the record | The bridge (operator's system) |
| **SHA-256 hash chain** | No records were removed or altered | The bridge (operator's system) |
| **OpenTimestamps** | When the record was written | Decentralized (no one controls it) |
| **Litestream + S3** | Records exist off-device, queryable backup | Operator's cloud account (but S3 Object Lock prevents deletion) |
| **FAA Remote ID** | The flight actually occurred | The FAA (operator cannot alter or delete) |

Together, these five layers answer every question a Part 108 reviewer or incident investigator would ask:

- **"Who recorded this?"** — Ed25519 signature traces to a specific bridge instance with a registered key fingerprint.
- **"Were any records deleted or altered?"** — The hash chain is intact (verifiable by the standalone tool).
- **"When was this recorded?"** — The OpenTimestamps proof is independently verifiable and immutable. This cannot be backdated or forged.
- **"Where is the backup?"** — Litestream continuously replicates to S3 with Object Lock retention. Even if the local database is destroyed, the replica exists.
- **"Did this flight actually happen?"** — FAA Remote ID independently recorded the aircraft's position broadcasts. Cross-reference the compliance record's GPS track against the FAA Remote ID database.

**What this system cannot prove:** That the operator did not fabricate records using modified bridge code. A modified bridge could write false records with valid signatures and timestamp them via OpenTimestamps. This is the fundamental limitation of any self-hosted compliance system. The mitigation is Remote ID cross-referencing: fabricated flights have no corresponding Remote ID track. See `docs/threat-model.md` Section 12 for the complete integrity analysis.

**Record types:**

| Record Type | Trigger | Content |
|-------------|---------|---------|
| Flight log | Per flight (start to land) | Trigger, authorization (who/when/mode), mission ID, weather at launch, takeoff time, landing time, max altitude, max distance, outcome |
| Telemetry archive | Continuous during flight | Full telemetry stream at native rate (compressed) |
| DAA event | Each ADS-B contact detected | Contact details, threat assessment, avoidance action (if any) |
| Weather record | At go/no-go decision | Wind speed/gust, rain, temperature, humidity — from local instruments |
| Personnel log | On duty change | Who is Operations Supervisor, who is Flight Coordinator, session start/end |
| Maintenance record | Manual entry | Aircraft and system maintenance actions |
| Anomaly report | On deviation | Any deviation from normal operations |
| Safety gate record | At each launch decision | Which gates passed, which failed, outcome |

**MQTT topics for compliance data:**

```
drone_hass/{drone_id}/compliance/flight_log
drone_hass/{drone_id}/compliance/daa_events
drone_hass/{drone_id}/compliance/weather_log
drone_hass/{drone_id}/compliance/personnel_log
drone_hass/{drone_id}/compliance/maintenance_log
```

### 11.3 Operational Area

A first-class configuration object defining the approved geographic volume for operations.

```json
{
  "id": "home_property",
  "name": "Residential Property — Eastside",
  "boundary": {
    "type": "Polygon",
    "coordinates": [[ [-122.3325, 47.6058], [-122.3315, 47.6058],
                      [-122.3315, 47.6068], [-122.3325, 47.6068],
                      [-122.3325, 47.6058] ]]
  },
  "altitude_floor_m": 0,
  "altitude_ceiling_m": 55,
  "lateral_buffer_m": 5,
  "airspace_class": "G"
}
```

The bridge validates every mission against this area before upload. Waypoints outside the polygon or above the ceiling are rejected. The operational area is included in compliance records and visualizable in the HA dashboard.

ArduPilot's firmware geofence is configured to match the operational area — providing a second, independent enforcement layer in the flight controller itself.

#### Altitude Invariant

The altitude parameters are interlocked and must be configured together. Changing one without the others breaks safe operation:

```
tree_max  <  RTL_ALT  <  altitude_ceiling_m  <  FENCE_ALT_MAX  <  Part 107 §107.51 (122 m)
  30 m   +20m  50 m       +5m   55 m              +5m   60 m       <       122 m
```

- **`tree_max → RTL_ALT`**: 20 m / 65 ft margin covers wind, baro drift, and rotor-downwash effects during the vertical RTL climb-out.
- **`RTL_ALT → ceiling`**: 5 m so the RTL climb does not trip the operational ceiling.
- **`ceiling → FENCE_ALT_MAX`**: 5 m so warm-day baro thermals do not nuisance-trip the firmware fence at the operational ceiling.
- **ComplianceGate** rejects any mission with `max(waypoint.alt) > ceiling - 5 m` (same baro-noise reasoning).
- **`WPNAV_SPEED_UP`**: configure conservative climb rate; fast climbs overshoot and can punch through the fence at apex.

**Annual checklist (operator action):** re-survey tree heights every spring before leaf-out canopy stabilizes. If the tallest tree on or near the parcel has grown past 30 m, raise all four numbers in lockstep so the inequality chain still holds. Record the survey in the compliance log.

### 11.4 Weather Monitoring

Local instruments (not API data) mounted at the dock site:

| Instrument | Measurement | Go/No-Go Threshold |
|-----------|-------------|---------------------|
| Anemometer | Wind speed + gust | < 15 mph sustained, < 25 mph gust |
| Rain gauge / sensor | Precipitation | No active rain |
| Temperature (dock) | Ambient temperature | 5-40 C |
| Humidity (dock) | Relative humidity | Informational (logged, not gating) |

Weather conditions at the go/no-go decision are logged as compliance records.

### 11.6 Time Synchronization

Compliance records, OpenTimestamps proofs, hash-chain ordering, MAVLink v2 signed-message replay protection, and S3 Object Lock retention enforcement all require monotonic, accurate UTC across every component. A multi-second clock skew breaks signature freshness, breaks OpenTimestamps verification, breaks MAVLink v2 replay protection, and creates audit-defeating gaps in the chain. Hash-chain monotonicity additionally requires that two records written within the same millisecond stay correctly ordered.

#### Architecture

| Role | Component | Source |
|---|---|---|
| Stratum-1 reference (off-property) | `time.cloudflare.com`, `time.nist.gov`, `nts.netnod.se` | NTS-secured (NTPv4 + Network Time Security, RFC 8915) |
| Stratum-2 server (on-property, primary) | `chronyd` on the Ubuntu LLM host (10.10.2.222, VLAN 2) | Pulls from upstream NTS pool over WAN; serves VLAN 10 + VLAN 20 via inter-VLAN routing on the ASUS |
| Stratum-2 fallback | `systemd-timesyncd` on HAOS host pulling NTS upstream directly | Used by VLAN 10 clients only if Ubuntu LLM is down |
| Stratum-3 clients | Bridge container, Mosquitto, ESPHome dock, ArduPilot companion (RPi) | Pull from Ubuntu LLM host (primary) with HAOS as backup |
| Aircraft FC clock | Pixhawk 6C RTC (CR1220 battery — verify fitted!) | Set from companion RPi via MAVLink `SYSTEM_TIME` (#2) at boot and every 60 s in flight |

**Why Ubuntu LLM hosts the stratum-2 server, not HAOS:** the HA Supervisor manages `systemd-timesyncd` on the HAOS host and does not allow native chronyd installation; running chronyd inside an add-on with `SYS_TIME` capabilities is technically possible but tightly couples the local time service to HA Core lifecycle, which violates the compliance-independence principle that motivated the add-on/integration split. Ubuntu LLM is already running, has native chronyd 4.5+ with full NTS support, and survives HA Core restarts independently. HAOS still runs `systemd-timesyncd` to NTS upstream as a fallback so VLAN 10 clients can fail over if Ubuntu LLM is down.

**Why a local stratum-2 at all:** the drone VLAN is firewalled off the internet (R-03), so VLAN 20 components cannot reach `pool.ntp.org` directly.

**IPv6:** chronyd is configured with `ipv4` directive on every pool/server line — the IPv6 plan is undefined and dual-stack chronyd silently prefers v6 if router-advertisements leak in.

**GPS fallback:** when WAN is down, `gpsd` on the companion RPi feeds the airframe GPS time into `chronyd` via `refclock SHM`, giving the property bounded recovery without internet.

#### Pre-arm and abort thresholds

| Condition | Threshold | Action | Rationale |
|---|---|---|---|
| Bridge host clock offset vs stratum-1 (chronyc tracking) | > 250 ms | Pre-arm fail | Hash-chain monotonicity at sub-second resolution; tighter than MAVLink replay needs |
| In-flight clock step | > 2 s in any single chrony adjustment (`maxchange 2.0 1 -1`) | Force RTL + alert RPIC | A 2 s step mid-flight indicates upstream attack or hardware fault |
| Pixhawk RTC vs companion RPi | > 5 s | Pre-arm fail | Cold-boot Pixhawk without RTC battery reads 1980-01-01 until SYSTEM_TIME arrives |
| Upstream NTS sources lost | > 15 min | Alert (HA repair issue), continue serving from local crystal | ~10 ppm drift = ~36 ms/hour, tolerable for hours |
| Local stratum-2 drift | > 100 ms | ComplianceGate refuses new flights | Hash-chain ordering depends on a stable reference |

```python
# Bridge startup (added to checklist in resolutions-ua.md §1326).
import subprocess
result = subprocess.run(['chronyc', '-c', 'tracking'], capture_output=True, text=True)
fields = result.stdout.split(',')
offset_s = abs(float(fields[4]))                  # "Last offset" in seconds
if offset_s > 0.250:
    raise PreArmFailure(f"Clock offset {offset_s:.3f}s exceeds 250 ms threshold")
```

#### Compliance integration

- **Compliance event `compliance/clock_step`:** chronyd is configured with `makestep 0.1 -1` so any correction larger than 100 ms emits a syslog line. A journald exporter publishes the event so audit can correlate "the chain has a 200 ms gap because chrony stepped at T."
- **Hourly snapshot:** `chronyc sources` output is logged to the compliance DB every hour for forensic reconstruction.
- **Hash-chain sequence numbers** are derived from a monotonic counter, not wall time — wall time is stored alongside but never used for ordering.
- **`SYSTEM_TIME` (#2) MAVLink message** must be added to the AP_Signing whitelist (it is *not* signed by default in ArduPilot 4.x), otherwise an injector on VLAN 20 can skew the FC RTC. Bridge enforces signed-only on this message at the MAVLink layer.
- **Leap-second handling:** chronyd `leapsectz right/UTC` + `smoothtime 400 0.001 leaponly` so the chain never sees a 23:59:60.

#### Bounded attack window

The OpenTimestamps anchor caps **forward-dating** attacks: a compromised local clock cannot produce an OTS proof claiming an earlier Bitcoin block-time than the one the calendar server actually issued. Litestream object metadata in S3 (write times the local host does not control) caps **backward-dating** attacks for replicated records. The combination bounds the window during which a single-host clock compromise can rewrite the chain to within (a) the OTS calendar submission interval and (b) the Litestream replication latency — both seconds-scale, not hours-scale.

#### Health publishing

Bridge publishes `drone_hass/{drone_id}/health/chrony` (retained, QoS 1, 30 s rate) with stratum, offset_ms, last_rx_age_s, source_count. HA exposes a sensor with an alert if stratum > 3 or offset_ms > 100.

#### Outbound dependencies and firewall rules

```
# WAN VLAN: allow Ubuntu LLM host outbound to NTS pool
ALLOW 10.10.2.222 -> 0.0.0.0/0 :123/udp        # NTP query
ALLOW 10.10.2.222 -> 0.0.0.0/0 :4460/tcp       # NTS-KE handshake

# Optional: HAOS host fallback NTS upstream
ALLOW <HAOS-host-IP> -> 0.0.0.0/0 :123/udp
ALLOW <HAOS-host-IP> -> 0.0.0.0/0 :4460/tcp

# VLAN 20 (drone): companion RPi -> Ubuntu LLM only
ALLOW 10.10.20.10 -> 10.10.2.222 :123/udp
DENY  10.10.20.0/24 -> 0.0.0.0/0 :123/udp      # explicit deny anywhere else

# VLAN 10 (IoT/dock): same pattern. ESPHome dock cannot do NTS yet, so it
# must be pinned to the local stratum-2 via DHCP option 42 and locked down
# by iptables; do not let the dock fall back to public NTP servers.
ALLOW 10.10.10.0/24 -> 10.10.2.222 :123/udp
DENY  10.10.10.0/24 -> 0.0.0.0/0 :123/udp      # blocks dock fallback
```

ASUSWRT does not filter intra-VLAN L2 traffic, so `client → 10.10.2.222` only needs an inter-VLAN allow when client and server are on different VLANs.

---

## 12. Feature Feasibility Matrix

| Feature | Feasible? | How | Limitations |
|---------|-----------|-----|-------------|
| Alarm-triggered mission (Part 107) | **Yes** | HA automation + RPIC tap | Requires RPIC on-site within VLOS |
| Alarm-triggered mission (Part 108) | **Yes** (when rule is final) | HA automation + autonomous launch | Requires Permit, DAA, FC on duty |
| Execute predetermined mission | **Yes** | MAVLink mission protocol | Up to 718 waypoints (ArduPilot) |
| Stream video from drone | **Yes** | RTSP from camera/companion → media server | Resolution depends on camera hardware |
| Record video | **Yes** | Server-side from RTSP stream + optionally onboard | Both copies available immediately |
| Take snapshots | **Yes** | MAVLink camera protocol v2 | Depends on camera hardware supporting the protocol |
| Get flight status | **Yes** | MAVLink GLOBAL_POSITION_INT + HEARTBEAT at 10 Hz | Full telemetry suite |
| Get battery level | **Yes** | MAVLink BATTERY_STATUS | %, voltage, current, temp, remaining mAh |
| Return to base | **Yes** | MAVLink MAV_CMD_NAV_RETURN_TO_LAUNCH | Configurable RTL altitude |
| Detect air traffic (DAA) | **Yes** | ADS-B In receiver + ArduPilot AP_Avoidance | Cooperative targets only (sufficient for Class G Cat 2-3) |
| Firmware geofence | **Yes** | ArduPilot polygon geofence + altitude ceiling | Enforced in flight controller, independent of bridge/HA |
| Physical dock | **Yes** | Custom NEMA enclosure + ESPHome | Aircraft-agnostic design |
| Auto battery charging | **No** | No standardized in-aircraft charging for multirotor | External charger on smart outlet only |
| Fully autonomous (Part 108) | **Pending** | Architecture ready; awaiting final rule + Permit | Airworthiness acceptance for DIY build is uncertain |
| Obstacle avoidance | **Limited** | Rangefinders for proximity; no vision-based avoidance | Mitigate with altitude margins and corridor planning |

---

## 13. Security Considerations

### Critical Mitigations (must-have before deployment)

| Attack | Mitigation |
|--------|------------|
| **Unauthenticated MQTT** | MQTT authentication mandatory. TLS on port 8883. ACLs restrict publish to command topics to HA's client ID only. Bind to VLAN, not 0.0.0.0. |
| **Command injection via MQTT** | Bridge validates ALL missions: operational area geofence (waypoints within property), altitude ceiling, speed limits, distance from home. Mission allowlist. |
| **Unauthorized flight** | Bridge requires a time-limited, single-use authorization token before executing any flight command. Token issued only via validated pilot tap (Part 107) or ComplianceGate autonomous authorization (Part 108). |
| **LiPo fire via dock** | Smoke sensor → hardware relay (not software) cuts charger power. ESP32 firmware enforces charge temperature limits independently of HA. Max-on timer for charger outlet in firmware. |
| **Safety gate bypass** | Safety checks enforced in TWO places: HA automation (first line) AND bridge + flight controller (second line, not bypassable). ArduPilot firmware geofence provides a third independent layer. |

### High Mitigations

| Attack | Mitigation |
|--------|------------|
| **WiFi deauth (secondary video link only)** | WPA3 with PMF on dedicated drone SSID. Loss of WiFi degrades video feed only — primary C2 (SiK 915 MHz) keeps the mission alive. Severity downgraded after the C2 inversion (architecture.md §6.3). |
| **Primary C2 (SiK) link loss / jamming** | MAVLink v2 signing on SiK + AES-128. ArduPilot `FS_GCS_TIMEOUT=15s` + `FS_GCS_ENABLE=2` (continue mission to next safe waypoint then RTL — avoids RTL on transient FHSS fades). RPIC manual override via ELRS 2.4 GHz remains available. |
| **RTSP interception** | Media server authentication. Bind to localhost/VLAN. |
| **Notification spoofing (Part 107 mode)** | Authorization token architecture prevents fake events from triggering flights. |
| **Dock lid during flight** | ESP32 interlock: refuse close unless pad-clear sensor confirms AND flight state = landed. |
| **ESPHome takeover** | API encryption key + OTA password mandatory. |

### Medium Mitigations

| Attack | Mitigation |
|--------|------------|
| **Command replay** | Commands include timestamp, rejected if stale. Single-use correlation IDs. |
| **Retained message poisoning** | Bridge validates mission checksums. MQTT ACLs restrict publish to state topics. |
| **MQTT flood DoS** | Mosquitto rate limiting. Coordinator debounces. Network isolation. |
| **Compliance log tampering** | Append-only store with cryptographic hash chain. Bridge independently logs. |
| **Aircraft theft from dock** | Physical lock. Tamper sensor. Missions stored on bridge, not aircraft. |

### Accepted Residual Risk

| Attack | Justification |
|--------|---------------|
| **GPS spoofing** | Requires specialized illegal equipment. Multi-constellation GNSS provides partial protection. Low probability for residential target. |
| **RF jamming** | Illegal (FCC violation). ArduPilot failsafe (RTL) handles this. Drone continues mission on flight controller if C2 link is lost. |
| **Bridge host compromise** | Mitigated by VLAN isolation. Accepted risk on isolated service. |

### Defense-in-Depth Principle

No single security control protects the system. The architecture enforces **three independent safety boundaries**:

1. **HA layer** — automation conditions, notification workflow, audit logging
2. **Bridge layer** — authorization token, operational area validation, ComplianceGate, DAA monitoring, compliance recording
3. **Flight controller firmware** — RTL failsafe, firmware geofence, low-battery auto-land, AP_Avoidance (ADS-B), OpenDroneID

An attacker must compromise all three layers to cause a dangerous unauthorized flight.

---

## 14. Failure Modes and Recovery

| Failure | Detection | Recovery |
|---------|-----------|----------|
| Bridge loses WiFi | MQTT LWT → "offline" (HA-side only) | Primary C2 (SiK) is unaffected; mission continues. HA marks integration unavailable until WiFi restored. |
| Bridge process crash | MQTT LWT → "offline"; SiK link goes silent | Supervisor auto-restarts container. ArduPilot `FS_GCS_TIMEOUT=15s` + `FS_GCS_ENABLE=2` (continue then RTL). |
| MAVLink primary link lost (SiK 915 MHz) | RADIO_STATUS rate stops; bridge sees no telemetry | Bridge publishes `link_degraded`. ArduPilot fails safe per `FS_GCS_*`. RPIC manual override on ELRS 2.4 GHz remains available. WiFi-secondary path may still carry video for situational awareness. |
| Secondary WiFi video lost mid-flight | go2rtc reports stream timeout | Mission continues on SiK. Onboard SD recording continues. Live video resumes when WiFi recovers. |
| MQTT broker down | Bridge reconnect loop | Commands blocked. Drone unaffected (mission continues on flight controller). |
| Media server down | Stream error | Stream stops. Flight unaffected. |
| Mission upload fails | MAVLink MISSION_ACK error → MQTT response | HA shows error. Drone stays on ground. |
| Low battery during mission | ArduPilot auto-RTL at configurable threshold | Flight controller firmware handles safety. |
| GPS loss during mission | ArduPilot EKF failsafe | Flight controller switches to land mode. Bridge publishes state change. |
| Geofence breach | ArduPilot firmware geofence | Flight controller executes configured action (RTL/land/brake). Bridge logs event. |
| ADS-B traffic detected | AP_Avoidance evaluates threat | Flight controller executes avoidance maneuver. Bridge logs DAA event. |
| Dock lid actuator stuck | Motion timeout on ESP32 | Controller flags fault. HA alerts operator. |
| Dock smoke sensor triggered | ESP32 hardware interlock | Charger power cut immediately (hardware relay). HA alerts. |
| Power outage | UPS → sensor reports | Dock remains closed. System unavailable until power restored. |
| Pilot/FC doesn't authorize in time | 2-minute timeout in Part 107 automation | Mission not launched. Event logged. |
| Android bridge device loses power | N/A | No longer applicable — MAVLink bridge runs on HA server. |

---

## 15. Platform Migration Strategy

### 15.1 Aircraft-Agnostic Design

The system is built around **interfaces, not a specific drone**:

| Abstraction | What Changes on Aircraft Swap |
|-------------|-------------------------------|
| Landing pad geometry | Adjustable alignment guides |
| Battery type/charging | Swap charger on smart outlet |
| MQTT topics | Same protocol, new `drone_id` |
| Mission definitions | Same JSON format, new waypoints for new flight characteristics |
| MAVLink bridge | Same code — MAVLink is the standard |
| HA integration | Unchanged (MQTT abstraction) |
| Dock | Unchanged (aircraft-agnostic) |

### 15.2 Multi-Aircraft Support

The MQTT topic design supports multiple drones with different `drone_id` values. The HA integration discovers each independently and creates separate entity sets. Both ArduPilot-native platforms and Parrot/Olympe-bridged platforms can coexist on the same MQTT topic structure.

**Regulatory constraint:** One drone airborne at a time per qualified person. Under Part 107, one RPIC cannot maintain VLOS on two aircraft. Under Part 108, Flight Coordinator oversight limits apply.

### 15.3 Future Platform Evaluation Criteria

When evaluating successor aircraft, prioritize:

1. MAVLink support (native or well-maintained bridge)
2. ADS-B In capability or mounting point for external receiver
3. Firmware geofence support
4. RTSP video output
5. OpenDroneID / Standard Remote ID
6. Manufacturer likely to pursue Part 108 Declaration of Compliance
7. Blue UAS listed or NDAA-compliant by construction
8. Available parts and battery supply chain

---

## 16. Implementation Plan

### Phase 0: SITL + Bridge MVP (Weeks 1-3, no hardware needed)

1. Install ArduPilot SITL in WSL2
2. Scaffold `mavlink-mqtt-bridge` Python project (MAVSDK-Python + aiomqtt)
3. Run as standalone `python -m mavlink_mqtt_bridge` during development
4. Connect to SITL, verify telemetry reception
5. Implement telemetry → MQTT publishing (flight, battery, state)
6. Implement MQTT command → MAVLink translation (arm, takeoff, land, RTL)
7. Implement ComplianceGate skeleton (Part 107 mode)
8. Test with Mosquitto + MQTT Explorer
9. **Deliverable:** Bridge publishes telemetry from simulated drone, accepts basic commands

### Phase 1: HA Integration MVP (Weeks 2-4, no hardware needed)

1. Scaffold `custom_components/drone_hass/` using `homeassistant.components.mqtt`
2. Config flow (MQTT + drone discovery + legal acknowledgment)
3. MQTT coordinator (using HA's managed MQTT client)
4. Sensor + binary sensor entities
5. Service handlers (takeoff, land, RTL)
6. Package bridge as HA add-on (Dockerfile + S6 overlay + add-on metadata)
7. Test add-on lifecycle: HA restart while bridge running, add-on crash recovery
8. **Deliverable:** Simulated drone telemetry in HA dashboard, basic commands work, bridge running as add-on

### Phase 2: Missions in SITL (Weeks 3-5, no hardware needed)

1. Bridge: JSON mission format → MAVLink mission upload protocol
2. Bridge: Mission execution monitoring (MISSION_CURRENT, MISSION_ITEM_REACHED)
3. HA: Mission services + progress entity
4. Build actual property mission corridors as JSON files
5. Test in SITL — watch simulated drone fly the perimeter
6. **Deliverable:** End-to-end mission execution from HA through simulated drone

### Phase 3: Compliance + DAA Framework (Weeks 4-6, no hardware needed)

1. Implement compliance recorder with SQLite backend (append-only, hashed chain)
2. Implement operational area validation (GeoJSON)
3. Implement DAA event logging (simulated ADS-B in SITL)
4. Implement weather integration (local instruments entity mapping)
5. Implement Flight Coordinator status tracking
6. Implement Part 108 mode in ComplianceGate
7. **Deliverable:** Full compliance framework working against SITL

### Phase 4: Video Pipeline (Weeks 5-7, minimal hardware)

1. Set up go2rtc or mediamtx
2. Create test RTSP source (FFmpeg test pattern or USB webcam)
3. Configure go2rtc to pull RTSP, serve to HA
4. HA camera entity consuming stream
5. Server-side recording from stream
6. **Deliverable:** Video pipeline working end-to-end (real camera comes with aircraft)

### Phase 5: Site Survey + Mission Geometry (1 day, on property)

1. Map obstacles: tallest trees, canopy extents, no-fly wedges
2. Identify clear takeoff/landing cylinder above shed roof
3. Verify clear approach lane (no branches in RTL direction)
4. Define mission corridors
5. Define operational area (GeoJSON polygon + altitude ceiling)
6. **Deliverable:** Property mission map + operational area definition + dock location decision

### Phase 6: Hardware Build (Weeks 8-12)

1. Assemble X500 V2 + Pixhawk 6C
2. ArduCopter firmware flash, basic parameter tuning
3. Mount companion computer (RPi), configure serial MAVLink + WiFi
4. Install ADS-B In receiver (pingRX)
5. Install Remote ID module
6. Install anti-collision strobe
7. Configure ArduPilot firmware geofence to match operational area
8. Bench test: MAVLink connection, verify bridge connects
9. First outdoor hover (manual RC)
10. Auto-tune PID, verify GPS hold, test RTL
11. **Deliverable:** Flyable drone connected to bridge

### Phase 7: Dock Build (Weeks 10-14)

1. Source NEMA 4X enclosure + lid material
2. Install ESPHome ESP32 with temp/humidity/smoke sensors
3. Install linear actuator + limit switches
4. Install weather station (anemometer, rain gauge)
5. Wire power (UPS + fused rails)
6. Configure ESPHome entities in HA
7. Test lid open/close cycle, interlock logic
8. Install ADS-B ground receiver (optional)
9. **Deliverable:** Dock operational, controlled from HA

### Phase 8: Integration + Hardening (Weeks 12-16)

1. Real missions on property (low altitude, slow speed, manual RC override ready)
2. Camera/gimbal integration + RTSP stream from air
3. Dock integration (open lid before launch, close after land)
4. Full Part 107 workflow: alarm → notification → authorize → mission → RTL → dock close
5. Battery maintenance automations
6. Edge case testing (all failure modes in Section 14)
7. Geofence validation testing (intentional approach to boundary)
8. DAA testing (if ADS-B traffic available in area)
9. Night operations with strobe
10. Operational rehearsals (day/night, wind)
11. MQTT TLS
12. **Deliverable:** System you trust at 3 AM in winter rain, under Part 107

### Phase 9: Part 108 Transition (When Final Rule is Published)

1. Evaluate final rule against architecture
2. Assess airworthiness acceptance pathway for aircraft
3. Adjust DAA requirements if final rule differs from NPRM
4. Prepare Permit application with compliance data collected since Phase 3
5. Switch to Part 108 mode
6. **Deliverable:** Autonomous alarm-triggered perimeter patrol

---

## 17. Cost Estimate

### Open Platform System (this design)

| Component | Estimated Cost |
|-----------|---------------|
| Aircraft (X500 V2 + Pixhawk + companion + camera) | $1,700-$2,750 |
| ADS-B In receiver (pingRX) | $250-$350 |
| Remote ID module | $100-$150 |
| Anti-collision strobe | $30-$80 |
| Batteries (3x 4S 5200mAh) | $120-$200 |
| RC transmitter + receiver (manual backup) | $150-$250 |
| Weatherproof dock enclosure + lid | $300-$900 |
| Dock heating + ventilation | $150-$400 |
| Dock sensors (temp, humidity, smoke) | $150-$300 |
| Smart power + UPS | $300-$800 |
| Lid actuator + mechanism | $200-$600 |
| Landing pad + alignment | $100-$300 |
| ESP32 + wiring + misc | $100-$200 |
| Weather station (anemometer + rain) | $200-$400 |
| ADS-B ground receiver (optional) | $50-$150 |
| Aircraft weatherproofing (conformal coat, sealant, enclosures, dielectric grease) | $100-$250 |
| Spare parts budget (incl. annual motor replacement) | $400-$700 |
| **Total** | **$4,500-$8,850** |

### vs. Commercial Autonomous Platforms

| Platform | Total Cost (3-year) |
|----------|-------------------|
| This design (open platform + DIY dock) | $4,200-$8,400 + annual batteries |
| Parrot ANAFI Ai + DIY dock | $6,000-$12,000 |
| Skydio X10 + Dock | $20,000-$30,000 |
| Sunflower Labs | $20,000-$50,000 |
| Percepto AIM | $100,000+ |

---

## 18. Open Questions

1. **Part 108 final rule:** Specific DAA performance standards, airworthiness acceptance pathway for homebuild/open-source, permit application process.
2. **Camera selection:** Siyi A8 Mini vs RPi HQ Camera + custom gimbal vs other options. Trade-off between RTSP native, image quality, and weight.
3. **Companion computer placement:** On aircraft (direct serial, lower latency) vs at dock (simpler aircraft, higher latency). Start on HA server, evaluate later.
4. **Mission editor:** Define missions via HA UI (map), YAML, or import from Mission Planner/QGC?
5. **SD card media retrieval:** Automate downloading 4K footage from onboard recording? Server-side recording from RTSP may be sufficient.
6. **Weather station model:** Davis Vantage Vue (integrated) vs individual anemometer + rain gauge on ESP32.
7. **Insurance:** Commercial drone liability coverage for residential autonomous operations — pricing and availability.

---

## Sources

- [ArduPilot Documentation](https://ardupilot.org/)
- [ArduPilot SITL Documentation](https://ardupilot.org/dev/docs/using-sitl-for-ardupilot-testing.html)
- [MAVLink Protocol Specification](https://mavlink.io/)
- [MAVSDK-Python](https://mavsdk.mavlink.io/main/en/)
- [pymavlink](https://mavlink.io/en/mavgen_python/)
- [Holybro X500 V2](https://holybro.com/products/x500-v2-kits)
- [uAvionix pingRX (ADS-B In)](https://uavionix.com/products/pingrx-pro/)
- [uAvionix ping Remote ID](https://uavionix.com/products/ping-remote-id/)
- [Parrot ANAFI Ai](https://www.parrot.com/en/drones/anafi-ai)
- [Parrot Olympe SDK](https://developer.parrot.com/docs/olympe/)
- [Skydio X10](https://www.skydio.com/x10)
- [Blue UAS Cleared List (DoD)](https://www.diu.mil/blue-uas-cleared-list)
- [FAA Part 108 NPRM (August 2025)](https://www.faa.gov/newsroom/BVLOS_NPRM_website_version.pdf)
- [14 CFR Part 107](https://www.ecfr.gov/current/title-14/chapter-I/subchapter-F/part-107)
- [DJI FCC Covered List Addition (December 2025)](https://www.fcc.gov/document/fcc-updates-covered-list-add-certain-uas-and-uas-components-0)
- [RosettaDrone (GitHub)](https://github.com/RosettaDrone/rosettadrone)
