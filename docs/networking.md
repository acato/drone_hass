# Networking

Canonical reference for VLANs, IP plan, inter-host flows, firewall rules, DNS, NTP, and bandwidth budget. The values in this doc are for the **reference deployment** described in `architecture.md` §8.1.1. Operators adapting drone_hass to their own properties should treat their actual addresses, Net IDs, and bucket names as deployment-private and substitute placeholders before publishing forks.

**Scope:** IP-layer flows only. RF links (SiK 915 MHz, ELRS 2.4 GHz, drone WiFi PHY) are documented in `architecture.md` §5.9 RF Channel Plan.

## 1. VLAN Map

Cross-references `architecture.md` §8.1.1. Restated here for self-containment of the firewall ruleset.

| VLAN | Subnet | Role | Internet egress | Gateway |
|---|---|---|---|---|
| 1 | 10.10.0.0/24 | Management / home LAN (workstations, phones) | Yes | 10.10.0.1 |
| 2 | 10.10.2.0/24 | Ubuntu LLM server (Ollama, Plex, go2rtc, mediamtx, chronyd) | Yes (NTS upstream + general) | 10.10.0.1 |
| 4 | 10.10.4.0/24 | Synology DS1819+ (NAS, MinIO, NFS) | Yes (Synology updates only) | 10.10.0.1 |
| 7 | 10.10.7.0/24 | IoT (generator monitor, etc.) | Limited (vendor cloud allow-list) | 10.10.0.1 |
| 10 | 10.10.10.0/24 | HAOS host + drone integration components + ESPHome dock | Yes (Litestream→S3, OpenTimestamps, push notifications) | 10.10.0.1 |
| 20 | 10.10.20.0/24 | Drone-side: companion RPi, camera, payload | **No** — DMZ, drone VLAN cannot reach internet | 10.10.0.1 (used only for inter-VLAN routing) |

## 2. Host Inventory and Interfaces

| Host | VLAN | Interface | IP | Role (see architecture.md §8.1.1 for full role detail) |
|---|---|---|---|---|
| ASUS router | 1, 2, 4, 7, 10, 20 | trunk to switch | 10.10.{vlan}.1 | DHCP, inter-VLAN router, firewall, NTP relay (none — chronyd serves NTP) |
| HAOS host | 10 | eth0 trunk, untagged 10 | 10.10.10.10 (reserved) | Bridge add-on, HA Core, Mosquitto (host-network) |
| ESPHome dock | 10 | PoE Cat6 (W5500) | 10.10.10.20 (reserved) | Dock controller |
| Ubuntu LLM | 2 | eth0 | 10.10.2.222 | go2rtc, mediamtx, chronyd, Plex, Ollama |
| Synology DS1819+ | 4 | bond0 | 10.10.4.186 | NFS, MinIO, backups |
| Companion RPi | 20 | eth0 (or wlan0 to drone SSID) | 10.10.20.10 (reserved) | MAVLink router, gpsd, RTSP source |
| Camera (Siyi A8 Mini) | 20 | wlan0 to drone SSID | 10.10.20.50 (reserved) | RTSP server |
| ADS-B ground RX (PiAware) | 20 | eth0 | 10.10.20.30 (reserved) | ADS-B feed to bridge |

## 3. DHCP Reservations

All safety-relevant hosts must have DHCP reservations (static leases). Dynamic IPs would break the firewall rules below.

| MAC | IP | Hostname |
|---|---|---|
| (HAOS NIC) | 10.10.10.10 | `haos.drone.lan` |
| (Dock ESP32) | 10.10.10.20 | `dock.drone.lan` |
| (Ubuntu LLM NIC) | 10.10.2.222 | `llm.drone.lan` |
| (Synology bond) | 10.10.4.186 | `nas.drone.lan` |
| (Companion RPi NIC) | 10.10.20.10 | `companion.drone.lan` |
| (Siyi camera NIC) | 10.10.20.50 | `camera.drone.lan` |
| (PiAware NIC) | 10.10.20.30 | `piaware.drone.lan` |

## 4. Canonical Inter-VLAN Flow Table

One row per direction. ASUSWRT inter-VLAN default is permit-any; this table is the **policy source of truth** that the firewall script (§6) enforces by explicit DENY for everything not listed.

