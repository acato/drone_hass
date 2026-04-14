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

### 3.1 Applicable Law

Drone operation in the U.S. is governed by federal law (FAA), not state law. This use case — property security triggered by an alarm — is **commercial/operational**, meaning **14 CFR Part 107** applies today and **14 CFR Part 108** will apply when finalized.

### 3.2 Part 107: Current Operating Mode

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

### 3.3 Part 108: Target Operating Mode

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

### 3.4 Dual-Mode Architecture

The system operates in one of two modes, selectable via configuration:

```
Part 107 mode (default):
  Alarm → Safety checks → RPIC notification → Human tap required → Launch

Part 108 mode:
  Alarm → Safety checks + DAA health + FC on duty → Autonomous launch → FC notified
```

Part 107 mode is a strict subset of Part 108 mode — everything Part 108 requires (DAA, logging, weather checks, operational area validation), Part 107 operations also benefit from. The only difference is whether a human tap is required before launch.

### 3.5 Washington State Specifics

WA adds minimal flight restrictions beyond FAA:
- Privacy: avoid surveillance where people have reasonable expectation of privacy (neighbor yards/windows)
- Property overflight: perimeter patrol must avoid crossing into neighbors' airspace
- State parks require permission; private residential land is fine

### 3.6 Non-Operator Deployments

This is a public open-source project. Operators deploying it are responsible for their own regulatory compliance. The system includes:
- Explicit prerequisites in this document (Section 2)
- Acknowledgment step in HA config flow
- Operational mode requires manual configuration (Part 108 mode is not the default)
- Geofence and operational area validation cannot be bypassed from HA

These measures do not transfer legal responsibility from the operator but create a documented record that requirements were communicated.

---

## 4. Operational Concept

### 4.1 The Alarm Response Workflow

**Part 107 mode (current):**

```
Alarm Sensor (PIR, gate, camera AI)
    │
    ▼
Home Assistant Automation
    │
    ├── Safety Gate Check
    │   ├── Wind < 15 mph? (local weather station)
    │   ├── No rain? (local rain gauge)
    │   ├── Battery > threshold?
    │   ├── GPS lock confirmed?
    │   ├── Dock connected?
    │   ├── Drone connected?
    │   ├── DAA system healthy?
    │   ├── Airspace clear? (ADS-B ground check)
    │   └── Not already airborne?
    │
    ├── Select Mission Profile
    │   ├── Driveway sensor → front sweep
    │   ├── Backyard motion → rear orbit
    │   ├── Full alarm → full perimeter loop
    │   └── Manual → investigate waypoint
    │
    ├── Prepare Dock
    │   └── Open lid (if closed)
    │
    ▼
Actionable Push Notification to RPIC
    ┌─────────────────────────────────┐
    │ Perimeter Alert — East Fence    │
    │ Wind OK · GPS OK · Battery 85% │
    │ ADS-B Clear · DAA Healthy       │
    │ Mission: Full Perimeter         │
    │                                 │
    │  [LAUNCH DRONE]    [IGNORE]     │
    └─────────────────────────────────┘
    │
    ▼ (RPIC taps LAUNCH — Part 107 compliance moment)
    │
    ├── Compliance record: trigger, authorization, weather, personnel
    ├── Start live stream
    ├── Execute waypoint mission
    ├── Display live feed in HA dashboard
    ├── Record video (onboard + media server)
    │
    ▼
Mission completes → auto RTL → dock lid closes
    │
    ▼
Compliance record: mission outcome, DAA events, flight log
```

**Part 108 mode (target):**

Same flow, except the actionable notification is replaced by:
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

### 5.6 Placement

On the shed roof. Requirements:
- Clear vertical column above (no overhanging branches)
- Clear lateral clearance ~30-50 ft for takeoff/landing
- Clear approach lane for return-to-home (no branches in the direction of final approach)
- Power from shed below
- WiFi coverage from house network
- Local weather station mounted nearby (anemometer, rain gauge)

### 5.7 Power Architecture

```
Mains (from shed) → UPS → 12/24V DC supply
                          ├── Actuator rail (fused)
                          ├── Compute/sensor rail (fused)
                          └── Heater/fan rail (fused)

Separate smart outlet → Battery charger → battery
(HA controls the outlet; never modify OEM charging electronics)
```

