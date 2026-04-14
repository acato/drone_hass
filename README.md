# drone_hass

Commercial drone-in-a-box security systems cost $20,000-$100,000. drone_hass is the open-source alternative — alarm-triggered autonomous perimeter patrol, live video streaming, and FAA-compliant audit logging, built on Home Assistant, MAVLink, and ArduPilot.

Your alarm triggers. Thirty seconds later, the drone is airborne, flying a predefined perimeter mission, streaming live video to your HA dashboard. When it lands, a signed compliance record is timestamped via OpenTimestamps and replicated to immutable cloud storage — independently verifiable, permanently anchored, ready for an FAA Part 108 Operating Permit review.

## What this project is

- **Alarm-to-airborne in under 30 seconds.** HA automation handles safety checks, dock opens, drone launches, video streams — fully autonomous under Part 108, or one-tap RPIC authorization under Part 107.
- **Live RTSP video in your HA dashboard.** No proprietary app, no cloud subscription. Camera streams directly through go2rtc/mediamtx to a standard HA camera entity.
- **Develop without hardware.** ArduPilot SITL simulates a full drone on your workstation. Build and test the entire system — bridge, HA integration, missions, compliance — before you touch a soldering iron.
- **Part 108 compliance framework from day one.** Not bolted on later. Every flight produces a verifiable audit trail backed by five independent integrity mechanisms — each proving a different property, each controlled by a different entity:

  | Mechanism | What it proves | Who controls it |
  |-----------|---------------|-----------------|
  | **Ed25519 signatures** | Who wrote the record | The bridge instance |
  | **SHA-256 hash chain** | No records removed or altered | The bridge instance |
  | **OpenTimestamps** | When the record was written | No one (decentralized) |
  | **Litestream + S3 Object Lock** | Off-device backup exists | Operator's cloud (deletion-proof) |
  | **FAA Remote ID** | The flight actually occurred | The FAA (operator cannot alter) |

  The open-source Part 108 compliance tooling is the most novel contribution of this project.
- **MAVLink-native, aircraft-agnostic.** No proprietary SDKs, no vendor lock-in. Any MAVLink-compatible drone works. The MQTT abstraction means the HA integration never knows or cares what's flying.
- **$4,500-$9,000 total system cost** vs $20,000-$100,000 for commercial alternatives (Skydio Dock, Sunflower Labs, Percepto).

## What this project is not

- **Not ready to fly.** The project is in active design phase. No code has been released yet. See [Status](#status) below.
- **Not a toy.** This system puts an aircraft in the air. The regulatory, safety, and security requirements are treated with the seriousness they demand.
- **Not a DJI integration.** An earlier version targeted DJI Mavic 2 hardware; that path is abandoned due to the FCC Covered List, proprietary SDK lock-in, and no Part 108 viability.
- **Not a substitute for regulatory compliance.** The operator is solely responsible for FAA certifications, airspace verification, Remote ID, insurance, and all applicable law.

## How it works

<p align="center"><img src="https://raw.githubusercontent.com/acato/drone_hass/main/docs/diagrams/system-overview.svg" alt="System Architecture"></p>

The add-on and integration communicate **exclusively via MQTT**. The bridge owns the drone. The integration owns the HA experience. The dock runs its own safety logic.

## Status

Architecture and design phase. The four design documents below define the complete system — MQTT schemas, state machines, JSON schemas, entity design, threat model with red team validation.

**The first code milestone** is the MAVLink-MQTT bridge running against ArduPilot SITL. No physical hardware needed. This is where implementation starts.

## Get involved

This project needs collaborators. The design is mature; the implementation is starting. If you have experience in any of these areas, there is meaningful work to do:

- **ArduPilot / MAVLink** — bridge implementation, SITL testing, mission protocol, MAVLink v2 signing, AP_Avoidance tuning
- **Python async** — MAVSDK-Python, aiomqtt, the bridge event loop, compliance recorder
- **Home Assistant integration development** — custom components, MQTT coordinator pattern, config flow, entity platforms, Lovelace cards
- **ESPHome / embedded** — dock controller firmware, safety interlocks, sensor integration
- **Hardware / mechanical** — dock enclosure, aircraft weatherproofing, antenna placement, power systems
- **FAA Part 107/108 regulatory** — operational procedures, compliance documentation, Permit application process
- **Security** — the [threat model](docs/threat-model.md) has 26 threats with resolutions and red team validation. Pressure-testing welcome.
- **Go / Rust** — the standalone compliance chain verifier needs to be a single portable binary

The SITL-based development path means you can contribute to the bridge, integration, and compliance framework without owning a drone.

## Documentation

| Document | What it covers |
|----------|---------------|
| [System Architecture](docs/architecture.md) | Regulatory framework, platform strategy, dock design, software architecture, compliance framework, weatherproofing, implementation plan, cost estimate |
| [MAVLink-MQTT Contract](docs/mavlink-mqtt-contract.md) | Every MAVLink-to-MQTT field mapping with unit conversions, command sequences, JSON Schema for all payloads, 6 state machines (drone lifecycle, mission, DAA, connection, upload protocol, avoidance) |
| [HA Integration Spec](docs/ha-integration-spec.md) | Entity design, services, config flow, MQTT coordinator pattern, dashboard layout, recorder strategy, event design |
| [Threat Model](docs/threat-model.md) | Attack surface map, 26 threats with implementable resolutions, red team validation of all mitigations, 13-layer compliance data integrity chain |

## Legal notice

Drone operation in the U.S. is regulated by the FAA (14 CFR Part 107, upcoming Part 108) and by state law. Before any flight, the operator must hold the required certifications, verify airspace classification, equip Remote ID, and obtain appropriate insurance. See [Architecture Section 2](docs/architecture.md#2-legal-prerequisites) for the complete prerequisites checklist.

**This software is provided as-is with no warranty. The operator accepts full responsibility for lawful operation and for any damages or penalties resulting from use. This software makes no representation that its use will result in compliance with FAA Part 107, Part 108, or any other regulation. Regulatory compliance is the operator's sole responsibility.**

## Trademarks

ArduPilot is a trademark of the ArduPilot Project. MAVLink is associated with the Dronecode Foundation. Home Assistant is a trademark of the Open Home Foundation. Pixhawk is a trademark of the Dronecode Foundation. Holybro, Siyi, uAvionix, Skydio, DJI, Raspberry Pi, and all other product and company names mentioned are trademarks or registered trademarks of their respective owners.

drone_hass is an independent open-source project. It is not affiliated with, endorsed by, or sponsored by any of the above organizations or companies. This project is not affiliated with the FAA. No FAA approval of this software is implied or claimed.

## License

[Apache 2.0](LICENSE)
