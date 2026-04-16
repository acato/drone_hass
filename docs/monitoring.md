# Monitoring

Prometheus + Grafana + alertmanager stack for drone_hass. Alert rules, scrape configs, dashboards.

Cross-references: `networking.md` §12 (probe target inventory), `operations.md` §6 (compliance-relevant alerts), `architecture.md` §11.6 (NTP).

## 1. Architecture

| Component | Host | Notes |
|---|---|---|
| Prometheus | Ubuntu LLM (10.10.2.222) | Docker Compose stack at `/home/aless/monitoring/`, data on NFS-backed `/mnt/` to survive container rebuilds |
| Alertmanager | Ubuntu LLM | Same compose stack |
| Grafana | Ubuntu LLM | Dashboard JSON in `grafana/dashboards/` in repo |
| Healthchecks.io | hosted (cloud) | Dead-man's-switch — must bypass HA so HA-down also triggers alert |

**Alert fan-out (priority order):**

1. **HA notify** (primary): single point of routing for mobile_app + Pushover + Slack
2. **ntfy.sh self-hosted** on Ubuntu LLM (backup): used when HA itself is down
3. **Email** (last resort): SMTP via Mailgun for asynchronous awareness

Pure-vendor dependencies (Pushover-only, Slack-only) are deliberately not direct alertmanager targets.

## 2. Scrape Config

`prometheus.yml` snippet (full file in `monitoring/prometheus.yml`):

```yaml
scrape_configs:
  # Bridge add-on — direct port, NOT through Ingress (auth proxy adds latency
  # and breaks scrape on HA restart, violating compliance independence)
  - job_name: drone_hass_bridge
    static_configs:
      - targets: ['10.10.10.10:9101']
        labels: { drone_id: 'patrol' }

  # Mosquitto broker (mosquitto-exporter sidecar)
  - job_name: mosquitto
    static_configs: [{ targets: ['10.10.10.10:9234'] }]

  # HAOS host
  - job_name: haos_node
    static_configs: [{ targets: ['10.10.10.10:9100'] }]

  # Ubuntu LLM host (self)
  - job_name: llm_node
    static_configs: [{ targets: ['10.10.2.222:9100'] }]

  # Synology DS1819+ via SNMP
  - job_name: synology_snmp
    metrics_path: /snmp
    params:
      module: [synology]
    static_configs: [{ targets: ['10.10.4.186'] }]
    relabel_configs:
      - source_labels: [__address__]
        target_label: __param_target
      - target_label: __address__
        replacement: '10.10.2.222:9116'   # snmp_exporter

  # ESPHome dock — native /metrics
  - job_name: dock_esphome
    static_configs: [{ targets: ['10.10.10.20:80'] }]

  # chronyd stratum-2 (chrony_exporter)
  - job_name: chrony
    static_configs: [{ targets: ['10.10.2.222:9123'] }]

  # Litestream
  - job_name: litestream
    static_configs: [{ targets: ['10.10.10.10:9090'] }]

  # ASUS router via SNMP
  - job_name: asus_snmp
    metrics_path: /snmp
    params: { module: [if_mib] }
    static_configs: [{ targets: ['10.10.0.1'] }]
    relabel_configs:
      - source_labels: [__address__]
        target_label: __param_target
      - target_label: __address__
        replacement: '10.10.2.222:9116'

  # Blackbox probes (TCP, ICMP, HTTP, SSL)
  - job_name: blackbox
    metrics_path: /probe
    params: { module: [tcp_connect] }
    static_configs:
      - targets:
          - 10.10.10.10:8883             # Mosquitto TLS
          - 10.10.4.186:9000             # MinIO
          - s3.us-west-2.amazonaws.com:443
    relabel_configs:
      - source_labels: [__address__]
        target_label: __param_target
      - target_label: __address__
        replacement: 10.10.2.222:9115

  # SSL cert expiry
  - job_name: blackbox_ssl
    metrics_path: /probe
    params: { module: [tcp_connect_tls] }
    static_configs:
      - targets:
          - 10.10.10.10:8883
          - homeassistant.local:443
          - s3.us-west-2.amazonaws.com:443
```

## 3. Bridge `/metrics` Endpoint

