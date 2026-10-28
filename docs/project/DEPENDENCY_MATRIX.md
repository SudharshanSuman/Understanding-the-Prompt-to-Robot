# Dependency Matrix — Munder Difflin

_Owner: Stanley (REL) · Status: v1, refreshed after the human's apt install (MD-REL-002) · Source of "Installed": `scripts/audit_env.sh` run of 2026-10-28T02:40:46Z (`docs/environment_report.md`), plus `backend/.venv` and the `package.json` files for per-project items. Pin columns marked TBD are decisions for the owning agent, not facts._

Legend — **Installed** = seen on this machine. **Pin** = version the project commits to (TBD until the owner decides). **Source** = how it gets onto a machine. **Owner** = agent/role that decides the pin.

## 1. System / robotics layer (apt, system-wide — installed by the human, not by agents)

| Component | Role | Installed (2026-10-28) | Pin | Source | Owner |
|---|---|---|---|---|---|
| Ubuntu 24.04 (noble) | Host OS | 24.04.5 | 24.04 LTS | OS | REL |
| ROS 2 Jazzy | Middleware | `ros-jazzy-desktop` 0.11.0 | jazzy | apt (packages.ros.org) | Architect |
| Gazebo Harmonic (`gz sim`) | Simulator | 8.15.0 | Harmonic (8.x) | apt (ROS vendor pkgs) | Architect |
| `ros_gz_sim`, `_bridge`, `_interfaces`, `_image` | ROS↔Gazebo bridge | 1.0.24 | = installed version (apt, Jazzy; hold with `apt-mark hold` if drift is a concern) | apt | Architect |
| `gz_ros2_control` | Sim hardware interface | 1.2.20 | = installed version (apt, Jazzy; hold with `apt-mark hold` if drift is a concern) | apt | Robotics |
| `ros2_control`, `controller_manager`, `hardware_interface` | Control framework | 4.48.1 | = installed version (apt, Jazzy; hold with `apt-mark hold` if drift is a concern) | apt | Robotics |
| `ros2_controllers` (+ `joint_state_broadcaster`, `joint_trajectory_controller`, position/velocity/effort/gripper/forward_command/diff_drive) | Joint and gripper controllers | 4.42.1 | = installed version (apt, Jazzy; hold with `apt-mark hold` if drift is a concern) | apt | Robotics |
| MoveIt 2 (`ros-jazzy-moveit`, `moveit_servo`, `moveit_setup_assistant`, OMPL planners, kinematics) | Motion planning | 2.12.4 | = installed version (apt, Jazzy; hold with `apt-mark hold` if drift is a concern) | apt | Robotics |
| `moveit_resources_panda_description` + `_moveit_config` | Primary arm (ADR-006) | 3.1.0 | = installed version (apt, Jazzy; hold with `apt-mark hold` if drift is a concern) | apt | Robotics |
| `ur_description` / `ur_simulation_gz` / `ur_moveit_config` / `ur_controllers` | Fallback arm UR5e (ADR-006) | 3.5.1 / 2.5.0 / installed / installed | = installed version (apt, Jazzy; hold with `apt-mark hold` if drift is a concern) | apt | Robotics |
| `franka_ros2` | Franka-specific controllers and Gazebo support | not present in `ros2_ws/src` at 2026-10-28 (earlier checkout was v3.6.1) | tag v3.6.1 | git via `ros2_ws/munder_difflin.repos` + `vcs import` (decided; Andy writes the file; no submodules) | Robotics / Andy |
| `franka_description` | Franka URDF/meshes | not present in `ros2_ws/src` at 2026-10-28 (earlier checkout was 2.9.0) | tag 2.9.0 | git via `ros2_ws/munder_difflin.repos` (pinned) | Robotics / Andy |
| `joint_state_publisher_gui` | Dev convenience | 2.4.3 | — | apt | Robotics |
| `rviz2`, `xacro`, `robot_state_publisher`, `tf2_ros` | Visualisation / URDF | 14.1.24 / 2.1.1 / 3.3.4 / 0.36.23 | — | apt (part of desktop) | Robotics |
| `colcon`, `rosdep` | Build / deps | 0.3.0-100 / 0.27.0 | — | apt | REL |
| `rosbridge_server` | ROS↔web bridge | **not installed** (cand. 2.7.1) | **not used** — decided: rclpy in-process via the Executor, no rosbridge | — | Architect |
| `rmw_cyclonedds_cpp`, `moveit_visual_tools` | Optional | not installed (cand. 2.2.4 / 4.2.0) | not planned | apt | Robotics |
| NVIDIA driver | GPU compute/render | **not installed** — human decided to skip; local GPU inference is out of scope | n/a | — | REL |

