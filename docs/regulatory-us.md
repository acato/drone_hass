# United States — Regulatory Specialisation

> **Date:** 2026-04-20
> **Status:** Primary target jurisdiction — worked scenario (Seattle Eastside)
> **Version:** 0.1.0
> **Layers covered:** **Level 5** (national specialisation: FAA, Part 107, Part 108), **Level 6** (site-specific: Seattle Eastside 1-acre property). Inherits Levels 0–2 from [`regulatory-layered-model.md`](regulatory-layered-model.md). Does **not** inherit Level 3 (SORA) or Level 4 (EU framework) — US regulation is a parallel branch from the Level-2 risk-based cluster.
> **Peer:** [`regulatory-eu.md`](regulatory-eu.md) (EU framework). Both docs are meant to be read as symmetric jurisdiction-specific specialisations.

---

## 1. Purpose and Scope

This document covers US regulatory compliance for `drone_hass`, parallel to `regulatory-eu.md`. It is the **worked specialisation** for the project's primary deployment target — a ~1-acre private property on the Seattle Eastside under FAA jurisdiction.

**What this document covers:**

- FAA regulatory framework (Part 107 + Part 108 NPRM)
- Dual-mode operation (RPIC-authorised → autonomous with Flight Coordinator monitoring)
- Washington State overlay
- US insurance market, pilot certification, occurrence-reporting endpoints
- Worked scenario: Seattle Eastside 1-acre deployment
- US-specific deliverables checklist

**What it does not cover:**

- EU/SORA compliance — `regulatory-eu.md` + country specialisations
- International variants (UK, Canada, Australia) — not yet in the doc tree
- Hardware/aircraft/dock engineering — `architecture.md` Sections 5–7
- Layer-1 compliance primitives (recorder, chain, Remote ID, etc.) — `architecture.md` §8, §11 and `compliance-recorder-two-tier.md`

---

## 2. Bottom Line

| Question | Answer |
|---|---|
| Is the operation legal now (2026-Q2)? | **Yes, under Part 107** with RPIC present and authorising each flight. VLOS-constrained. |
| Is fully autonomous alarm-triggered flight legal now? | Not as a routine product. Under **ordinary Part 107 operations** the RPIC must maintain VLOS and be on-site — the "alarm triggers flight while no one is home" scenario does not fit that. The planned path is **Part 108 once finalised**. Extraordinary §107.31 / §107.33 waiver-based pathways may exist but are fact-specific, case-by-case, and uncertain — not a productisable design target. |
| Expected Part 108 availability | NPRM published 2025-08-07. **Final rule is not yet published; timeline estimates (e.g. "summer 2026") are planning assumptions derived from the NPRM comment-cycle schedule, not present legal certainty.** Verify publication status before relying on any Part-108-based compliance claim. |
| Operating tier likely to apply | **Part 108 Operating Permit** (not Certificate) — lower-risk operations, population density Categories 1–3. |
| Which SAIL-like tier? | Part 108 uses population density Categories (1–4), not SAIL. This property is Category 2–3 (residential suburban). |
| Does FAA accept DIY / homebuilt airframes under Part 108? | **Unclear.** NPRM is manufacturer-centric (Declaration of Compliance required). Homebuilder pathway depends on final rule. |
| FAA Part 107 certificate transfer to EU? | No — not recognised. See `regulatory-eu.md §7`. |
| Biggest non-aviation concern | **Washington State privacy law** (reasonable expectation of privacy on neighbouring property) + homeowner's insurance exclusions for commercial UAS. |
| Timeline / cost (Part 107) | Already flying — Part 107 certificate (~$175 fee + ~40 h study) + drone insurance ($500–1,500/year) + Remote ID module + standard hardware. |
| Timeline / cost (Part 108) | First permit cycle after final rule; estimated 6–12 months, FAA fees TBD, engineer time significant for compliance evidence. |

---

## 3. FAA Regulatory Framework

### 3.1 Applicable Law

Drone operation in the US is governed by **federal law (FAA)**, not state law. Aviation is a preempted federal domain under 49 U.S.C. § 40103. State laws on privacy, trespass, and property rights still apply (§7), but states cannot regulate airspace or aircraft operation.

