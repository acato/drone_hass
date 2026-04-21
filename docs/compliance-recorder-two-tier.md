# Two-Tier Compliance Recorder

> **Date:** 2026-04-20
> **Status:** Proposal
> **Version:** 0.1.0
> **Layers covered:** **Level 1** (project architecture — the split itself) with per-jurisdiction configuration consumed at **Level 5** (retention-class durations, sensitive-sector definitions, DPIA hash integration). See [`regulatory-layered-model.md`](regulatory-layered-model.md).
> **Supersedes:** Single-tier compliance store semantics in `architecture.md` §8 (chain + blob-in-chain assumption)

---

## 1. Context and Motivation

The Phase 0 compliance recorder (`mavlink_mqtt_bridge/compliance.py`, see `architecture.md` §8.6–8.7 and `memory/compliance_store.md`) is designed as a **single-tier, append-only, cryptographically protected store**: SQLite with SHA-256 hash chain, Ed25519 signatures per record, OpenTimestamps anchoring, Litestream streaming backup. Append-only is a first-class property — records are **never** deleted, and this is load-bearing for the chain's audit value.

Video footage in the current mental model would be captured by the same chain — either as large records inline or as file-path references with per-file hashes included in chain records.

**This is incompatible with GDPR** (`regulatory-eu.md` §8) and with any retention regime that requires footage to be deleted on a schedule or on data-subject request. The Italian Garante's established position on **fixed CCTV videosorveglianza** (Provvedimento 11 ottobre 2018) sets a default retention window of 24 h, extensible to 7 days with justification, longer only for incident-linked footage. Extending that to drone footage is a **DPIA working assumption by analogy**, not a drone-specific published rule — see `regulatory-eu-it.md §6.2`. Either way, "never delete" is a GDPR violation, not a feature, and the two-tier recorder must support scheduled deletion.

It is **also worth doing in US-only mode**. Even under FAA Part 107/108, storing unlimited video footage forever is:

- Expensive (gigabytes per hour of 4K per mission × daily operations).
- Legally risky in US civil discovery (unnecessary retention expands liability exposure).
- Operationally pointless (routine no-incident footage has no evidentiary value after the flight window closes).

This document specifies a **two-tier compliance recorder** that preserves the chain's integrity guarantees for the metadata of every event while allowing the underlying video payloads to follow a retention-class-gated lifecycle with lawful deletion.

---

## 2. Design

### 2.1 Two tiers

**Tier 1 — Metadata chain (unchanged semantics, strengthened role)**
- SQLite, append-only, per-record SHA-256 chain, Ed25519 signatures, OpenTimestamps anchors, Litestream-backed off-site.
- Stores: all flight events, mission plans, compliance gate records, safety events, DAA events, **and a cryptographic reference to every video segment** (segment content hash, byte size, time range, mask state, retention class, blob locator).
- **Never deleted, never modified.** Ships with the same guarantees as today.

**Tier 2 — Blob store**
- Separate storage: local filesystem by default, optionally S3-compatible (Minio on NAS, or cloud).
- Contains only the opaque binary payloads (MP4 segments, H.265 streams, thumbnails).
- **Retention-class-gated lifecycle.** A daemon prunes blobs whose retention class has expired and whose linked incident promotes have not elevated them to a longer class.
- Each blob is named by its tier-1 content hash — the lookup from chain to blob is `hash → filesystem path` or `hash → object key`.
- **Deletion is allowed** and is itself a tier-1 event (signed, chain-protected).

### 2.2 What the chain proves after a blob is deleted

Before deletion:
- Chain contains: "at time T, during flight F, authorised under A, a video segment with SHA-256 H was captured covering FOV sector S, mask applied, retention class R."
- The blob exists at location L, hash-verifiable against H.

After deletion (chain unchanged, blob gone):
- Chain still proves: "a video segment was captured with hash H, under the above conditions, and was deleted at time T' under retention class R by actor X." The deletion is itself a chain record.
- The content is no longer reconstructible — by design, this is the GDPR-compliant outcome.
- **The integrity claim is preserved**: the chain protects the *history of what happened*, not the video content. Any auditor reviewing the chain can verify that the recorder operated correctly, that retention policy was applied, that the deletion was lawful per the recorded retention class.

For incident-linked blobs (elevated to long retention), the blob survives for the relevant evidentiary window; the chain's re-verifiability against the blob is preserved during that window.

### 2.3 Retention classes

