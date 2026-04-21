# Layered Invariance Model

> **Date:** 2026-04-20
> **Status:** Framework document
> **Version:** 0.1.0
> **Purpose:** Conceptual spine for all regulatory and architecture discussion. Navigation aid for adopters and contributors.

---

## 1. Why This Document Exists

`drone_hass` is simultaneously:

- A piece of software architecture (bridge + HA integration + dock firmware)
- A regulatory scaffold (SORA artifacts, compliance recorder, ComplianceGate, Remote ID, privacy masking)
- An open-source project that multiple operators will adapt to their own jurisdictions

Those three facets tangle easily in discussion. A claim like "the compliance recorder is GDPR-compliant" is true at one level (the two-tier architecture makes GDPR retention *possible*) and false at another (the specific retention windows are a per-DPA policy decision outside the code). A question like "how do we add Switzerland?" collapses unless we already know which parts are physics, which are EU-wide, and which are CNIL-vs-Garante.

This document defines a **layered invariance model** — seven concentric rings, from "physics never changes" to "this deployment's neighbour-parcel map" — that:

- **Gives every regulatory and architectural claim a layer.** You can say "this is a Level 1 decision" and the conversation is clearer.
- **Tells adopters exactly what they inherit for free and what they must produce.**
- **Tells contributors where their work scales.** Inner-layer work compounds across every deployment; outer-layer work is per-operator.
- **Mirrors the module layout** under `regulatory/` so code structure and conceptual structure match.

---

## 2. The Model at a Glance

Layers are numbered **inside-out**: Level 0 is physics (never changes); Level 6 is the specific deployment (changes every time). Each higher-numbered layer depends on the ones below and specialises them.

