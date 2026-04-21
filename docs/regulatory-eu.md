# EU — Regulatory Framework (Pan-European)

> **Date:** 2026-04-20
> **Status:** Design-review / pressure test
> **Version:** 0.2.0
> **Layers covered:** primarily **Level 4** (EU regulatory framework) with **Level 3** (SORA methodology) context and pointers to **Level 2** (`regulatory-layered-model.md` §3.3) primitives. National specialisations below are **Level 5**.
> **Specialisations:** [`regulatory-eu-it.md`](regulatory-eu-it.md) (Italy, worked scenario), [`regulatory-eu-fr.md`](regulatory-eu-fr.md) (France, seed), [`regulatory-eu-de.md`](regulatory-eu-de.md) (Germany, seed)
> **See also:** [`regulatory-layered-model.md`](regulatory-layered-model.md) — the conceptual spine for all regulatory docs.

---

## 1. Purpose and Scope

This document is a **pressure test of the `drone_hass` design against the European regulatory framework**. It parallels `architecture.md §2–3` (US Part 107/108) at the EU layer.

**What this document is:**

- A gap analysis of what the current design would need to change to operate legally under EU Regulations 2019/947 and 2019/945 and the attendant delegated acts.
- The **EU-common core** — harmonised framework, category determination, SORA methodology overview, GDPR baseline, EU-wide hardware/firmware one-way-doors, architecture abstractions for per-country pluggability.
- A map to country-specific specialisations. Italy is the worked scenario (`regulatory-eu-it.md`, fully developed); France and Germany are seeded (`regulatory-eu-fr.md`, `regulatory-eu-de.md`) with the cross-country findings but are not yet deployment-ready.

**What this document is not:**

- Legal advice. Any real deployment requires an avvocato / avocat / Rechtsanwalt with aviation + data-protection practice in the target member state, plus pre-consultation with the relevant NAA.
- A commitment to deploy in Europe. Primary target remains WA state under Part 107/108; the EU analysis exists to avoid foreclosing the option and to surface cheap hedges in current design decisions.

**Uncertainty flags** are called out throughout. EU drone regulation is a fast-moving space — verify current text at implementation time.

---

## 2. Bottom Line

| Question | Answer |
|---|---|
| Does the Open category work for autonomous BVLOS perimeter patrol? | **No.** BVLOS breaks Open. A2 is VLOS-only; A3 requires 150 m from residential areas. |
| Does the Certified category apply? | No. Not transporting people or dangerous goods. |
| Does Specific category work? | **Yes, via PDRA-S02 as the primary path.** Order: (1) **PDRA-S02** — Predefined Risk Assessment for BVLOS with airspace observers, sparsely populated, ≤4 kg, ≤120 m AGL. **Does NOT require C-class marking**; per EASA, PDRA gives flexibility for UAS that are not C5/C6-marked, open to Article-14 privately-built builds like this project. This is the primary path. (2) **Full SORA operational authorisation** — fallback when PDRA operational conditions don't fit. (3) **STS-01/02** — declarative scenarios requiring C5/C6 class marking; **closed for self-built ArduPilot**, but this does not block PDRA or full SORA. See §4.3. |
| Realistic SAIL target | **SAIL II** achievable with appropriate mitigations; SAIL III is fallback. Site geometry is decisive (see country specialisations). |
| Architectural mapping | **EU Specific operational authorisation ≈ US Part 108 permit.** Same software shape (pre-approved volume, human monitors without gating, mandatory logging). Compliance-store and privacy semantics differ. |
| Does FAA Part 107 transfer? | **No.** Operator re-qualifies via the national CAA (A2 CofC + STS/Specific theoretical exam). |
| Biggest non-aviation gap | **GDPR**, enforced by the national DPA. Drives the two-tier compliance recorder design (`compliance-recorder-two-tier.md`). |
| How much varies between member states? | **~65% of the analysis is EU-common, ~25% swaps cleanly, ~10% needs rewriting** (principally the DPA layer). See §12. |
| Timeline / cost (typical SAIL II, self-built) | **2–7 months, €500–€5k fees** depending on country. Engineer time 150–250 h regardless. See country docs. |

---

## 3. Applicable Regulatory Framework

EU drone law is two regulations plus national implementations. Everything below is **direct-effect** — it applies identically across all 27 member states without national transposition.

### 3.1 Core instruments