UPS is important: brownouts during storms are common — exactly when you want the system most.

### 5.8 Ground Infrastructure

| Component | Purpose | Part 108 Relevance |
|-----------|---------|-------------------|
| Local weather station (anemometer + rain gauge) | Automated go/no-go with measured data | Operational safety documentation; not API-derived |
| ADS-B ground receiver (FlightAware PiAware or similar) | Extended traffic awareness beyond airborne receiver | Supplements onboard DAA, earlier warning |
| Directional WiFi antenna | Reliable C2 link to aircraft | Part 108 emphasizes C2 link integrity |
| SiK 915 MHz telemetry radio (backup) | Redundant C2 link if WiFi degrades | C2 redundancy |

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
| Telemetry radio (backup C2) | SiK 915 MHz | $50 |
| Companion computer | Raspberry Pi 5 (4GB+) | $60-$100 |
| Camera + gimbal | Siyi A8 Mini (3-axis, 4K, RTSP native) | $300-$400 |
| Batteries | 4S 5200mAh LiPo x3 | $120-$200 |
| Anti-collision strobe | Firehouse Technology ARC II or uAvionix | $30-$80 |
| Remote ID module | uAvionix ping Remote ID | $100-$150 |
| ADS-B In receiver | uAvionix pingRX Pro | $250-$350 |
| WiFi adapter (companion) | Alfa AWUS036ACS + directional antenna at dock | $40-$80 |
| RC transmitter (manual backup) | RadioMaster TX16S + ELRS receiver | $150-$250 |
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

### 8.2 High-Level Overview

```
┌──────────────────────────────────────────────────────────────────────┐
│                         HOME ASSISTANT SERVER                        │
│                                                                      │
│  ┌────────────────────┐  ┌─────────────────────────────────────┐    │
│  │  ESPHome Dock      │  │     drone_hass Integration          │    │
│  │  Controller        │  │     (custom_components/)             │    │
│  │                    │  │                                     │    │
│  │  cover.dock_lid    │  │  ┌──────────┐  ┌────────────────┐   │    │
│  │  sensor.dock_temp  │  │  │  MQTT    │  │  Service        │   │    │
│  │  switch.dock_heat  │  │  │  Coord.  │  │  Handlers       │   │    │
│  │  binary.dock_smoke │  │  └────┬─────┘  └──────┬─────────┘   │    │
│  │  ...               │  │       │               │              │    │
│  └─────────┬──────────┘  │  Uses homeassistant.components.mqtt  │    │
│            │ ESPHome API │  (HA's managed MQTT client, not own) │    │
│            │             │                  │                    │    │
│  ┌─────────┴──────────┐  │  Sensors│Binary│Camera│DeviceTracker │    │
│  │  Mosquitto Broker  │◄─┤  Compliance│FC Status│DAA Traffic    │    │
│  │  (add-on)          │  └──────────────────┬───────────────────┘    │
│  └─────────┬──────────┘                     │                       │
│            │                      ┌──────────┴──────────┐           │
│  ┌─────────┴──────────┐          │  camera.drone_live   │           │
│  │  Media Server      │◄─────────┤  consumes stream    │           │
│  │  (go2rtc add-on)   │  WebRTC  │  from media server  │           │
│  └─────────┬──────────┘          └─────────────────────┘           │
│            │ ▲ Pulls RTSP                                           │
└────────────┤─┤──────────────────────────────────────────────────────┘
             │ │              ▲ MQTT (sole interface between
             │ │              │ add-on and integration)
     ┌───────┤─┤──────────────┤────────────────────────────────┐
     │       │ │              │                                 │
     │  drone_hass Bridge Add-on (Docker container)            │
     │  Managed by HA Supervisor — starts before HA Core       │
     │  Keeps running through HA restarts                      │
     │                                                         │
     │  ┌──────────────────────────────────────────────────┐   │
     │  │  MAVSDK-Python (async) ←→ aiomqtt               │   │
     │  │                                                  │   │
     │  │  ┌──────────────┐ ┌──────────────┐               │   │
     │  │  │ Telemetry    │ │ Command      │               │   │
     │  │  │ Publisher    │ │ Handler      │               │   │
     │  │  └──────┬───────┘ └──────┬───────┘               │   │
     │  │  ┌──────┴───────┐ ┌──────┴───────┐               │   │
     │  │  │ Mission      │ │ DAA Monitor  │               │   │
     │  │  │ Manager      │ │ (ADS-B)      │               │   │
     │  │  └──────┬───────┘ └──────┬───────┘               │   │
     │  │  ┌──────┴────────────────┴───────┐               │   │
     │  │  │ Compliance Recorder (SQLite)  │               │   │
     │  │  │ /data/compliance/compliance.db │               │   │
     │  │  └───────────────────────────────┘               │   │
     │  │  ┌───────────────────────────────┐               │   │
     │  │  │ ComplianceGate (107/108 mode) │               │   │
     │  │  └───────────────────────────────┘               │   │
     │  └──────────────────────┬───────────────────────────┘   │
     │                         │ MAVLink (UDP/TCP over WiFi    │
     │                         │  + SiK 915MHz backup)         │
     │     ┌───────────────────┴───────────────────┐           │
     │     │           AIRCRAFT                     │           │
     │     │                                        │           │
     │     │  Flight Controller (ArduPilot)         │           │
     │     │    ├── AP_Avoidance (ADS-B)            │           │
     │     │    ├── Firmware geofence (polygon)     │           │
     │     │    ├── Failsafe (GCS loss, battery,    │           │
     │     │    │   geofence, EKF)                  │           │
     │     │    └── OpenDroneID (Remote ID)         │           │
     │     │                                        │           │
     │     │  ADS-B In Receiver (pingRX)            │           │
     │     │  Companion Computer (RPi)              │           │
     │     │    └── Camera RTSP server              │──────────►│ RTSP
     │     │  Camera + Gimbal                       │  (WiFi)   │
     │     │  Anti-collision strobe                 │           │
     │     │  Remote ID module                      │           │
     │     └────────────────────────────────────────┘           │
     │                                                          │
     │     ┌────────────────────────────────────────┐           │
     │     │           PHYSICAL DOCK                │           │
     │     │  ESPHome ESP32: lid, sensors, heater   │           │
     │     │  Weather station: anemometer, rain     │           │
     │     │  ADS-B ground receiver (optional)      │           │
     │     └────────────────────────────────────────┘           │
     └──────────────────────────────────────────────────────────┘
```