## 2. Backend (pip, inside `backend/.venv` — never system-wide, ADR-005)

| Component | Role | Installed (`backend/.venv`) | Pin | Source | Owner |
|---|---|---|---|---|---|
| Python | Runtime | 3.12.3 | 3.12 | apt | Backend |
| FastAPI | API | 0.162.0 | `backend/requirements.lock` (hash-pinned) | pip in venv | Backend |
| Starlette | ASGI toolkit (FastAPI dependency) | 1.10.0 | lockfile | pip | Backend |
| Uvicorn | ASGI server | 0.54.0 | lockfile | pip | Backend |
| websockets | WebSocket | 17.2 | lockfile | pip | Backend |
| Pydantic / pydantic-core | Schema validation | 2.14.1 / 2.50.1 | lockfile | pip | Backend |
| pytest | Tests | 9.1.1 | `backend/requirements-dev.lock` | pip | QA |
| httpx | Test client / outbound HTTP | 0.28.1 | lockfile | pip | Backend |
| AI provider SDK(s) | LLM planner | not checked | TBD | pip | AI |

Lockfiles: 18 packages (runtime) / 23 (dev), sha256-pinned, linux x86_64 / CPython 3.12 only. Install: `pip install --require-hashes -r backend/requirements-dev.lock`. Regenerate on any `requirements*.txt` change.

## 3. Frontend / desktop shell (npm, per project)

| Component | Role | Version (from `package.json`) | Pin | Source | Owner |
|---|---|---|---|---|---|
| Node.js | Runtime | v20.20.2 (installed) | TBD — no `.nvmrc` yet | apt | Frontend |
| npm | Package manager | 10.8.2 (installed) | TBD | bundled | Frontend |
| React / React DOM | UI | 19.3.1 | exact in `frontend/package-lock.json` (SEC-014) | npm | Frontend |
| TypeScript, Vite, Vitest, Testing Library, jsdom | Build and test | 5.9.3 / 7.3.7 / 4.1.12 / 16.3.3 (+ dom 10.4.2) / 27.4.0 | exact in lockfile | npm | Frontend |
| Electron | Desktop shell (**decided**, SEC-015 applies) | 44.9.3 (`desktop/package.json`; `desktop/package-lock.json`) | exact | npm | Desktop |
| Tauri, Rust toolchain, WebKitGTK dev libs | — | **dropped** (Electron chosen) | n/a | n/a | n/a |

`npm audit` not executed yet (see RELEASE_CHECKLIST §4).

## 4. Tooling

| Component | Role | Installed | Pin | Source | Owner |
|---|---|---|---|---|---|
| git | VCS | 2.43.0 | — | apt | REL |
| gh | PRs from CLI | **missing** (cand. 2.45.0); option B, not requested yet | — | apt, human | REL |
| cmake / gcc / make / ninja | Native builds | 3.28.3 / 13.3.0 / 4.3 / 1.11.1 | — | apt | REL |
| Docker + Compose | Containers | 29.9.2 / v5.1.2 | TBD | existing install | REL |
| ffmpeg | Media/recording | 6.1.1 | — | apt | — |
| shellcheck | Shell lint | **missing** — SEC-008 check not executed | — | apt, human | REL |

## 5. Rules

1. Every dependency enters with a pinned version and a lockfile (`package-lock.json`, hash-pinned `requirements*.lock`, `rosdep` keys / `.repos` tags) before release.
2. System packages are installed only by the human via the commands in `docs/environment_report.md` §4; agents do not run `sudo`.
3. No `curl | bash` installers; downloads need a published checksum (SEC-008).
4. Re-run `scripts/audit_env.sh` after any install and refresh the "Installed" column.
5. Third-party source checkouts (Franka) are pinned by tag in a committed manifest, not committed as nested git repositories.
6. License review per dependency: TBD (Legal/QA).
