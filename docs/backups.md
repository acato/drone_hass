# Backups

Backup matrix, restore procedures, integrity verification, disaster scenarios. Backups themselves are an attack surface — every artifact below is encrypted at rest before leaving the source host.

Cross-references: `architecture.md` §8.1.1 (deployment topology), `resolutions-ha.md` R-08 (Ed25519 key wrapping), R-27 (build hardening), `operations.md` §5 (rotation calendar).

## 1. Backup Matrix

| Artifact | Source | Encryption at rest | Primary destination | Secondary | Cadence | Retention | Restore SLO |
|---|---|---|---|---|---|---|---|
| Compliance DB (SQLite) | bridge add-on `/data/compliance/` | wrapped per-record signatures + Litestream WAL streaming | S3 us-west-2 (Object Lock COMPLIANCE 3 yr) | MinIO on Synology (Object Lock) | continuous (Litestream WAL) | 3 yr active + Glacier Deep Archive 7 yr | < 10 min for active; 12-48 hr for Glacier |
| Ed25519 compliance signing key | bridge `/data/compliance/signing_key.enc` | scrypt+AES-GCM (R-08) | NAS `/volume1/llm_backup/drone_hass/keys/` | S3 sibling prefix (Object Lock) | nightly | 5 yr | < 5 min |
| MAVLink signing key | bridge `/data/compliance/mavlink_signing.key` | **wrapped with same scrypt+AES-GCM scheme**, separate passphrase from Ed25519 | NAS `/volume1/llm_backup/drone_hass/keys/` | S3 sibling prefix | nightly + on rotation | 2 yr (rotated annually) | < 5 min |
| HA full snapshot | HA Supervisor | AES-128-CBC if backup password set (**MANDATORY**, never plaintext) | NAS `/volume1/llm_backup/drone_hass/ha_snapshots/` | S3 sibling prefix | nightly | 30 d active + 1 yr cold | < 30 min |
| HA `secrets.yaml` | `/config/secrets.yaml` | inside HA snapshot + separate copy in 1Password vault | password manager | paper copy (fireproof box) | per change | indefinite | manual |
| ESPHome dock firmware source | git repo | git | GitHub | self-hosted Gitea on Synology | per change | git history | < 1 min |
| ESPHome dock secrets | dock `secrets.yaml` | age-encrypted | NAS `/volume1/llm_backup/drone_hass/esphome/` | password manager | per change | indefinite | < 1 min |
| ArduPilot params (`.parm`) | manual export pre/post tuning | git LFS | GitHub | NAS | per session | indefinite | < 1 min |
| Mosquitto passwd + ACL | `/share/mosquitto/` | inside HA snapshot + age-encrypted standalone | NAS `/volume1/llm_backup/drone_hass/mosquitto/` | — | per change | indefinite | < 5 min |
| `bridge_config.yaml` + operational area GeoJSON | bridge `/data/` | inside HA snapshot + git copy of canonical | git + NAS | — | per change | indefinite | < 1 min |
| Network config (ASUS export, dock YAML) | router admin export, repo | git + age-encrypted router export | GitHub + NAS | — | per change | indefinite | < 5 min |
| Dock↔bridge HMAC key | dock NVS + bridge config | wrapped envelope | NAS + password manager | paper copy | per dock reflash | indefinite | < 1 min |

## 2. Off-Property Strategy

Single-cloud is a single-point-of-failure. AWS account closure (ToS suspension, hostile state action, billing dispute) would silently halt Litestream replication and stop OTS proof anchoring of new records.

**Resilience design:**

- **Primary cloud**: AWS S3 us-west-2 with Object Lock COMPLIANCE 3 yr (anchor for compliance retention).
- **Second cloud**: Backblaze B2 OR Cloudflare R2 (S3-compatible, cheaper egress) as a parallel Litestream replica. Litestream supports multiple replica destinations.
- **Cold tier**: S3 Glacier Deep Archive for >90 day artifacts via lifecycle rule. Separate IAM principal with `s3:GetObject + s3:RestoreObject` only — no `s3:DeleteObject`, no bucket-config writes. Object Lock COMPLIANCE on the Glacier tier survives credential compromise; that is the actual control, not the credential surface.
- **OpenTimestamps calendars** are independent of any chosen cloud. The chain proofs survive AWS loss as long as the SQLite DB and the OTS receipts are replicated elsewhere (MinIO + B2/R2 satisfy this).

## 3. Backup Integrity Verification

Backups themselves are chained: the SHA-256 of every backup artifact is recorded into the compliance DB at backup creation time. A tampered backup is detected on the next restore-verification.

```python
# Pseudocode in backup script
sha = hashlib.sha256(open(artifact, 'rb').read()).hexdigest()
emit_compliance_event(
    type='backup_artifact_created',
    artifact=artifact_name, dest=destination_uri,
    sha256=sha, size=os.path.getsize(artifact),
    source='backup_script',
)
```

