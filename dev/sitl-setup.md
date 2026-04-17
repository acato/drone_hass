# ArduPilot SITL — WSL2 Ubuntu 22.04 setup

This is a one-time install. Target: working **ArduCopter SITL** in WSL2 that the `mavlink_mqtt_bridge` can connect to over UDP.

## Prerequisites

- Windows 11 with WSL2
- Ubuntu 22.04 distro installed (`wsl -l -v` shows it)
- ~5 GB free disk, ~45 min build time

## 1. Enter WSL and update

Run in PowerShell / Windows Terminal:

```
wsl -d Ubuntu
```

Inside Ubuntu:

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y git build-essential ccache g++ gawk genromfs libc6-dev-i386 \
    libtool-bin python3-dev python3-pip python3-venv libxml2-dev libxslt1-dev \
    rsync zip gcc-arm-none-eabi
```

## 2. Clone ArduPilot

```bash
cd ~
git clone --recurse-submodules https://github.com/ArduPilot/ardupilot.git
cd ardupilot
git submodule update --init --recursive
```

## 3. Install ArduPilot Python prereqs

ArduPilot's `install-prereqs-ubuntu.sh` script is flaky on Ubuntu 22.04 — it sometimes exits before the pip section runs, leaving pymavlink/MAVProxy unavailable. It also puts its PATH exports inside `~/.bashrc` **below** the interactive-shell guard, so they never fire under non-interactive shells.

Skip the script and install deps directly:

```bash
# pip packages (empy must be pinned to 3.3.4 — 4.x broke the MAVLink generator)
pip3 install --user pymavlink MAVProxy 'empy==3.3.4' pexpect future dronecan lxml
```

Then append the SITL PATH to `~/.profile` (not `~/.bashrc` — profile fires for both interactive and scripted login shells):

```bash
cat >> ~/.profile <<'EOF'

# ArduPilot SITL PATH
if [ -d "$HOME/ardupilot/Tools/autotest" ] ; then
    PATH="$PATH:$HOME/ardupilot/Tools/autotest"
fi
if [ -d "/usr/lib/ccache" ] ; then
    PATH="/usr/lib/ccache:$PATH"
fi
export PATH
EOF
```

Start a new shell (or `exec bash -l`) and verify:

```bash
which sim_vehicle.py mavproxy.py
python3 -c "import pymavlink, MAVProxy, em; print('empy', em.__version__)"
```

Expected: paths resolve and `empy 3.3.4` prints.

## 4. Build ArduCopter SITL

```bash
cd ~/ardupilot
./waf configure --board sitl
./waf copter
```

First build takes 20–40 min. Output lands in `build/sitl/bin/arducopter`.

## 5. First run — smoke test

```bash
cd ~/ardupilot/ArduCopter
sim_vehicle.py --console --map -w
```

- `--console` shows heartbeat + GPS fix
- `--map` opens a map window (WSLg needed; works on Windows 11 by default)
- `-w` wipes EEPROM on first run to pick up default params

Expected:
- MAVProxy console shows `APM: EKF3 IMU0 is using GPS` within ~30 s
- Vehicle state reaches `Mode GUIDED` after `arm throttle` commands

Leave this running. It exposes MAVLink on **UDP 127.0.0.1:14550** (primary) and **14551** (secondary).

## 6. Expose SITL to Windows host (optional)

WSL2 uses a virtual NIC. SITL binds to all interfaces, so from Windows you can reach it at the WSL instance IP:

```
wsl hostname -I
```

If the bridge runs on the Windows host, point it at `udp://<wsl-ip>:14550`. Easier path: run the bridge **inside** WSL too (matches production add-on environment). That's the recommended dev setup.

## 7. Useful SITL commands (MAVProxy prompt)

```
arm throttle            # arm motors
mode GUIDED             # set guided mode
takeoff 20              # take off to 20 m
mode RTL                # return to launch
param set SIM_SPEEDUP 5 # 5x sim time for faster iteration
```

## Troubleshooting

- **`./waf configure` fails on missing compiler:** `sudo apt install build-essential g++` (the ArduPilot installer should have done this — re-check step 1).
- **MAVProxy map window never opens:** WSLg requires Windows 11 22H2+. If headless, drop `--map`.
- **No GPS fix:** `-w` on first boot; wait 30 s for EKF to converge. `EKF2/3 IMU0 is using GPS` = healthy.
- **Port already bound:** another SITL instance is running. `pkill -f arducopter`.
- **`Failed to download /SRTM3/filelist_python : 'utf-8' codec can't decode byte 0x80`:**
  Cosmetic bug in `MAVProxy/modules/lib/srtm.py`. The terrain module parses the `/SRTM3/`
  HTML directory listing and tries to fetch a pre-baked pickle file `filelist_python` as
  if it were a continent subdirectory. SITL still runs correctly. One-line patch:
  in `~/.local/lib/python3.10/site-packages/MAVProxy/modules/lib/srtm.py`, find the line:
  ```python
  if not continent[0].isalpha() or continent.startswith('README'):
  ```
  and replace with:
  ```python
  if (not continent[0].isalpha() or continent.startswith('README')
      or continent == 'filelist_python'):
  ```
  `pip install --upgrade MAVProxy` will undo the patch; re-apply if needed.

## Teardown

```bash
pkill -f arducopter
pkill -f mavproxy
```

## References

- [ArduPilot SITL setup](https://ardupilot.org/dev/docs/setting-up-sitl-on-linux.html)
- [SITL with MAVProxy](https://ardupilot.org/dev/docs/sitl-with-mavproxy.html)
- [sim_vehicle.py options](https://ardupilot.org/dev/docs/sim-vehicle-command.html)
