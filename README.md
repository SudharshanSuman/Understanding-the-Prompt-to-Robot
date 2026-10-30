# Understanding the Prompt to Robot

### Munder Difflin: Natural-Language Robotic Manipulation (Prompt → Tokens → Task → ROS 2 / Gazebo Arm)

Natural-language control for a simulated robot arm. You type an instruction (*"Pick up the red cube and place it in the storage box"*). A language model—or a deterministic rule-based fallback—parses the instruction into a structured task. A deterministic safety validator verifies object existence and kinematic reachability. An in-process ROS 2 executor plans collision-free trajectories using MoveIt 2 and executes them on a 7-DOF Franka Emika Panda arm inside Gazebo Harmonic. A web console (or Electron desktop application) renders live stage-by-stage pipeline progress, telemetry, and forward-kinematic 3D arm motions.

---

## 1. Safety & Architecture Overview

> [!IMPORTANT]
> **Deterministic Interlock Principle (ADR-001):** Model proposals **never** directly actuate robot joints or command controllers. Language models act solely as high-level task proposal parsers. Every motion trajectory is collision-checked, bounds-verified, and generated through MoveIt 2.

### Pipeline Flow

```
[ User Instruction ]
         │
         ▼
[ 1. Tokenization ] ────► Approximate word-level tokens (inspection only; never drives the arm)
         │
         ▼
[ 2. Interpretation ] ──► Pluggable AI Provider (Cloud / NVIDIA / Ollama / Fallback)
         │
         ▼
[ 3. Structured Task ] ─► Strict Pydantic TaskPlan schema
         │
         ▼
[ 4. Safety Validator ] ─► Deterministic workspace & object registry bounds checking
         │
         ▼
[ 5. MoveIt 2 Planning ]─► OMPL collision-aware trajectory computation
         │
         ▼
[ 6. ros2_control ] ────► Joint trajectory controller & gripper action servers
         │
         ▼
[ 7. Gazebo Harmonic ] ──► Physics simulation & DetachableJoint hybrid grasping
         │
         ▼
[ 8. Verification ] ────► Live spatial sensor & joint tolerance verification
```

### 14 Canonical Pipeline Stages (ADR-009)

Every command flows through 14 inspectable stages surfaced live over WebSocket:
1. `instruction`: Command ingestion, normalization, and sanitization.
2. `tokenization`: Lexical boundary segmentation and token-level categorization.
3. `interpretation`: Semantic intent extraction via configured language provider.
4. `structured_task`: Conversion to strongly typed robotic task action proposal.
5. `schema_validation`: Strict validation against Pydantic action models.
6. `feasibility`: Spatial workspace bounds, reachability, and ambiguity gating.
7. `grounding`: Spatial mapping of target entities to perception coordinate frames.
8. `planning_scene`: MoveIt 2 collision world and geometry state synchronization.
9. `ik`: Numerical inverse kinematics resolution for target end-effector poses.
10. `planning`: Collision-free path planning using OMPL path solvers.
11. `trajectory_validation`: Velocity, acceleration, and joint limit compliance checks.
12. `execution`: Joint trajectory streaming via `ros2_control` hardware interfaces.
13. `simulation`: Gazebo physics propagation and DetachableJoint hybrid grasp attach/detach.
14. `verification`: Final post-execution joint state and object pose read-back verification.

---

## 1b. How It Works (Plain-Language Guide)

The system has two halves. A **Python backend** (`backend/app/`) turns your sentence into a safe, structured task. A **ROS 2 executor** (`ros2_ws/.../ros_executor.py`) turns that task into arm motion. The stages are run in order by `backend/app/pipeline.py`.

### Half 1: Sentence → structured task (`backend/app/`)