| Instrument | Purpose |
|---|---|
| **Regulation (EU) 2019/947** | Operational rules. Categories (Open / Specific / Certified), subcategories (A1/A2/A3), Remote ID, geographical zones, registration, training, SORA-based authorisation path. |
| **Regulation (EU) 2019/945** | Product rules. Classes C0–C6 with mass, speed, geo-awareness, Remote ID, energy requirements. Self-built UAS carved out via **Article 14 of 2019/947**. |
| **Delegated Regulation (EU) 2020/1058** | Remote ID technical requirements (ASD-STAN EN 4709-002 reference). |
| **Regulations (EU) 2021/664 / 665 / 666** | U-space regulatory package. Framework for designated U-space airspace and USSPs. |
| **Regulation (EC) 785/2004** | Third-party liability insurance minimums for aircraft. Floor: 750,000 SDR (~€900,000) for <500 kg MTOM. Applies to UAS. |
| **Regulation (EU) 376/2014** | Occurrence reporting. 72 h for reportable events. Each MS has a national endpoint; all accept ECCAIRS-format XML underneath. |
| **EU AMC & GM to 2019/947** — "Easy Access Rules" | Consolidated guidance including SORA methodology and Standard Scenarios (STS-01, STS-02). |
| **EASA SORA 2.5** | Methodology refinement, applicable to new applications from 1 January 2026. National adoption of the 2.5 AMC **varies** — verify at submission time. |

### 3.2 National layer

Each member state designates a **competent authority** (national CAA) and a **data protection authority** (GDPR enforcement). The two combined produce most of the per-country variation. See `regulatory-eu-it.md`, `regulatory-eu-fr.md`, `regulatory-eu-de.md`.

What member states get to do themselves (Article 15 of 2019/947):

- Designate **UAS geographical zones** (the no-fly, altitude-capped, time-restricted polygons visible on national zone maps).
- Run the **national operator/pilot registry** and the **zone map portal**.
- Issue **operational authorisations** under SORA.
- Set **fees** and **review timelines** for authorisations.
- Interpret the **Article 14 privately-built carve-out**.
- Specify **pre-flight notification** requirements (where any).
- Enforce **GDPR** via the national DPA (for the camera payload).

National CAAs cannot override the category system, the SORA methodology, the C-class marking regime, Remote ID, the insurance floor, or Art. 13 cross-border recognition.

---

## 4. Category Determination

### 4.1 Open — ruled out for BVLOS

- **A1** (C0 <250 g, C1 <900 g): aircraft mass disqualifies a 2–5 kg target.
- **A2** (C2, <4 kg, 30 m from uninvolved / 5 m low-speed mode): **VLOS-only**. BVLOS breaks Open. Out.
- **A3** (C3/C4, <25 kg, 150 m from residential/commercial/recreational areas): disqualified wherever the deployment site is inside a residential/tourism area. Also VLOS-only.
- Open requires VLOS per Art. 4(1)(d). Full stop.

### 4.2 Certified — not required

Certified targets transport of people, dangerous goods, or operations where risk is already Certified-level. A small-property perimeter patrol doesn't approach this.

### 4.3 Specific-category pathways — ordered primary → fallback → closed

**Primary: PDRA-S02** — this is the viable path for this project.

**PDRA-S02** (Predefined Risk Assessment, Appendix 1 to AMC1 Article 11 of Reg (EU) 2019/947) covers BVLOS operation with airspace observer(s) in a controlled or sparsely-populated environment, aircraft ≤4 kg MTOM, ≤120 m AGL. **PDRA-S02 does not require C5/C6 class-marked aircraft.** EASA's own STS/PDRA materials state that PDRA gives operators "flexibility to use UAS that do not need to be marked as class C6," setting operational and technical requirements directly instead. The PDRA is available to Article-14 privately-built UAS that meet the PDRA's technical requirements. Operator files an authorisation request citing the PDRA rather than constructing a full SORA; NAA review is lighter (typically weeks, lower fees) than full SORA.

**PDRA-S01** analogously corresponds to STS-01 (VLOS, controlled ground area, ≤4 kg) and is available for VLOS operations on the same basis — **no C-class marking required**.

**Fallback: full SORA operational authorisation** — if a deployment's geometry or autonomy model doesn't fit PDRA-S02 (e.g., no airspace observer, wider operational volume, higher SAIL than PDRA permits), the operator constructs a bespoke SORA submission. Still viable, more engineer-time and NAA-review-time than PDRA.

