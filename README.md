# drone_hass

Commercial drone-in-a-box security systems cost $20,000–$100,000. drone_hass is the open-source alternative — alarm-triggered autonomous perimeter patrol, live video streaming, and compliance-grade audit logging, built on Home Assistant, MAVLink, and ArduPilot.

Your alarm triggers. Thirty seconds later, the drone is airborne, flying a predefined perimeter mission, streaming live video to your HA dashboard. When it lands, a signed compliance record is timestamped via OpenTimestamps and replicated to immutable cloud storage — independently verifiable, permanently anchored, ready for an **FAA Part 108 Operating Permit** or an **EU Specific-category operational authorisation** review.

## Scope and jurisdictions

The project targets **two jurisdictions from a single codebase**: the **United States** (FAA Part 107 today, Part 108 when the final rule lands) and the **European Union** (EASA 2019/947, Specific category via national SORA authorisation). Both deployments share the same aircraft, bridge, integration, compliance recorder, Remote ID primitive, DAA monitor, and geofence primitives. They differ in operator credentials, national portal integration, data-protection overlay, geographical zones, insurance market, and mission geometry.

Per-jurisdiction work is cleanly separated through a **7-layer inside-out invariance model** — see [`docs/regulatory-layered-model.md`](docs/regulatory-layered-model.md). Adopters in a new jurisdiction inherit physics, project architecture, and regulatory primitives (Levels 0–2) untouched; they write the national specialisation (Level 5) and site specifics (Level 6). The model also tells contributors where their work scales — inner layers compound across every adopter forever.

Two concrete deployments drive the design:

| Use case | Jurisdiction | Status |
|---|---|---|
| **Seattle Eastside, WA** | US — FAA Part 107 → Part 108 | Primary target; actively designed |
| **Lavagna, Liguria, IT** | EU — ENAC Specific category via SORA, SAIL II | Pressure-tested; deferred deployment |

Each use case has its own constraints. Under Part 107 the RPIC must be on-site and within visible range of the aircraft; routine productised "alarm triggers flight while no one is home" is not available under ordinary Part 107 operations, and the planned path is Part 108 once finalised. (Extraordinary §107.31 / §107.33 waiver-based pathways exist but are fact-specific and uncertain.) Under EU Specific, self-built ArduPilot cannot obtain C-class marking so **STS** is closed, but **PDRA-S02** (BVLOS with airspace observers, in a controlled ground area, sparsely populated environment; UAS MTOM ≤25 kg, max dimension ≤3 m, ≤120 m AGL) does not require C-class marking and is open to Article-14 privately-built UAS. **PDRA-S02 prohibits fully autonomous operation** — it requires the remote pilot / airspace observer to retain control / intervention capability throughout the flight. The project's alarm-triggered-mission-with-Flight-Coordinator-on-duty model fits that; a truly unattended no-human-in-loop model does not, and would require a bespoke full-SORA authorisation. GDPR via the national DPA is a parallel regulatory surface with no US analogue. Full analysis in the regulatory documents listed below.

## What this project is