| Class | Default duration | Deletion trigger | Typical use |
|---|---|---|---|
| `short` | 72 h | Lifecycle daemon | Routine non-incident footage, FOV overlapping sensitive sector (§3.3) |
| `long` | 30 d (configurable) | Lifecycle daemon | Routine non-incident footage, FOV on-property |
| `incident` | Indefinite (until release) | Manual release + chain event | Footage linked to a recorded `incident` event (DAA trigger, geofence breach, parachute deploy, reported occurrence) |
| `legal_hold` | Indefinite | Manual release + chain event + signed-off hold release record | Litigation, active investigation, Garante inquiry |
| `dsar_frozen` | Until DSAR resolved | Resolution event | Data subject has requested access; freeze any scheduled deletion until the request is handled |

All classes are **durations from capture time**, not wall-clock absolutes. Class transitions (`short → incident`, `long → legal_hold`, `short → dsar_frozen`) are themselves chain events — the history of why a blob lived longer than its default class is preserved.

### 2.4 FOV-gated classification (from `regulatory-eu.md` §8.4)

At segment finalization, the recorder tags each segment with a `retention_class` derived from:

1. **Mask state** — if the privacy mask was active for >X% of the segment's frames, that's a signal the camera was pointed at a sensitive sector.
2. **Gimbal bearing** — mean yaw relative to property geography during the segment. For the Lavagna case, segments where mean yaw points into the south FOV sector get `short`; others get `long`.
3. **Operator override** — ConOps-level setting can force all segments of a mission profile to a specific class.

Default mapping (configurable):

```
if segment.gimbal_sector in operational_config.sensitive_sectors:
    retention_class = "short"
else:
    retention_class = "long"
```

Classification runs once at segment close and is recorded in the chain's `video_reference` record. It cannot be changed later without a chain event (`retention_reclassify`).

---

## 3. Data Model

### 3.1 Tier 1 schema additions

Existing tables (events, hash chain) unchanged. New tables:

```sql
CREATE TABLE video_reference (
  ref_id        TEXT PRIMARY KEY,           -- UUID v7
  flight_id     TEXT NOT NULL,
  segment_hash  BLOB NOT NULL,              -- SHA-256 of blob content (32 bytes)
  blob_locator  TEXT NOT NULL,              -- e.g. "file:///data/blobs/ab/cd/<hash>.mp4" or "s3://bucket/blobs/<hash>"
  byte_size     INTEGER NOT NULL,
  started_at    INTEGER NOT NULL,           -- unix epoch ms
  ended_at      INTEGER NOT NULL,
  mask_profile  TEXT NOT NULL,              -- mask profile name in effect
  mask_coverage REAL NOT NULL,              -- 0..1, fraction of frames with mask active
  gimbal_sector TEXT,                       -- e.g. "south", "north", "mixed"
  retention_class TEXT NOT NULL,            -- short | long | incident | legal_hold | dsar_frozen
  classified_at INTEGER NOT NULL,           -- when class was assigned
  chain_record_id INTEGER NOT NULL,         -- FK to events.id where this reference lives in the chain
  FOREIGN KEY (flight_id) REFERENCES flight_log(flight_id)
);

CREATE INDEX ix_video_reference_retention
  ON video_reference(retention_class, ended_at);

CREATE TABLE blob_lifecycle (
  ref_id        TEXT NOT NULL,
  transition    TEXT NOT NULL,              -- created | reclassified | deleted | restored
  from_class    TEXT,                       -- null on creation
  to_class      TEXT,                       -- null on deletion
  actor         TEXT NOT NULL,              -- "lifecycle_daemon" | "operator:<id>" | "dsar:<request_id>"
  reason        TEXT NOT NULL,
  at            INTEGER NOT NULL,
  chain_record_id INTEGER NOT NULL,
  PRIMARY KEY (ref_id, at),
  FOREIGN KEY (ref_id) REFERENCES video_reference(ref_id)
);

CREATE TABLE dsar_request (
  request_id    TEXT PRIMARY KEY,
  subject_contact TEXT NOT NULL,
  scope_start   INTEGER NOT NULL,
  scope_end     INTEGER NOT NULL,
  status        TEXT NOT NULL,              -- received | frozen | in_review | exported | denied | closed
  received_at   INTEGER NOT NULL,
  resolved_at   INTEGER,
  resolution_note TEXT,
  chain_record_id INTEGER NOT NULL
);
```

Each row also lives as a chain-protected event (see `chain_record_id`). The tables above are **indexable projections** for operational queries; the chain is the source of truth.

### 3.2 Tier 2 layout

Local filesystem default:

```
/data/blobs/
  ab/
    cd/
      abcd1234...ef.mp4         # content-addressed by SHA-256
      abcd1234...ef.thumb.jpg
```