This use case — property security triggered by an alarm — is **commercial/operational**, not hobby/recreational. **14 CFR Part 107** applies today; **14 CFR Part 108** will apply when finalised.

### 3.2 Key instruments

| Instrument | Purpose |
|---|---|
| **14 CFR Part 107** | "Small Unmanned Aircraft Systems" — current operational rule for commercial UAS <55 lb. VLOS, 400 ft AGL cap, daylight+civil-twilight, Remote ID required, RPIC certificate required. |
| **14 CFR Part 108 (NPRM 2025-08-07)** | BVLOS operational rule. Two tiers (Permit, Certificate). Operations Supervisor + Flight Coordinator model. Population density Categories 1–4 replace blanket altitude caps. Cooperative DAA (ADS-B In) mandatory. |
| **14 CFR Part 48** | FAA drone registration (every aircraft, commercial or recreational). |
| **14 CFR Part 89** | Remote Identification. Mandatory since September 2023. ASTM F3411 + FAA-specific profile. |
| **14 CFR Part 91.225 / 91.227** | ADS-B Out equipage rule (most US GA ≥2020); why US ADS-B coverage is much higher than EU. |
| **Advisory Circulars** (90-0, 107, future 108) | FAA non-binding guidance; effectively the interpretive authority operators rely on for ambiguous rules. |
| **49 U.S.C. §§ 44809, 44807** | Hobbyist and commercial authorisation statutes; authority for Parts 107/108. |

### 3.3 Remote ID profile (Level 4-US)

US Remote ID uses **ASTM F3411-22a** as the underlying standard (shared with EU) with an FAA-specific frame profile and a **CTA-2063-A** serial number format. Differs from the EU EN 4709-002 profile in operator-ID format and frame fields.

Dual-certified modules (Dronetag, BlueMark) carry both FAA and ASD-STAN declarations. This is the cheapest EU-hedge on the hardware side.

---

## 4. Part 107 — Current Operating Mode *(L5 specialisation)*

Part 107 governs all flight operations until a Part 108 Permit is obtained.

### 4.1 Prerequisites

| Requirement | Status |
|-------------|--------|
| FAA Part 107 Remote Pilot certificate (RPIC) | Required — 60-question exam ($175), biennial recurrent training |
| FAA drone registration (Part 48) | Required |
| Remote ID broadcast (Part 89) | Required. ArduPilot supports OpenDroneID; external module (e.g., uAvionix ping Remote ID, Dronetag BS) required if firmware lacks it |
| Anti-collision strobe for night ops | Required — must be visible for 3 statute miles |
| Visual Line of Sight (VLOS) | Required — RPIC or visual observer must see drone with unaided vision (corrective lenses OK, binoculars not). The live video feed does **NOT** satisfy VLOS |
| Fly under 400 ft AGL | Yes (missions at 80–120 ft) |
| Class G airspace verification | Confirm property is in unrestricted airspace via FAA B4UFLY or sectional charts |
| LAANC authorisation | Not required for Class G |
| RPIC physical presence | RPIC must be on or near the property — within visual range of the aircraft — before authorising launch. Tapping LAUNCH from an office while watching a phone stream is a Part 107 violation |

### 4.2 The human-in-the-loop constraint

Under Part 107, a **Remote Pilot in Command** must be responsible for the flight, be able to intervene immediately, and explicitly authorise takeoff. The system satisfies this with a **single-tap authorisation** step — the same compliance pattern used commercially by DJI Dock, Skydio Dock, and Percepto.

### 4.3 VLOS realities for this property