**Closed: STS-01 / STS-02** — Standard Scenarios are declarative operational authorisations available only to **C5/C6 class-marked aircraft**. Self-built ArduPilot cannot obtain C-class marking, so STS is unavailable. This forecloses *STS only*; it does not affect PDRA or full-SORA paths.

**PDRA-first framing (the correct bottom line):**

- **PDRA-S02 is the primary path.** Not blocked by lack of C-class marking.
- **Full SORA is the fallback** when PDRA operational conditions don't fit.
- **STS is unavailable** because of C-class marking. That does not block PDRA.

Prior drafts of this document incorrectly grouped STS and PDRA together as "blocked by lack of C-class marking," which contradicted EASA's published guidance. The correct framing is as above — evaluate PDRA-S02 first.

**Note on national interpretation**: EASA AMC1 makes PDRAs available to UAS meeting the PDRA's technical requirements without requiring C-class marking. **National CAAs occasionally interpret Article 14 and PDRA eligibility more narrowly in practice**, particularly around airframe-conformity evidence. This is a verify-before-relying item: confirm with the national CAA (ENAC, DGAC, LBA/Länder respectively) at pre-consultation that PDRA-S02 is accepted for the specific Article-14 airframe.

### 4.4 Accepted one-way-doors

- **No C-class marking possible for self-built ArduPilot.** This forecloses **STS only**. **PDRA-S01/S-02 remain open** — they do not require C-class marking. Full SORA also remains available. Reopening STS specifically requires replacing the flight stack with a certified commercial UAS.
- **No ANSI/CTA 2063 serial number flow for STS.** Same root cause. PDRA and full-SORA paths are unaffected.

---

## 5. SORA Methodology — 10 Steps

SORA 2.5 (EASA ED-Decision 2019/021/R, as amended). Common across all EU member states.

1. **ConOps** — narrative + tabular description of the operation. 15–25 pages covering aircraft, crew, procedures, area, altitudes, C2 link, DAA, contingencies.
2. **Intrinsic Ground Risk Class (iGRC)** — Annex F lookup by aircraft characteristic dimension and operational scenario.
3. **Ground risk mitigations** — M1 (strategic: controlled ground area, buffers), M2 (impact reduction: parachute, frangible design), M3 (Emergency Response Plan).
4. **Final GRC** — iGRC minus mitigation credits.
5. **Initial Air Risk Class (ARC)** — Annex D airspace encounter category.
6. **Strategic ARC mitigations** — operational volume restriction, time-of-day, NOTAM coordination.
7. **Residual ARC.**
8. **SAIL** — GRC × ARC matrix determines Specific Assurance and Integrity Level (I–VI).
9. **OSO evidence** — 24 Operational Safety Objectives. Each rated at required robustness (Low/Medium/High) per SAIL. Each gets a compliance statement + evidence.
10. **Adjacent area / airspace containment** — geofence + FTS + kinetic-energy argument demonstrating no SAIL escalation if aircraft exits operational volume. Most-commonly-rewritten OSO on NAA RFI.

Typical SORA document: **60–120 pages** including annexes. Full application package (SORA + ConOps + Ops Manual + Tech Docs + ERP + training records + insurance + Remote ID decl + DPIA): **130–260 pages**.

---

## 6. GDPR Baseline

The camera payload triggers GDPR processing in almost every deployment. The landowner becomes a **data controller** with obligations under Regulation (EU) 2016/679.

### 6.1 Domestic exemption is unreliable

GDPR Art. 2(2)(c) excludes "purely personal or household activity." National DPAs (Italian Garante, French CNIL, German Länder DPAs) have consistently ruled that routine surveillance capturing neighbours' property, public roads, or public spaces loses the exemption. A camera-equipped drone overflying property boundaries is worse than fixed CCTV on this axis — it moves, the camera pans, and it operates autonomously.

**Assume the exemption does not apply** for any autonomous perimeter patrol.

### 6.2 Core obligations (EU-common)