Two-level directory prefix by hash avoids flat directory blow-up at scale.

S3-compatible variant:

```
s3://<bucket>/blobs/<ab>/<cd>/<hash>.mp4
```

Bucket lifecycle rules **are not used** for retention — the lifecycle daemon owns deletion, because deletion must generate a chain event. Object versioning should be **disabled** to ensure `DeleteObject` is final.

### 3.3 Incident linkage

Any tier-1 event with type in `{daa_event, geofence_breach, parachute_deploy, emergency_rtl, occurrence_report, operator_incident_flag}` can specify `incident_window: {start, end}`. On commit, the lifecycle daemon reclassifies any `video_reference` whose time range intersects the incident window from its current class to `incident`. Reclassification is a `blob_lifecycle` event + chain record.

---

## 4. API Surface

(Illustrative — concrete Python module layout TBD.)

```python
class TwoTierRecorder:
    def record_event(self, event: Event) -> int:
        """Write to the chain. Returns the chain record id.
        Unchanged semantics from Phase 0."""

    def reference_video(self, ref: VideoReference) -> None:
        """Emit a chain event describing a newly finalized video segment
        and insert a projection row into video_reference.
        Retention class is computed here from mask_coverage + gimbal_sector."""

    def promote_to_incident(self, ref_id: str, incident_id: str, actor: str, reason: str) -> None:
        """Reclassify to 'incident'. Emits chain event + blob_lifecycle row."""

    def place_legal_hold(self, ref_id: str, actor: str, reason: str) -> None:
        """Reclassify to 'legal_hold'. Emits chain event."""

    def release_hold(self, ref_id: str, actor: str, reason: str) -> None:
        """Release legal_hold back to the originally-assigned class.
        Emits chain event. Subject to role check."""

    def freeze_for_dsar(self, request_id: str, ref_ids: list[str]) -> None:
        """Reclassify each to 'dsar_frozen' pending resolution.
        Emits chain events + dsar_request row."""

    def delete_blob(self, ref_id: str, actor: str, reason: str) -> None:
        """Tier-2 delete + chain event. Must match retention class policy;
        incident / legal_hold / dsar_frozen refuse.
        Deletion is final — no undelete, by design."""

    def export_dsar(self, request_id: str, subject_attestation: str) -> DsarExport:
        """Assemble an export bundle for a DSAR request. Reads tier 1 for
        matching references; reads tier 2 for blobs still present; applies
        secondary masking (blur non-subject faces) in the export pipeline.
        Emits chain events for the request resolution."""
```

The `LifecycleDaemon` process polls `video_reference` on a schedule, selects rows whose `retention_class` has expired at `ended_at + class.duration`, and calls `delete_blob`. In US-only mode the daemon is still running; classes just default to `long` everywhere and blobs live out their natural lifespan.

---

## 5. Integrity and Auditability

**What the chain still proves** (unchanged):
- Every event is append-only and hash-linked to predecessors.
- Every event is Ed25519-signed by the recorder.
- The chain head is OpenTimestamps-anchored on a schedule.
- Litestream streams WAL to off-site storage.

**What the chain proves about video specifically**:
- Every captured segment was logged with its content hash, time range, mask state, and retention class at the moment of finalization.
- Every class transition (reclassify, hold, freeze, delete) is a chain event — the lifecycle of each blob is fully reconstructible from the chain alone.
- If a blob is present, its content is verifiable against the chain-recorded hash.
- If a blob is absent, the chain records when it was deleted, by whom, and under what retention policy.

**What the chain cannot do after deletion**:
- Reproduce the video content. By design.
- Retroactively prove what the frames showed, beyond what was recorded as metadata at capture time (mask state, gimbal sector, mask coverage, etc.). This is why mask state and sector are captured in the chain record, not derived from the blob post-hoc.

For regulatory audit purposes (ENAC occurrence reporting, Garante inquiry, FAA incident investigation), the relevant blobs are in `incident` class and survive the relevant evidentiary window. For routine operations, the chain demonstrates policy compliance without retaining the content.

---

## 6. Interaction with Existing Components

**ComplianceGate** — unchanged for arming. Gains a preflight check (EU mode only) that the recorder is configured with at least one non-default retention class definition and that the privacy-mask profile is active.

**Video pipeline (go2rtc / mediamtx)** — already the authority for RTSP ingest. New outputs: finalised segments written to `/data/blobs/` under content-hash names, plus a `segment_finalized` hook that calls `reference_video` with mask / gimbal metadata from the current frame metadata stream. Masking is applied **pre-write** — the blob is masked.