- Property is ~300 ft × 150 ft, flat, 1 acre. VLOS is maintainable for daylight operations on all planned mission corridors.
- "Maintainable" is not the same as "maintained" — the RPIC must actually be watching the aircraft, not the HA dashboard. The live video feed is for situational awareness and evidence capture, not for satisfying VLOS.
- Night operations: anti-collision strobe must be visible for 3 statute miles. At 80–110 ft on a 1-acre property, VLOS via strobe is achievable, but the RPIC must be **outdoors** watching the aircraft.
- The RPIC must be **physically present on or near the property** before tapping LAUNCH. The system cannot technically enforce RPIC location, but the burden is on the operator: *do not authorise flight unless you are within visual range of the planned flight corridor.*
- The "person detected while no one is home" scenario is **not a routine Part 107 use case** — ordinary Part 107 requires VLOS maintained by the RPIC or a visual observer on-site (14 CFR 107.31, 107.33). The *planned* path is Part 108 once finalised. **An extraordinary §107.31 / §107.33 waiver pathway may exist** and the FAA has granted VLOS and related waivers in the past, but such waivers are fact-specific, case-by-case, heavily documented, non-transferable, and uncertain to obtain. Treat waiver-based operation as off-path for design purposes — it is not a productisable target, and this document and the ComplianceGate assume ordinary Part 107 constraints (VLOS + on-site RPIC) until Part 108 is final.

### 4.4 Operations over non-participants and moving vehicles

14 CFR Part 107 Subpart D (§§ 107.100–107.155) regulates operations over people and moving vehicles. The perimeter-patrol use case routinely flies near both — neighbours on adjacent property, pedestrians on the public road, and vehicles on that road. The ComplianceGate and geofence must encode these rules explicitly; the privacy discussion in §7 is **not** a substitute.

#### 4.4.1 Over people (14 CFR 107, Subpart D)

The FAA defines four categories of small UAS cleared to operate over people; each requires the aircraft to meet specific kinetic-energy and safety criteria:

- **Category 1** — UAS ≤ 0.55 lb (250 g), no exposed rotating parts that could cause laceration.
- **Category 2, 3, 4** — each defined by declining permissibility against uninvolved persons, tied to Means of Compliance (MoC) declarations the manufacturer must file. The self-built ArduPilot in this project **does not hold any of these MoC declarations** and therefore cannot lawfully operate over uninvolved persons in its current configuration.

**Operational implication for this project:** operations over uninvolved persons are **not authorised** regardless of Part 107 certificate status, until either (a) the aircraft meets a relevant Category and a declaration is filed, or (b) a specific waiver is obtained. The "non-participant" concept applies broadly — anyone who is not directly involved in the operation (neighbours, visitors, passers-by) is an uninvolved person.

**Design controls:**

- **Geofence hard-excludes** any corridor that would place the aircraft over a public road, a neighbouring residence's curtilage, or other known uninvolved-person locations.
- **Mission planning** restricts flight paths to the operator's own property, accounting for realistic flight-path dispersion (see the SORA-analogue GRB thinking in the EU docs, which applies conceptually here too even if not legally required).
- **Abort logic** triggers if a person is detected inside the mission area — either via pre-flight check (visual / camera sweep before takeoff) or during flight via operator override.

#### 4.4.2 Over moving vehicles (14 CFR 107.145)

§ 107.145 permits sustained flight over moving vehicles only under narrow conditions (within a closed or restricted-access site where all persons in vehicles are participants, or a per-flight waiver). For perimeter patrol near a **public road** these conditions are not met: road users are not participants.

**Operational implication:** the aircraft must not sustain flight over the public road at the property's south boundary. Transient crossings may be permissible in limited cases; sustained patrol is not.

**Design controls:**

- Geofence hard-excludes the road corridor (matching the EU Lavagna-scenario asymmetric south inset, for the same reason).
- Mission logic does not generate waypoints inside the road-exclusion polygon.
- If a mission requires approaching the south boundary, the altitude cap and speed profile must keep the ground-risk buffer entirely on-property — same math as the EU SORA GRB analysis, applied as a safety-of-flight discipline even where Part 107 does not require a formal document.

#### 4.4.3 Assembly of persons

§ 107.145(b) also forbids flight over open-air assemblies of persons (e.g., a backyard gathering, a community event). The ComplianceGate cannot detect an assembly in real time, but the operator / RPIC can — **and must abort the flight if one is observed within the operational area before or during launch.** The pre-flight checklist includes a neighbour-awareness step: confirm no visible gathering on adjacent property. This is operational discipline, not software-enforceable.