| Src host | Src VLAN | Dst host | Dst VLAN | Proto | Port | Purpose | Retain on partition? |
|---|---|---|---|---|---|---|---|
| Companion RPi | 20 | go2rtc (Ubuntu LLM) | 2 | TCP | 8554 | RTSP video push | N — video pause acceptable |
| Companion RPi | 20 | chronyd (Ubuntu LLM) | 2 | UDP | 123 | NTP only — companion has no other VLAN-2 reach | N — companion holds local crystal |
| Dock ESP32 | 10 | Mosquitto (HAOS) | 10 | TCP | 8883 | MQTT-TLS | Y — fail-open lid policy triggers (see §5.5) |
| Dock ESP32 | 10 | chronyd (Ubuntu LLM) | 2 | UDP | 123 | NTP | N — local crystal |
| HAOS Bridge | 10 | chronyd (Ubuntu LLM) | 2 | UDP | 123 | NTP | Y — pre-arm fails after 250 ms offset (see §11.6) |
| HAOS Bridge | 10 | mediamtx control (Ubuntu LLM) | 2 | TCP | 9997 | Stream provisioning | N |
| HAOS Bridge | 10 | go2rtc API (Ubuntu LLM) | 2 | TCP | 1984 | Camera registration | N |
| HAOS Bridge | 10 | MinIO (Synology) | 4 | TCP | 9000 | Litestream secondary replica | Y — Litestream lag check trips at 5s in Part 108 |
| HAOS HA Core | 10 | ESPHome dock native API | 10 | TCP | 6053 | HA→dock entity API (intra-VLAN, ASUS does not see) | Y |
| HAOS HA Core | 10 | go2rtc WebRTC (Ubuntu LLM) | 2 | TCP | 8555 | Camera entity stream source | N |
| Workstations | 1 | HAOS Web UI | 10 | TCP | 8123 | HA UI | N |
| Workstations | 1 | All hosts | * | TCP | 22 | Admin SSH (out of scope of safety) | N |

## 5. Egress Matrix (WAN-bound)

| Src host | Src VLAN | WAN destination | Proto | Port | Purpose |
|---|---|---|---|---|---|
| HAOS Bridge | 10 | AWS S3 us-west-2 | TCP | 443 | Litestream primary replica (Object Lock COMPLIANCE) |
| HAOS Bridge | 10 | OpenTimestamps calendars (alice.btc.calendar.opentimestamps.org, bob, finney) | TCP | 443 | Compliance chain anchor |
| Ubuntu LLM (chronyd) | 2 | `time.cloudflare.com`, `time.nist.gov`, `nts.netnod.se` | UDP / TCP | 123 / 4460 | NTS upstream |
| HAOS systemd-timesyncd (NTS fallback) | 10 | same NTS pool | UDP / TCP | 123 / 4460 | Stratum-2 fallback if Ubuntu LLM down |
| HAOS HA Companion (Nabu Casa) | 10 | `*.ui.nabu.casa` | TCP | 443 | Push notifications (Android FCM, iOS APNs via Nabu) |
| HAOS Renovate / GitHub Actions polling | 10 | `api.github.com`, `ghcr.io` | TCP | 443 | Image digest, dependency updates |
| Synology MinIO | 4 | (none — MinIO does not initiate WAN) | — | — | — |
| Companion RPi | 20 | (none — VLAN 20 has no internet) | — | — | — |
| Dock ESP32 | 10 | `esphome.io` (only during firmware compile, never at runtime) | TCP | 443 | Excluded at runtime |

Out: Pixhawk firmware (`.apj`) is fetched by the operator on a workstation, GPG-verified, then flashed via USB. Not an inter-VLAN flow.

## 6. ASUSWRT-Merlin Firewall Script

ASUS's default inter-VLAN policy is permit-any. The drone VLAN is a DMZ that must be default-deny on egress (no internet, no lateral movement to IoT/management). Inserted at boot via `/jffs/scripts/firewall-start`. Use `iptables -I FORWARD` (insert) not `-A` (append) — ASUS appends its own rules after yours and would override.

