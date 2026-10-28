# Installation

Target: Ubuntu 24.04, Python 3.12, Node 20, ROS 2 Jazzy. Steps marked **HUMAN (sudo)** change the
system. Agents never run them; the person who owns the machine does. Everything else installs into
the repo (a Python venv, local `node_modules`) and needs no sudo.

The system package state below comes from Stanley's read-only audit (`docs/environment_report.md`,
2026-10-28T00:17Z). Re-run `bash --noprofile --norc scripts/audit_env.sh` to check your machine.

## 1. Backend (Python venv, no sudo)

```bash
cd backend
python3 -m venv .venv
.venv/bin/pip install --require-hashes --no-deps -r requirements.lock        # runtime only
# or, for development and tests:
.venv/bin/pip install --require-hashes --no-deps -r requirements-dev.lock
```

The lock commands come from the lock files' headers (Stanley). A fresh install from them was not
run for this doc; the existing `backend/.venv` was used for the test runs below. The lock files are hash-pinned for linux x86_64 / CPython 3.12; other platforms must regenerate
them. `requirements.txt` / `requirements-dev.txt` list the direct dependencies. Settings are read
from the environment; their names (no values) are in `backend/.env.example`.

Check: `.venv/bin/python -m pytest` (from `backend/`). Last run: 272 passed, 1 skipped.

## 2. Frontend (npm, no sudo, no global installs)

```bash
cd frontend
npm ci              # exact versions from package-lock.json
npm run typecheck && npm test && npm run build
```

Last run: typecheck OK, 13/13 tests, build OK (no source maps, CSP injected).

## 3. Desktop (Electron, optional)

```bash
cd desktop
npm ci              # downloads the pinned Electron binary (44.9.3)
npm test            # 7/7
```

npm prints `EBADENGINE` warnings: Electron's installer packages ask for Node >= 22.12. With Node
20.20.2 the install and download still worked. The app itself runs on Electron's own Node.

**HUMAN (sudo), Ubuntu 23.10+ only:** the Chromium sandbox needs the AppArmor profile from
`desktop/README.md` ("Linux sandbox setup"). Without it Electron aborts at start (see
troubleshooting). The app refuses `--no-sandbox` on purpose.

## 4. ROS 2 stack (for the executor and simulation)

Already present (audit): ROS 2 Jazzy desktop 0.11.0, Gazebo Harmonic 8.15.0 (`gz sim`), `ros_gz`
1.0.24, colcon, rosdep. Missing, with Jazzy apt candidates: MoveIt 2, ros2_control, the
controllers, `gz_ros2_control`, and the Panda and UR5e descriptions.

**HUMAN (sudo)**, from `docs/environment_report.md` §4:

```bash
# A. Required for simulation + planning
sudo apt update
sudo apt install -y \
  ros-jazzy-moveit ros-jazzy-ros2-control ros-jazzy-ros2-controllers \
  ros-jazzy-gz-ros2-control \
  ros-jazzy-moveit-resources-panda-description ros-jazzy-moveit-resources-panda-moveit-config \
  ros-jazzy-ur-description ros-jazzy-ur-simulation-gz \
  ros-jazzy-joint-state-publisher-gui

# B. Optional
sudo apt install -y gh                                                        # PR workflow
sudo apt install -y ros-jazzy-rosbridge-server ros-jazzy-rmw-cyclonedds-cpp ros-jazzy-moveit-visual-tools
```

The audit notes the disk is 83% full. MoveIt plus the arm packages are estimated (not measured)
at 1–2 GB.

The executor package lives in `ros2_ws/` (Andy). Build and launch steps will be in
`docs/ros2_interfaces.md` when it lands; they are not documented here because they have not been
run.

## 5. NVIDIA driver (optional, HUMAN, sudo + reboot)

The RTX 3050 runs on `nouveau` with no NVIDIA driver and no CUDA. The backend and frontend do not
need a GPU. Gazebo renders with Mesa. If GPU rendering or local CUDA inference is wanted:

```bash
sudo apt install -y nvidia-driver-595-open && sudo reboot   # ubuntu-drivers' recommendation (audit)
```

This changes the graphics stack on a hybrid laptop. Do it on purpose, not as part of setup.

## 6. Run

See the quick start in `../README.md`, `frontend/README.md` (browser mode) and `desktop/README.md`
(desktop mode). Model provider keys: `docs/model_configuration.md`.

### With the ROS 2 executor (real sim)

The backend runs tasks through `RosExecutor` (Andy's `munder_difflin_control`, see `docs/ros2_interfaces.md` s7) when a
launcher passes it to `app.main.main(executor)`. That entry keeps the startup checks: it binds `MD_BIND_HOST`/`APP_PORT`
and refuses a weak `MD_API_TOKEN`. Start the sim and `move_group` first (`ros2 launch munder_difflin_bringup moveit.launch.py`), then:

```bash
source /opt/ros/jazzy/setup.bash && source ros2_ws/install/setup.bash
export ROS_DOMAIN_ID=42 ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST ROS_LOCALHOST_ONLY=1  # localhost-only DDS (SEC-011)
cd backend && PYTHONPATH="$PWD:$PWD/../ros2_ws/pylib" .venv/bin/python -c \
  'from app.main import main; from munder_difflin_control.ros_executor import RosExecutor; main(RosExecutor())'
```
Use `ros2_ws/pylib`, not `/usr/lib/python3/dist-packages` (its `typing_extensions` breaks pydantic).
`/api/v1/telemetry` and `/ws/telemetry` show live data only when the executor implements `telemetry()`; otherwise they say
"ros unavailable".
