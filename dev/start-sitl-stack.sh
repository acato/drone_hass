#!/usr/bin/env bash
# Launch the full SITL dev stack:
#   1. Mosquitto (detached Docker container)
#   2. SITL        — new Windows Terminal tab, interactive MAVProxy
#   3. Bridge      — new Windows Terminal tab, live log
#   4. Observer    — attached to this shell (Ctrl-C stops watching)
#
# Run this from any shell on the Windows host (Git Bash, WSL, etc.).
# Stops cleanly with `./stop-sitl-stack.sh`.

set -euo pipefail

REPO_WIN='C:\Users\aless\dji_hass'
REPO_WSL='/mnt/c/Users/aless/dji_hass'
WSL_DISTRO='Ubuntu'
DRONE_ID='sitl1'   # must match dev/bridge.yaml drone.id

say() { printf '[%s] %s\n' "$(date +%H:%M:%S)" "$*"; }
fail() { say "ERROR: $*" >&2; exit 1; }

# --- Pre-flight ---

command -v wt.exe >/dev/null 2>&1 || fail "wt.exe (Windows Terminal) not in PATH. Install from Microsoft Store."
command -v wsl.exe >/dev/null 2>&1 || fail "wsl.exe not in PATH."
command -v docker  >/dev/null 2>&1 || fail "docker not in PATH. Start Docker Desktop."
docker info >/dev/null 2>&1 || fail "docker daemon not responding — is Docker Desktop running?"
wsl.exe -l -q 2>/dev/null | tr -d '\r' | grep -qx "$WSL_DISTRO" \
    || fail "WSL distro '$WSL_DISTRO' not found (got: $(wsl.exe -l -q 2>/dev/null | tr -d '\r' | xargs))"

# bridge.yaml — seed from example on first run
if [ ! -f "$REPO_WSL/dev/bridge.yaml" ]; then
    say "seeding dev/bridge.yaml from example"
    cp "$REPO_WSL/dev/bridge.yaml.example" "$REPO_WSL/dev/bridge.yaml"
fi

# --- 1. Mosquitto (detached) ---

say "[1/4] starting Mosquitto"
( cd "$REPO_WSL/dev" && docker compose up -d ) >/dev/null

for i in $(seq 1 10); do
    if docker exec drone_hass_mosquitto_dev sh -c 'echo > /dev/tcp/localhost/1883' >/dev/null 2>&1; then
        say "       broker ready"
        break
    fi
    [ "$i" = 10 ] && fail "Mosquitto did not open 1883 within 10s"
    sleep 1
done

# --- 2. SITL in a new WT tab ---

say "[2/4] opening SITL tab"
wt.exe --window 0 new-tab --title "SITL" wsl.exe -d "$WSL_DISTRO" -- bash -lc \
    "cd ~/ardupilot/ArduCopter && sim_vehicle.py --console --map -w --out=udp:127.0.0.1:14540; exec bash" \
    >/dev/null 2>&1

# SITL needs a few seconds to bind the UDP listener before the bridge connects.
say "       waiting 6s for SITL UDP listener"
sleep 6

# --- 3. Bridge in a new WT tab ---

say "[3/4] opening Bridge tab"
wt.exe --window 0 new-tab --title "Bridge" wsl.exe -d "$WSL_DISTRO" -- bash -lc \
    "cd $REPO_WSL && uv run python -m mavlink_mqtt_bridge --config dev/bridge.yaml; exec bash" \
    >/dev/null 2>&1

# --- 4. Observer attached here ---

say "[4/4] attaching MQTT observer (Ctrl-C to detach — stack keeps running)"
say "       filter: drone_hass/$DRONE_ID/#"
echo
exec docker exec -it drone_hass_mosquitto_dev mosquitto_sub -t "drone_hass/$DRONE_ID/#" -v