**Verification cadence:**

- **Monthly**: random restore of one artifact from the matrix (rotated) to a throwaway path. SHA-256 must match the recorded value.
- **Quarterly**: full Litestream restore from S3 → throwaway SQLite → `verify_chain.py` end-to-end (Ed25519 signatures + SHA-256 hash chain + OpenTimestamps proof walk for each anchored record). This is the gold-standard integrity check; failure halts production until investigated.
- **Annual**: restore-from-zero drill (per `operations.md` §2.1).

## 4. Restore Procedures

Procedures live in `docs/runbooks/<topic>.md`. Index:

- `runbooks/restore-compliance-db.md` — Litestream restore, both replicas
- `runbooks/restore-ed25519-key.md` — unwrap envelope, verify against fingerprint, reinstall
- `runbooks/restore-mavlink-key.md` — same flow for MAVLink signing key
- `runbooks/restore-ha-snapshot.md` — HA Supervisor restore + backup-password handling
- `runbooks/restore-from-zero.md` — bare-metal HAOS rebuild (referenced from operations.md §2.1)

**Restore-time RPIC notification:** any restore action posts a critical-priority push to all RPIC devices and logs a compliance event. Reason: insider threat — a restored DB could be a tampered version, and the chain-restart procedure must be visible.

## 5. Disaster Scenarios

| Scenario | Effect | Recovery |
|---|---|---|
| Synology fire / theft | Lose secondary replica + nightly key backups | S3 primary still active; restore secondary from S3 onto replacement Synology; takes ~hours including cosign-verified rebuild |
| AWS account closure | Lose primary replica + Object Lock anchor | Switch Litestream to second cloud (B2/R2); chain continues; OpenTimestamps proofs unaffected (stored in DB itself) |
| HAOS host failure | Bridge down; chain stops; flights blocked | Restore-from-zero drill: rebuild HAOS, install bridge add-on (cosign-verified), Litestream restore, unseal Ed25519, verify chain |
| Ed25519 passphrase loss + TPM unavailable | Cannot unwrap signing key | R-08 chain restart procedure: new keypair, new genesis row referencing prior chain's last hash + OTS proof, document loss event |
| MAVLink signing key passphrase loss | Cannot unwrap; bridge cannot communicate with FC | Re-key via physical USB to FC (resolutions-ua.md ATK-MAV-01), new wrapped envelope, new backup |
| Ransomware on Synology | Secondary replica encrypted | MinIO Object Lock prevents encryption-in-place if enabled (REQUIRED); S3 primary unaffected; restore Synology from S3 |
| Ransomware on HAOS | Compliance DB encrypted in place | SQLite live writes blocked; Litestream replicas unaffected (objects already written immutable); restore-from-zero |

## 6. Key Ceremony (Ed25519 Passphrase)

The Ed25519 signing-key passphrase is the single secret that unlocks compliance-record forgery. Loss = chain restart. Compromise = forged records possible until rotation.

**Storage policy** (operator personal copies):
1. Paper, sealed envelope, fireproof box
2. Password manager entry (1Password / Bitwarden) with the recovery procedure URL
3. Sealed copy with a designated alternate (attorney, family member with operator's permission)

**Optional Shamir 2-of-3 split** for multi-operator deployments: shares to operator, alternate, attorney. Requires `shamir-secret-sharing` tool; reconstruct with any 2 of 3. Sysop runbook: `runbooks/shamir-key-ceremony.md`.

The passphrase is **never** stored in HA `secrets.yaml`, in any backup, or in the compliance DB itself. Loss is recoverable (chain restart with link to prior); compromise is silent and dangerous.

## 7. HA Snapshot Encryption

HA backups default to plaintext tarball if no backup password is set. **The backup password is mandatory for drone_hass deployments.** Set via HA Supervisor → Backups → Set encryption password.

Rotation:
- Per `operations.md` §5: annual rotation
- Per personnel change: immediate rotation
- Old backups remain encrypted with the old password — keep a historical password log in the password manager (not paper, since these grow over time)

## 8. NAS-Side Hardening (MinIO and Filesystem)

- MinIO bucket Object Lock enabled (COMPLIANCE mode), 3 yr retention, mirroring the S3 setup.
- DSM Btrfs snapshots on `/volume1/llm_backup/drone_hass/` daily, retained 30 days. Defeats accidental overwrite even before MinIO Object Lock kicks in.
- DSM user account for backup writes is non-admin, write-only on the target paths, no shell access.
- Synology firewall: deny WAN, allow only HAOS host IP to MinIO port 9000.

## 9. Restore Drill Audit Log

Every monthly random restore + quarterly full-chain restore + annual restore-from-zero is logged into the compliance chain with a `restore_drill_completed` event including: source replica, artifact name, SHA-256 match (or mismatch), `verify_chain.py` exit code, timestamp, operator. Audit history of drill compliance is itself audit evidence.