#### 4.4.4 Summary

| Concern | Rule | This project's enforcement |
|---|---|---|
| Sustained flight over uninvolved persons | Part 107 Subpart D Categories 1–4 (MoC-dependent) | Geofence excludes known uninvolved-person locations; no MoC filed, so default is "no overflight" |
| Transient overflight of uninvolved persons | Still requires Category compliance in most cases | Geofence + pre-flight check; operator abort on observation |
| Sustained flight over moving vehicles on public road | § 107.145 generally prohibits | Geofence excludes road corridor |
| Flight over open-air assembly of persons | § 107.145 prohibits | Operator pre-flight check + in-flight abort |
| Neighbour-property corridor traversal | Not per se prohibited, but implicates both Subpart D (if people present) and state trespass / privacy law (§7) | Geofence keeps mission corridors on own property |

These controls apply regardless of Part 107 vs Part 108 mode — even under Part 108 the operational volume defined in the Permit must respect the over-people and over-vehicles rules at whatever form they take in the final rule.

### 4.5 ComplianceGate behaviour — Part 107 mode

```
Alarm
  → Safety checks (weather, battery, dock, DAA health, op-area)
  → RPIC notification (HA mobile tap required)
  → Human tap within timeout
  → Launch
  → Per-flight compliance record written
```

The per-flight tap is the invariant Part 107 requires; everything else is shared with Part 108 mode.

---

## 5. Part 108 — Target Operating Mode *(L5 specialisation)*

Part 108 is the target regulatory framework. The NPRM was published **2025-08-07**. The final rule has not been published as of this document's date. **All Part-108-specific claims in this section are forecast from the NPRM, not present legal conclusions.** The final rule may diverge from the NPRM on any or all of: timeline, permit-tier definitions, DAA performance standards, airworthiness acceptance pathway, population-density categorisation, and equipment mandates. Estimates like "summer 2026," "Operating Permit likely applies to this property," and the equipment tables below are planning assumptions, not settled law. Re-verify the final rule when it is published.

### 5.1 What Part 108 changes

| Part 107 Constraint | Part 108 Replacement |
|---|---|
| RPIC must authorise each flight | Operations Supervisor + Flight Coordinator roles; no per-flight authorisation required |
| RPIC must hold Part 107 certificate | Organisational responsibility model; no individual pilot certification required in the same form |
| VLOS required | BVLOS authorised within approved operational area |
| Per-flight waivers for BVLOS | Operational area pre-approved; routine flights within it without per-flight permission |
| Human is a gatekeeper | Human is a monitor — Flight Coordinator can intervene but does not pre-authorise |

### 5.2 Two authorisation tiers (from NPRM)

1. **Operating Permit** — in the NPRM framing, lower-risk operations, less FAA oversight. Available for operations in population density Categories 1–3 as proposed. Residential suburban (Seattle Eastside) is likely Category 2–3 under the NPRM classification and therefore would be within the Permit pathway *as proposed*. **Forecast, not certainty — the final rule may redefine tiers, density categories, or the operations eligible for each.**
2. **Operating Certificate** — higher-risk/complexity operations, greater organisational obligations.

### 5.3 DAA requirements for Class G, Category 2–3

- **Cooperative DAA mandatory**: detect aircraft broadcasting ADS-B (1090 MHz and UAT/978 MHz).
- **Non-cooperative detection** (radar, optical): NOT required for this category.
- Aircraft must determine collision risk and execute avoidance manoeuvres autonomously.

US ADS-B Out equipage is high (91.225 mandate), so ADS-B In alone is a much stronger DAA position than in the EU, where EU light-aviation ADS-B Out equipage is sparse and FLARM fills the gap.

### 5.4 Prerequisites