**Litestream** — unchanged. Streams SQLite WAL off-site. Does **not** stream blobs. Blob off-site redundancy, if desired, is a separate problem (rclone sync, S3 replication, etc.) — and that sync must respect retention class (don't replicate a `short` blob off-site if it'll outlive its local retention window).

**OpenTimestamps anchoring** — unchanged. Anchors the chain head; blobs are not anchored.

**HA integration** — new entities:
- `sensor.drone_recorder_tier1_head` (chain head hash, last-anchored timestamp).
- `sensor.drone_recorder_tier2_blob_count` / `_bytes_used`.
- `sensor.drone_recorder_pending_deletions` (blobs past retention, awaiting daemon pass).
- Service `drone_hass.compliance_export_dsar(request_id, subject_contact, scope_start, scope_end)` — invokes `export_dsar` on the bridge.

---

## 7. Migration from Phase 0

Phase 0 (commit `468d526`) shipped the MVP recorder with the chain but **not yet the video reference schema**. This is the correct time to do the split — before video is integrated.

Migration steps:

1. Add `video_reference`, `blob_lifecycle`, `dsar_request` tables to the SQLite schema (new migration).
2. Introduce the `reference_video` API alongside existing `record_event`. Both emit chain events.
3. Integrate go2rtc / mediamtx segment-finalize hook to call `reference_video`.
4. Ship the lifecycle daemon with a safe default: **all classes default to `long` (30 d)** in US mode until the operator explicitly configures shorter classes or sensitive sectors.
5. Document in `architecture.md` the updated chain+blob split. Cross-link from §8.

Because Phase 0 shipped without video-in-chain, **there is no data migration** — the two-tier model is greenfield from this side. Existing chain records are unaffected.

---

## 8. Configuration

New bridge config stanza:

```yaml
compliance_recorder:
  tier1:
    db_path: /data/compliance.sqlite
    anchor_interval_s: 3600
    litestream_enabled: true
  tier2:
    backend: filesystem          # or: s3
    root: /data/blobs
    # s3_endpoint, s3_bucket, s3_access_key, ... when backend: s3
  retention:
    default_class: long
    classes:
      short:  { duration_s: 259200 }   # 72 h
      long:   { duration_s: 2592000 }  # 30 d
      # incident, legal_hold, dsar_frozen have no scheduled expiry
  classification:
    sensitive_sectors:           # mean gimbal yaw (deg) ranges → short
      - { name: "south_road", yaw_from: 135, yaw_to: 225, class: short }
    mask_coverage_threshold: 0.20   # >=20% masked frames → short regardless
  lifecycle:
    sweep_interval_s: 900        # 15 min
    deletion_dry_run: false      # set true during bring-up
```

EU-mode default profile ships with `default_class: short` and the Lavagna south-road sensitive sector; US-mode default profile ships with `default_class: long` and no sensitive sectors.

---

## 9. Open Questions

- **Blob off-site replication policy.** Default to local-only (no off-site for any retention class) vs. off-site for `incident` + `legal_hold` only? Leaning toward the latter — incident footage is precisely what you want redundant.
- **Deletion durability.** On a journaled filesystem, `unlink` leaves blocks recoverable. For strong GDPR-erasure claims, a secure-erase path may be warranted for `short`-class deletions. Budget: optional `secure_unlink: true` config, off by default.
- **Export pipeline for DSAR: secondary masking of non-subject faces.** Requires face-detection + blur in the export path. Not in scope for v0.1; acknowledgment-tier DSAR (manual review) is the Phase-1 answer.
- **Chain record size for video references.** With H.265 segments of ~30 MB per minute × continuous operations, reference record count dominates the chain. At 1000 segments/year × several years the chain has ~tens of thousands of records — still trivially small. Not a concern.
- **SORA OSO #24 and #10 interaction.** Incident class promotion on `parachute_deploy` / `geofence_breach` strengthens the OSO #10 evidence story. Worth calling this out in the SORA submission.

---

## 10. Summary

- **One-way-door hedge**: the two-tier split is the biggest architectural decision that benefits both US and EU deployments. Deferring it past video integration means a painful chain migration later.
- **Chain integrity preserved**: deletion is a first-class lifecycle event, signed and anchored like any other. The chain proves *what happened*, not *what was on camera*.
- **GDPR-native**: retention classes, DSAR freeze, legal hold, and FOV-gated classification are first-class citizens.
- **US-mode cost**: essentially zero — defaults produce the current `long` retention behaviour.
- **EU-mode cost**: one consequential behavioural change (lifecycle daemon is now pruning), plus the integration work for privacy masking which is separate and already required by the Lavagna SORA analysis.