- **Art. 6 legal basis** — legitimate interest (Art. 6(1)(f)) is the only realistic path; requires a documented Legitimate Interest Assessment (LIA) balancing security interest against data subjects' privacy.
- **Art. 13 notice** — boundary signage + published privacy notice.
- **Art. 5(1)(c) data minimisation** — privacy masks on sensitive sectors.
- **Art. 5(1)(e) storage limitation** — retention policy with scheduled deletion.
- **Arts. 15–22 data subject rights** — access (DSAR), rectification, erasure pipeline.
- **Art. 35 DPIA** — required for "systematic monitoring of a publicly accessible area on a large scale." Autonomous aerial surveillance hits this threshold in all plausible DPA interpretations.
- **Art. 36 prior consultation** — required if residual risk post-DPIA is "high." Threshold is DPA-specific; site geometry materially affects the outcome.

### 6.3 DPA-specific overlays

| DPA | Posture | Published drone guidance |
|---|---|---|
| **Garante (IT)** | Most lenient baseline guidance; aggressive enforcement when triggered. CCTV-derived from Garante's general *Provvedimento 8 aprile 2010* on videosurveillance; no consolidated drone-specific Garante general provision. | Indirect — CCTV precedents applied to drones by analogy, counsel-required inference. |
| **CNIL (FR)** | **Most prescriptive in EU.** Privacy masking expected by design; 30-day default retention; model Art. 13 notice. | Direct — multiple updates since 2020 on drone camera processing. |
| **BfDI + 16 Länder DPAs (DE)** | Heterogeneous; jurisdiction at the Land level. §35 BDSG prior-consultation stricter than GDPR baseline. | Varies (BayLDA, Hamburg, ULD Schleswig-Holstein have published opinions; others do not). |

**Hardness ranking for autonomous aerial surveillance:** CNIL > Länder top-end > Garante. See country docs for specialised DPA guidance.

### 6.4 Architectural translation

- **Two-tier compliance recorder** (immutable metadata chain + GDPR-retentable blob tier). See `compliance-recorder-two-tier.md`. Common to all EU deployments; applicable in US mode too.
- **Pre-record privacy masking** in the RTSP pipeline (go2rtc/mediamtx), not HA post-hoc. If frames are recorded unmasked, the raw exists and is GDPR-scoped.
- **DPIA template** as a country-specific overlay on a common GDPR Art. 35 base.
- **DSAR pipeline** — minimum acknowledgment-tier procedure. Self-service only where request volume justifies it.

---

## 7. Pilot Competency (EU-harmonised)

A1/A3 online test, A2 CofC, STS theoretical exam — **all issued by a national CAA but mutually recognised across the EU** under Art. 8. Operator holds them once, uses them anywhere.

- **A1/A3 online test** — free, covers the Open subcategories.
- **A2 Certificate of Competency** — theory exam + self-declared practical. Prerequisite for most Specific-category operations.
- **STS / Specific-category theoretical exam** — required for Specific operations. Note: STS *Certificate* requires C-class aircraft; for self-built under Art. 14, what's relevant is the underlying theoretical assessment.
- **Operation-specific training** — documented syllabus for the specific ConOps. Evaluated under OSO #17 / #22.

**FAA Part 107 does not transfer.** Operator re-qualifies via any EU NAA.

---

## 8. Cross-border Mechanisms

### 8.1 Article 13 — cross-border authorisation recognition

Operator holds a valid operational authorisation from member state A, wants to operate in MS B. Submit to MS B's NAA a cross-border application including the original OA, ConOps, and any MS-B-specific mitigations (local geographical zones, population density, DPA overlays).

MS B issues confirmation (often with additional operational conditions) or rejection with reasons. **Both DGAC and LBA tend to substantively review rather than rubber-stamp.** Typical timelines: DGAC 6–10 weeks; German Länder 8–16 weeks.

**Practical win is ~30–50% of original effort, not 90%.** For a single hobbyist-scale operation, fresh filing in MS B is often comparable effort. Art. 13 wins clearly when the OA is polished and the local mitigations are light.

### 8.2 LUC — Light UAS Operator Certificate

Art. 83 of 2019/947 Annex Part C. Organisational certificate granting self-authorisation privileges within a declared scope. EU-recognised.

**Rational when**: multiple distinct operations, frequent ConOps changes, multiple airframes, 3+ deployment sites across 2+ member states, or willingness to run a formal Safety Management System.

**Not rational when**: single-landowner, single-operation perimeter patrol on one property.

**Costs** (representative):

