# Germany — Regulatory Specialisation (Seed)

> **Date:** 2026-04-20
> **Status:** Partial seed — requires completion before deployment
> **Version:** 0.1.0
> **Layers covered:** **Level 5** (national specialisation: LBA + Länder Luftfahrtbehörden + DIPUL + BfDI + Länder DPAs). Germany's federal/Länder split means this layer internally fragments further — see §2 and §5. Inherits Levels 0–4 from [`regulatory-layered-model.md`](regulatory-layered-model.md) and [`regulatory-eu.md`](regulatory-eu.md). Level 6 (specific German site) not yet chosen.
> **Parent:** `regulatory-eu.md` (pan-EU framework)
> **Siblings:** `regulatory-eu-it.md` (worked scenario), `regulatory-eu-fr.md` (seed)

---

## 1. Scope and Completion State

This document seeds the Germany specialisation with **findings from the cross-country analysis** (2026-04-20). It has not yet been built out to the depth of `regulatory-eu-it.md` — there is **no worked site scenario, no GRB math for a specific German location, no full cost breakdown, no 27-item checklist, and no German-language submission templates**.

Germany is the **hardest EU country to port to** from the Italian baseline — not because aviation regulation is stricter, but because of structural fragmentation (16 Länder + federal) in both the NAA and DPA layers.

**Completion required before any German deployment** includes:

- Worked site scenario (candidate: coastal Schleswig-Holstein or Baltic coast — Rügen, Sylt area, or inland single-family property in a less-fragmented Land)
- Selection of **one specific Land** to target first (SH or Bayern are reasonable starting points)
- SORA worked example adapted to German airspace, with additional Art. 14 airframe-conformity evidence the Länder tend to request
- **Per-Land DPA** overlay (e.g., ULD Schleswig-Holstein or BayLDA) — note this needs to be redone per additional Land
- DIPUL portal integration + chosen Land's submission portal integration
- German pilot competency sitting details (LBA-accredited centres)
- Validated German BVLOS insurance quote
- German-language strings / templates
- Consultation with a German Rechtsanwalt (*Luftrecht + Datenschutzrecht*)

**Use this document as:** a decision record of the cross-country findings, a scaffold for the eventual Länder-by-Länder rollout, and a realistic warning that German deployment is months-scale, not weeks-scale.

---

## 2. Competent Authorities — The Federal/Länder Split

Unlike Italy (ENAC, single national) and France (DGAC, single national), Germany has a **two-level structure**:

- **LBA** (Luftfahrt-Bundesamt) — federal aviation authority. Publishes rules, handles some categories of authorisation (notably operations crossing multiple Länder), manages the federal registry.
- **16 Länder Luftfahrtbehörden** — each federal state has its own aviation authority. **Most operational authorisations for fixed-site operations issue at the Land level**, not from LBA. Each Land runs its own submission process, forms, fees, and review culture.
- **BfDI** (Bundesbeauftragter für den Datenschutz und die Informationsfreiheit) — federal DPA. Limited direct role for private landowner drone operations.
- **16 Länder DPAs** — each Land has its own DPA. **Enforces GDPR for drone operations within the Land.** Guidance varies dramatically.

**Culture snapshot** (from cross-country analysis):

- Review posture: **engineering-rigorous, evidence-heavy, expects traceable mitigation** per component.
- Typical SAIL II review timeline: **3–6 months, highly Land-dependent.** Bavaria (Bayern) and NRW often cited as reasonable speed; eastern Länder historically slower.
- Language: **German mandatory in most Länder.** A few accept English for technical annexes (SORA worksheet, link budget), but ConOps and Ops Manual in German.
- Article 14 (self-built UAS) stance: **most documentation-heavy of the three.** Länder tend to request a **structured airframe justification** going beyond what ENAC or DGAC ask for — mass/CG, ESC/battery qualification, failure-mode-by-component analysis, effectively a mini-type-certification narrative.

**Practical consequence**: a single Italian or French SORA does not straightforwardly cross-recognise into Germany under Art. 13; substantive re-review is expected, and Land-specific additions are likely required.

---

## 3. National Layer

### 3.1 DIPUL — federal geo-zone and registration

DIPUL (`dipul.de`, run by DFS on behalf of LBA) is the **federal** side:

