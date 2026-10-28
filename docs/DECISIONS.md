# Munder Difflin: Architecture Decision Records (ADRs)
**Status:** Living Document  
**Author:** Jim - Architect (A) (`jim-architect-a--mvr0ee0w`)  
**Project Root:** `/home/sudharshan/Documents/Robotic Operation with Prompt Engineering/munder_difflin`  
**Related Documents:** [architecture.md](file:///home/sudharshan/Documents/Robotic%20Operation%20with%20Prompt%20Engineering/munder_difflin/docs/architecture.md), [INTERFACE_CONTRACTS.md](file:///home/sudharshan/Documents/Robotic%20Operation%20with%20Prompt%20Engineering/munder_difflin/docs/INTERFACE_CONTRACTS.md)

---

## Index of Decisions

- [ADR-001: Deterministic Safety Interlock Between AI Models and Robot Control](#adr-001-deterministic-safety-interlock-between-ai-models-and-robot-control)
- [ADR-002: Pluggable LanguageModelProvider Strategy Based on Host Hardware Audit](#adr-002-pluggable-languagemodelprovider-strategy-based-on-host-hardware-audit)
- [ADR-003: Dual-Mode Perception Architecture (Ground-Truth vs Vision RGB-D)](#adr-003-dual-mode-perception-architecture-ground-truth-vs-vision-rgb-d)
- [ADR-004: 7-State Pipeline Lifecycle & WebSocket Event Streaming](#adr-004-7-state-pipeline-lifecycle--websocket-event-streaming)
- [ADR-005: Decoupled Backend Core for Headless Non-ROS Unit Testing](#adr-005-decoupled-backend-core-for-headless-non-ros-unit-testing)
- [ADR-006: Primary Robotic Arm Selection (Franka Panda with UR5e Fallback)](#adr-006-primary-robotic-arm-selection-franka-panda-with-ur5e-fallback)
- [ADR-007: Gazebo Harmonic Hybrid Grasping Architecture](#adr-007-gazebo-harmonic-hybrid-grasping-architecture)
- [ADR-008: Authentic Tokenization Visualization Without Fabricated Token IDs](#adr-008-authentic-tokenization-visualization-without-fabricated-token-ids)
- [ADR-009: Canonical 14-Stage Execution Pipeline Specification](#adr-009-canonical-14-stage-execution-pipeline-specification)
- [ADR-010: Isaac Sim Evaluation and Cloud-Only Extension Boundary](#adr-010-isaac-sim-evaluation-and-cloud-only-extension-boundary)
- [ADR-011: Pre-Interpretation Ambiguity Gating and Headless Terminal Stage Invariant](#adr-011-pre-interpretation-ambiguity-gating-and-headless-terminal-stage-invariant)
- [ADR-012: Panda Model Specification via apt moveit_resources_panda (Supersedes franka_ros2 part of ADR-006)](#adr-012-panda-model-specification-via-apt-moveit_resources_panda-supersedes-franka_ros2-part-of-adr-006)
- [ADR-013: Formal In-Process RosExecutor Architecture (Supersedes Custom ROS Action Stack)](#adr-013-formal-in-process-rosexecutor-architecture-supersedes-custom-ros-action-stack)

---

## ADR-001: Deterministic Safety Interlock Between AI Models and Robot Control

### Context
Natural language models (LLMs) are probabilistic and prone to hallucination, formatting variations, out-of-distribution coordinates, or physically impossible joint commands. Direct control of physical or simulated robotic actuators by an LLM poses unacceptable safety hazards.

### Decision
Establish an inviolable boundary: **Raw LLM output shall never command robot controllers or hardware directly.**
1. The LLM acts solely as a task proposal parser.
2. Every LLM output must be parsed into a strict Pydantic `RoboticTask` / `TaskPlan` schema.
3. The parsed task must pass a deterministic safety validator verifying:
   - Object existence in perception registry.
   - Target coordinate reachability within defined workspace bounding box ($X, Y \in [-0.8, 0.8]\text{ m}, Z \in [0.0, 1.2]\text{ m}$).
   - Clear reference frames (rejecting underspecified relative directions like "move left" without a reference anchor).
4. Physical motion is generated exclusively by MoveIt 2 through collision-checked trajectory planning.

### Consequences
- **Positive:** Guarantees robotic safety; eliminates hallucinations causing erratic motion; ensures reproducible testing; passes SEC-012 quality gate.
- **Negative:** Adds validation latency (~5-20ms), which is negligible compared to motion execution times.

---

## ADR-002: Pluggable LanguageModelProvider Strategy Based on Host Hardware Audit

### Context
Oscar (R)'s verified host hardware audit (`docs/research/ai_options.md`) revealed:
- GPU: NVIDIA GeForce RTX 3050 Mobile with **4 GB GDDR6 VRAM**.
- Kernel Driver: Open-source `nouveau` driver is active; official proprietary NVIDIA driver and CUDA userspace (`nvidia-smi`, `libcuda.so`) are absent.
- System RAM: 14.0 GiB total, with only ~4.9 GiB available and 1.7 GiB swap active.

Local LLMs (even quantized 7B/8B models like Llama 3) require 5.5 to 8+ GB VRAM or heavy CPU offloading that would saturate the remaining 4.9 GiB RAM and cripple Gazebo Harmonic physics simulation.

### Decision
1. **Primary AI Modes:**
   - **Mode A (Cloud APIs):** OpenAI, Anthropic, or Gemini via secure environment variables (`OPENAI_API_KEY`, etc.). Zero secrets in frontend or code repository.
   - **Mode C (NVIDIA-Hosted Model APIs):** Remote NVIDIA NIM endpoints (e.g. Nemotron models hosted on build.nvidia.com) accessed via standard OpenAI-compatible REST interface without requiring local GPU CUDA hardware.
2. **Deterministic Baseline:**
   - **DeterministicFallbackProvider:** Rule-based parser handling standard demonstration and test commands (`pick_and_place`, `avoid_objects`, `keep_upright`) with zero API keys or network dependencies, enabling offline regression testing.
3. **Local GPU Inference Status:** Marked as **unsupported on current host hardware**. If local inference is requested, it must default to CPU-quantized small models (e.g. SmolLM-135M or Qwen2.5-0.5B via Ollama) with explicit resource warnings, or defer to Cloud/NVIDIA NIM.

### Consequences
- **Positive:** Prevents out-of-memory kernel panics; keeps Gazebo simulation smooth; ensures CI tests pass reliably with zero API keys.
- **Negative:** Offline demonstration with unscripted natural language requires a remote internet connection for Cloud/NIM.

---

## ADR-003: Dual-Mode Perception Architecture (Ground-Truth vs Vision RGB-D)

### Context
Developing robotic motion planning alongside computer vision introduces tight coupling: camera noise or lighting changes can obscure kinematic planning bugs. However, relying purely on hardcoded coordinates prevents real-world perception integration.

### Decision
Create a unified ROS 2 interface (`munder_difflin_msgs/msg/DetectedObjectArray`) supported by two swappable nodes:
1. `simulation_ground_truth`: Extracts exact model poses directly from Gazebo Harmonic physics world. Explicitly labeled in the UI as ground-truth.
2. `rgbd_vision`: Subscribes to simulated RGB-D camera pointclouds and image topics, executes 3D segmentation and centroid estimation, and broadcasts `tf2` transforms.

### Consequences
- **Positive:** Enables motion planning and UI engineers to develop against verified ground-truth while perception engineers develop the vision pipeline in parallel.
- **Negative:** Requires maintaining two perception adapters that adhere to the identical ROS 2 message contract.

---

## ADR-004: 7-State Pipeline Lifecycle & WebSocket Event Streaming

### Context
A robotic manipulation pipeline contains multiple asynchronous stages. A binary "success/failure" status leaves users unaware of where and why an operation paused or failed.

### Decision
Standardize all pipeline stages onto a strict 7-state lifecycle:
`waiting` | `running` | `success` | `warning` | `failed` | `cancelled` | `needs_clarification`.
Stream structured `PipelineStageEvent` objects over a persistent WebSocket (`/ws/pipeline`) to the React dashboard.

### Consequences
- **Positive:** Enables step-by-step visual feedback in the UI; provides clear distinction between execution errors, planning failures, and clarification requests.
- **Negative:** Requires every ROS 2 action and backend stage to emit event transitions cleanly.

---

## ADR-005: Decoupled Backend Core for Headless Non-ROS Unit Testing

### Context
ROS 2 packages and Gazebo simulations require complex system dependencies, GPU acceleration, and substantial memory. Requiring full ROS 2 build environments to test parsing, schema validation, and provider fallback creates developer friction and slows CI pipelines.

### Decision
Architect the `backend/` directory as an independent, standard Python package (using Pydantic, FastAPI, and pytest) isolated in its own virtual environment. The ROS 2 client nodes in `ros2_ws/` interface with the backend via clean action/service bindings or lightweight IPC.

### Consequences
- **Positive:** Pam (D) can develop and run 100% of schema, provider, validation, and tokenization unit tests in seconds on standard Python without installing ROS 2 or Gazebo.
- **Negative:** Requires separate virtual environment and dependency tracking for the backend versus ROS 2 workspace.

---

## ADR-006: Primary Robotic Arm Selection (Franka Panda with UR5e Fallback)

### Context
Oscar (R)'s research (`docs/research/arm_selection.md`) evaluated the 3 candidates for Ubuntu 24.04, ROS 2 Jazzy, and Gazebo Harmonic:
- **Franka Emika Panda (7-DOF):** Native parallel jaw gripper (`franka_hand`), MoveIt 2 configs pre-packaged in official ROS 2 Jazzy apt (`ros-jazzy-moveit-resources-panda-*`), active `jazzy` branch maintained upstream by Franka Robotics with `gz_ros2_control` support.
- **Universal Robots UR5e (6-DOF):** Official simulation stack released as Debian binary `ros-jazzy-ur-simulation-gz`, but lacks a native gripper and requires attaching a third-party end-effector.
- **Kinova Gen3:** Rejected due to unstable Jazzy Gazebo Harmonic bridge and mimic joint physics bugs.

### Decision
1. **Primary Robot Arm:** Franka Emika Panda (7-DOF) with native Franka Hand.
   - Planning group: `panda_arm` + `panda_hand`
   - Arm Controller: `/panda_arm_controller/follow_joint_trajectory`
   - Gripper Controller: `/panda_hand_controller/gripper_cmd`
   - Base frame: `panda_link0`, Tool frame: `panda_hand`
2. **Fallback Robot Arm:** Universal Robots UR5e (6-DOF) via `ros-jazzy-ur-simulation-gz` with Robotiq 2F-85 or standard parallel gripper macro attached to `tool0`.

### Consequences
- **Positive:** 7-DOF provides kinematic redundancy for smooth obstacle avoidance; MoveIt configurations are pre-packaged in Jazzy apt; fully native gripper.
- **Negative:** Requires building `franka_ros2` from source workspace if advanced FCI features are needed beyond `moveit_resources`.

---

## ADR-007: Gazebo Harmonic Hybrid Grasping Architecture

### Context
Oscar (R)'s research (`docs/research/grasp_mechanism.md`) analyzed friction grasping in Gazebo Harmonic with DART physics:
- Friction grasping alone frequently exhibits finger slip, contact bounce, and micro-penetration during arm acceleration, causing intermittent drops in regression tests.
- Pure detachment plugins without physical fingers look unrealistic and break collision checking.

### Decision
Adopt a **Hybrid Grasping Architecture**:
1. Realistic physical finger collision surfaces with Coulomb friction ($\mu = 1.5$) and contact stiffness in the URDF/SDF.
2. Gazebo Harmonic's `gz-sim-detachable-joint-system` attached dynamically between `panda_hand` and the grasped object model upon verified contact closure ($|d_{\text{finger}}| < \epsilon$).
3. Detachment and unparenting executed upon gripper open command during the release stage.
4. Grasp action server in `munder_difflin_control` manages this dual physical-kinematic lock deterministically.

### Consequences
- **Positive:** 100% deterministic grasp retention during transit; realistic visual contact; eliminates flaky test failures.
- **Negative:** Requires including the `DetachableJoint` system tag in the Gazebo world SDF.

---

## ADR-008: Authentic Tokenization Visualization Without Fabricated Token IDs

### Context
Spec Section 7 mandates an interactive tokenization visualizer. When calling remote language models (e.g. cloud APIs) where token IDs are not returned in the completion response, fabricating integer token IDs would mislead users.

### Decision
1. When a true local tokenizer is available (e.g. `tiktoken` for OpenAI models or HuggingFace tokenizers for local models), display exact token IDs and boundaries.
2. When calling remote endpoints that do not return token IDs, use an explicit rule/regex boundary tokenizer, clearly display `is_approximate: true`, and label the tokenizer as `educational_approximation`.
3. Never fabricate synthetic token IDs or claim an approximate tokenizer represents the proprietary internal representation of a remote LLM.

### Consequences
- **Positive:** Strict technical integrity and educational honesty aligned with project specification.
- **Negative:** The UI must display visual badges distinguishing live exact token IDs from approximate tokens.

---

## ADR-009: Canonical 14-Stage Execution Pipeline Specification

### Context
A conflict emerged across documents regarding pipeline stages:
- Initial `INTERFACE_CONTRACTS.md` draft listed 9 grouped stages.
- `project-spec.md` Section 5 defines an end-to-end 14-step computational workflow.
- Angela (T)'s `TEST_PLAN.md` and test suite (`test_acceptance_i_inspectable_pipeline.py`) rely on the 14 stages.
- Pam (D)'s early backend milestone implements the initial parsing/validation prefix (`tokenization`, `ambiguity_check`, `parsing`, `validation`).

### Decision
Project Specification Section 5 is the authoritative single source of truth. The platform adopts **14 Canonical Pipeline Stages**:
1. `instruction` — Raw user command ingestion and sanitization.
2. `tokenization` — Text tokenization and boundary segmentation.
3. `interpretation` — Language model parsing and semantic intent extraction.
4. `structured_task` — Structured task proposal conversion.
5. `schema_validation` — Strict Pydantic schema validation.
6. `feasibility` — Deterministic bounds, safety, and ambiguity check.
7. `grounding` — Spatial object and destination grounding.
8. `planning_scene` — MoveIt 2 collision scene preparation.
9. `ik` — Inverse kinematics resolution for reachability.
10. `planning` — Collision-aware trajectory planning via MoveIt 2 OMPL.
11. `trajectory_validation` — Velocity, acceleration, and joint limit validation.
12. `execution` — Controller execution via ros2_control.
13. `simulation` — Gazebo Harmonic physics motion and hybrid grasp action.
14. `verification` — Post-execution spatial sensor verification.

**Mapping Rules:**
- The backend emits all 14 stages. During initial offline development, stages 1 through 6 execute against Python logic; stages 7 through 14 remain announced as `waiting` until connected to ROS 2/Gazebo.
- Pam's subroutines map: `parsing` $\rightarrow$ `interpretation`/`structured_task`; `ambiguity_check` $\rightarrow$ `feasibility`; `validation` $\rightarrow$ `schema_validation`.
- Frontend displays all 14 stages, with optional visual grouping into 5 functional panels.

### Consequences
- **Positive:** Complete consistency across Specification, Contract, Test Plan, and Implementation; zero test impedance.
- **Negative:** Requires Pam to align event stage strings to the canonical 14 enum keys.

---

## ADR-010: Isaac Sim Evaluation and Cloud-Only Extension Boundary

### Context
Project Specification Section 4 requires evaluating NVIDIA Isaac Sim. Oscar (R)'s research (`docs/research/isaac_sim.md`) confirmed:
- Isaac Sim requires NVIDIA RTX GPU with minimum 12 GB VRAM (RTX 3080/4080 or A4000), proprietary NVIDIA driver $\ge 535$, and CUDA 12.
- The host machine has an RTX 3050 Mobile with 4 GB VRAM running the `nouveau` driver.
- Attempting to install or run Isaac Sim locally will fail immediately with driver and out-of-memory errors.

### Decision
1. **Primary Simulation Engine:** Gazebo Harmonic (gz-sim 8) remains the authoritative, fully supported simulation environment.
2. **Isaac Sim Status:** Documented strictly as an **optional architectural extension**. If demonstrated, it must run on a remote cloud GPU workstation (e.g. AWS EC2 `g5.2xlarge` or NVIDIA Omniverse Cloud) with ROS 2 bridge connections streamed over DDS/WebRTC, never on the local development host.

### Consequences
- **Positive:** Protects local host stability; focuses team engineering velocity on the core Gazebo Harmonic stack.
- **Negative:** Local NVIDIA Omniverse photorealistic rendering is not available on this laptop.

---

## ADR-011: Pre-Interpretation Ambiguity Gating and Headless Terminal Stage Invariant

### Context
Pam (D) identified two operational issues during backend implementation of the 14 pipeline stages:
1. **Ambiguity Gating Sequence:** If ambiguity checks wait until `feasibility` (Stage 6), instructions like *"Move the box to the left"* get dispatched to an LLM provider during `interpretation` (Stage 3). The LLM will hallucinate or guess a destination (e.g. `storage_box`), which then fails during `schema_validation` as an invalid grasp or coordinate, resulting in state `failed` instead of `needs_clarification` (violating Acceptance Test D and Spec Section 6).
2. **Headless Stage Lifecycle Invariant:** In headless mode, stages 1 through 6 run, while downstream ROS 2 simulation stages (`grounding` through `verification`) were announced as `waiting`. However, Angela's Acceptance Test I (`test_every_stage_ends_in_a_terminal_ui_state`) enforces that when a pipeline run completes, all emitted stages in `run.events` must reach a terminal state (`TERMINAL_STATES = {success, warning, failed, cancelled, needs_clarification}`). Leaving stages perpetually `waiting` violates state machine closure and leaves UI panels ambiguous.

### Decision
1. **Pre-Interpretation Ambiguity Gating:**
   - Deterministic ambiguity and unknown-reference checks run at the boundary of the `interpretation` stage *before* calling any external LLM provider.
   - If an instruction lacks an explicit reference frame (e.g. "left" without anchor) or omits target/destination objects, `interpretation` immediately transitions to `StageState.NEEDS_CLARIFICATION`, populates clarification questions/options in event details, and terminates upstream computation.
   - All subsequent stages (4 through 14) are marked `StageState.CANCELLED`.
2. **Terminal Invariant for Completed Runs:**
   - When a pipeline run finishes (whether headless or live), **every stage recorded in that run's event log must reach a terminal state**.
   - In headless mode, upon successful completion of Stage 6 (`feasibility`), downstream stages 7 through 14 (`grounding` $\rightarrow$ `verification`) transition from `waiting` to `StageState.CANCELLED` with explicit detail `{"reason": "headless_run_complete", "message": "ROS 2 simulation execution skipped in headless mode"}`.
   - Downstream stages remain `waiting` only while an active run is in progress (`run.state == RUNNING`).

### Consequences
- **Positive:**
  - Prevents prompt token waste and stops LLMs from guessing past ambiguous instructions.
  - Satisfies Acceptance Test D (`NEEDS_CLARIFICATION` triggered reliably).
  - Satisfies Acceptance Test I (`test_every_stage_ends_in_a_terminal_ui_state` passes without hanging states).
  - Eliminates infinite spinners or ambiguous statuses in UI telemetry.
- **Negative:** None. Fully adheres to formal state machine semantics.

---

## ADR-012: Panda Model Specification via apt moveit_resources_panda (Supersedes franka_ros2 part of ADR-006)

### Context
ADR-006 initially specified Franka Emika Panda using upstream `franka_ros2` / `franka_description`. During live workspace bringup (MD-ROS-001 Milestone 1), Integration Engineer Andy (`andy-integration-engineer-i--mvr0ckuy`) audited the actual ROS 2 Jazzy packages and uncovered two major integration obstacles with `franka_ros2`:
1. Upstream `franka_description` in the Jazzy branch models the Franka Emika Research 3 (FER / FR3) arm with renamed joints (`fer_joint1..7`, `fer_finger_joint1/2`, `fer_link0`, `fer_hand`), breaking the contract names established in `INTERFACE_CONTRACTS.md` Section 8.
2. `franka_ros2` introduces hardware plugin dependencies on `libfranka` and real robot communication libraries, which require invasive mock plugin exclusions for pure simulation.

Conversely, the official Debian binary packages `ros-jazzy-moveit-resources-panda-description` and `ros-jazzy-moveit-resources-panda-moveit-config` are pre-compiled and readily installable via `apt`:
- Uses the standard, canonical naming: `panda_joint1` through `panda_joint7`, `panda_finger_joint1`, `panda_finger_joint2`, `panda_link0`, and `panda_hand`.
- Contains zero `libfranka` hardware dependencies.
- Has been verified running live in Gazebo Harmonic with active `ros2_control` controllers: `panda_arm_controller` (JointTrajectoryController) and `panda_hand_controller` (GripperActionController).

### Decision
1. **Model Source Supersession:**
   - Explicitly supersede the `franka_ros2`/`franka_description` packaging recommendation of ADR-006.
   - Authoritatively specify **`moveit_resources_panda_description`** and **`moveit_resources_panda_moveit_config`** (from `ros-jazzy-moveit-resources-panda-*`) as the official Panda model and MoveIt 2 configuration source for Munder Difflin.
2. **Canonical Naming Confirmed from Live Graph:**
   - Joint Names: `panda_joint1`, `panda_joint2`, `panda_joint3`, `panda_joint4`, `panda_joint5`, `panda_joint6`, `panda_joint7`.
   - Gripper Finger Joints: `panda_finger_joint1`, `panda_finger_joint2`.
   - Links: Base link is `panda_link0`; end-effector planning frame is `panda_hand`.
   - Active Controllers:
     - `/panda_arm_controller/follow_joint_trajectory` (`control_msgs/action/FollowJointTrajectory`)
     - `/panda_hand_controller/gripper_cmd` (`control_msgs/action/GripperCommand`)
     - `joint_state_broadcaster` on `/joint_states` (`sensor_msgs/msg/JointState`)
3. **Simulation Launch Entrypoint:**
   - Authoritative launch command: `ros2 launch munder_difflin_bringup sim.launch.py` (runs Gazebo Harmonic headless with `-s`, optional `rviz:=true`).
4. **Fallback Retained:**
   - Universal Robots UR5e via `ros-jazzy-ur-simulation-gz` is retained as the secondary fallback.

### Consequences
- **Positive:**
  - 100% zero-compilation, zero-sudo apt deployment for the robot arm model.
  - Matches live verified test evidence (`m1_controllers.log`, `m1_trajectory.log` showing 0.4 rad joint motion, error_code 0).
  - Preserves exact contract naming without requiring translation layers or joint re-mapping.
- **Negative:** None. Fully aligned with upstream ROS 2 Jazzy MoveIt 2 standards.

---

## ADR-013: Formal In-Process RosExecutor Architecture (Supersedes Custom ROS Action Stack)

### Context
During integration of the simulation backend with the ROS 2 workspace (MD-ROS-001), Integration Engineer Andy developed `RosExecutor` in `munder_difflin_control.ros_executor`. A architectural decision was required from `god` regarding whether to build dedicated custom ROS packages and action interfaces (`munder_difflin_msgs`, `/munder_difflin/execute_task`, `/grasp`, `/verification/verify_placement`, `/perception/detected_objects`) or adopt an in-process execution model.

Building custom ROS action packages introduces colcon build complexity, separate package maintenance, and inter-process serialization overhead for tasks orchestrated by the backend. In contrast, standard ROS 2 actions provided by MoveIt 2 (`/move_action` via `moveit_msgs/action/MoveGroup`) and ros2_control (`/panda_arm_controller/follow_joint_trajectory`, `/panda_hand_controller/gripper_cmd`) are active, verified in simulation, and directly accessible via `rclpy`.

### Decision (Authoritative Decision from Orchestrator / God)
1. **In-Process Execution Model:**
   - **Do NOT build `munder_difflin_msgs` or custom ROS action/service servers** (`/munder_difflin/execute_task`, `/munder_difflin/grasp`, `/munder_difflin/verification/verify_placement`, `/perception/detected_objects`).
   - Andy's **`RosExecutor`** (`munder_difflin_control.ros_executor.RosExecutor`, implementing the backend abstraction `backend/app/executor.py::Executor`) is the sole execution driver for the ROS 2 simulation. It executes grasping, placement verification, and perception in-process.
   - Downstream pipeline stages (`grounding`, `planning_scene`, `ik`, `planning`, `trajectory_validation`, `execution`, `simulation`, `verification`) are driven directly by `RosExecutor` calling standard MoveIt 2 actions, ros2_control controllers, and Gazebo topic bridges.
2. **Swappable Object-Pose Perception Abstraction:**
   - The perception interface retains a clean swappable design (`ObjectPoseSource` protocol).
   - Currently, `RosExecutor` ingests Gazebo ground-truth poses from `/model/{red_cube,blue_cube,green_cylinder}/pose` (20 Hz).
   - Future RGB-D camera perception connects into the identical `ObjectPoseSource` interface without altering task planning or execution pipelines.
3. **MoveIt 2 Planning Group Naming:**
   - In `config/panda.srdf`, upstream group `hand` was explicitly renamed to `panda_hand` to maintain 100% adherence to `INTERFACE_CONTRACTS.md`.
4. **Gripper Kinematics and Mimic Joint:**
   - `panda_finger_joint1` is the active command joint; `panda_finger_joint2` mimics it. Position travel is parameterized as 0.0 m (closed) to 0.04 m (open) per finger (total grip span 0.08 m).
5. **Emergency Stop Verification (SEC-013):**
   - The service `/munder_difflin/safety/emergency_stop` cancels active MoveIt goals, deactivates `panda_arm_controller`, samples `/joint_states` joint velocities across 10 iterations, and only reports `e_stop_confirmed: true` if all velocities are $< 1e-4\text{ rad/s}$ and controller state is `inactive`.
6. **Known Architectural Limitation:**
   - **Single-Process Coupling:** All task execution, grasp state tracking, placement verification, and perception grounding run inside the single `RosExecutor` process. They are not independently restartable microservice nodes. If the executor process terminates, all active control loops and state tracking terminate simultaneously.

### Consequences
- **Positive:**
  - Highly performant, direct trajectory execution without redundant middleware translation hops.
  - 100% verified against live simulation graph (`m1_controllers.log`, `m1_trajectory.log`, `docs/ros2_interfaces.md`).
  - Simplifies workspace dependencies (eliminates `munder_difflin_msgs` build bottlenecks).
  - Preserves swappable perception architecture.
- **Negative:**
  - Perception and grasp verification cannot be restarted independently of the backend executor (documented known limitation).
- **Negative:**
  - The ROS 2 graph operates with standard MoveIt/controller actions rather than dedicated custom actions.