| Requirement | Detail |
|-------------|--------|
| Operating Permit or Certificate | Application to FAA for approved operational area |
| Cooperative DAA (ADS-B In) | Aircraft must detect and yield right-of-way to ADS-B-broadcasting traffic |
| Standard Remote ID | Continuous position broadcast during operations (Part 89 compliance unchanged) |
| Airworthiness acceptance | Aircraft must have a Declaration of Compliance from manufacturer — see §5.6 |
| Operations Supervisor designation | Person responsible for safe operation of all flights |
| Flight Coordinator designation | Person with tactical oversight during flight; must be able to intervene |
| Compliance records | Flight logs, DAA events, weather, personnel — see `architecture.md §11` |
| Defined operational area | Pre-approved geographic volume for BVLOS operations |

### 5.5 ComplianceGate behaviour — Part 108 mode

```
Alarm
  → Automated safety checks (weather, DAA health, airspace, battery, dock)
  → Operational area validated
  → Flight Coordinator on duty confirmed
  → Autonomous launch
  → Flight Coordinator notified (monitoring, can ABORT/RTH)
  → Mission executes
  → RTL → dock closes
  → Compliance record written
```

The per-flight human tap disappears. The Flight Coordinator is a monitor with override capability, not a gatekeeper.

### 5.6 The airworthiness question

The Part 108 NPRM's airworthiness acceptance framework is built around **manufacturers** issuing Declarations of Compliance. A homebuilt ArduPilot quad does not have a "manufacturer" in the regulatory sense.

**Current uncertainty:** The NPRM does not clearly accommodate DIY/homebuilt UAS. The 3,000+ NPRM comments likely included pushback on this point, and the final rule may create a homebuilder pathway. **As of 2026-04, a DIY build may not qualify for Part 108 operations.**

**Mitigations:**

1. Use a commercial ArduPilot-based airframe (Holybro, CubePilot) from a vendor likely to pursue Declaration of Compliance.
2. The ArduPilot project may pursue a means of compliance for the firmware itself.
3. The software stack is airframe-agnostic — if Part 108 requires a specific manufacturer's DoC, swap the drone and keep the entire ground system intact.
4. Monitor the final rule; if the homebuilder pathway is closed, Parrot ANAFI (Olympe SDK, Blue UAS) becomes the flight hardware with this open-source ground system.

**Strategy:** Build on a commercial ArduPilot frame from a recognised manufacturer. Design the software to be airframe-agnostic. Wait for the final rule before committing to a specific compliance path. See `architecture.md §6.6` for the ongoing hardware-strategy discussion.

---

## 6. Dual-Mode Architecture *(L1 primitive, L5 parameterisation)*

The ComplianceGate implements both Part 107 and Part 108 modes, selectable via configuration. **Part 107 mode is a strict subset of Part 108 mode** — everything Part 108 requires (DAA, logging, weather checks, operational-area validation), Part 107 operations also benefit from. The only operational difference is whether a human tap is required before launch.

This mirrors the architectural pattern used by the `ComplianceGate` in `mavlink_mqtt_bridge/compliance.py`, with `OperationalMode.PART_107` and `OperationalMode.PART_108` enum values. The same module extends naturally to `OperationalMode.EU_SPECIFIC_SORA` for EU deployments — see `regulatory-eu.md §10`.

---

## 7. Washington State Overlay *(L6)* — a Litigation-Risk Surface, Not Black-Letter Rule

**Federal preemption on airspace is real.** Under 49 U.S.C. § 40103, the federal government has exclusive sovereignty over navigable airspace; states cannot regulate flight as such. What remains to the states is **everything adjacent to aviation**: privacy, trespass, nuisance, property rights, some municipal ground-level restrictions. The legal landscape for drone overflight of neighbouring property is **unsettled** in Washington as in most U.S. jurisdictions; this section describes it as a litigation-risk surface, not a clean rule the project can enforce by geofence alone.