- Operator registration → EU operator number (German format, no letter prefix — all-numeric).
- UAS geographical zone map (**clean and well-metadata'd**).
- Flight notification for federal-category operations.

**Operational authorisations are NOT filed in DIPUL.** They go to the relevant Land authority. This is the biggest architectural wrinkle vs. IT (D-Flight does both) and FR (AlphaTango does both).

### 3.2 Land-level submission

Each Land's Luftfahrtbehörde has its own submission process:

- Some Länder run their own web portals.
- Several still accept **PDF applications by email** with subsequent tracking by phone / post.
- Decisions are issued as **PDF on Land letterhead**, not via an API response.

**Architectural implication**: the abstraction `NationalPortalClient` for Germany needs to be composite — one DIPUL client for federal operations (register, zones, notification) + N Land adapters for authorisation submissions. Each Land adapter is 1–2 weeks of effort.

Recommended starting point: pick one Land (where the target deployment is), build that adapter, defer others until needed.

### 3.3 Naturschutzgebiete — the Land-environmental-agency data gap

German coastal Länder have extensive *Naturschutzgebiete* (nature reserves) and bird sanctuaries that carry **Länder-specific overflight bans not uniformly reflected in DIPUL's base layer**. Cross-referencing Land environmental agency maps (e.g., LLUR in SH, BayStMUV in Bayern) is required.

**Architectural implication**: `ZoneProvider` for Germany is a **composite source** — DIPUL base layer + Land environmental agency overlay. This is a substantive codebase difference from IT and FR, where the national portal is authoritative.

---

## 4. SORA Process (Germany-specific notes)

General SORA methodology in `regulatory-eu.md §5`. Germany-specific differences:

- **Submission destination**: Land Luftfahrtbehörde, not LBA directly.
- **Fees**: **€500–3,000 in Land fees**, wider variance than IT/FR. Some Länder also charge for pre-consultation.
- **Review timeline**: **3–6 months** with Land variance. Expect more detailed technical review than ENAC or DGAC.
- **Art. 14 airframe documentation**: **expect supplementary evidence beyond the SORA technical UAS documentation**. Mass and CG measurement with tolerances, ESC/motor/battery qualification records, structural analysis for critical failure modes, airframe-level MTBF estimate. Budget **~1 additional engineer-week** vs. Italy for this alone.
- **Language**: German for ConOps, Ops Manual, ERP. Technical annexes in English may be accepted depending on Land — **verify with the specific Land** before translating.

**Estimated total cost** (self-prepared + expert review): **€2–4k fees + higher engineer-hours (~200–300 h)** due to the additional airframe-conformity work and Land-specific documentation.

---

## 5. GDPR — The 16-Länder Problem

### 5.1 Jurisdictional structure

For a fixed-site drone operation in Germany, the **Land DPA where the operation occurs** has primary authority. In practice both the operation-location DPA and the operator-residence DPA may claim jurisdiction — verify with German GDPR counsel at deployment time.

Examples of Länder DPAs with published drone guidance:

- **BayLDA** (Bayerisches Landesamt für Datenschutzaufsicht, Bavaria) — has issued opinions on drone video surveillance.
- **HmbBfDI** (Hamburgische Beauftragte für Datenschutz und Informationsfreiheit) — published drone-relevant positions.
- **ULD Schleswig-Holstein** (Unabhängiges Landeszentrum für Datenschutz) — historically progressive DPA, likely to have or develop drone guidance.
- Remaining 13 Länder DPAs — guidance depth varies from "specific drone opinion" to "general GDPR guidance only." No central consolidated source.

### 5.2 §35 BDSG — stricter than GDPR baseline

The **Bundesdatenschutzgesetz** (federal data protection act) §35 imposes prior-consultation triggers that are **stricter than GDPR Art. 36 baseline**. Effective implication: even a medium-risk DPIA may trigger mandatory consultation in Germany where it would not in Italy or France.

**Architectural implication**: ComplianceGate's EU-DE mode should gate arming on a recorded prior-consultation outcome (not just a DPIA hash), where a Länder DPA requires it.

### 5.3 Signage

§35 BDSG and Land-level guidance commonly demand signage content beyond the EU baseline:

- Controller identity (full name and address).
- Purposes of processing.
- Legal basis.
- Retention periods.
- Data subject rights contact.
- **QR code linking to the full privacy notice.**
- Posted at **every reasonable approach** to the monitored zone.

Some Länder have issued specific signage templates. The architecture's signage generator should emit a Land-parameterised German notice.

### 5.4 Suggested retention defaults (indicative)

To be refined per Land guidance at deployment time:

```yaml
# indicative - verify per Land DPA
classification:
  mask_coverage_threshold: 0.15
  retention:
    classes:
      short:  { duration_s: 172800 }   # 48 h - conservative midpoint
      long:   { duration_s: 1209600 }  # 14 d - conservative midpoint
```

Less aggressive than CNIL's 30-day default (Länder guidance is more varied, no single prescriptive standard), but tighter than Garante's up-to-7-days tolerance.

---

## 6. Pilot Competency

A2 CofC and STS theoretical exam are EU-harmonised — an ENAC-issued A2 CofC is valid in Germany. **If the operator already has Italian certifications, they transfer.**

Germany-specific practical items:
- Operator registration in DIPUL (not D-Flight).
- LBA-accredited A2 CofC centres exist if the operator wants to sit the exam in Germany.
- Operation-specific training records in German if requested by the Land Luftfahrtbehörde.

---

## 7. Insurance Market (Germany)

Reg 785/2004 floor applies. Germany is the **most competitive of the three** EU markets covered:

- **€400–900 / year** for typical €1–3M coverage policies. Some Länder authorisations condition issuance on proof of **€3M** coverage for BVLOS over non-sparsely-populated areas — not a statutory mandate, but a common Land-level requirement.
- BVLOS endorsement is well understood in the German market.

Brokers active in the German drone market: Helvetia DE, Allianz DE, specialist brokers via *Luftfahrt-Versicherung* markets.

---

## 8. Article 13 Cross-border from Italy → Germany

If the operator has shipped an ENAC operational authorisation:

- Submit original OA + ConOps + Germany-specific mitigations (Land DPA overlay, DIPUL + Land environmental agency zone compliance, German signage, language-adjusted Ops Manual).
- **Typical Land review timeline: 8–16 weeks** for Art. 13 recognition — slower than DGAC (6–10 weeks) because substantive re-review is standard and Art. 14 airframe-conformity supplements may be required.
- Effective savings: ~30–40% of original effort. The Land DPA overlay, supplementary airframe documentation, and language conversion are not covered by recognition.

For a hobbyist-scale single-site deployment, **fresh filing in the target Land is often comparable effort** to Art. 13 recognition. Art. 13 wins only when the OA is unusually polished and the Land is one that welcomes cross-border recognition (varies — some Länder are more receptive than others).

---

## 9. Occurrence Reporting

Reg (EU) 376/2014 compliance:

- **Endpoint**: **BAF** (Bundesstelle für Flugunfalluntersuchung — the accident investigation board) handles severe incidents. Routine occurrence reports file through the LBA's electronic reporting surface.
- **Format**: ECCAIRS-compatible.
- **Timeline**: 72 h, same as EU-wide.

Implementation: common ECCAIRS XML serializer + BAF / LBA submission adapter. See `regulatory-eu.md §12.3`.

---

## 10. Gaps to Close Before German Deployment

1. [ ] **Select target Land.** Recommended: Schleswig-Holstein (coastal, progressive DPA in ULD) or Bayern (inland, experienced Land Luftfahrtbehörde). Each additional Land is a separate project.
2. [ ] Select specific candidate site within the Land and do airspace + zone analysis (DIPUL + Land environmental agency layer).
3. [ ] Build Land-specific DPA overlay (ULD or BayLDA, aligned with their published opinions).
4. [ ] DIPUL client + Land submission adapter (PDF-by-email workflow likely for first Land).
5. [ ] German-language translations of ConOps template, Ops Manual, ERP, signage text.
6. [ ] Validated BVLOS insurance quote from a German-licensed broker; confirm €3M condition where applicable.
7. [ ] Operator registration in DIPUL (separate from D-Flight if establishing German operations).
8. [ ] **Art. 14 airframe-conformity supplement**: mass/CG measurement, ESC/motor/battery qualification, structural analysis, MTBF estimate. This is the single-biggest SORA delta vs. Italy.
9. [ ] Pre-consultation with Land Luftfahrtbehörde.
10. [ ] Consult German Rechtsanwalt (*Luftrecht + Datenschutzrecht*). Expect higher fees than Italian or French counsel.
11. [ ] Validate that ComplianceGate's EU-DE mode prior-consultation hook satisfies §35 BDSG where applicable.
12. [ ] Signage generator emits Land-compliant German text including QR-code support.
13. [ ] Complete scenario-specific SORA (SAIL II target).

---

## 11. Open Questions / Verify-Before-Relying

- Which Land is the first deployment target? This is a load-bearing decision before most of the above items can be scoped.
- Current publication status of Länder DPA drone guidance. Some Länder DPAs update infrequently; BayLDA and ULD are the most likely to have recent positions; other Länder DPAs may have nothing drone-specific.
- Whether the target Land accepts English-language technical annexes in the SORA.
- Whether the target Land's Luftfahrtbehörde requires a particular airframe-conformity evidence format.
- Jurisdictional overlap between operator-residence DPA and operation-location DPA in the specific deployment scenario.
- LBA vs. Land authority boundary for multi-Land operations (not applicable to a single-property deployment).
- Whether SORA 2.5 AMC has been adopted by the target Land or whether transitional 2.0 applies.

---

## 12. References (Germany-specific)

- **LBA** — `lba.de` (federal aviation authority UAS pages).
- **DIPUL** — `dipul.de` (federal registry + zone map, run by DFS).
- **Target Land Luftfahrtbehörde** — identify at deployment time.
- **BayLDA** — `lda.bayern.de` (Bavarian DPA drone opinions).
- **HmbBfDI** — Hamburg DPA.
- **ULD Schleswig-Holstein** — `datenschutzzentrum.de`.
- **BfDI** — `bfdi.bund.de` (federal DPA — limited drone role for private operators).
- **BAF / BFU** — `bfu-web.de` (accident investigation, Reg 376/2014 submissions).
- **BDSG** — Bundesdatenschutzgesetz, §35 prior-consultation provisions.

EU-common references in `regulatory-eu.md §15`.

---

*This document is a partial seed for a future deployment. Legal advice required before any German flight operation. Länder-level practice is the least-well-documented surface in the EU drone regulatory space — verify with German Luftrecht counsel before any commitment.*
