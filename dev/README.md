# Local development setup

End-to-end loop for Phase 0: SITL in WSL2 ↔ bridge ↔ Mosquitto (Docker).

## One-time install

1. **ArduPilot SITL** — follow [`sitl-setup.md`](sitl-setup.md) (~45 min first build).
2. **uv** (Python package manager, replaces pip + venv + pyenv):
   ```bash
   # inside WSL Ubuntu
   curl -LsSf https://astral.sh/uv/install.sh | sh
   source $HOME/.local/bin/env
   ```
3. **Python 3.12 + deps** (from repo root, inside WSL):
   ```bash
   cd /mnt/c/Users/aless/dji_hass
   uv sync --extra dev      # creates .venv with Python 3.12 and installs all deps
   ```
   > Running on the Windows filesystem via `/mnt/c/...` is slower than native WSL. For faster iteration, clone the repo into `~/dji_hass` inside WSL.
4. **Docker Desktop** — must be running on Windows with WSL2 integration enabled for the Ubuntu distro.

## Running the dev loop — one shot (recommended)

From any shell on the Windows host:

```bash
cd /c/Users/aless/dji_hass/dev
./start-sitl-stack.sh
```

The script:
1. Starts Mosquitto (Docker container, detached)
2. Opens a new Windows Terminal tab running SITL (`sim_vehicle.py` with `--console --map --out=udp:127.0.0.1:14540`)
3. Opens a new Windows Terminal tab running the bridge (`uv run python -m mavlink_mqtt_bridge --config dev/bridge.yaml`)
4. Attaches an MQTT observer (`mosquitto_sub -t 'drone_hass/sitl1/#' -v`) to the current shell

Pre-flight checks: `wt.exe`, `wsl.exe`, `docker` all in PATH; Docker daemon responding; WSL `Ubuntu` distro present. `dev/bridge.yaml` is seeded from the example on first run.

Ctrl-C the observer to detach (the stack keeps running). To tear everything down:

```bash
./stop-sitl-stack.sh
```

## Running the dev loop — manual (fallback / reference)

Four terminals, in this order:

**Terminal 1 — Mosquitto**
```bash
cd /mnt/c/Users/aless/dji_hass/dev
docker compose up
```

**Terminal 2 — SITL** (in WSL)
```bash
cd ~/ardupilot/ArduCopter
sim_vehicle.py --console --map -w --out=udp:127.0.0.1:14540
```
The `--out=udp:127.0.0.1:14540` fans telemetry out to the MAVSDK listener port.

**Terminal 3 — Bridge** (in WSL, repo root)
```bash
cp dev/bridge.yaml.example dev/bridge.yaml   # first time only
uv run python -m mavlink_mqtt_bridge --config dev/bridge.yaml
```
Expected log lines:
- `mqtt.connected host=localhost port=1883 ...`
- `mavsdk.connecting url=udp://:14540`
- `mavsdk.connected`

**Terminal 4 — MQTT observer** (any host)

Scope the filter — `drone_hass/#` is a firehose (1 Hz telemetry) that buries command traffic. Use two tighter panes instead:

```bash
# Pane A: telemetry + connection state
docker exec drone_hass_mosquitto_dev mosquitto_sub \
  -t 'drone_hass/sitl1/telemetry/#' -t 'drone_hass/sitl1/state/#' -v

# Pane B: commands + responses
docker exec drone_hass_mosquitto_dev mosquitto_sub \
  -t 'drone_hass/sitl1/command/#' -v
```

Expected:
```
drone_hass/sitl1/state/connection online
drone_hass/sitl1/telemetry/flight {"lat":...,"armed":false,...}
drone_hass/sitl1/telemetry/battery {"charge_percent":100,...}
```

For a GUI, **MQTT Explorer** (free, Windows) on `localhost:1883` shows a tree view that collapses the noise.

### Sending commands

```bash
# Takeoff to 15 m (auto-arms if needed)
docker exec drone_hass_mosquitto_dev mosquitto_pub \
  -t drone_hass/sitl1/command/takeoff \
  -m '{"id":"t1","params":{"altitude_m":15}}'

# Return to launch
docker exec drone_hass_mosquitto_dev mosquitto_pub \
  -t drone_hass/sitl1/command/return_to_home -m '{"id":"r1"}'

# Land
docker exec drone_hass_mosquitto_dev mosquitto_pub \
  -t drone_hass/sitl1/command/land -m '{"id":"l1"}'
```

## Running tests

```bash
uv run pytest
```

## Teardown

```
Ctrl-C   # terminals 3, 2
docker compose down
pkill -f arducopter; pkill -f mavproxy   # in WSL
```
