# Dependency Matrix — Munder Difflin (SKELETON)

_Owner: Stanley (REL) · Status: skeleton, v0 · Source of "installed" column: `docs/environment_report.md` (audit of 2026-10-28). Pin columns marked TBD are decisions for the owning agent, not facts._

Legend — **Installed** = seen by `scripts/audit_env.sh`. **Pin** = version the project commits to (TBD until the owner decides). **Source** = how it gets onto a machine. **Owner** = agent/role that decides the pin.

## 1. System / robotics layer

| Component | Role | Installed (2026-10-28) | Pin | Source | Owner |
|---|---|---|---|---|---|
| Ubuntu 24.04 (noble) | Host OS | 24.04.5 | 24.04 LTS | OS | REL |
| ROS 2 Jazzy | Middleware | desktop 0.11.0 | jazzy | apt (packages.ros.org) | Architect |
| Gazebo Harmonic (`gz sim`) | Simulator | 8.15.0 | Harmonic (8.x) | apt (ROS vendor pkgs) | Architect |
| `ros_gz_*` | ROS↔Gazebo bridge | 1.0.24 | TBD | apt | Architect |
| `gz_ros2_control` | Sim hardware interface | missing (cand. 1.2.20) | TBD | apt | Robotics |
| `ros2_control` / `controller_manager` | Control framework | missing (cand. 4.48.1) | TBD | apt | Robotics |
| `ros2_controllers` | Joint/gripper controllers | missing (cand. 4.42.1) | TBD | apt | Robotics |
| MoveIt 2 | Motion planning | missing (cand. 2.12.4) | TBD | apt | Robotics |
| Panda description + MoveIt config (`moveit_resources_panda_*`) | Primary arm (ADR-006) | missing (cand. 3.1.0) | TBD | apt | Robotics |
| UR5e (`ur_description`, `ur_simulation_gz`) | Fallback arm (ADR-006) | missing (cand. 3.5.1 / 2.5.0) | TBD | apt | Robotics |
| `colcon`, `rosdep` | Build / deps | 0.3.0-100 / 0.27.0 | — | apt | REL |
| NVIDIA driver | GPU compute/render | missing (rec. `nvidia-driver-595-open`) | TBD | apt, human-approved | REL |

## 2. Backend

| Component | Role | Installed | Pin | Source | Owner |
|---|---|---|---|---|---|
| Python | Runtime | 3.12.3 | 3.12 | apt | Backend |
| venv + pip | Isolation (ADR-005) | present | — | apt | Backend |
| FastAPI, Uvicorn, websockets, Pydantic | API / WS / schema validation | missing | TBD (lockfile) | pip in venv | Backend |
| pytest | Tests | not checked | TBD | pip in venv | QA |
| AI provider SDK(s) | LLM planner | not checked | TBD | pip in venv | AI |

## 3. Frontend / desktop shell

| Component | Role | Installed | Pin | Source | Owner |
|---|---|---|---|---|---|
| Node.js | Runtime | v20.20.2 | TBD (`.nvmrc`) | apt | Frontend |
| npm | Package manager | 10.8.2 | TBD | bundled | Frontend |
| React + TypeScript + Vite | UI | per-project | TBD (`package-lock.json` committed — SEC-014) | npm | Frontend |
| Electron **or** Tauri | Desktop packaging (open decision) | none | TBD | npm / cargo | Architect |
| Rust toolchain (Tauri only) | Tauri build | missing (apt has 1.75.0) | TBD | checksum-verified download (SEC-008) | REL |
| WebKitGTK + friends (Tauri only) | Tauri build libs | 5 of 9 missing | distro | apt | REL |

## 4. Tooling

| Component | Role | Installed | Pin | Source | Owner |
|---|---|---|---|---|---|
| git | VCS | 2.43.0 | — | apt | REL |
| gh | PRs from CLI | missing (cand. 2.45.0) | — | apt | REL |
| cmake / gcc / make / ninja | Native builds | 3.28.3 / 13.3.0 / 4.3 / 1.11.1 | — | apt | REL |
| Docker + Compose | Containers | 29.9.2 / v5.1.2 | TBD | existing install | REL |
| ffmpeg | Media/recording | 6.1.1 | — | apt | — |

## 5. Rules (draft)

1. Every dependency enters with a pinned version and a lockfile (`package-lock.json`, `requirements.lock`/`uv.lock`, `rosdep` keys) before release.
2. System packages are installed only by the human via the commands in `docs/environment_report.md` §4; agents do not run `sudo`.
3. No `curl | bash` installers; downloads need a published checksum (SEC-008).
4. Re-run `scripts/audit_env.sh` after any install and refresh the "Installed" column.
5. License review per dependency: TBD (Legal/QA).
