# France — Regulatory Specialisation (Seed)

> **Date:** 2026-04-20
> **Status:** Partial seed — requires completion before deployment
> **Version:** 0.1.0
> **Layers covered:** **Level 5** (national specialisation: DGAC/DSAC + CNIL + AlphaTango). Inherits Levels 0–4 from [`regulatory-layered-model.md`](regulatory-layered-model.md) and [`regulatory-eu.md`](regulatory-eu.md). Level 6 (specific French site) not yet chosen.
> **Parent:** `regulatory-eu.md` (pan-EU framework)
> **Siblings:** `regulatory-eu-it.md` (worked scenario), `regulatory-eu-de.md` (seed)

---

## 1. Scope and Completion State

This document seeds the France specialisation with **findings from the cross-country analysis** (2026-04-20). It has not yet been built out to the depth of `regulatory-eu-it.md` — there is **no worked site scenario, no GRB math for a specific French location, no full cost breakdown, no 27-item checklist, and no French-language submission templates**.

**Completion required before any French deployment** includes:

- Worked site scenario (candidate: Riviera coastal property near Menton or eastern Var, clear of the Nice CTR)
- SORA worked example adapted to French airspace
- CNIL-aligned DPIA overlay (the single hardest remaining piece of work)
- AlphaTango portal integration
- French pilot competency sitting details
- Validated French insurance market quotes
- French-language strings / templates
- Consultation with a French avocat (aviation + RGPD)

**Use this document as:** a decision record of the cross-country findings, a scaffold for the eventual full specialisation, and a checklist of gaps to close.

---

## 2. Competent Authorities