| Step | File | What happens |
|---|---|---|
| Instruction | `pipeline.py` | `sanitize_instruction` cleans the text and rejects bad input. |
| Tokenization | `tokenizer.py` | Splits the sentence into words, numbers and punctuation with a regex (`regex_word_level`). It is labelled **approximate**: there are no token IDs. A real BPE tokenizer (`tiktoken`) is optional and not installed by default. Tokens are for display only and never decide an action. |
| Word checks | `validation/validator.py` | Deterministic code runs *before* any model. An unknown object (e.g. "yellow sphere") is rejected. An ambiguous command ("move it over there") returns a clarification question instead of guessing. |
| Interpretation | `providers/chain.py` | Tries each configured provider in order; if one is missing or fails, it moves to the next. The rule-based fallback always runs last. |
| Structured task | `schemas/task.py` | The answer must be a strict `TaskPlan`: `action` (`pick_and_place`), `object`, `destination`, `constraints` (e.g. avoid the blue cube, keep upright) and `confidence`. Anything else is rejected. |
| Schema + scene check | `validation/validator.py` | The plan is re-validated and compared with your request (it must not name an object you never mentioned) and with `config/scene.json`. |
| Feasibility | `validation/validator.py` | Reachability and confidence gate. Often "unknown" at this point; MoveIt's inverse kinematics (IK) gives the real answer later. |

### Which models are used

| Provider | Model (default) | Needs |
|---|---|---|
| Cloud (`providers/http_providers.py`) | `claude-sonnet-5-5` (Anthropic API) | `ANTHROPIC_API_KEY` |
| NVIDIA hosted | `meta/llama-3.1-8b-instruct` (OpenAI-compatible API, temperature 0) | `NVIDIA_API_KEY` |
| Local (Ollama, CPU) | `llama3.2` (JSON mode) | the model pulled with `ollama pull`; or set `MD_LOCAL_MODEL` to a model you already have |
| Deterministic fallback (`providers/fallback.py`) | **No AI model.** Rule-based parser for the action verb, target, destination, "avoid X" and "keep upright" | nothing |

> [!NOTE]
> With no API key and no matching Ollama model, **every prompt is handled by the rule-based fallback**, not an AI model. The interpretation stage in the console shows which provider ran. MoveIt, OMPL (path planner) and IK are classical algorithms, not learned models.

Each model gets a system prompt (`build_system_prompt` in `providers/base.py`) built from the scene's object list, asking for **one JSON object** and no guessing. Your sentence is sent as quoted data (`{"instruction": "..."}`), so text like "ignore your rules" is just data. Invalid replies are retried, then rejected. A model's output is only ever a *proposal*.

### Half 2: Structured task → arm motion (`ros_executor.py`)

Stages 7–14 run inside `RosExecutor` and each is reported only after reading real state:

1. **Grounding:** reads true object poses from Gazebo (labelled `simulation-ground-truth`; there is no camera).
2. **Planning scene:** gives MoveIt the table, storage box and other obstacles.
3. **IK:** solves joint angles for four poses (pre-grasp, grasp, pre-place, place). Any unreachable pose fails the task.
4. **Planning:** MoveIt/OMPL finds a collision-free path to the pre-grasp pose.
5. **Trajectory validation:** joint limits and timing are checked.
6. **Execution (via `ros2_control`):** open gripper → pre-grasp → descend → close gripper → attach (finger friction plus a Gazebo `DetachableJoint`) → lift → move above the box → descend → release → retreat → return home.
7. **Simulation + verification:** confirms the object really moved in Gazebo and landed within 0.09 m (x/y) of the destination.

### Safety rule

Model text never reaches the joints. Only MoveIt-planned, validated trajectories are executed, and e-stop / cancel work at any time.

---

## 2. System Requirements

| Component | Required Version | Purpose |
|---|---|---|
| **Operating System** | Ubuntu 24.04 LTS (Noble Numbat) | Host OS for ROS 2 Jazzy & Gazebo Harmonic |
| **ROS 2** | Jazzy Jalisco (`ros-jazzy-desktop` or base) | Robot middleware & node communication |
| **Simulator** | Gazebo Harmonic (`gz sim` 8.15.0) | Physics simulation and sensor rendering |
| **Motion Planning** | MoveIt 2 (`ros-jazzy-moveit`) | Inverse kinematics & trajectory planning |
| **Python** | Python 3.12+ | Backend runtime, validation, and ROS node |
| **Node.js** | Node.js 20.x + npm | Frontend dashboard and Electron desktop app |
| **Hardware** | x86_64 CPU, 16 GB RAM recommended | ~5 GB available RAM required for simulation |
| **GPU / Driver** | Mesa (CPU) or NVIDIA proprietary | Gazebo rendering (`--software` flag for Mesa fallback) |