### 8.3 Bridge Add-on

**Purpose:** Owns the drone. Translates between MAVLink and MQTT. Records compliance data. Enforces the ComplianceGate. Runs independently of HA Core.

**Technology:** Python 3.12+, MAVSDK-Python (async), aiomqtt, SQLite (compliance DB)

**Container:** Docker, managed by HA Supervisor on HAOS. Uses S6-overlay init system. Multi-arch (amd64, aarch64, armv7). Bundles `mavsdk_server` binary per architecture.

**Add-on metadata:**

```yaml
name: "drone_hass MAVLink Bridge"
slug: "drone_hass_bridge"
startup: system          # Starts before HA Core
boot: auto               # Auto-starts on HA boot
arch: [amd64, aarch64, armv7]
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
    async def authorize_flight(self, mission, context):
        # Common gates (both modes)
        if not await self._safety_checks_pass(context):
            return False
        if not self._mission_within_operational_area(mission):
            return False
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
```

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

```
Step 1: Connection
  ├── MQTT Broker Host (default: core-mosquitto)
  ├── MQTT Port (default: 1883)
  ├── MQTT Username / Password
  └── Drone ID (auto-discovered from drone_hass/+/state/connection)

Step 2: Media Server (optional)
  ├── Media Server Type (go2rtc / mediamtx / none)
  └── RTSP Source URL

Step 3: Compliance
  ├── Operational Mode (Part 107 / Part 108)
  └── Operational Area definition (GeoJSON file path)

Step 4: Legal Acknowledgment
  └── User confirms: Part 107 certificate held, airspace verified,
      Remote ID equipped, insurance obtained

Step 5: Validation
  ├── Test MQTT connection
  ├── Check bridge heartbeat
  ├── Verify DAA system status
  └── Verify media server reachability (if configured)
```

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