- **Privacy** — avoid surveillance where people have a reasonable expectation of privacy (neighbour yards, windows, curtilage). RCW 9A.44.115 (voyeurism) and common-law intrusion-upon-seclusion are the relevant causes of action. Camera angle, mask polygons, and retention settings are partial technical mitigations; they do not eliminate litigation risk if a neighbour alleges observation of private space.
- **Neighbour-airspace overflight** — crossing into the column above a neighbour's parcel is a **contested legal question**, not a settled prohibition. The FAA preempts regulation of navigable airspace; the neighbour retains property-law and tort-law claims for surface-adjacent low-altitude overflight under doctrines that trace back to *United States v. Causby* and have been applied unevenly to drones. Washington case law on drone overflight is thin; *Baggett v. Gates* and its progeny address related (not identical) issues. Prudent project posture: **treat neighbour airspace as a litigation-risk surface**. The ComplianceGate geofence is configured to keep missions within the operator's own property column as a risk-reduction measure, not because black-letter law requires it in every case.
- **Trespass by aircraft** — WA courts have not squarely ruled on drone trespass at operational altitudes (80–120 ft AGL). Outcomes in related jurisdictions have been fact-dependent, varying with altitude, duration, camera use, and whether the neighbour suffered measurable intrusion or harm. Operators should assume worst-case for planning: a neighbour can sue, and whether the suit succeeds depends on facts we cannot predict.
- **State parks** — require permission; private residential land is fine under state rules.
- **No statewide drone registration** beyond FAA Part 48; no WA-specific Remote ID.
- **Local ordinances** — some municipalities (Seattle, Redmond) have park-area drone restrictions. Verify city/county code at the deployment site.

**No state DPA equivalent.** Unlike GDPR under EU regimes, the US has no federal data-protection law. Washington's My Health My Data Act (2024) is scoped to health data and is not typically implicated by perimeter-patrol footage. Privacy litigation exposure rests on common-law and RCW 9A.44.115, not on a regulatory DPIA regime.

**Design discipline in response:** the project's asymmetric geofence keeping missions on-property, the wide-angle camera default, the mask polygons, and short-retention defaults are all chosen to *minimise* (not eliminate) the WA litigation-risk surface. None of these replace counsel review for the specific deployment.

---

## 8. Seattle Eastside — Worked Site Scenario *(L6)*

### 8.1 Site

~1-acre property in Seattle's Eastside suburban corridor. Flat, ~300 ft × 150 ft, residential zoning. 50+ trees on-property (some >100 ft). Surrounded by similar residential parcels, no public-road frontage close to mission corridors, no commercial/industrial neighbours.

### 8.2 Airspace

- **Class G at surface**, transitioning to controlled airspace above.
- Verify via FAA B4UFLY and VFR sectional at the exact property coordinates before any flight.
- No nearby CTR within ~15 NM. Seattle-Tacoma International (KSEA) Class B is ~20 NM west; Renton (KRNT) Class D is within range depending on exact Eastside location — check during prerequisites.
- Operational altitude: 80–120 ft AGL (well under 400 ft cap).

### 8.3 Mission design

With 50+ trees (some >100 ft), missions are **constrained corridor sweeps**, not a simple perimeter orbit:

| Mission | Description | Altitude |
|---|---|---|
| `front_sweep` | Driveway + front edge | 80 ft (clear corridor) |
| `rear_sweep` | Back fence line | 80 ft |
| `east_edge` | East property boundary | 110 ft (taller trees) |
| `west_edge` | West property boundary | 80 ft |
| `full_perimeter` | All 4 edges sequentially | Variable per segment |
| `corner_ne / nw / se / sw` | Quick corner investigation | 80–110 ft |

Altitude is a **safety spec** (tree clearance + margin), not a fixed number. Camera angle compensates: gimbal at −30 to −45° provides border coverage from higher altitudes.

All missions must stay within the defined operational area (`architecture.md §11.3`).

### 8.4 Weather envelope

Seattle Eastside climate: mild but wet. Condensation is a bigger threat than rain. Relevant operational limits:

- Wind: ≤20 kt cruise, ≤15 kt launch/land (configurable).
- Visibility: Part 107 requires ≥3 SM. Low marine-layer fog common morning/evening spring-through-fall.
- Precipitation: no rain during flight; wet-dock condensation managed by ESPHome dock thermal controls.

See `architecture.md §5.3` for dock environmental control.

---

## 9. Insurance Market (US)

