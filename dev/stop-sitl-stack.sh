#!/usr/bin/env bash
# Tear down the SITL dev stack cleanly.
#   - Kills bridge + SITL inside WSL
#   - Stops Mosquitto container
# Safe to run even if some processes are already gone.

set -euo pipefail

REPO_WSL='/mnt/c/Users/aless/dji_hass'
WSL_DISTRO='Ubuntu'

say() { printf '[%s] %s\n' "$(date +%H:%M:%S)" "$*"; }

say "stopping bridge (if any)"
wsl.exe -d "$WSL_DISTRO" -- bash -lc "pkill -f 'python.*mavlink_mqtt_bridge' || true" >/dev/null 2>&1 || true

say "stopping SITL / MAVProxy (if any)"
wsl.exe -d "$WSL_DISTRO" -- bash -lc "pkill -f 'arducopter|mavproxy' || true" >/dev/null 2>&1 || true

say "stopping Mosquitto"
( cd "$REPO_WSL/dev" && docker compose down ) >/dev/null 2>&1 || true

say "done. Close the SITL/Bridge tabs manually if they're still open."