The bridge add-on exposes Prometheus metrics on `127.0.0.1:9101` (Docker host network, separate from the Ingress port 8099 which is behind HA's auth proxy). Direct LAN scrape from Prometheus to HAOS host port 9101.

Rationale:
- Ingress auth proxy adds latency and breaks scrape on HA restart, violating the compliance-independence principle.
- Prometheus has no clean way to carry HA's session cookie.
- LAN-only binding plus iptables (allow only 10.10.2.222 → 10.10.10.10:9101) is sufficient access control.

Documented in `networking.md` §12.

## 4. Alert Rules

`monitoring/alerts.yml` (excerpt — see file for full set):

```yaml
groups:
  - name: drone_hass.bridge
    rules:
      - alert: BridgeUnplannedRestart
        expr: changes(drone_hass_bridge_uptime_seconds[10m]) > 0
        for: 1m
        labels: { severity: warning, ops_event: 'true' }
        annotations:
          summary: "Bridge restarted unexpectedly"
          runbook: "runbooks/bridge-restart.md"

      - alert: LitestreamReplicationLag
        expr: litestream_replication_lag_seconds > 5
        for: 30s
        labels: { severity: critical, compliance_relevant: 'true' }
        annotations:
          summary: "Litestream lag {{ $value }}s exceeds 5s threshold"
          runbook: "runbooks/litestream-lag.md"

      - alert: ComplianceChainVerifyFailure
        expr: increase(drone_hass_chain_verify_failures_total[10m]) > 0
        for: 0m
        labels: { severity: critical, compliance_relevant: 'true' }
        annotations:
          summary: "Compliance chain verification failed"
          runbook: "runbooks/chain-verify-failure.md"

      - alert: ChronyOffsetHigh
        expr: abs(chrony_tracking_last_offset_seconds) > 0.1
        for: 5m
        labels: { severity: warning }
        annotations:
          summary: "Chrony stratum-2 offset {{ $value }}s exceeds 100 ms"

      - alert: PreArmClockSkewBlocked
        expr: increase(drone_hass_prearm_clock_skew_blocks_total[1h]) > 0
        for: 0m
        labels: { severity: critical }
        annotations:
          summary: "Pre-arm blocked due to clock skew >250 ms"

      - alert: DockHeartbeatStale
        expr: time() - drone_hass_dock_heartbeat_last_seen_seconds > 5
        for: 30s
        labels: { severity: critical }
        annotations:
          summary: "Dock heartbeat stale ({{ $value }}s); fail-open lid policy may engage"

      - alert: DockFailOpenEngaged
        expr: increase(drone_hass_dock_fail_open_engaged_total[5m]) > 0
        for: 0m
        labels: { severity: critical, compliance_relevant: 'true' }
        annotations:
          summary: "Dock fail-open lid policy engaged"
          runbook: "runbooks/dock-fail-open.md"

      - alert: UnsignedSafetyMessageDropped
        expr: increase(drone_hass_unsigned_dropped_total[5m]) > 0
        for: 0m
        labels: { severity: critical, compliance_relevant: 'true' }
        annotations:
          summary: "Unsigned safety-critical MAVLink dropped — possible injector on VLAN 20"

      - alert: SignatureVerificationFailed
        expr: increase(drone_hass_signature_verification_failures_total[1h]) > 0
        for: 0m
        labels: { severity: critical }
        annotations:
          summary: "cosign verify failed for running bridge image"

      - alert: KeyUnsealFailureBurst
        expr: increase(drone_hass_key_unseal_failures_total[5m]) >= 3
        for: 0m
        labels: { severity: critical }
        annotations:
          summary: "3+ failed unseal attempts in 5 minutes — possible passphrase brute-force"

  - name: drone_hass.infra
    rules:
      - alert: SSLCertExpiry
        expr: probe_ssl_earliest_cert_expiry - time() < 14*86400
        for: 1h
        labels: { severity: warning }
        annotations:
          summary: "{{ $labels.instance }} cert expires in <14 days"

      - alert: DiskFreeBridge
        expr: (node_filesystem_avail_bytes{mountpoint="/data"} / node_filesystem_size_bytes{mountpoint="/data"}) < 0.15
        for: 30m
        labels: { severity: warning }
        annotations:
          summary: "Bridge /data free space < 15%"

      - alert: SynologyVolumeFree
        expr: synology_volume_size_free_bytes / synology_volume_size_total_bytes < 0.20
        for: 1h
        labels: { severity: warning }
        annotations:
          summary: "Synology /volume1 free space < 20%"

      - alert: ADSBReceiverStale
        expr: time() - drone_hass_pingrx_last_msg_seconds > 60
        for: 1m
        labels: { severity: warning }
        annotations:
          summary: "ADS-B pingRX has not produced a message in 60 s — DAA degraded"
```

## 5. Compliance-Relevant Alert Routing

Alerts labeled `compliance_relevant: "true"` are also written into the compliance DB by an `alertmanager_webhook` consumer in the bridge. Audit trail proves the system noticed the event and which routing fired.

The list mirrors `operations.md` §6 audit-logging policy:
- LitestreamReplicationLag, ComplianceChainVerifyFailure
- DockFailOpenEngaged, UnsignedSafetyMessageDropped
- SignatureVerificationFailed, PreArmClockSkewBlocked

## 6. Dashboards

`grafana/dashboards/` (versioned in repo):

| Dashboard | Audience | Panels |
|---|---|---|
| `flight-status.json` | RPIC during ops | Battery %, GPS HDOP, link RSSI (SiK + WiFi), mode, altitude, distance from home, current waypoint |
| `compliance-chain.json` | audit | Records/day, last OTS proof anchor age, Litestream lag, chain verify status, signing-key fingerprint |
| `infrastructure.json` | sysop | All node_exporter, Mosquitto throughput, MinIO bucket size, Synology volume usage, chrony tracking, ASUS interface counters |
| `safety-events.json` | sysop + RPIC | DAA contacts, fail-open events, unsigned-dropped counter, pre-arm denials, signature-verification status |

## 7. Dead-Man's-Switch

Bridge POSTs to a Healthchecks.io check daily. Healthchecks.io alerts via independent email + Pushover if the ping is missing. This is the only alert path that does not depend on HA, alertmanager, or Prometheus — covers "everything is down so no one alerts."

```python
# In bridge daily cron
import requests
requests.get(f"https://hc-ping.com/{HEALTHCHECKS_UUID}", timeout=10)
```

## 8. Synthetic SITL Shadow Mission

Nightly cron on Ubuntu LLM runs ArduPilot SITL + a throwaway bridge container, executes a canned mission, asserts:
- Compliance row count incremented as expected
- Hash chain validates end-to-end
- Ed25519 signatures verify
- All MQTT topics published with expected schemas

A failed shadow mission alerts at `severity: warning, ops_event: true`. Catches schema drift, dependency upgrades, and ArduPilot behaviour changes that unit tests miss.

## 9. Runbook Convention

Every alert annotation includes a `runbook:` URL pointing into `docs/runbooks/<topic>.md`. The runbook must contain: trigger description, immediate action, diagnostic commands, escalation path, post-incident compliance event template.