- **Alarm-to-airborne in under 30 seconds.** HA automation handles safety checks, dock opens, drone launches, video streams — **supervised-autonomy under Part 108 / EU PDRA-S02** (alarm-triggered mission, Flight Coordinator / airspace observer on duty retaining intervention capability; no per-flight human tap), or one-tap RPIC authorisation under Part 107. Truly unattended no-human-in-loop autonomy is not PDRA-S02 territory and requires a bespoke full-SORA authorisation in the EU.
- **Live RTSP video in your HA dashboard.** No proprietary app, no cloud subscription. Camera streams directly through go2rtc / mediamtx to a standard HA camera entity. Pre-record geospatial privacy masking for GDPR compliance in EU mode.
- **Develop without hardware.** ArduPilot SITL simulates a full drone on your workstation. Build and test the entire system — bridge, HA integration, missions, compliance — before you touch a soldering iron.
- **Compliance framework from day one, both jurisdictions.** Not bolted on later. Every flight produces a verifiable audit trail — a two-tier recorder (immutable metadata chain + retention-class-gated video blobs) backed by four independent integrity mechanisms, each proving a different property, each controlled by a different entity:

  | Mechanism | What it proves | Who controls it |
  |---|---|---|
  | **Ed25519 signatures** | Who wrote the record | The bridge instance |
  | **SHA-256 hash chain** | No records removed or altered | The bridge instance |
  | **OpenTimestamps** | When the record was written | No one (decentralised) |
  | **Litestream + S3 Object Lock** | Off-device backup exists | Operator's cloud (deletion-proof) |

  **Plus a fifth, contemporaneous signal that is not a lookup:** during flight the aircraft broadcasts **Remote ID** (FAA Part 89 / EN 4709-002). Any receiver in RF range — the FAA's network, law-enforcement DiSCVR, cooperative third-party listeners — can log it independently. **The FAA does not expose a public flight-history database for routine operator/auditor lookup.** Treat Remote ID as a compliance broadcast and a possible law-enforcement corroboration channel, not a routine evidentiary mechanism.

  The two-tier split keeps metadata immutable while allowing lawful video deletion under GDPR retention rules. Applicable in US mode too — routine footage retention is expensive and legally risky even under FAA-only. The open-source compliance tooling is the most novel contribution of this project.

- **MAVLink-native, aircraft-agnostic.** No proprietary SDKs, no vendor lock-in. Any MAVLink-compatible drone works. The MQTT abstraction means the HA integration never knows or cares what's flying.
- **$4,500–$9,000 total system cost** versus $20,000–$100,000 for commercial alternatives (Skydio Dock, Sunflower Labs, Percepto).

## What this project is not