```bash
#!/bin/sh
# /jffs/scripts/firewall-start
# drone_hass network policy. Source of truth: docs/networking.md §4 + §5.

LOG="logger -t drone_hass_fw"
$LOG "loading drone_hass firewall rules"

# --- VLAN 20 (drone DMZ): default deny everything except listed flows ---

# Companion -> go2rtc (RTSP)
iptables -I FORWARD -s 10.10.20.10 -d 10.10.2.222 -p tcp --dport 8554 -j ACCEPT
# Companion -> chrony (NTP)
iptables -I FORWARD -s 10.10.20.10 -d 10.10.2.222 -p udp --dport 123 -j ACCEPT
# Camera -> go2rtc (RTSP)
iptables -I FORWARD -s 10.10.20.50 -d 10.10.2.222 -p tcp --dport 8554 -j ACCEPT
# PiAware -> bridge (ADS-B feed)
iptables -I FORWARD -s 10.10.20.30 -d 10.10.10.10 -p tcp --dport 30005 -j ACCEPT
# Stateful return for established connections
iptables -I FORWARD -s 10.10.10.0/24 -d 10.10.20.0/24 -m state --state RELATED,ESTABLISHED -j ACCEPT
iptables -I FORWARD -s 10.10.2.0/24  -d 10.10.20.0/24 -m state --state RELATED,ESTABLISHED -j ACCEPT
# Bridge -> Companion SSH for ops (rate-limited)
iptables -I FORWARD -s 10.10.10.10 -d 10.10.20.10 -p tcp --dport 22 -m limit --limit 6/minute -j ACCEPT

# Default deny VLAN 20 -> anywhere (including WAN)
iptables -A FORWARD -s 10.10.20.0/24 -j LOG --log-prefix "DRONE_VLAN_DROP: " --log-level 4
iptables -A FORWARD -s 10.10.20.0/24 -j DROP
iptables -A FORWARD -d 10.10.20.0/24 -j DROP

# --- VLAN 10 -> 2/4 (HAOS to media/backup hosts) ---
iptables -I FORWARD -s 10.10.10.10 -d 10.10.2.222 -p tcp -m multiport --dports 9997,1984,8555 -j ACCEPT
iptables -I FORWARD -s 10.10.10.10 -d 10.10.4.186 -p tcp --dport 9000 -j ACCEPT
iptables -I FORWARD -s 10.10.10.10 -d 10.10.2.222 -p udp --dport 123 -j ACCEPT
iptables -I FORWARD -s 10.10.10.20 -d 10.10.2.222 -p udp --dport 123 -j ACCEPT  # dock NTP

# --- VLAN 10 NTP lockdown — block public NTP for the dock (which can't do NTS) ---
iptables -I FORWARD -s 10.10.10.20 ! -d 10.10.2.222 -p udp --dport 123 -j DROP
iptables -I FORWARD -s 10.10.10.20 ! -d 10.10.2.222 -p tcp --dport 4460 -j DROP

# --- WAN egress: explicit allow-list for HAOS Bridge ---
# (S3, OpenTimestamps, Nabu Casa, GitHub) — let stateful return handle responses.
# Implementation depends on whether ASUS uses a separate WAN chain; document only.

$LOG "drone_hass firewall rules loaded"
```

A drift-detection script (`scripts/firewall-diff.sh`) runs nightly and diffs `iptables-save` against this canonical script, alerting on mismatch.

## 7. DNS

Split-horizon `*.drone.lan` zone served by the ASUS router (or `dnsmasq` on a dedicated host). All hostnames in §2 resolve to the listed IPs.

ASUS DNS Rebind Protection has explicit exceptions for `drone.lan` so local FQDNs resolving to RFC1918 are not blocked.

mDNS (`*.local`) is **not** bridged across VLANs. The `mdns-repeater` package is intentionally not deployed; cross-VLAN service references use the IP literals from §2 or the `drone.lan` FQDNs from §3.

## 8. NTP

Cross-reference `architecture.md` §11.6. Stratum-2 = Ubuntu LLM (10.10.2.222). Stratum-2 fallback = HAOS systemd-timesyncd (NTS upstream direct).

## 9. MTU per Segment