### System Package Installation (Human sudo step)

To install the necessary ROS 2, controller, and simulation packages:

```bash
sudo apt update && sudo apt install -y \
  ros-jazzy-moveit \
  ros-jazzy-ros2-control \
  ros-jazzy-ros2-controllers \
  ros-jazzy-controller-manager \
  ros-jazzy-gz-ros2-control \
  ros-jazzy-gz-ros2-control-demos \
  ros-jazzy-moveit-resources-panda-description \
  ros-jazzy-moveit-resources-panda-moveit-config \
  ros-jazzy-joint-state-publisher \
  ros-jazzy-joint-state-publisher-gui \
  ros-jazzy-ur-simulation-gz \
  ros-jazzy-ur-moveit-config
```

---

## 3. Repository Structure

```
munder_difflin/
├── backend/            # FastAPI REST & WebSocket server, validation, provider chain
│   ├── app/            # Application logic (api, schemas, providers, validation)
│   ├── requirements.txt # Production Python dependencies
│   └── requirements.lock# Hash-pinned reproducible lockfile
├── frontend/           # React 19 + TypeScript + Vite + three.js operator console
│   └── src/            # FlowView, ArmView3D, SceneView, socket telemetry
├── desktop/            # Electron wrapper with secure preload IPC bridge
├── ros2_ws/            # ROS 2 workspace
│   └── src/
│       ├── munder_difflin_description/  # Robot URDF/xacro and controller YAML
│       ├── munder_difflin_gazebo/       # Gazebo simulation worlds and models
│       ├── munder_difflin_moveit_config/# MoveIt 2 SRDF and kinematics configs
│       ├── munder_difflin_bringup/      # Launch scripts, smoke tests, and probes
│       └── munder_difflin_control/      # In-process RosExecutor & bridge
├── scripts/            # Launchers: demo.sh, demo_cli.sh, setup_pylib.sh
├── tests/              # Static, unit, API, UI, and ROS integration test suites
└── docs/               # Architecture decisions (ADRs), contracts, and test reports
```

---

## 4. Installation Step-by-Step

### 1. Python Environment Setup

Install dependencies into `backend/.venv`:

```bash
# From the repository root:
python3 -m venv backend/.venv
source backend/.venv/bin/activate

# Standard install:
pip install -r requirements.txt

# Or for development and testing:
pip install -r requirements-dev.txt

# For hash-pinned reproducible installation (CPython 3.12 / Linux x86_64):
pip install --require-hashes --no-deps -r backend/requirements.lock
```

### 2. Frontend Setup

```bash
cd frontend
npm ci
npm run build
cd ..
```

### 3. ROS 2 Workspace Build

```bash
cd ros2_ws
source /opt/ros/jazzy/setup.bash
colcon build --symlink-install
cd ..

# Initialize Python path symlinks for ROS packages
./scripts/setup_pylib.sh
```

### 4. Desktop Setup (Optional)

```bash
cd desktop
npm ci
cd ..
```

---

## 5. How to Run

### Option A: One-Command Visible Demo (Recommended)

Run the full stack (Gazebo GUI + MoveIt 2 + Backend + Web Dashboard) in a single command:

```bash
./scripts/demo.sh
```

**Options:**
- `--software` : Force software rendering (`LIBGL_ALWAYS_SOFTWARE=1`) if your GPU crashes on the Gazebo window.
- `--no-gui`    : Run Gazebo headlessly (server only, saves ~400 MB RAM and CPU overhead).
- `--rviz`      : Open RViz along with Gazebo.
- `--open`      : Automatically open the browser dashboard once ready.

Wait until `[4/4] ready` appears. The script prints a unique API token and outputs:
```
------------------------------------------------------------
 Dashboard : http://127.0.0.1:5173   (backend http://127.0.0.1:8000)
 API token : <GENERATED_TOKEN>
 Stop      : Ctrl+C
------------------------------------------------------------
```
Open `http://127.0.0.1:5173` in your browser and paste the API token to connect.

**Example Prompts to Try:**
- **Standard pick and place:**  
  `"Pick up the red cube and place it in the storage box"`
- **Obstacle avoidance constraint:**  
  `"Move the red cube to the storage box without touching the blue cube"`