| Level | Name | Invariant across | Changes at |
|---|---|---|---|
| **0** | Physics & engineering | Everywhere, always | Never |
| **1** | Project architecture | All `drone_hass` deployments | Project rearchitecture |
| **2** | Risk-based UAS regulation family | FAA, EASA, TC, UK CAA, CASA, CAAi, ANAC — the "Western" risk-based cluster | Non-risk-based regimes (e.g., China's permit-list model) |
| **3** | SORA methodology cluster | EU + JARUS-adopting jurisdictions | Non-SORA regimes (FAA Part 107/108, Transport Canada, CASA) |
| **4** | EU regulatory framework | All 27 EU member states + EASA-bound non-EU (NO, IS, CH to varying degrees) | Non-EU regimes |
| **5** | National specialisation | A single member state / jurisdiction | Every new country |
| **6** | Site-specific | A single deployment | Every operator, every property |

A rough rule: **the effort of adding a new jurisdiction equals the depth at which you have to branch.** Adding another EU state is Level 5 only (weeks). Adding a non-SORA risk-based regime is Level 3+5 (months). Adding a non-risk-based regime is Level 2+ (structural).

---

## 3. Layer Definitions

### 3.1 Level 0 — Physics & engineering

**Invariant:** Gravity, kinetic energy, battery chemistry, motor/ESC efficiency curves, RF propagation, weather physics, MAVLink wire protocol, ArduPilot control loops, SITL determinism.

**Variables it produces:** GRB geometry (altitude × speed + drift → buffer), link-budget ranges, thrust-to-weight margins, battery cycle counts, rain/wind/temp tolerance envelopes.

**Lives in:** firmware (ArduPilot, ESPHome), `mavlink_mqtt_bridge/` core, hardware BOM. Test coverage in SITL.

### 3.2 Level 1 — Project architecture

**Invariant (by our choice):** Bridge ↔ HA integration split; MQTT as sole interface; compliance-first design; safety in firmware; aircraft-agnostic; two-tier compliance recorder (`compliance-recorder-two-tier.md`); three-tier geofence primitives; MAVLink signing + MQTT ACLs; SITL-first dev loop.

**Scope:** These decisions are invariant across every deployment of `drone_hass`. Changing them would be a project rearchitecture, not an adaptation.

**Lives in:** `architecture.md`, `mavlink_mqtt_bridge/`, `custom_components/drone_hass/`, the two-tier recorder spec.

### 3.3 Level 2 — Risk-based UAS regulation family

**Invariant across cluster:** Operator/pilot/aircraft trichotomy; risk-based categorisation (low risk permissive, high risk restricted); VLOS↔BVLOS as regulatory step-change; occurrence reporting; Remote ID mandate; third-party insurance mandate (most regulators); data-protection overlay (always present, varies in strictness).

**What's in the cluster:** FAA Part 107/108 (US), EASA 2019/947 (EU), Transport Canada RPAS (CA), UK CAA (UK post-Brexit), CASA (AU), CAAi (JP), ANAC (BR). Draft regulations in India (DGCA), Korea (MOLIT), etc. are converging on this family.

**Not in the cluster:** Permit-list models (CN's CAAC approach), blanket-ban regimes. Adapting `drone_hass` to non-cluster regimes is a much larger project.

**Lives in:** `regulatory/_core/` — concepts and primitives that any risk-based regulator uses. ECCAIRS occurrence serialiser, insurance certificate JSON schema, generic Remote ID frame builder, risk-class abstractions.

### 3.4 Level 3 — SORA methodology cluster

**Invariant across cluster:** SORA 10-step process; SAIL I-VI matrix; 24 OSOs; M1/M2/M3 mitigations; intrinsic / final GRC; initial / residual ARC; adjacent-area containment.

**What's in the cluster:** All EU member states + EASA-country observers. JARUS SORA is the parent methodology adopted by EASA; other NAAs (UK CAA, partial Transport Canada alignment) draw from it. **The US FAA Part 108 NPRM borrows concepts but does not adopt SORA wholesale** — Part 108 uses population density categories and its own operational framework.

**Consequence:** SORA code/templates are reusable across all EU states and close neighbours. A separate risk methodology abstraction is needed for non-SORA regulators (FAA, CASA, TC).

**Lives in:** `regulatory/sora/` — SAIL calculator, OSO matrix with robustness levels, ConOps template generator, SORA worksheet, OSO evidence checklist.

### 3.5 Level 4 — EU regulatory framework

**Invariant across all 27 MS (direct-effect regulations):** Texts of Reg (EU) 2019/947, 2019/945, Delegated Reg 2020/1058, Reg (EC) 785/2004, Reg (EU) 376/2014, Regulations (EU) 2021/664–666; the Open/Specific/Certified categories; A1/A2/A3 subcategories; class marking C0–C6; Article 14 privately-built carve-out; Article 13 cross-border recognition; LUC provisions (Art. 83); A2 CofC content; GDPR text (Art. 6, 13, 35, 36 baseline).

**What's at this layer but NOT in the regulatory text:** EASA AMC & GM, SORA 2.5 methodology document, ASD-STAN EN 4709-002 Remote ID frame spec, ECCAIRS 376/2014 schema.

**Lives in:** `regulatory/eu/_base/` — EU-wide DPIA Art. 35 base template, EN 4709-002 Remote ID profile, 785/2004 insurance schema, Article 13 cross-border application scaffolding, A2/STS-theoretical competency validator.

### 3.6 Level 5 — National specialisation

**What varies:** Competent authority name and structure (single CAA vs federal/Länder split); national portal (D-Flight, DIPUL, AlphaTango, FAA DroneZone, Transport Canada RPAS portal, etc.); fee schedule; review timeline; language; data protection authority and its drone-specific guidance; UAS geographical zones and their data source; occurrence reporting submission endpoint; pilot competency sitting infrastructure; insurance market.

**Asymmetry flag:** The **national DPA is at Level 5, not Level 4**, even inside the EU. GDPR's article text is Level 4; the practical compliance target (CNIL vs Garante vs Länder DPAs) is Level 5. See §6.

**Lives in:** `regulatory/eu/{it,fr,de,…}/`, `regulatory/us/{part107,part108}/`, `regulatory/uk/`, etc. Each directory contains: `portal/` (national portal client), `dpa/` (DPIA overlay + signage generator), `zones/` (geographical-zone provider), `occurrence/` (submission endpoint adapter), `strings/` (language templates).

### 3.7 Level 6 — Site-specific

**What varies per deployment:** Exact property coordinates and boundary geometry; neighbour land use; specific airspace picture after zone lookup; operator legal identity; insurance policy issued to that operator; ConOps narrative; DPIA content populated with this deployment's controller, purposes, and retention; pilot of record; maintenance logbook.

**Lives in:** *Out of repo.* Operator's deployment config, their signed Ops Manual, their ConOps, their DPIA, their insurance certificate, their flight logs. The code can validate format and presence; it cannot author content.

---

## 4. Constants, Variables, Out-of-Repo

| Layer | Constants (in `_core/` or shared) | Variables (pluggable strategy) | Out-of-repo (operator-owned) |
|---|---|---|---|
| 0–1 | MAVLink↔MQTT translation, compliance-recorder data model, hash chain + Ed25519 + OpenTimestamps, three-tier geofence primitives, privacy-mask projection math, DAA event processing, auth state machine, SITL dev env | — | Site survey, measured flight-test data |
| 2 | ECCAIRS XML serialiser, Remote ID frame-builder primitive, insurance JSON schema (issuer-parameterised), risk-class abstractions | `RemoteIDProfile` (FAA/EU/UK), `RadioProfile` (EIRP per spectrum), `OccurrenceReporter` endpoint adapter | — |
| 3 | SORA worksheet generator, SAIL calculator, OSO matrix, ConOps template, ERP template | — (methodology is uniform) | Completed SORA, signed ConOps, signed Ops Manual, signed ERP |
| 4 | EU DPIA Art. 35 base, EN 4709-002 RID profile, 785/2004 schema, A2/STS competency validator, Art. 13 application scaffold | — | — |
| 5 | — | `ComplianceGate.mode`, `NationalPortalClient`, `ZoneProvider`, `OperatorIdentifier`, `DPIATemplate` overlay, `SignageGenerator` locale, `PilotCredentialValidator`, insurance issuer allowlist | Pilot training syllabus per national requirement |
| 6 | — | — | Deployment config, operator entity, insurance policy, DPIA content, site-specific privacy masks, per-flight logs |

**Rule of thumb:** everything marked "constant" scales — one engineer-week of work benefits every adopter forever. Everything marked "variable" is per-jurisdiction. Everything marked "out-of-repo" is per-operator and cannot be shipped.

---

## 5. Module Layout Mirroring the Layers

```
mavlink_mqtt_bridge/          # L0–L1: protocol, bridge, state
custom_components/drone_hass/ # L1: HA integration

regulatory/
  _core/                      # L2: risk concepts, ECCAIRS, RID primitive, insurance schema
    remote_id/                # profile-parameterised frame builder
    occurrence/               # ECCAIRS serialiser
    insurance/                # JSON schema validator
    risk/                     # risk-class abstractions

  sora/                       # L3: SORA methodology
    sail.py                   # GRC × ARC matrix
    oso/                      # 24 OSOs with robustness levels
    conops_template/          # reusable ConOps scaffold
    worksheet/                # SORA worksheet generator

  eu/
    _base/                    # L4: EU-wide
      dpia/                   # Art. 35 base template
      remote_id/              # EN 4709-002 profile
      competency/             # A2 / STS theoretical validator
      cross_border/           # Art. 13 scaffolding
    it/                       # L5: Italy
      portal/                 # D-Flight client
      dpa/                    # Garante overlay, videosorveglianza signage
      zones/                  # D-Flight zone provider
      occurrence/             # eE-MOR endpoint
      strings/                # Italian templates
    fr/                       # L5: France (seed)
    de/                       # L5: Germany (seed)

  us/
    _core/                    # L2-specific for US
      remote_id/              # ASTM F3411 + FAA profile
    part107/                  # L5-equivalent: Part 107 mode
    part108/                  # L5-equivalent: Part 108 mode
      ground_risk/            # population density categories (non-SORA)

  uk/, ca/, au/               # Future: non-EU Level 3 regulators
```

The module tree is a literal mirror of the layer stack. Reading the layer of a file from its path is a feature, not an accident.

---

## 6. Porting Effort by Layer

Adding a new jurisdiction = identifying the deepest layer where it branches.

| New jurisdiction | Deepest branch | Reuses | Rewrites | Engineer-weeks |
|---|---|---|---|---|
| Another EU state (e.g., Spain, Netherlands) | L5 only | L0–L4 | `es/` or `nl/` directory: portal client, DPA overlay, zones, strings | **3–5** (similar to France) |
| Germany-like (federal/Länder fragmentation) | L5, fragmented | L0–L4 | L5 split into federal + N Länder adapters | **6–10** |
| UK (post-Brexit, drifting from EU) | L4.5, L5 | L0–L3 | EU base → UK base (close but diverging); UK-specific L5 | **4–7** |
| Non-SORA risk-based (CA Transport Canada, AU CASA) | L3, L5 | L0–L2 | L3 risk methodology (not SORA); L5 per-jurisdiction | **6–10** |
| US Part 107 or 108 | L3-equivalent, L5 | L0–L2 | Population-density risk model (not SORA); per-mode L5 | **Already scoped in primary project** |
| Non-risk-based regime (e.g., strict permit-list) | L2 | L0–L1 | L2 onward | **12+**, may not be worth it |

**The inner-layer investments pay back at this step.** A well-designed `regulatory/_core/` and `regulatory/sora/` layer means each new EU state is a ~4-week contribution, not a ~3-month one.

---

## 7. Asymmetries and Gotchas

Cases where the layer model bends or fragments:

1. **DPA is at Level 5, not Level 4.** GDPR article text is invariant across the EU (Level 4). Practical compliance target is the national DPA (Level 5). CNIL, Garante, and the 16 Länder DPAs interpret the same text differently — sometimes incompatibly. Consequence: the DPIA template *base* is Level 4; the *overlays* are Level 5 and diverge more than aviation regulators do.

2. **CNIL as reference overlay.** Adopt the strictest national DPA's interpretation (CNIL) as the Level 4+5 default, downscope per country. Cheaper than the reverse.

3. **German Länder fragmentation.** Level 5 splits further at a Land level in Germany — both for aviation authority and DPA. Treat as L5.5: federal adapter + N Land adapters.

4. **Radio spectrum bimodality.** Nominally Level 5 (national allocation), but the band choice is so bimodal (915 MHz ISM / 1 W in the Americas vs 868 MHz SRD / 25 mW in EU + many neighbours) that it behaves as a Level 2 hardware-hedge for anyone aiming to ship to both. The `RadioProfile` abstraction sits at Level 2 accordingly.

5. **Remote ID profile selection.** ASTM F3411 underlies both FAA and EU profiles but the frame fields differ (EU carries operator registration number prefixed differently from FAA CTA-2063). `RemoteIDProfile` sits at Level 2 with EU and US profile variants at Level 4/5.

6. **UK post-Brexit drift.** UK retained EU drone law on exit but is diverging slowly. As of 2026-04, UK is close enough to EU that a `uk/_base/` can inherit most of `eu/_base/`. Over time this may need to split.

7. **Occurrence reporting format uniformity.** ECCAIRS is the international standard; all EU MS use it; FAA, TC, CASA submit similar data through different endpoints. Serialiser is Level 2; endpoint adapter is Level 5. This is one of the cleanest layer splits in the stack.

8. **LUC is not a platform construct.** A Light UAS Operator Certificate is operator-bound (Level 6), not platform-bound (Level 1). Open-source projects cannot hold a LUC. Community-level LUC via a foundation is a governance decision, not a code decision. See `regulatory-eu.md §8.2`.

9. **SORA-like thinking in non-SORA regulators.** Part 108 NPRM, Transport Canada's risk methodology, and CASA's operational approval process all share vocabulary with SORA without being SORA. Tempting to reuse `regulatory/sora/` code; resist unless the risk matrix is mathematically identical.

---

## 8. How to Use This Model

### 8.1 For adopters (you want to run `drone_hass` in your jurisdiction)

Work from inside-out:

1. **Inherit Levels 0–2 untouched.** Aircraft, bridge, HA integration, compliance-recorder primitives, Remote ID builder, ECCAIRS serialiser — these are yours for free.
2. **Identify your regulator's layer-3 position.** If it's SORA-adopting (EU, UK, etc.) inherit `regulatory/sora/`. If it's non-SORA (FAA, CASA, TC) you'll need the analogous module (Part 108 directory, etc.).
3. **Check if your Level-4 is in the tree.** If your regulator is EU, use `regulatory/eu/_base/`. If it's US, use `regulatory/us/_core/`. If it's a new one, you're contributing the Level-4 module.
4. **Your Level-5 is what you write or fund.** A `NationalPortalClient`, a DPA overlay, zones, strings, occurrence adapter, insurance issuer allowlist. Typically 3–5 weeks for another EU state, 6–10 for a non-SORA regulator. Reference the France/Germany seeds in `regulatory-eu-fr.md` / `-de.md` for the pattern.
5. **Your Level-6 is your deployment.** Site survey, ConOps, DPIA, Ops Manual, insurance, operator registration — your work, your responsibility, every time.

If you're a senior engineer with a specific deployment in mind, reading the layered model first gives you a realistic effort estimate before you start.

### 8.2 For contributors (you want to improve the platform)

Work from inside-out for leverage:

1. **Level 0–2 contributions compound across every adopter forever.** Better compliance-recorder primitives, a tighter ECCAIRS serialiser, a more-portable Remote ID profile abstraction, a cleaner geofence three-tier model — every future operator benefits.
2. **Level 3 contributions (SORA tooling) benefit every SORA-adopting jurisdiction.** SORA worksheet generator, OSO evidence templates, SAIL calculator, MoC candidates for OSO #5 / #6 / #24.
3. **Level 4 contributions benefit the EU cluster.** DPIA base template, Art. 13 scaffolding, A2 validator.
4. **Level 5 contributions benefit one country.** Still valuable, but narrowly.

**The leverage gradient is clear: inner layers scale, outer layers don't.** A well-designed `regulatory/_core/` is worth more than a polished `regulatory/eu/it/portal/`.

### 8.3 For reviewers / auditors

When reviewing a contribution or a SORA submission, ask:

- "What layer is this claim at?"
- "Is the evidence at the same layer or higher?"

A claim at Level 2 (e.g., "our compliance chain is audit-grade") must be backed by Level 2 evidence (the SQLite schema, the test suite), not Level 5 (a French lawyer's sign-off). Cross-layer arguments are usually bugs.

---

## 9. Cross-References

- **Level 0–1 detail**: `architecture.md` (project architecture, MQTT, compliance recorder), `compliance-recorder-two-tier.md` (L1 architectural primitive).
- **Level 2 detail**: `architecture.md §3` (risk-based framing), `architecture.md §11` (compliance framework), `architecture.md §13` (security considerations).
- **Level 3 detail**: `regulatory-eu.md §5` (SORA methodology 10-step overview).
- **Level 4 detail**: `regulatory-eu.md` (EU-wide framework).
- **Level 5 detail**: `regulatory-eu-it.md` (worked Italy), `regulatory-eu-fr.md` (France seed), `regulatory-eu-de.md` (Germany seed), `architecture.md §3.1–§3.6` (US Part 107/108 specialisation).
- **Level 6 detail**: not in repo; lives in operator's deployment configuration, manuals, insurance, and flight records.

---

## 10. Open Questions

- How should `regulatory/_core/` and `regulatory/sora/` handle risk-matrix differences between SORA and FAA Part 108 population categories cleanly? Likely a separate `regulatory/risk/` layer; to be sorted at Phase 2.
- Where should C-class marking (EU 2019/945) sit in the model? It's Level 4 regulation but the *evidence for a class-marked aircraft* is hardware. Currently an accepted one-way-door (closed for self-built ArduPilot); revisit if/when the project gains a certified-drone pathway.
- Should LUC governance (foundation / cooperative / umbrella) get its own doc or stay a note in `regulatory-eu.md §8.2`?
- When does the UK diverge enough from the EU to justify `uk/_base/` rather than an `uk/` wrapper over `eu/_base/`? Monitor annually.

---

*This is a framework document. Layers are a mental model, not a legal structure — regulators don't care about your layering, they care about the submitted SORA. The model exists to make contribution and adoption navigable.*