- Application fee: ~€1,500–3,000.
- Full SMS documentation: 100+ pages.
- Accountable Manager designation, compliance monitoring, internal audit cycle.
- NAA initial audit (1–2 days on-site).
- **Timeline 9–14 months**; engineering effort **12–24 months, €15–30k all-in**.

LUC is a multi-country scale-up tool, not a hobbyist shortcut.

---

## 9. Insurance (EU-common floor, national market rates)

**Reg (EC) 785/2004 Art. 7 minimums** for aircraft <500 kg MTOM: **750,000 SDR (~€900,000)** per accident. Specific-category operations are not authorised without insurance evidence.

National market rates for ~5 kg multirotor BVLOS at SAIL II (April 2026 ranges):

| Country | Typical all-in policy | Notes |
|---|---|---|
| **Germany** | **€400–900 / year** | Most competitive EU market; some Länder request €3M for BVLOS over non-sparsely-populated areas. |
| **France** | €700–1,400 / year | DGAC does not mandate above floor; insurers often include €1.5M standard for S3/BVLOS. |
| **Italy** | €1,100–1,800 / year | Priciest; BVLOS endorsements add 30–50%. |

No country *statutorily* mandates above the 785/2004 floor, but Land authorisations in DE can condition issuance on proof of higher coverage.

---

## 10. Technical Changes vs. Current (US-only) Design

EU-wide changes required regardless of which member state. Country-specific overlays in the country docs.

| Area | Change |
|---|---|
| **Remote ID** | Module must carry **Delegated Reg (EU) 2020/1058 + ASD-STAN EN 4709-002** declaration, not just FAA MoC. Dual-certified modules (Dronetag, BlueMark) exist. Operator ID + operation category + UAS registration marker per EU frame format. |
| **C2 link** | **868 MHz SiK EU variant** (RFD868x) instead of 915 MHz. 868 MHz SRD band limit typically 25 mW ERP vs. US 915 MHz ISM 1 W — link-budget implications for range. **LTE C2 backup** for SAIL II+ robustness argument. |
| **DAA** | ADS-B In (pingRX) is **insufficient** — EU light-aviation ADS-B Out equipage is much lower than US. **Add FLARM receiver** (PowerFLARM Core, or open-source FLARM-compatible like SoftRF). Extend `daa_monitor` and ArduPilot `AP_Avoidance` with FLARM source. |
| **Geofence** | Three nested polygons per SORA 2.x (operational volume + contingency volume + ground risk buffer). Per-edge asymmetric setback where boundary conditions vary. ArduPilot 4.5+ multi-fence or bridge-side Guided-mode clamping. |
| **Parachute + FTS** | Parachute deploy output + **independent watchdog MCU** trigger (must fire even if autopilot hangs). `MAV_CMD_DO_PARACHUTE` integration. Compliance event on deploy. Not currently in BOM. |
| **Camera / gimbal** | Wide-angle default (short focal length argues against identifiable-capture under GDPR). Gimbal must expose real-time yaw/pitch for geospatial / FOV-sector mask projection. |
| **Video pipeline** | **Pre-record privacy masking** in go2rtc/mediamtx. Geospatial polygons or FOV-sector rules projected per-frame. Default deny outside mask. |
| **Compliance recorder** | **Two-tier split**: hash-chained metadata chain (immutable) + video blob tier (GDPR-retention-compliant, deletable with incident-linked exception). See `compliance-recorder-two-tier.md`. |
| **Privacy module** (new) | `privacy_officer.py`: DPIA hash, legal basis declarations, DSAR contact, retention policy, privacy-zone / FOV-sector definitions. ComplianceGate consults it pre-arm. |
| **ComplianceGate modes** | Add `Mode.EU_SPECIFIC_SORA` (country-parameterised) alongside `Mode.PART_107`, `Mode.PART_108`. Pre-arm checks: national operator ID + insurance + operational authorisation reference + operational volume polygon + altitude/speed caps per authorisation + DPIA hash + ERP version acknowledged. |
| **HA integration entities** | `sensor.drone_operator_registration`, `sensor.drone_insurance_expiry`, `sensor.drone_operational_authorisation`, `sensor.drone_dpia_version`, `binary_sensor.drone_eu_mode_arm_allowed`. Service `drone_hass.export_dsar`. |

---

## 11. EU One-Way-Door Constraints (Baked in Now)

Decisions being made in the current (US-target) design that would be **hard or expensive to reverse** if the EU path is activated later. Cheap hedges now; real commitments later.