### 11.1 Purpose

Part 108 requires flight data recording, quality assurance, and auditability. This framework is implemented from day one — it makes Part 107 operations better now and becomes the evidence base for the Part 108 Permit application.

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

**Daily integrity heartbeat with RFC 3161 timestamp:** The recorder writes a heartbeat record once per day, even if no flights occur. The heartbeat hashes the chain head and submits it to an RFC 3161 Timestamp Authority (e.g., FreeTSA.org). The signed timestamp token is stored as part of the heartbeat record. This provides an external, cryptographically verifiable proof that the chain existed at a specific time — not self-asserted by the bridge, but independently attested.

**Verification:** A standalone verification tool (Go binary, zero dependencies, cross-platform) takes a compliance database export and a public key as input and outputs a detailed PASS/FAIL report. The public key is embedded in the export format so auditors need only the export file. A 2-page plain-language auditor guide documents: (a) run the verifier, (b) compare key fingerprint against operator's registered fingerprint, (c) check S3 Object Lock retention policy, (d) cross-reference flight records against FAA Remote ID database.

**Bridge startup self-checks:** On every startup, the bridge verifies its own deployment security:
1. Attempts an unauthenticated MQTT connection — if it succeeds, drops to telemetry-only mode (no flight commands)
2. Checks its own IP against the expected VLAN subnet — logs warning if outside expected range
3. Verifies Litestream is actively replicating — refuses Part 108 mode if replication is not active
4. Logs container image digest as a compliance record (for reproducible build verification)

**Continuous Litestream health monitoring:** The bridge monitors replication lag in real time. If lag exceeds 5 seconds, the bridge refuses to arm the aircraft and logs a `replication_stalled` compliance event. Litestream runs as a separate add-on that the bridge cannot stop or reconfigure. This closes the "stop replication before a risky flight" attack vector.

**Compliance data integrity: what this chain proves to a Part 108 reviewer:**
- The system's safety posture during every flight (DAA active, weather checked, personnel authorized, geofence enforced) — via the signed, hash-chained, replicated compliance chain
- Flights actually occurred — via FAA Remote ID cross-referencing (external, operator-uncontrollable)
- The chain has not been tampered with — via the standalone verifier with RFC 3161 time proofs
- The system was running published code — via container image digest verification

**What this chain cannot prove:** That the operator did not fabricate records using modified bridge code. This is the fundamental limitation of any self-hosted compliance system and is documented rather than glossed over. See `docs/threat-model.md` Section 12 for the complete integrity analysis.

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
  "altitude_ceiling_m": 37,
  "lateral_buffer_m": 5,
  "airspace_class": "G"
}
```

The bridge validates every mission against this area before upload. Waypoints outside the polygon or above the ceiling are rejected. The operational area is included in compliance records and visualizable in the HA dashboard.

ArduPilot's firmware geofence is configured to match the operational area — providing a second, independent enforcement layer in the flight controller itself.

### 11.4 Weather Monitoring

Local instruments (not API data) mounted at the dock site:

| Instrument | Measurement | Go/No-Go Threshold |
|-----------|-------------|---------------------|
| Anemometer | Wind speed + gust | < 15 mph sustained, < 25 mph gust |
| Rain gauge / sensor | Precipitation | No active rain |
| Temperature (dock) | Ambient temperature | 5-40 C |
| Humidity (dock) | Relative humidity | Informational (logged, not gating) |

Weather conditions at the go/no-go decision are logged as compliance records.

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
| **WiFi deauth / C2 link loss** | WPA3 with PMF. Dedicated VLAN. Backup SiK 915 MHz radio for redundant C2 link. ArduPilot RTL failsafe on GCS heartbeat loss. |
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
| Bridge loses WiFi | MQTT LWT → "offline" | HA marks unavailable. Bridge auto-reconnects. ArduPilot GCS-loss failsafe (RTL after timeout). |
| Bridge process crash | MQTT LWT → "offline" | systemd auto-restarts service. ArduPilot continues mission autonomously or RTL on GCS loss. |
| MAVLink link lost (WiFi) | Heartbeat timeout | Bridge publishes "offline". SiK 915 MHz backup link available. ArduPilot RTL failsafe. |
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