- **DGAC** (Direction Générale de l'Aviation Civile) — competent authority for UAS under 2019/947. The umbrella civil aviation authority.
- **DSAC** (Direction de la Sécurité de l'Aviation Civile) — the DGAC oversight arm that executes operational authorisations. Regional DSAC offices handle submissions.
- **BEA** (Bureau d'Enquêtes et d'Analyses) — accident investigation; receives occurrence reports under Reg 376/2014 for severe events.
- **CNIL** (Commission Nationale de l'Informatique et des Libertés) — French DPA. **Arguably the most active drone-related DPA in the EU.** Has published specific drone guidance (multiple updates since 2020, dedicated "captation d'images par drone" analysis).

**Culture snapshot** (from cross-country analysis):

- Review posture: **procedural-pragmatic, well-tooled, MTOM-class-conscious**.
- Typical SAIL II review timeline: **2–4 months** — **the fastest of the three covered countries** (IT: 4–7 months; DE: 3–6 months with Land variance).
- Language: French mandatory for main application; English accepted for technical annexes.
- Article 14 (self-built UAS) stance: **friendliest of the three**. The French "aéronef construit par un amateur" tradition gives DGAC the clearest published guidance on homebuilt airframes.

---

## 3. National Layer

### 3.1 AlphaTango — the national portal

AlphaTango (operated by DGAC) is the **most mature of the three national portals** covered. Provides:

- Operator registration → EU operator number (French format, `FRA`-prefixed)
- Pilot registration and competency declarations
- National-scenario declarations (S1/S2/S3, being phased out in favour of EASA STS)
- BVLOS authorisation submissions
- Flight declarations (*déclarations de vol*) for notification-required operations

Reasonable JSON-ish REST surface for some operations; no published OpenAPI spec; community-reverse-engineered clients exist. Much of the user-facing surface is form-driven.

### 3.2 Géoportail / UAS zones

French UAS geographical zones are published via AlphaTango's integration with **Géoportail**. Quality is high; conventions are well-documented. Coastal deployment near Nice is dominated by LFMN CTR proximity (within ~15 km is a ZIT-type restricted zone with altitude caps well below 120 m). Parc National des Calanques (further west) and Monaco overflight prohibition are absolute.

A candidate site on the eastern Riviera (e.g., Menton) is far enough from LFMN to be cleaner airspace but still coastal — similar airspace picture to Lavagna with different specific zones.

### 3.3 Historical phase-out: S1 / S2 / S3 scenarios

France maintained national scenarios (*scénarios nationaux* S1, S2, S3) pre-EASA, broadly analogous to today's STS. These are being phased out as EASA STS + PDRA take effect. Any current submission should target **PDRA-S02** (BVLOS with airspace observers in a controlled ground area, sparsely populated environment; UAS MTOM ≤25 kg, max dimension ≤3 m, ≤120 m AGL — **no C-class marking required**, open to Article-14 privately-built UAS; note PDRA-S02 prohibits autonomous operations — remote pilot retains intervention capability) as the first choice, with **full SORA operational authorisation** as fallback for operations outside the PDRA-S02 envelope (including truly unattended autonomy). Legacy S-authorisations remain valid during the transition but are not the right target for new work.

---

## 4. SORA Process (France-specific notes)

General SORA methodology in `regulatory-eu.md §5`. France-specific differences vs. the Italian walkthrough in `regulatory-eu-it.md §5`:

- **Submission portal**: AlphaTango (vs. ENAC Servizi Online).
- **Fees**: **€0 operator registration; ~€500–2,000 for operational authorisation** depending on complexity (vs. Italy's €400–800 + higher BVLOS endorsement costs overall).
- **Review timeline**: **2–4 months** desk review + typically 1–2 RFI rounds (vs. Italy's 3–6 months + 2–3 RFI rounds).
- **Pre-consultation**: regional DSAC office. Practice is similar to ENAC-Liguria — informal pre-consultation is high-leverage.
- **Self-built airframe**: DGAC's published guidance is more permissive than ENAC's informal stance. **Budget less rework on Art. 14 justification** than for Germany.
- **Language**: French mandatory for main application, ConOps narrative, and Ops Manual. English acceptable for technical annexes (SORA worksheet, link budget, OSO evidence tables).

**Estimated total cost** (self-prepared + expert review): **€2.5–4k + ~150 engineer-hours** — lowest of the three countries.

---

## 5. CNIL — the Hardest GDPR Surface in the EU

This is the **single biggest France-specific work item** and the primary reason the France specialisation needs more than a week of effort to complete.

### 5.1 CNIL posture

CNIL has issued multiple updates on drone camera processing since 2020, with a dedicated "captation d'images par drone" analysis. Positions (paraphrased from cross-country analysis; verify against current CNIL publications at implementation time):

- **Private-property autonomous surveillance with any spill-over onto public or neighbouring land triggers DPIA-mandatory treatment.** Lower threshold than Garante.
- **Privacy masking is expected by design, not optional.** CNIL explicitly cites technical privacy mitigations as a DPIA adequacy factor. "Mask everything we couldn't have lawful interest in" is the effective default.
- **Default retention: 30 days** for passive surveillance recordings. Longer only where justified by a documented incident or legal hold. This is *longer* than Garante's 24–72 h but stricter on access control to the recordings.
- **Signage**: CNIL's model notice is prescriptive about content and placement. Controller identity, purposes, legal basis, retention, DSAR contact, DPO if applicable, reference to full privacy notice URL or posted document, placement at every reasonable approach to the monitored zone.

### 5.2 Implications for `drone_hass`

- **Privacy masking must be stricter than the Lavagna FOV-sector approach.** CNIL expects masking of *neighbouring parcels*, not just obviously-public spaces. The architecture's geospatial polygon masking (rather than the Italian simplification to a single FOV sector) is what France actually requires.
- **Retention default** in EU-FR mode: `long` class = 30 d, `short` class = 7 d (more aggressive than Italy's 72 h default for short, but within CNIL's framework).
- **DPIA template** needs a CNIL-specific overlay. **This should be the reference template** for the pan-EU design — CNIL is the most prescriptive, so a CNIL-compliant DPIA is also DE and IT compliant. Downscoping for other countries is easier than upscoping.
- **Signage generator** must emit CNIL-model text in French.
- **DSAR pipeline** — CNIL's enforcement on DSAR is active. An acknowledgment-only procedure may not survive a CNIL inquiry. Budget a self-service tier (or at least a tested manual export pipeline) for French deployment.

### 5.3 Privacy-masking defaults for France

Suggested `classification.sensitive_sectors` default for EU-FR mode (to be refined when a specific French site is scoped):

```yaml
# indicative - refine per site
classification:
  sensitive_sectors:
    - { name: "all_neighbouring_parcels", geofence_mode: "outside_property_polygon", class: short }
  mask_coverage_threshold: 0.10       # lower than IT (0.20)
  retention:
    classes:
      short:  { duration_s: 604800 }  # 7 d
      long:   { duration_s: 2592000 } # 30 d
```

Compare to the Italian FOV-sector approach — France requires a broader, geographically-grounded mask.

---

## 6. Pilot Competency

A2 CofC and STS theoretical exam are EU-harmonised — an ENAC-issued A2 CofC is valid in France and vice versa. **If the operator already has Italian certifications, they transfer.**

French-specific practical items:
- Operator registration in AlphaTango (even if already registered in D-Flight — operator registration is per country of residence; operations in another MS require separate registration only if establishing there).
- Operation-specific training records in French if requested by DSAC.

---

## 7. Insurance Market (France)

Reg 785/2004 floor applies. French market rates for ~5 kg BVLOS multirotor at SAIL II:

- **€700–1,400 / year** for typical policies at €1.2M coverage.
- DGAC does not statutorily mandate above-floor coverage.
- Insurers often include **€1.5M standard for S3/BVLOS** scenarios.

Middle of the three countries for cost (IT priciest, DE cheapest).

---

## 8. Article 13 Cross-border from Italy → France

If the operator has shipped an ENAC operational authorisation, DGAC cross-border recognition is available:

- Submit original OA + ConOps + France-specific mitigations (CNIL overlay, Géoportail zone compliance, French signage, language-adjusted Ops Manual excerpts).
- **Typical DGAC timeline: 6–10 weeks.**
- Effective savings: ~30–50% of original effort. The CNIL overlay and Géoportail zone work are not covered by recognition — they must be produced regardless.

For a hobbyist-scale single-site deployment, **fresh filing in France is often comparable effort** to Art. 13 recognition. Art. 13 wins when the OA is polished and local mitigations are light; mostly that means "when the French DPA overlay was already anticipated in the Italian filing."

---

## 9. Occurrence Reporting

Reg (EU) 376/2014 compliance:

- **Endpoint**: DGAC / BEA portal. BEA handles severe-incident investigations; routine occurrence reports file through DGAC's e-reporting surface (*portail Sinistres Aéronautiques* or similar — **verify current endpoint**).
- **Format**: ECCAIRS-compatible (same underlying standard as Italy's eE-MOR and Germany's BAF).
- **Timeline**: 72 h, same as EU-wide.

Implementation: a common ECCAIRS XML serializer with a per-country submission adapter handles this cleanly. See `regulatory-eu.md §12.3`.

---

## 10. Gaps to Close Before French Deployment

1. [ ] Select a specific candidate site and do the airspace + zone analysis via Géoportail.
2. [ ] Build the CNIL-aligned DPIA overlay + signage generator. **Adopt as the pan-EU reference.**
3. [ ] AlphaTango portal client (registration, authorisation submission, flight notification, status polling).
4. [ ] French-language translations of ConOps template, Ops Manual, ERP, signage text.
5. [ ] Validated BVLOS insurance quote from a French-licensed broker.
6. [ ] Operator registration in AlphaTango (separate from D-Flight if establishing French operations).
7. [ ] Pre-consultation with regional DSAC office.
8. [ ] Consult French avocat specialising in *aviation + RGPD*.
9. [ ] Build out Art. 14 self-built justification for DGAC (lighter lift than Germany but still required).
10. [ ] Complete the scenario-specific SORA (SAIL II target, adapted to French airspace + CNIL masking posture).
11. [ ] Validate the two-tier compliance recorder's retention classes against CNIL expectations (7 d / 30 d rather than 72 h / 30 d).
12. [ ] Test the geospatial (rather than FOV-sector) privacy-mask implementation end-to-end.

---

## 11. Open Questions / Verify-Before-Relying

- Current CNIL drone guidance version and any 2025–2026 updates.
- Exact DGAC / BEA occurrence-reporting endpoint and submission format.
- Whether DGAC is currently accepting SORA 2.5 AMC or still applying 2.0 transitional rules.
- AlphaTango API surface for authorisation submission specifically (much of the public API is form-only).
- Whether Géoportail coverage includes all Natura 2000 and regional parc overflight restrictions in the target deployment area.
- CNIL enforcement record on autonomous aerial surveillance specifically (as opposed to commercial drone photography) — if no direct precedent, the posture above is inferred from the general drone guidance.

---

## 12. References (France-specific)

- **DGAC** — drone regulation portal (`ecologie.gouv.fr` drone section, `alphatango.aviation-civile.gouv.fr`).
- **AlphaTango** — registration and authorisation portal.
- **Géoportail** — UAS geographical zones.
- **CNIL** — "Captation d'images par drone" analysis and guidance (verify current publication).
- **CNIL** — drone-specific updates since 2020 on `cnil.fr`.
- **BEA** — `bea.aero` (occurrence reporting and investigation).

EU-common references in `regulatory-eu.md §15`.

---

*This document is a partial seed for a future deployment. Legal advice required before any French flight operation. Do not rely on inferred CNIL positions without verifying against current published guidance.*