See `architecture.md §3.6` for the hedged-vs-naive table. Highlights:

### 11.1 Aircraft / hardware (cheap hedges)

- **Primary C2 radio**: buy **RFD868x (868 MHz)** or dual-band variant rather than US-only 915 MHz. Radio swap + re-pair later is more expensive than picking the right SKU now.
- **Remote ID module**: **dual-certified (FAA + ASD-STAN EN 4709-002)**. Minimal premium.
- **Autopilot firmware**: **ArduPilot 4.5+** for multi-fence support.
- **Airframe payload margin**: +**1 kg headroom** for parachute (200–500 g) + FLARM (~50 g) + independent FTS MCU (~30 g) + LTE modem (~100 g).
- **Independent FTS MCU footprint**: reserve PCB space + UART/relay line on an autopilot-external MCU (ESP32 / STM32 with own power rail). Firmware can be stubbed.
- **Camera focal length**: default **wide-angle (≤30 mm equiv)** for GDPR identifiability argument.
- **Gimbal**: **real-time queryable attitude (MAVLink-native / SBUS)** for privacy-mask projection. Closed-API gimbals foreclose the mask.
- **Autopilot UART budget**: reserve 1 UART for FLARM + 1 for LTE C2.

### 11.2 Software / data (architectural)

- **Compliance recorder schema**: **two-tier from day one**. Retrofitting after video-in-chain means migrating the chain. Biggest software one-way-door.
- **Privacy masking**: **pre-record in RTSP pipeline**, not HA post-hoc.
- **`OperationalMode` enum** (`mavlink_mqtt_bridge/compliance.py`): keep extensible; no `assert mode in (…)` patterns in callers.
- **Operator ID schema**: **country-keyed tagged union** (ISO 3166-1 alpha-2 tag + MS-specific payload format).
- **Geofence representation**: three nested polygons with per-edge setback values.
- **Flight log**: `country` + `regulator` columns.

### 11.3 Real commitments (defer until deployment)

- Parachute hardware.
- FLARM receiver.
- National CAA fees, insurance policy, operator registration.
- DPIA + national DPA-aligned lawyer sign-off.
- STS / Specific-category exam sitting.
- SORA application submission.

---

## 12. Architecture: Per-Country Abstraction Boundaries

The EU framework is ~80% identical across member states. The architecture should put the pluggable seams in the ~20% that varies.

### 12.1 Effort split (IT baseline → add DE or FR)

Working from a shipped Italian deployment:

- **~65% of the regulatory content is MS-neutral** (SORA worksheet, SAIL determination, OSO mapping, ConOps, mitigation reasoning). Reuses untouched.
- **~25% swaps cleanly** (portal names, fees, operator-ID format, zone lookup URL, occurrence reporting endpoint, language strings).
- **~10% needs real rewriting** — principally the national DPA layer (DPIA template, signage text, retention defaults) and the geographical-zones narrative.

### 12.2 Recommended module layout

```
regulatory/
  eu/
    _base/
      sora/              # SORA 2.5 worksheet generators, OSO matrix
      gdpr/              # Art. 35 DPIA base template, Art. 13 notice base
      insurance/         # Reg 785/2004 schema validator
      remote_id/         # EN 4709-002 frame builder
      occurrence/        # ECCAIRS XML serializer
    it/
      portal/            # D-Flight client
      dpa/               # Garante DPIA overlay, videosorveglianza-aligned notice
      zones/             # D-Flight zone provider
      occurrence/        # eE-MOR endpoint
      strings/           # Italian-language templates
    fr/                  # AlphaTango / CNIL / BEA / French strings
    de/
      portal/            # DIPUL + Land adapters (NRW, Bayern, SH, …)
      dpa/               # BfDI + Länder overlays
      zones/             # DIPUL + Land environmental agency composite
      occurrence/        # BAF endpoint
      strings/
```

### 12.3 Pluggable interfaces