- **Not ready to fly.** Active design phase. Phase 0 bridge MVP is merged; HA integration is next. See [Status](#status) below.
- **Not a toy.** This system puts an aircraft in the air. The regulatory, safety, and security requirements are treated with the seriousness they demand.
- **Not a DJI integration.** An earlier version targeted DJI Mavic 2 hardware; that path was abandoned due to the FCC Covered List, proprietary SDK lock-in, and no Part 108 viability.
- **Not a substitute for regulatory compliance.** The operator is solely responsible for certifications, airspace verification, Remote ID, insurance, DPIA (EU), and all applicable law. The project provides the software scaffold; the operator writes the ConOps, obtains the authorisation, and accepts liability.

## How it works

<p align="center"><img src="https://raw.githubusercontent.com/acato/drone_hass/main/docs/diagrams/system-overview.svg" alt="System Architecture"></p>

The add-on and integration communicate **exclusively via MQTT**. The bridge owns the drone. The integration owns the HA experience. The dock runs its own safety logic.

## Status

Design mature; implementation in progress.

- **Phase 0 (shipped)** — MAVLink-MQTT bridge MVP with telemetry publishers, command handlers, ComplianceGate Part 107 skeleton, one-shot SITL dev stack. No aircraft required for development.
- **Phase 1 (next)** — HA integration repo: entities, services, config flow, dashboard.
- **Phase 2+** — Dock ESPHome firmware, two-tier compliance recorder video integration, DAA extensions (FLARM for EU), EU country-specialisation plugins.

## Get involved

This project needs collaborators. If you have experience in any of these areas, there is meaningful work to do:

- **ArduPilot / MAVLink** — bridge implementation, SITL testing, mission protocol, MAVLink v2 signing, AP_Avoidance tuning.
- **Python async** — MAVSDK-Python, aiomqtt, the bridge event loop, compliance recorder.
- **Home Assistant integration development** — custom components, MQTT coordinator pattern, config flow, entity platforms, Lovelace cards.
- **ESPHome / embedded** — dock controller firmware, safety interlocks, sensor integration.
- **Hardware / mechanical** — dock enclosure, aircraft weatherproofing, antenna placement, power systems.
- **Regulatory** — FAA Part 107/108 operational procedures, EU Specific-category SORA submissions, national DPA DPIA overlays (CNIL / BfDI / Länder / Garante).
- **Security** — the [threat model](docs/threat-model.md) has 26 threats with resolutions and red-team validation. Pressure-testing welcome.
- **Go / Rust** — the standalone compliance chain verifier needs to be a single portable binary.

The SITL-based development path means you can contribute to the bridge, integration, and compliance framework without owning a drone.

## Documentation

**Architecture and scaffold**

| Document | What it covers |
|---|---|
| [System Architecture](docs/architecture.md) | Executive summary, legal prerequisites (universal / US / EU), regulatory framework structure, platform strategy, dock design, software architecture, compliance framework, implementation plan, cost estimate |
| [Layered Invariance Model](docs/regulatory-layered-model.md) | 7-layer inside-out model that structures all regulatory + architecture discussion; adopter and contributor navigation |
| [Compliance Recorder — Two-Tier](docs/compliance-recorder-two-tier.md) | Immutable metadata chain + retention-class-gated video blob tier; applies in US mode too |
| [MAVLink-MQTT Contract](docs/mavlink-mqtt-contract.md) | MAVLink-to-MQTT field mappings with unit conversions, command sequences, JSON Schema for all payloads, 6 state machines |
| [HA Integration Spec](docs/ha-integration-spec.md) | Entity design, services, config flow, MQTT coordinator pattern, dashboard layout, recorder strategy |
| [Threat Model](docs/threat-model.md) | Attack surface map, 26 threats with implementable resolutions, red-team validation, 13-layer compliance data integrity chain |

**Regulatory (per jurisdiction)**

| Document | What it covers |
|---|---|
| [Regulatory — United States](docs/regulatory-us.md) | FAA Part 107/108 with Seattle Eastside worked scenario; 25-item deliverables checklist |
| [Regulatory — European Union (framework)](docs/regulatory-eu.md) | Pan-EU direct-effect regulations, SORA methodology, GDPR baseline, per-country architecture abstractions |
| [Regulatory — Italy](docs/regulatory-eu-it.md) | ENAC + Garante + D-Flight; worked Lavagna scenario with asymmetric south-facing geofence and GRB math; 27-item deliverables checklist |
| [Regulatory — France (seed)](docs/regulatory-eu-fr.md) | DGAC + AlphaTango + CNIL — flagged as partial; CNIL DPIA overlay is the reference template |
| [Regulatory — Germany (seed)](docs/regulatory-eu-de.md) | LBA + 16 Länder + DIPUL + Länder DPAs — flagged as partial; Länder fragmentation is the structural problem |

## Legal notice

Drone operation is regulated by national aviation authorities (FAA in the US; EASA + national CAAs in the EU) and by applicable state / national privacy and property law. Before any flight, the operator must hold the required certifications, verify airspace classification, equip Remote ID, obtain appropriate insurance, and — in EU mode — conduct the required data-protection impact assessment. See [Architecture Section 2](docs/architecture.md#2-legal-prerequisites) for the complete universal / US / EU prerequisites split, and the per-jurisdiction regulatory documents for full depth.

**This software is provided as-is with no warranty. The operator accepts full responsibility for lawful operation and for any damages or penalties resulting from use. This software makes no representation that its use will result in compliance with FAA Part 107, FAA Part 108, EASA Regulation 2019/947, GDPR, or any other regulation. Regulatory compliance is the operator's sole responsibility.**

## Trademarks

ArduPilot is a trademark of the ArduPilot Project. MAVLink is associated with the Dronecode Foundation. Home Assistant is a trademark of the Open Home Foundation. Pixhawk is a trademark of the Dronecode Foundation. Holybro, Siyi, uAvionix, Skydio, DJI, Raspberry Pi, and all other product and company names mentioned are trademarks or registered trademarks of their respective owners.

drone_hass is an independent open-source project. It is not affiliated with, endorsed by, or sponsored by any of the above organisations or companies. This project is not affiliated with the FAA, EASA, ENAC, DGAC, LBA, CNIL, the Italian Garante, the BfDI, or any other regulator. No regulatory approval of this software is implied or claimed.

## License

[Apache 2.0](LICENSE)