- **Homeowner's policies exclude commercial UAS** in almost all cases. A property-security drone is commercial operation regardless of whether it's on one's own land.
- **Commercial drone liability** (small UAS, Part 107 or 108): **$500–1,500 / year** for $1M coverage. Representative providers: Verifly (per-flight), BWI Aviation, SkyWatch, Avion Insurance, commercial aviation brokers.
- **Part 108 autonomous operations** will likely command higher premiums — market is pricing risk conservatively until the final rule lands.
- **No statutory minimum** equivalent to EU Reg 785/2004. FAA has no insurance mandate for Part 107; Part 108 NPRM hints at coverage expectations but does not set a floor.
- **FAA Operating Permit/Certificate applications** will likely request proof of coverage at submission; the exact floor will be set in the final rule.

Compare: EU Italy €1,100–1,800/year, France €700–1,400/year, Germany €400–900/year — US is middle-of-range for Part 107 and likely comparable to EU Italy once Part 108 premiums firm up.

---

## 10. Pilot Competency

- **Part 107 Remote Pilot certificate** — 60-question multiple-choice exam at an FAA-authorised testing centre. $175 fee. Covers airspace, weather, regulations, decision-making. Biennial recurrent training (free, online).
- **Part 108 (NPRM)** — no individual pilot certificate in the Part 107 sense. Operations Supervisor and Flight Coordinator roles are organisational designations with training and oversight requirements TBD in the final rule.
- **TRUST (The Recreational UAS Safety Test)** — not applicable here; TRUST is for recreational flyers under §44809, not commercial operators.

**Part 107 does not transfer to EU** (see `regulatory-eu.md §7`). EU A2 CofC / STS theoretical similarly does not transfer to FAA.

---

## 11. Occurrence Reporting

Under Part 107, accident reporting is required within **10 days** for:

- Serious injury or loss of consciousness.
- Property damage >$500 (other than the UAS itself).

Reports filed via **FAA Form 8710-13** (Accident/Incident Report) or the FAA's online reporting portal.

Part 108 NPRM contemplates a more structured occurrence-reporting framework closer to manned-aviation Mandatory Occurrence Reporting (analogous to EU Reg 376/2014). Final rule pending.

The bridge's occurrence-reporting module uses ECCAIRS-compatible serialisation (same underlying standard as EU); the US submission adapter targets the FAA portal rather than the Italian eE-MOR or the German BAF endpoint. See `regulatory-layered-model.md §3.3` and `architecture.md §11`.

---

## 12. US Cost Breakdown

| Line item | USD | One-time / Annual | Mandatory | Self-doable |
|---|---|---|---|---|
| FAA Part 107 exam | 175 | one-time + biennial recurrent (free) | yes | yes |
| FAA drone registration (Part 48) | 5 | every 3 years | yes | yes |
| Remote ID module (EU-dual-cert hedged) | 100–300 | one-time | yes | yes |
| Commercial drone liability insurance ($1M) | 500–1,500 | annual | effectively yes | yes |
| FAA Part 108 Permit application fee | TBD | one-time + renewal | yes (Part 108) | likely yes |
| FAA Part 108 compliance evidence | — | one-time | yes (Part 108) | significant engineer time |
| Aircraft + dock (standard BOM) | 4,500–9,000 | one-time | yes | yes — see `architecture.md §17` |
| Engineer time (Part 108 permit, self-prepared) | 50–150 h | one-time | n/a | — |

**Total operator cost (Part 107 current)**: ~$600–1,700 first year (excluding aircraft).
**Additional for Part 108** (once final rule lands): ~TBD + 50–150 engineer-hours.

Compare with EU Italy: €3.5–5k + 150–250 engineer-hours. The US path is **cheaper in fees but requires more aircraft-side infrastructure** (commercial airframe with Declaration of Compliance), which is a larger hardware cost under Part 108.

---

## 13. Self-do vs Consultant (US)

Senior engineer, Part 107 literate:

