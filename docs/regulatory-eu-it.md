# Italy — Regulatory Specialisation

> **Date:** 2026-04-20
> **Status:** Worked scenario (Lavagna, Liguria)
> **Version:** 0.1.0
> **Layers covered:** **Level 5** (national specialisation: ENAC + Garante + D-Flight) and **Level 6** (site-specific: the Lavagna boundary geometry and GRB math). Inherits Levels 0–4 from [`regulatory-layered-model.md`](regulatory-layered-model.md) and [`regulatory-eu.md`](regulatory-eu.md).
> **Parent:** `regulatory-eu.md` (pan-EU framework)
> **Siblings:** `regulatory-eu-fr.md`, `regulatory-eu-de.md`

---

## 1. Scope

This document specialises the pan-EU analysis in `regulatory-eu.md` to the Italian national layer and to a specific worked scenario — deployment at a ~1-acre private property in **Lavagna, Liguria** (Tigullio coast, Genoa metropolitan area). It assumes the reader has already read `regulatory-eu.md` and does not repeat the EU-common framework.

The scenario is the reference worked example for the project. France and Germany specialisations (siblings) are partial seeds; this is the complete one.

---

## 2. Italian National Layer

### 2.1 Competent authorities

- **ENAC** (Ente Nazionale per l'Aviazione Civile) — competent authority for UAS under 2019/947. Direzione Regolazione Spazio Aereo (Rome) handles Specific-category operational authorisations. **ENAC-Liguria** (Genova Sestri airport office) provides regional input for Ligurian operations.
- **ENAV** — Italian ANSP; airspace data source feeding D-Flight.
- **Garante per la Protezione dei Dati Personali** — Italian DPA. Enforces GDPR and the national privacy code on the camera payload. **Parallel regulator with no US analogue.**

ENAC is a conservative NAA for drones by EU standards. Garante is aggressive on video-surveillance when triggered but has less drone-specific published guidance than CNIL in France — most case law derives from CCTV precedents (videosorveglianza).

### 2.2 Regolamento UAS-IT

ENAC's national regulation complementing 2019/947. Provides:

- Operator registration framework (via D-Flight)
- National interpretation of population density thresholds (used in SORA GRC)
- Provisions for privately built UAS (clarifying Article 14 scope)
- Rules for State UAS (not applicable here)

### 2.3 D-Flight

D-Flight S.p.A. (owned by ENAV + Leonardo) runs the national UAS platform at `d-flight.it`:

- Operator registration → EU operator number (`IT...` prefix)
- UAS geographical zone map (yellow/red polygons)
- Flight plan notifications (where required)
- Future U-space Common Information Services

Access requires **SPID / CIE digital identity** and **codice fiscale**. Partial public API (zones as WMS/WFS); mission filing is still partly PDF/manual.

---

## 3. Site Scenario — Lavagna, Liguria

### 3.1 Airspace

Lavagna sits roughly **35 km east-southeast of Genoa Cristoforo Colombo (LIMJ)** by straight line. LIMJ's CTR almost certainly does not extend that far (typical CTR radii 5–10 NM). Overlying Genoa TMA and the coastal arrival corridor are in play at higher altitudes, but sub-120 m AGL ops should be in Class G at the surface.

**Must verify on D-Flight map** before any assumption: UAS geographical zones, Natura 2000 sites, Parco di Portofino (not at Lavagna itself but nearby), military reservations, coastal heliport footprints. Rapallo (~10 km west) has an active heliport; medical-evacuation helipads are common in Tigullio coastal towns.

**DAA environment is materially weaker than US.** EU ADS-B Out equipage below FL100 is much lower than US. Coastal helicopter traffic (EMS, Coast Guard, tourist sightseeing) is often not ADS-B equipped. ADS-B-In-only is **insufficient** for Italian BVLOS — add **FLARM receiver** (standard cooperative traffic awareness system for European light aviation / gliding, much higher equipage in the relevant traffic).

### 3.2 Boundary geometry

The property borders:

| Sector | Neighbour | Uninvolved density |
|---|---|---|
| **North** | Larger (>1 acre) property, house ≥91 m (100 yd) from shared boundary | ~1–5 persons/km² average; house outside worst-case GRB |
| **East** | Empty orchard | <10 persons/km² (transient farm workers) |
| **West** | Empty orchard | <10 persons/km² |
| **South** | Public road | Highly variable; peaks 100s–1000s/km² equivalent during traffic |

The orchard buffers and the 91 m north setback move SORA iGRC from generic "populated coastal residential" (5–6) to **3–4** before mitigations. **The south road is the binding constraint** — the only sector with continuous exposure to non-negligible uninvolved density.

### 3.3 Ground Risk Buffer (GRB) math

SORA 2.5 GRB (simplified ballistic): altitude + 1-second reaction throw + parachute drift. For ~2 kg multirotor:

| Altitude | Cruise speed | Approx. GRB | South-boundary setback required |
|---|---|---|---|
| 50 m | 5 m/s | ~60 m | 60 m |
| 30 m | 5 m/s | ~40 m | 40 m |
| 20 m | 3 m/s | ~25 m | 25 m |
| 15 m | 3 m/s | ~20 m | 20 m |

A 1-acre property is ~64 m × 64 m square. At 50 m AGL the south GRB alone consumes half the property. At **20 m AGL / 3 m/s** the south setback shrinks to ~25 m, leaving ~40 m of usable operational corridor — viable for perimeter inspection, not for full-property mapping.

**Conclusion: asymmetric geofence is mandatory.** Tight south setback (~25 m at capped altitude/speed), relaxed 5–10 m on N/E/W. The north 91 m setback + orchards E/W mean GRB spillover is tolerable on those sides; parachute M2 mitigation handles residual risk.

---

## 4. Specific-Category Path Selection

**Evaluate PDRA-S02 first, then fall back to full SORA.** Prior versions of this document walked directly to full SORA claiming STS/PDRA were both blocked by lack of C-class marking. That was a doctrinal error — corrected in [`regulatory-eu.md §4.3`](regulatory-eu.md). STS requires C5/C6 marking; **PDRA-S01/S-02 do not**.

**PDRA-S02** covers BVLOS with airspace observers over a controlled ground area, sparsely populated environment, ≤4 kg MTOM. Lavagna's geometry (orchards E/W, 91 m setback N, public road S) plausibly qualifies as "sparsely populated" for PDRA-S02 purposes with the same mitigations we'd bring to a SORA. An airspace observer is a human role — for the perimeter-patrol use case this is the RPIC or a designated observer on-site during flight windows, which fits the stepping-stone operational model.

**Verify with ENAC at pre-consultation** whether PDRA-S02 is accepted for Article-14 privately-built UAS under ENAC's current interpretation. EASA AMC1 does not condition PDRA on C-class marking; some national CAAs have interpreted PDRA eligibility more narrowly in practice. This is a verify-before-relying item.

**Full SORA remains the documented fallback** and the rest of §4 and §5 walk through it. If PDRA-S02 is accepted, most of the SORA methodology still applies (ConOps, OSO evidence, ERP, etc.) but without the full 10-step risk assessment — the operator files a compliance statement against the PDRA rather than constructing an iGRC/SAIL derivation from scratch. ENAC timeline and fees for PDRA-declarations are typically **lighter than full SORA** (weeks rather than months; fees in the low hundreds of euros rather than €400–800).

## 4.a SORA Assessment — SAIL II (fallback, if PDRA-S02 is not accepted)

### 4.1 Ground Risk

- **Intrinsic GRC** (Annex F lookup, 2–5 kg, BVLOS over controlled / sparsely populated): **4** as refined; **3** if aggressive argument that orchard sides qualify as "sparsely populated" under M1 controlled-ground-area with landowner agreement.
- **M1** (strategic ground mitigation): fenced controlled ground area on the property + landowner agreements with E/W orchards for non-simultaneous farm work during flight windows → −1.
- **M2** (effects-of-ground-impact reduction): parachute system with **Low** robustness evidence from vendor SORA-ready dossier → −1.
- **M3** (Emergency Response Plan): documented + at least one tabletop exercise logged → −1.
- **Final GRC: 3.** Defensible at SAIL II.

### 4.2 Air Risk

- **Initial ARC** (Class G at low altitude, coastal Liguria, no CTR overlap but Genoa TMA + coastal helo traffic): **ARC-b**.
- **Strategic mitigation**: altitude cap ≤30 m AGL can argue ARC-a in some interpretations; ENAC-dependent. Safer to plan on ARC-b.
- **Residual ARC: b.**

### 4.3 SAIL

- GRC 3 + ARC-b → **SAIL II.**
- GRC 4 + ARC-b → SAIL III (fallback if M1 orchard argument fails).

At SAIL II, ~9 OSOs require "Low" robustness, the remainder optional but recommended. SAIL III escalates many to "Medium" (notably OSO #05 UAS design assurance, OSO #06 C3 link, OSO #18 automatic envelope protection), which is where the self-built ArduPilot hurts.

### 4.4 Adjacent area / airspace containment (OSO #24)

Most commonly rewritten OSO on RFI. Argument: geofence polygon inset from property boundary + FTS (parachute + independent watchdog MCU) + kinetic-energy calculation showing no SAIL escalation if the aircraft leaves the operational volume. The asymmetric geofence (§3.3) feeds directly into this OSO — the south-edge inset is sized to keep worst-case GRB on-property at the altitude/speed cap.

---

## 5. ENAC SORA Process — Phase Walkthrough

### Phase 0 — Prerequisites (weeks 0–2)

- **SPID / CIE** digital identity.
- **Codice fiscale.**
- **D-Flight operator registration** → EU operator number (`IT...` prefix). Displayed on aircraft + embedded in Remote ID broadcasts.
- Insurance per Reg (EC) 785/2004 (§7).
- Pilot competency baseline: A2 CofC + STS/Specific theoretical exam at ENAC, plus operation-specific training syllabus.
- **Pre-application dialogue with ENAC-Liguria (Genova Sestri)** — optional but strongly recommended. A half-day meeting saves months of RFI churn.

### Phase 1 — Conduct the SORA (weeks 2–12)

Per the 10-step SORA 2.5 methodology (see `regulatory-eu.md §5`). Typical SORA document: **60–120 pages** including annexes.

### Phase 2 — Application Package (weeks 12–16)

Per ENAC circular **ATM-09A** (UAS Specific-category operations) and the EASA standard form:

| Document | Pages | Content |
|---|---|---|
| Cover letter + Art. 12 application form | 2–4 | ENAC form on Servizi Online portal |
| ConOps | 15–25 | Phase 1 output |
| SORA risk assessment | 40–80 | Steps 2–10 |
| Operations Manual | 30–60 | Org, responsibilities, normal/abnormal/emergency procedures, training, MEL |
| Technical UAS documentation | 20–40 | Build docs, airworthiness evidence, flight test log, MTBF estimates, C2 link budget |
| Emergency Response Plan | 5–15 | Ground impact response, notification chain, drills |
| Training & competency records | 5–10 | Pilot syllabus + records |
| Insurance certificate | 1 | Reg 785/2004 compliant |
| Remote ID declaration | 1 | Delegated Reg (EU) 2020/1058 compliance |
| DPIA | 10–20 | §6 below |

**Total: 130–260 pages.**

### Phase 3 — Submission (week 16)

- Submit via ENAC **Servizi Online** (`servizionline.enac.gov.it`).
- **Fee (ENAC Tariffario)**: first-issue operational authorisation ~**€400–800**; amendments ~€150–300. *Verify current Tariffario at submission time.*
- Payment via pagoPA / bollettino.

### Phase 4 — ENAC Review (3–6 months)

- Desk review by Direzione Regolazione Spazio Aereo + ENAC-Liguria regional input.
- **2–3 RFI rounds typical.** Frequent RFI targets: OSO evidence gaps, ERP weaknesses, insurance limit mismatches, ConOps ambiguity about autonomous-vs-supervised flight, OSO #24 containment.
- Site visit rare at SAIL II; possible for novel ConOps (autonomous perimeter patrol may qualify).

### Phase 5 — Authorisation Issued

ENAC letterhead PDF containing:

- Operator ID, operation ID, SAIL.
- Geographic scope (polygon or named area), altitude cap, time windows.
- UAS serial(s) covered.
- Limitations (wind, visibility, crew minimums).
- **Validity: typically 24 months, renewable.**
- Reporting obligations.

### Phase 6 — Ongoing compliance

- Flight log retention: 3 years.
- **Occurrence reporting** under Regulation (EU) 376/2014 via **eE-MOR** (ENAC's electronic Mandatory Occurrence Reporting portal), 72 h for reportable events.
- Recurrent training per Ops Manual (annual typical).
- Amendments required before any ConOps change.
- Renewal at T-90 days.

---

## 6. Garante — GDPR Specialisation

Italy's DPA handling is the gentler published-guidance surface but has aggressive enforcement when triggered. Compared to CNIL (FR, most prescriptive) and the Länder DPAs (DE, heterogeneous), Garante is the most lenient for **published baseline** but leaves operators more exposed to enforcement discretion.

### 6.1 Domestic exemption does not apply

GDPR Art. 2(2)(c) excludes "purely personal or household activity." Italian Garante has repeatedly ruled that fixed CCTV capturing neighbours' property, public roads, or beaches loses the exemption (decisions 10065894 and 9949494 on gdprhub.eu). A camera-equipped drone overflying property boundaries is **worse** than fixed CCTV on this axis — it moves, the camera pans, and it operates on automation.

The landowner becomes a **data controller**.

### 6.2 Videosurveillance source — counsel-required inference, not drone-specific rule

**Citation correction from earlier drafts.** Prior versions of this document cited "Provvedimento 11 ottobre 2018 on videosorveglianza" as the authoritative baseline for retention defaults. That was a sourcing error. The general authoritative baseline is Garante's **Provvedimento 8 aprile 2010** ("*Provvedimento in materia di videosorveglianza*"), which remains the reference general provision on video surveillance; later Garante items dated 2018 are **site-specific preliminary-verification decisions** (*provvedimenti preliminari di verifica*) rather than the general baseline source. Subsequent Garante FAQs, sectoral guidance, and GDPR-era reinterpretations supplement the 2010 provision but do not replace it as the source of the general retention framework.

Garante's general CCTV framework establishes, in broad terms:

- **Short default retention** (typically 24 hours) for routine surveillance.
- **Longer retention only with specific justification** — a commonly-cited cap of around 7 days without deeper justification, extending further only for incident-linked or investigation-linked footage.
- Proportionality and minimisation tied to the legitimate-interest balancing test.

**Important framing.** This is **CCTV guidance, not drone-specific published rule.** **The retention windows used throughout this document (24–72 h default, 30–90 d for privileged footage, etc.) are DPIA working assumptions inferred by analogy from the 2010 videosurveillance provision — they are not settled drone-specific law, and they must be re-derived per deployment under Italian counsel review.** The Garante has aggressive enforcement when triggered but has issued limited drone-specific published general guidance; any deployment must treat these numbers as a starting posture subject to:

- **Italian counsel review** against current Garante practice and any drone-relevant decisions issued after this document's date.
- **Pre-deployment DPIA** that justifies the selected retention windows against this project's specific operation profile.
- **Possible Garante pre-consultation** (GDPR Art. 36) if residual risk after mitigations is assessed as high.

Extending CCTV practice to drones is a reasonable starting position but is **not the same as drone-specific published rule**. Operators should not treat the numbers as safe defaults; they are defensible starting points for a counsel-reviewed DPIA.

### 6.3 Refined-site posture (Lavagna)

With the orchard/road/house geometry (§3.2), the GDPR posture softens materially:

| Obligation | Generic residential site | Refined Lavagna site |
|---|---|---|
| **Art. 6 legal basis** | Legitimate interest + LIA | Same; LIA passes more readily — less intrusion |
| **Art. 13 notice** | Boundary signage + published notice | Same |
| **Art. 5(1)(c) minimisation** | Four-sided world-polygon privacy masks | **Single south-facing FOV-sector mask** |
| **Art. 5(1)(e) retention** | Default 24–72 h Garante CCTV precedent | **FOV-gated**: 24–72 h for south-sector capture; 30–90 d for N/E/W |
| **Arts. 15–22 DSAR** | Self-service pipeline | **Acknowledgment-only** manual procedure — expected request volume ≈0 |
| **Art. 35 DPIA** | Required, high-risk | Required, **medium-risk** |
| **Art. 36 prior consultation** | Likely required | **Not required** — saves 1–3 months on timeline |

### 6.4 FOV-sector mask at Lavagna

The refined geometry admits a **single south-facing FOV-sector** privacy mask rather than a four-sided world-polygon:

- Mask applies when gimbal yaw bearing falls in the 135°–225° (southward) range.
- Mask also applies below a configurable altitude threshold where even off-axis frames could resolve the road.
- Above that altitude + outside the south sector: no mask, retention class `long`.

Implementation lives in the `compliance-recorder-two-tier.md` classification pipeline (`sensitive_sectors` config).

### 6.5 Signage

Garante expects Art. 13 signage at reasonable approaches to the monitored zone:

- Controller identity (landowner name / contact)
- Purposes (property security)
- Legal basis (legitimate interest, Art. 6(1)(f))
- Retention periods
- Data subject rights contact
- DPO if appointed (not required here; scale is too small)

Italian practice: *informativa breve* on signage + *informativa estesa* at a URL / posted document.

---

## 7. Insurance Market (Italy)

Reg (EC) 785/2004 floor: 750,000 SDR (~€900,000) for <500 kg MTOM. Specific-category operations are not authorised without insurance evidence.

Italian market for ~5 kg BVLOS multirotor at SAIL II:

- **€600–1,200 / year** for €1M coverage.
- **BVLOS endorsement adds 30–50%.**
- Typical all-in policy: **€1,100–1,800 / year**.

Providers: Allianz, Helvetia, Moncada, Lloyd's via AON. Italy is the **priciest of the three covered countries** for BVLOS endorsements (cf. France €700–1,400, Germany €400–900).

---

## 8. Pilot Competency (Italy)

- **A1/A3 online test** — free via ENAC/D-Flight.
- **A2 Certificate of Competency** — theory exam + self-declared practical. EU-harmonised.
- **STS / Specific-category theoretical exam** at ENAC — required for Specific operations (not STS Certificate itself, which requires C-class aircraft).
- **Operation-specific training** — documented syllabus for the specific ConOps. Evaluated under OSO #17 / #22.

**FAA Part 107 does not transfer.** Operator re-qualifies via ENAC.

---

## 9. Cost Breakdown (Italy)

| Line item | EUR | One-time / Annual | Mandatory | Self-doable |
|---|---|---|---|---|
| ENAC operational authorisation fee | 400–800 | one-time + renewal | yes | yes |
| Reg 785/2004 insurance (~5 kg BVLOS) | 1,100–1,800 | annual | yes | yes |
| D-Flight registration | ~6 | annual | yes | yes |
| Remote ID module (EU-certified) | 100–300 | one-time | yes | yes |
| Parachute system + mount | 1,200–2,500 | one-time | de-facto for M2 | install yes; vendor SORA dossier |
| FLARM receiver | 300–600 | one-time | optional, advised | yes |
| Pilot competency exams (A2 + STS/Specific) | 200–500 | one-time | yes | yes |
| SORA consultant (full package, IT rates) | 3,000–8,000 | one-time | no | *swing factor* |
| SORA consultant (review only) | 800–1,500 | one-time | no | **recommended if self-drafting** |
| DPIA / Garante-aligned lawyer sign-off | 500–1,200 | one-time | effectively yes | half-and-half |
| **Engineer time** | 150–250 h | one-time | — | — |

**Totals:**
- **Self-prepared + expert review**: ~**€3.5–5k + 4–6 engineer-weeks**.
- **Consultant-led**: ~**€7–10k + ~2 weeks** of operator time.

Biggest single swing: self-drafted vs. consultant-led SORA.

---

## 10. Self-do vs Consultant — Italy-specific notes

General guidance in `regulatory-eu.md §11`. Italy-specific considerations:

- **Italian-language submission is strongly preferred.** English technical annexes are accepted with friction. A senior engineer without Italian will need translation help even if self-drafting.
- **ENAC culture is conservative-formal.** Heavy documentation expectation. Informal pre-consultation with ENAC-Liguria is high-leverage — German and French engineering rigour is less critical than Italian procedural completeness.
- **OSO #24 (adjacent-area containment) is the most-commonly-rewritten OSO** on ENAC RFI. Worth a consultant pass even if the rest of the SORA is self-drafted.

---

## 11. Deliverables Checklist — Italy

**Identity & registration**

1. [ ] SPID / CIE active
2. [ ] Codice fiscale on file
3. [ ] D-Flight operator registration — EU operator number assigned
4. [ ] Aircraft marked with operator number + Remote ID serial

**Pilot competency**

5. [ ] A2 CofC
6. [ ] STS / Specific-category theoretical exam passed at ENAC
7. [ ] Operation-specific practical training syllabus completed and logged

**Aircraft & payload**

8. [ ] ArduCopter build docs + flight-test log (≥20 h without intervention)
9. [ ] Remote ID module compliant with Delegated Reg (EU) 2020/1058
10. [ ] Parachute system installed, vendor dossier obtained
11. [ ] FLARM or ADS-B In installed (optional but advisable)
12. [ ] Geofence + FTS verified in SITL and on-aircraft

**Insurance & legal**

13. [ ] Reg 785/2004 insurance certificate, MTOM-appropriate coverage
14. [ ] DPIA document reviewed by Italian GDPR counsel (Garante-aligned)

**SORA package**

15. [ ] ConOps v1.0 signed
16. [ ] SORA 2.5 risk assessment covering all 10 steps
17. [ ] Operations Manual signed by Accountable Manager
18. [ ] Emergency Response Plan + at least one tabletop exercise logged
19. [ ] Technical UAS documentation bundle
20. [ ] OSO evidence matrix at SAIL II Low robustness for all applicable OSOs
21. [ ] Adjacent-area containment argument (OSO #24)

**Submission**

22. [ ] ENAC Servizi Online application submitted
23. [ ] Fee paid (pagoPA)
24. [ ] RFI response pack template ready

**Post-issue**

25. [ ] Flight log retention policy (3 yr) operational
26. [ ] eE-MOR occurrence reporting procedure rehearsed
27. [ ] Renewal calendar reminder at T-90 days

---

## 12. Open Questions / Verify-Before-Relying

- ENAC SORA 2.5 AMC adoption status at submission time (2.0 → 2.5 transition in flight).
- Current-year ENAC Tariffario fees.
- Precise D-Flight geographical zones at the Lavagna coordinates (read live map, don't infer).
- Garante position on **autonomous aerial** perimeter surveillance specifically — no decision cited on this exact use case, only fixed CCTV. DPIA risk rating could still be pushed to high by a hostile reviewer.
- Actual Italian insurance-market minimums in practice for small multirotor BVLOS.
- ENAC policy on privately-built UAS at SAIL III without third-party design assurance — evolving.
- North neighbour's outdoor use pattern in the 0–91 m strip — affects whether the GRB clips uninvolved-person area even with the 91 m house setback. Site survey required.

---

## 13. References (Italy-specific)

- **ENAC** — UAS Specific category Operational Authorisation (circular ATM-09A)
- **ENAC** — Operators from other EU member states under Reg 2019/947
- **ENAC** — Non-EU pilot certification reciprocity
- **ENAV** — Services for your drone; U-space airspace of drones
- **D-Flight** — national UAS platform (`d-flight.it`)
- **Italian Garante** — *Provvedimento in materia di videosorveglianza*, 8 aprile 2010 (general baseline for CCTV retention; applied by analogy to drones — counsel review required)
- **GDPRhub** — Garante decisions 10065894 and 9949494 (CCTV + domestic exemption precedents)
- **ENAC Tariffario** — annual fee schedule (verify current year PDF from `enac.gov.it`)
- **Unmanned Airspace** — Italy's first declared U-space airspace (San Salvo, Abruzzo, 2026-01)

EU-common references in `regulatory-eu.md §References`.

---

*This document is a design-review artifact, not legal advice. Any real IT deployment requires consultation with an Italian avvocato specialising in aviation + data protection, plus pre-consultation with ENAC-Liguria.*