- **Unknown entity rejection:**  
  `"Pick up the yellow sphere and put it on the tray"` *(rejected at feasibility stage)*
- **Ambiguous instruction clarification:**  
  `"Move it over there"` *(returns clarification request without robot movement)*

### Option B: CLI Prompt Submission

When `scripts/demo.sh` is already running in another terminal, submit instructions via CLI:

```bash
./scripts/demo_cli.sh "Pick up the red cube and place it in the storage box"
```
The script reads the active session token automatically from `$XDG_RUNTIME_DIR/munder_difflin_demo.token` (typically `/run/user/<uid>/munder_difflin_demo.token`), falling back to `~/.cache/munder_difflin/munder_difflin_demo.token`. It streams pipeline stage progress and exits 0 on completion.

### Option C: Standalone Web Console (No ROS / Honest Fallback Mode)

Run the backend and frontend independently without ROS 2 or Gazebo:

```bash
# Terminal 1: Backend
cd backend
MD_API_TOKEN="$(python3 -c 'import secrets;print(secrets.token_urlsafe(32))')" \
  .venv/bin/python -m app.main

# Terminal 2: Frontend
cd frontend
npm run dev
```
Open `http://127.0.0.1:5173`. When no ROS executor is attached, safety validation completes normally, and subsequent ROS stages honestly report `validated_no_executor` and `cancelled`.

### Option D: Electron Desktop Application

```bash
cd frontend && npm run build
cd ../desktop && npm start
```
*Note for Ubuntu 23.10+ / 24.04:* The Chromium OS sandbox requires an AppArmor profile. See [`desktop/README.md`](desktop/README.md) for setup details.

---

## 6. Testing

### Test Suites Not Requiring ROS / Gazebo

Run these from the repository root with `backend/.venv` active and `PYTHONPATH=backend`:

```bash
source backend/.venv/bin/activate
export PYTHONPATH=backend

# Backend unit & schema validation tests (310 passed, 1 skipped)
pytest tests/unit -c tests/pytest.ini

# Static security and secret scanning (3 passed)
pytest tests/static -c tests/pytest.ini

# API integration tests (exercises live uvicorn subprocess)
pytest tests/api -c tests/pytest.ini

# Frontend unit and component tests (38 passed across 7 test files)
cd frontend && npm test && npm run typecheck && cd ..
```

### Test Suites Requiring ROS 2 / Gazebo Simulation

These suites require sourcing the built ROS 2 workspace and having a free simulation lock:

```bash
# Sourced ROS 2 environment:
source /opt/ros/jazzy/setup.bash
source ros2_ws/install/setup.bash

# ROS 2 workspace unit tests (no simulation required, 10 passed)
colcon test --base-paths ros2_ws/src/munder_difflin_control
colcon test-result --verbose

# ROS 2 simulation acceptance tests (requires Gazebo & MoveIt 2 running)
pytest tests/ros -c tests/pytest.ini

# Simulation headless smoke test (~58s wall time)
bash ros2_ws/src/munder_difflin_bringup/scripts/smoke_test.sh --moveit
```

---

## 7. Configuration & Providers

The system dynamically switches providers via `backend/app/providers/chain.py`:

```
Configured Provider (Cloud / NVIDIA / Ollama) ──(on failure)──► Deterministic Fallback
```

Configure providers by setting environment variables in your shell (or `.env`):

| Variable | Description | Default |
|---|---|---|
| `MD_API_TOKEN` | Secret bearer token (minimum 32 characters) | *Required for startup* |
| `MD_BIND_HOST` | Network interface host binding | `127.0.0.1` |
| `APP_PORT` | REST / WebSocket port | `8000` |
| `ANTHROPIC_API_KEY` | Anthropic Messages API key | None (Cloud provider skipped) |
| `MD_CLOUD_MODEL` | Claude model name | `claude-sonnet-5-5` |
| `NVIDIA_API_KEY` | NVIDIA API Catalog key | None (NVIDIA provider skipped) |
| `NVIDIA_BASE_URL` | NVIDIA OpenAI-compatible endpoint | `https://integrate.api.nvidia.com/v1` |
| `NVIDIA_MODEL` | NVIDIA hosted model identifier | `meta/llama-3.1-8b-instruct` |
| `OLLAMA_HOST` | Local Ollama daemon HTTP endpoint | `http://localhost:11434` |
| `MD_LOCAL_MODEL` | Local Ollama model tag | `llama3.2` |

