# Understanding the Prompt to Robot

### Munder Difflin: Natural-Language Robotic Manipulation (Prompt → Tokens → Task → ROS 2 / Gazebo Arm)

Natural-language control for a simulated robot arm. You type an instruction ("Put the red cube in
the storage box"). A language model, or a deterministic fallback, turns it into a structured task.
A safety validator checks the task, and a ROS 2 executor plans and runs it in Gazebo with
MoveIt 2. A web console (or the same console in an Electron window) shows every stage live with
animated flow visualization and 3D kinematics.

## Honest status (2026-10-28)

> [!NOTE]
> This codebase is under active integration and verification. It is **not** an official production release; QA live verification (Angela) remains open.

| Part | State |
|---|---|
| Backend (`backend/`, FastAPI) | Runs. Bearer-token auth, rate limits, redacted logs and responses, REST + WebSocket, telemetry stream `/ws/telemetry`, and `/health` reporting. |
| Pipeline: input → tokenization → interpretation → clarification → validation → feasibility | Runs. Model provider used if API keys configured; otherwise deterministic rule-based fallback operates. |
| ROS 2 stack (`ros2_ws/`) | Gazebo Harmonic + MoveIt 2 + Franka Panda arm (`moveit_resources_panda_*`). Controllers, hybrid grasp (physical fingers + DetachableJoint), and in-process `RosExecutor`. |
| Simulation Smoke Test | `smoke_test.sh --moveit` passes in headless mode (~58s wall time). |
| Full Demo Scripts | `scripts/demo.sh` (visible Gazebo GUI or `--no-gui`, backend, and web dashboard) and `scripts/demo_cli.sh`. |
| Frontend (`frontend/`, React + Vite) | Runs in browser. Live telemetry, interactive FlowView animation, forward kinematics ArmView3D, and scene schematic. Typecheck, unit tests, and build pass. |
| Desktop (`desktop/`, Electron) | Runs the same frontend build in an Electron shell. |
| Verification & Release Status | **In progress / Not released.** Headless unit and static suites pass; live multi-run sim acceptance suite (Angela) is active. |

"Runs" above means it was started and exercised on the dev machine (Ubuntu 24.04, Python 3.12.3,
Node 20.20.2), with the test suites listed in `docs/installation.md`.

## Quick start

Setup steps are in [docs/installation.md](docs/installation.md). Once installed:

```bash
# Browser mode: two terminals
cd backend  && MD_API_TOKEN="$(python3 -c 'import secrets;print(secrets.token_urlsafe(32))')" .venv/bin/python -m app.main
cd frontend && npm run dev        # open http://127.0.0.1:5173 and paste the same token
```

Generate the token in your own shell and paste it into the page; never commit it. The backend
binds `127.0.0.1:8000` and refuses to start without a token of at least 32 characters.

```bash
# Desktop mode: Electron starts the backend with a fresh token and connects by itself
cd frontend && npm run build
cd desktop  && npm start
```

## Docs

- [docs/installation.md](docs/installation.md): venv, npm, ROS 2 packages, the human-run sudo steps
- [docs/troubleshooting.md](docs/troubleshooting.md): known problems and their fixes
- [docs/model_configuration.md](docs/model_configuration.md): language model providers and keys (Oscar)
- [docs/architecture.md](docs/architecture.md), [docs/DECISIONS.md](docs/DECISIONS.md), [docs/INTERFACE_CONTRACTS.md](docs/INTERFACE_CONTRACTS.md)
- `frontend/README.md`, `desktop/README.md`: per-app details