- **Self-do comfortably**: all current Part 107 operations, aircraft assembly, ArduPilot configuration, SITL validation, ComplianceGate setup, ops manual drafting.
- **Likely self-do for Part 108**: operational area definition, ConOps narrative, compliance record management, FAA Permit application (following FAA templates once published).
- **Hire only if needed**: aviation attorney if the Part 108 homebuilder pathway requires legal interpretation; aviation insurance broker for Part 108 coverage at potentially higher limits.

Compared to EU Italy (where SORA documentation is the dominant effort and consultants are often hired), the US Part 107 path is low-friction; the Part 108 path has more unknowns until the final rule.

---

## 14. Deliverables Checklist (US)

**Registration & certification**

1. [ ] FAA Part 107 certificate issued
2. [ ] Part 107 recurrent training current (biennial)
3. [ ] FAA drone registration (Part 48)
4. [ ] Aircraft marked with FAA registration number + Remote ID

**Aircraft & payload**

5. [ ] Airframe airworthy (flight-tested ≥20 h without anomaly)
6. [ ] Remote ID module compliant with Part 89 (dual-cert module hedges EU path)
7. [ ] Anti-collision strobe for night ops (visible 3 SM)
8. [ ] Geofence verified in SITL and on-aircraft
9. [ ] DAA (ADS-B In via pingRX) integrated and tested (required for Part 108; prudent for Part 107)
10. [ ] Parachute system installed and tested (optional Part 107; advisable Part 108)

**Insurance & legal**

11. [ ] Commercial drone liability policy in force, $1M minimum
12. [ ] HA config flow acknowledgment completed by operator
13. [ ] Airspace verified via FAA B4UFLY for deployment site

**Part 107 operational**

14. [ ] Ops manual drafted and current
15. [ ] RPIC on-site before each flight (operational procedure, not technical enforcement)
16. [ ] VLOS verified each flight
17. [ ] Flight log retained (ComplianceGate automated)

**Part 108 additional** (when final rule applies)

18. [ ] FAA Operating Permit / Certificate issued
19. [ ] Operations Supervisor designated
20. [ ] Flight Coordinator designated and on duty
21. [ ] Declaration of Compliance from aircraft manufacturer (may require commercial airframe swap — see §5.6)
22. [ ] Compliance records submitted as required by rule

**Post-flight / ongoing**

23. [ ] Occurrence reporting procedure rehearsed (10-day window, Form 8710-13)
24. [ ] Insurance renewal calendar T-90 days
25. [ ] Part 107 recurrent T-90 days before biennial expiry

---

## 15. Open Questions / Verify-Before-Relying

- Part 108 final rule publication date and substantive divergence from the NPRM.
- Whether Part 108 final rule creates a homebuilder airworthiness pathway or closes it.
- Specific FAA Operating Permit application format and fee schedule (published with the final rule).
- Whether FAA will adopt a structured MOR-equivalent occurrence-reporting scheme under Part 108.
- ADS-B Out equipage for specific aircraft types (helicopters, gliders, ultralights) in the Seattle Eastside area — verify sector-by-sector before Part 108 application.
- Exact municipal/county drone ordinances at the deployment coordinates.

---

## 16. References

- **FAA** — B4UFLY, drone regulations portal (`faa.gov/uas`).
- **FAA** — Part 107 rule and Advisory Circular AC 107-2.
- **FAA** — Part 108 NPRM (published 2025-08-07, Federal Register).
- **FAA** — Part 48 drone registration.
- **FAA** — Part 89 Remote Identification rule.
- **14 CFR** — complete text via eCFR.
- **ASTM F3411-22a** — Remote ID technical standard (shared with EU).
- **CTA-2063-A** — Small UAS Serial Numbers.
- **RCW 9A.44.115** — Washington voyeurism (relevant privacy surface).
- `architecture.md` §6.6 — airworthiness strategy.
- `architecture.md` §11 — compliance framework.
- `architecture.md` §17 — cost estimate.

Peer: [`regulatory-eu.md`](regulatory-eu.md), layered model at [`regulatory-layered-model.md`](regulatory-layered-model.md).

---

*This document is a design-review artifact, not legal advice. Operators must verify current FAA regulations at implementation time and may require counsel for Part 108 edge cases once the final rule is published.*