| Component | Interface | Country variance |
|---|---|---|
| `NationalPortalClient` | `register_operator / resolve_zones / submit_authorisation / submit_flight / fetch_status` | Per-country strategy. DE needs one DIPUL + N Land adapters. |
| `OperatorId` | Country-keyed tagged union | ISO 3166-1 alpha-2 tag + MS-specific payload string |
| Authorisation lifecycle state machine | Country-**neutral** enum (`draft / submitted / clarification_requested / approved / denied / expired`) | Per-country adapter translates portal statuses |
| `ZoneProvider` | Returns normalised `ZoneRestriction` records | Per-country backend; DE is a composite source |
| Occurrence reporting | Common ECCAIRS serializer | Per-country submission endpoint |
| DPIA overlay | Base + country overlay | CNIL is the most prescriptive — use as reference, downscope for others |
| Privacy-mask defaults | Country-neutral schema | Per-country defaults (sensitive sectors, coverage thresholds) |
| Insurance certificate validator | Country-neutral JSON schema | Per-country issuer allowlist optional |

### 12.4 Porting effort from IT baseline

- **Add France**: **3–5 engineer-weeks.** AlphaTango client (1–1.5 weeks, most mature portal), CNIL DPIA overlay + signage generator (1–1.5 weeks, the substantial work), French strings, BEA/DGAC occurrence endpoint, insurance schema update. No SORA rework.
- **Add Germany**: **6–10 engineer-weeks.** DIPUL client (~1 week) + one Land adapter (1–2 weeks, pick SH or Bayern) + each additional Land (1–2 weeks). Länder DPA DPIA overlay (messier than CNIL). German strings. BAF occurrence reporting. Possibly supplementary airframe-conformity evidence in the SORA — real SORA rework.

**Summary assertion:** France is a weeks-scale extension. Germany is a months-scale extension, dominated by Länder fragmentation + DPA heterogeneity, not aviation regulation.

---

## 13. Country Specialisations

| Country | Status | Document | Highlight |
|---|---|---|---|
| Italy | **Worked scenario** | [`regulatory-eu-it.md`](regulatory-eu-it.md) | ENAC + Garante, D-Flight, Lavagna site with asymmetric south-facing geofence. Full cost / checklist / process detail. |
| France | **Seed** | [`regulatory-eu-fr.md`](regulatory-eu-fr.md) | DGAC/DSAC fastest review in EU. AlphaTango most mature portal. CNIL most prescriptive DPA — single hardest GDPR surface. |
| Germany | **Seed** | [`regulatory-eu-de.md`](regulatory-eu-de.md) | LBA + 16 Länder split is the structural problem. DIPUL + N Land adapters. BfDI + 16 Länder DPAs with heterogeneous drone guidance. Most documentation-heavy on Article 14 self-built. |

---

## 14. Open Questions / Verify-Before-Relying

- **SORA 2.5 adoption status** per NAA. ENAC, DGAC, and the German Länder are all in transition as of April 2026.
- **National DPA guidance updates** — CNIL drone guidance last materially updated 2024; Garante videosorveglianza from 2018 with ongoing drone-specific decisions; Länder DPA positions published sporadically.
- **U-space designations** — Italy's first was San Salvo (Abruzzo, 2026-01). Germany and France have not yet declared residential / coastal U-space airspace at this resolution. Monitor national implementation of Reg 2021/664–666.
- **Per-country insurance market quotes** are indicative. Verify with an EU-licensed aviation broker at deployment time.
- **Länder DPA jurisdictional boundaries** for Germany — in practice the Land DPA where the operation *occurs* enforces; where the operator *resides* sometimes also claims jurisdiction. Verify with German GDPR counsel.

---

## 15. References (EU-common)

- **EASA — Easy Access Rules for UAS** (Regulations (EU) 2019/947 and 2019/945).
- **EASA — SORA 2.5** methodology and implementation guidance.
- **EASA — Specific Operations Risk Assessment**.
- **EASA — Drones with class identification label C0–C6**.
- **EASA — Placing a drone on the market with class identification label**.
- **Delegated Regulation (EU) 2020/1058** — Remote ID.
- **Regulation (EC) 785/2004** — air carrier insurance.
- **Regulation (EU) 376/2014** — occurrence reporting.
- **Regulations (EU) 2021/664 / 665 / 666** — U-space regulatory package.
- **ArduPilot** — Remote ID (`ardupilot.org/copter/docs/common-remoteid.html`).
- **ArduPilot** — ArduRemoteID firmware project.
- **Dronetag** — EU retrofit integration guide.

National references in the country-specific docs.

---

*This document is a design-review artifact, not legal advice. Any real EU deployment requires consultation with national counsel specialising in aviation + data protection, plus pre-consultation with the relevant NAA.*