| Segment | MTU | Rationale |
|---|---|---|
| All wired Ethernet (VLAN 1, 2, 4, 7, 10) | 1500 | Standard; PMTU discovery covers any tunneling overhead |
| Drone WiFi 5 GHz to companion | 1500 | RTSP/RTP and MAVLink TCP both fit |
| Inter-VLAN routing through ASUS | 1500 | No jumbo frames; ASUS hardware switch is wire-speed at 1500 |
| Synology bond0 ↔ HAOS for MinIO/NFS | 9000 (jumbo) — *future optimisation* | Litestream + NFS recordings benefit; not required for safety |

## 10. Failure Modes per VLAN

| Failure | Effect on safety path | Mitigation |
|---|---|---|
| VLAN 2 down (Ubuntu LLM unreachable) | NTP degrades to HAOS systemd-timesyncd (fallback). Video stops. mediamtx recordings stop. | Bridge tolerates 1 s clock offset before pre-arm fails (~28 hrs at local crystal drift). |
| VLAN 4 down (Synology unreachable) | Litestream secondary replica stalls; primary S3 still active. NFS recordings buffer locally on Ubuntu LLM. | Litestream lag check (5 s) does not trip while S3 is alive. |
| VLAN 10 down (HAOS isolated) | Bridge cannot reach video, NTP, or MinIO. Aircraft already airborne continues on SiK + RTL. | Dock fail-open lid policy engages (§5.5). |
| VLAN 20 down (drone DMZ partition) | Companion isolated; video stops; ADS-B ground feed stops. SiK 915 MHz primary C2 unaffected. | Mission continues on SiK; bridge falls back to airborne ADS-B (pingRX) for DAA. |
| WAN down | Litestream replication halts; OpenTimestamps anchor delays; NTS upstream unavailable. | Pre-arm tolerates clock skew up to 1 s; Litestream lag check 5 s for Part 108 mode (R-07). Documented Part 108 grace period: 15 min WAN tolerance (architecture.md §14, network reviewer M5). |
| ASUS router down | Total inter-VLAN failure. | Same as VLAN 10 + 20 down simultaneously. |

## 11. Bandwidth Budget

Peak instantaneous load during an active mission:

| Flow | Peak | Notes |
|---|---|---|
| Companion → go2rtc (RTSP video, 1080p H.264) | 5 Mbps | Capped at 1080p30 / 5 Mbps for live; 4K recorded onboard, retrieved post-flight |
| Companion → chronyd (NTP) | <1 kbps | Negligible |
| Bridge → Mosquitto (MAVLink-derived telemetry) | 200 kbps | 1 Hz at ~200 bytes |
| Bridge → S3 (Litestream WAL replication) | 100 kbps avg, bursts to 5 Mbps on full snapshot | Avg dominates; full snapshots are infrequent |
| HA Core → ESPHome dock (native API) | <1 kbps | Negligible |
| Total inter-VLAN load | ~6 Mbps peak | Trivial on gigabit switching |
| Total WAN egress | 100 kbps avg, 5 Mbps peak | Within typical residential upload |

## 12. Monitoring Probe Targets

Full Prometheus scrape config and alert rules live in `monitoring.md` (TODO). This section enumerates probe targets:

| Probe | Target | Failure threshold |
|---|---|---|
| ICMP | All hosts in §2 | 3 consecutive losses (15 s) |
| TCP/8883 | Mosquitto on HAOS | 3 consecutive failures |
| TCP/9000 | MinIO on Synology | 3 consecutive failures |
| TCP/443 | AWS S3 us-west-2 | 5 consecutive failures (longer for transient WAN) |
| chrony tracking offset | Local stratum-2 | >100 ms |
| Litestream replication lag | bridge-side metric | >5 s in Part 108 mode |
| Bridge `health/chrony` MQTT | every 30 s | stale >60 s |
| Dock heartbeat MQTT | every 1 s | stale >5 s |

## 13. Change Log / Drift Detection

`scripts/firewall-diff.sh` runs nightly via cron; diffs `iptables-save` output against the rules in §6 and alerts on mismatch. The diff is logged into the compliance chain so any unauthorised firewall change is auditable.

When this doc changes, the firewall script must be regenerated and reloaded; the policy and the implementation cannot drift.