If no external API keys are configured and Ollama is unreachable, the **Deterministic Fallback Provider** handles supported lexical instructions locally without network dependencies.

---

## 8. Security Architecture

1. **Loopback Binding by Default (SEC-008):** The backend binds strictly to `127.0.0.1`. Remote binding (`0.0.0.0`) is refused unless `MD_ALLOW_REMOTE=true` is explicitly passed.
2. **Mandatory Bearer Authentication (SEC-004):** All REST and WebSocket routes enforce `Authorization: Bearer <token>`.
3. **Localhost DDS Isolation (SEC-011):** FastDDS is restricted to this machine via `ROS_LOCALHOST_ONLY=1` and `ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST` to prevent network robot control.
4. **Secret Hygiene:** Pre-commit hooks (`.githooks/pre-commit`) and automated tests (`test_no_secrets.py`) prevent accidental check-in of API keys or private tokens.

---

## 9. Troubleshooting Top 5

1. **First-Move Path Tolerance Abort on Fresh Simulation:**  
   *Symptom:* On a fresh simulator start, the first task failed in 11 of 12 runs without a reset due to joint trajectory controller path tolerance violation (`GOAL_TOLERANCE_VIOLATED` or `goal_time_tolerance exceeded`).  
   *Mitigation:* `RosExecutor` now automatically performs a reset once before the first task (resulting in 2 of 2 passes in later runs; root cause under active investigation by Andy). If the first command fails on a newly launched sim, simply retry the command.
2. **Simulation Lock Held (`hive/sim.lock`):**  
   *Symptom:* `sim_lock.sh` exits with `sim.lock is held`.  
   *Fix:* To protect host memory and ROS domain ports, only one Gazebo simulation can run at a time. Wait for the active process to finish, or verify no orphan `gz sim` processes remain using `ps aux | grep "gz sim"`.
3. **Electron Sandbox Crash on Ubuntu 24.04:**  
   *Symptom:* Electron terminates immediately with `The SUID sandbox helper binary was not found`.  
   *Fix:* Load the unprivileged user namespace AppArmor profile as described in [`desktop/README.md`](desktop/README.md).
4. **Gazebo GUI Window Crash on Hybrid Graphics / Nouveau:**  
   *Symptom:* Gazebo segmentation faults on launch with OpenGL/Mesa errors.  
   *Fix:* Run `./scripts/demo.sh --software` to force software OpenGL rendering (`LIBGL_ALWAYS_SOFTWARE=1`).
5. **Connection Refused / Unauthorized 401:**  
   *Symptom:* Dashboard shows "Connection refused" or requests fail with HTTP 401.  
   *Fix:* Ensure `MD_API_TOKEN` matches between backend and frontend. In demo mode, copy the token output in `[4/4] ready` or read `$XDG_RUNTIME_DIR/munder_difflin_demo.token` (fallback: `~/.cache/munder_difflin/munder_difflin_demo.token`).

---

## 10. Honest Status & Verification Notes

> [!NOTE]
> **State as of October 28, 2026:**
> - **Backend Core:** Verified. Unit and static tests pass (310 passed, 1 skipped).
> - **Frontend Console:** Verified. FlowView and ArmView3D components pass test suites (38 passed across 7 test files in `vitest`).
> - **Simulation Smoke Test:** Verified. `smoke_test.sh --moveit` completes in ~58 seconds wall time with clean shutdown.
> - **Live Multi-Run Acceptance Suite:** Under active verification by QA (Angela). Not yet signed off as an official production release.

### Verification Reports (Evidence)
For detailed test runs, outputs, and observed evidence, see:
- [`docs/project/TEST_REPORT_ros_m1.md`](docs/project/TEST_REPORT_ros_m1.md): ROS M1 milestone simulation and MoveIt verification.
- [`docs/project/TEST_REPORT_viz.md`](docs/project/TEST_REPORT_viz.md): Frontend FlowView, scene view, and replay verification.
- [`docs/project/DEFECTS_ROS_002.md`](docs/project/DEFECTS_ROS_002.md): Live integration defect log and tracking.
