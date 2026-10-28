# Munder Difflin: Interface Contracts & Schema Specifications
**Version:** 0.1.0-draft  
**Author:** Jim - Architect (A) (`jim-architect-a--mvr0ee0w`)  
**Status:** Approved for Implementation (Backend / Core / ROS2 Boundaries)  
**Related Documents:** [architecture.md](file:///home/sudharshan/Documents/Robotic%20Operation%20with%20Prompt%20Engineering/munder_difflin/docs/architecture.md), [DECISIONS.md](file:///home/sudharshan/Documents/Robotic%20Operation%20with%20Prompt%20Engineering/munder_difflin/docs/DECISIONS.md)

---

## 1. Overview & Safety Interlock Principle

> [!IMPORTANT]
> **Hard Architectural Rule (ADR-001):** Raw Language Model output **never** commands robot hardware or controllers directly. All language model outputs are treated as untrusted proposals and must pass through deterministic schema validation, spatial grounding, feasibility checks, collision-aware motion planning (MoveIt 2), and controller execution verification.

This document establishes the binding interface contracts for:
1. **Pydantic Task & Instruction Schema** (Target: `backend/app/schemas/task.py`) — *Pam (D) implementation target*
2. **Pipeline Stage Event Schema & 7-State Lifecycle** (Target: `backend/app/schemas/events.py`)
3. **LanguageModelProvider Interface** (Target: `backend/app/providers/base.py`)
4. **Perception & Spatial Grounding Interface** (Target: `backend/app/schemas/perception.py` / `munder_difflin_perception`)
5. **REST & WebSocket API Contracts** (Target: `backend/app/api/`, `backend/app/websocket/`)
6. **ROS 2 Package Boundaries & Topic/Action/Service Ownership** (Target: `ros2_ws/src/`)

---

## 2. Pydantic Task Schema (`app/schemas/task.py`)

This schema defines how natural language instructions are parsed into structured, validated robotic tasks. Pam (D)'s implementation uses strict validation (`extra="forbid"`, `frozen=True`) with a discriminated union between a definitive execution plan (`TaskPlan`) and a human-in-the-loop clarification request (`ClarificationRequest`).

### 2.1 Schema Definition

```python
"""
Strict Task Schema: App schemas implemented in `backend/app/schemas/task.py`
Every model forbids unknown fields to prevent prompt-injection key smuggling.
"""
from __future__ import annotations
from enum import Enum
from typing import Annotated, Literal, Union
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

SCHEMA_VERSION = "1.0"
Identifier = Annotated[str, Field(min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9_]*$")]

class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, frozen=True)

class TaskAction(str, Enum):
    PICK_AND_PLACE = "pick_and_place"

class TaskConstraints(_Strict):
    avoid_objects: list[Identifier] = Field(default_factory=list)
    keep_upright: bool = False

    @field_validator("avoid_objects")
    @classmethod
    def _unique(cls, value: list[str]) -> list[str]:
        if len(set(value)) != len(value):
            raise ValueError("avoid_objects must not contain duplicates")
        return value

class TaskPlan(_Strict):
    """A fully specified, unambiguous command ready for kinematic feasibility checking."""
    kind: Literal["task"] = "task"
    schema_version: Literal["1.0"] = SCHEMA_VERSION
    action: TaskAction
    object: Identifier
    destination: Identifier
    constraints: TaskConstraints = Field(default_factory=TaskConstraints)
    confidence: float = Field(ge=0.0, le=1.0)

    @model_validator(mode="after")
    def _consistent(self) -> "TaskPlan":
        if self.object in self.constraints.avoid_objects:
            raise ValueError("the target object cannot also be in avoid_objects")
        if self.object == self.destination:
            raise ValueError("object and destination must differ")
        return self

class ClarificationRequest(_Strict):
    """The command cannot be executed safely until the user answers a question."""
    kind: Literal["clarification"] = "clarification"
    schema_version: Literal["1.0"] = SCHEMA_VERSION
    question: str = Field(min_length=1, max_length=500)
    reason: str = Field(min_length=1, max_length=500)
    options: list[str] = Field(default_factory=list, max_length=20)

# Discriminated union parsed by LLM providers
ParsedCommand = Annotated[Union[TaskPlan, ClarificationRequest], Field(discriminator="kind")]

class ValidationIssue(_Strict):
    code: str = Field(pattern=r"^[A-Z][A-Z0-9_]*$")
    field: str | None = None
    message: str = Field(min_length=1)

class ValidationReport(_Strict):
    """Outcome of the deterministic safety/feasibility check."""
    ok: bool
    errors: list[ValidationIssue] = Field(default_factory=list)
    warnings: list[ValidationIssue] = Field(default_factory=list)

    @model_validator(mode="after")
    def _ok_matches_errors(self) -> "ValidationReport":
        if self.ok == bool(self.errors):
            raise ValueError("ok must be True exactly when there are no errors")
        return self


### 2.2 Specification Task Model (`RoboticTask` / `Task` for Contract CA-3)

To directly satisfy Spec Section 6 and the test harness contract `CA-3`, `backend/app/schemas` exposes `RoboticTask` (with alias `Task`):

```python
class RoboticTask(_Strict):
    """
    Direct representation of the Spec Section 6 task schema.
    Exported from app.schemas as both RoboticTask and Task.
    """
    task_id: str = Field(min_length=1)
    task_type: str = Field(default="pick_and_place")
    target_object: Identifier
    destination: Optional[Identifier] = None
    constraints: TaskConstraints = Field(default_factory=TaskConstraints)
    verification_required: bool = True

    @property
    def object(self) -> str:
        return self.target_object


# Export alias for contract CA-3:
Task = RoboticTask
```
```

---

## 3. Pipeline Stage Event Schema & 7-State Lifecycle (`app/schemas/events.py`)

The pipeline represents the **14 canonical computation stages** specified in Project Specification Section 5. Every observable step in the execution pipeline emits structured events transitioning through a strict 7-state lifecycle.

### 3.1 Canonical 14 Pipeline Stages (Spec Section 5 Source of Truth)

```python
class StageState(str, Enum):
    WAITING = "waiting"
    RUNNING = "running"
    SUCCESS = "success"
    WARNING = "warning"
    FAILED = "failed"
    CANCELLED = "cancelled"
    NEEDS_CLARIFICATION = "needs_clarification"


TERMINAL_STATES = frozenset(
    {
        StageState.SUCCESS,
        StageState.WARNING,
        StageState.FAILED,
        StageState.CANCELLED,
        StageState.NEEDS_CLARIFICATION,
    }
)


class PipelineStage(str, Enum):
    """
    Canonical 14 pipeline stages per Spec Section 5.
    Every stage is emitted with state 'waiting' at initialization,
    then progresses to 'running' and reaches a terminal state.
    """
    INSTRUCTION = "instruction"                     # 1. User instruction received & sanitized
    TOKENIZATION = "tokenization"                   # 2. Text tokenization & boundary segmentation
    INTERPRETATION = "interpretation"               # 3. Language model parsing & intent extraction
    STRUCTURED_TASK = "structured_task"             # 4. Conversion to structured task proposal
    SCHEMA_VALIDATION = "schema_validation"         # 5. Strict Pydantic schema validation
    FEASIBILITY = "feasibility"                     # 6. Safety boundary, bounds & ambiguity check
    GROUNDING = "grounding"                         # 7. Spatial object & destination grounding
    PLANNING_SCENE = "planning_scene"               # 8. MoveIt 2 collision scene preparation
    IK = "ik"                                       # 9. Inverse kinematics resolution
    PLANNING = "planning"                           # 10. Collision-aware motion planning
    TRAJECTORY_VALIDATION = "trajectory_validation" # 11. Joint limits & dynamic feasibility
    EXECUTION = "execution"                         # 12. ros2_control trajectory execution
    SIMULATION = "simulation"                       # 13. Gazebo physics & grasp action
    VERIFICATION = "verification"                   # 14. Post-execution spatial sensor check


CANONICAL_PIPELINE_STAGES: list[str] = [stage.value for stage in PipelineStage]


class PipelineStageEvent(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    run_id: str = Field(min_length=1, description="Associated task/run identifier.")
    stage: str = Field(min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9_]*$", description="PipelineStage value.")
    state: StageState = Field(..., description="Current state of the stage.")
    message: str = Field(default="", description="Human-readable log or explanation message.")
    detail: dict[str, Any] = Field(
        default_factory=dict,
        description="Structured stage-specific telemetry (tokens, IK joints, planner metrics, etc.)."
    )
    timestamp: datetime = Field(default_factory=_now, description="UTC timestamp.")

    @property
    def is_terminal(self) -> bool:
        return self.state in TERMINAL_STATES
```

### 3.2 UI Stage Grouping & Headless Terminal Closeout Rules

1. **Deterministic Ambiguity Interception (ADR-011):**
   - The deterministic ambiguity check runs at the threshold of the `interpretation` stage (before invoking any external LLM provider) to ensure ambiguous instructions (e.g. "Move the box to the left") trigger `StageState.NEEDS_CLARIFICATION` immediately without wasting tokens or allowing models to hallucinate invalid targets.
   - When an ambiguity or missing target is detected, `interpretation` transitions to `NEEDS_CLARIFICATION`, and all subsequent stages (4 through 14) are marked `CANCELLED`.

2. **Headless Execution Terminal Closeout:**
   - In headless mode (unit testing or non-ROS environments), the orchestrator executes the initial prefix stages:
     `instruction` $\rightarrow$ `tokenization` $\rightarrow$ `interpretation` $\rightarrow$ `structured_task` $\rightarrow$ `schema_validation` $\rightarrow$ `feasibility`.
   - **Terminal Invariant:** When a pipeline run finishes, **no emitted stage may remain in the non-terminal `waiting` state**.
   - Upon successful completion of `feasibility` in headless mode, downstream stages (`grounding` through `verification`) transition from `waiting` to `StageState.CANCELLED` with detail `{"reason": "headless_run_complete", "message": "ROS 2 simulation execution skipped in headless mode"}`.
   - This guarantees that every stage in a completed run resolves to a `TERMINAL_STATE` (`success`, `warning`, `failed`, `cancelled`, or `needs_clarification`).

3. **UI Visual Hierarchy:**
   On the React frontend, the 14 stages are presented directly or grouped into 5 logical panels:
   - **NL Processing:** `instruction`, `tokenization`, `interpretation`, `structured_task`
   - **Safety Interlock:** `schema_validation`, `feasibility`
   - **Spatial & Kinematics:** `grounding`, `planning_scene`, `ik`
   - **Motion Planning:** `planning`, `trajectory_validation`
   - **Simulation & Verification:** `execution`, `simulation`, `verification`

### 3.2 State Transition Matrix

| Current State | Allowed Next States | Trigger / Condition |
| :--- | :--- | :--- |
| `waiting` | `running`, `cancelled` | Stage begins execution or task cancelled |
| `running` | `success`, `warning`, `failed`, `cancelled`, `needs_clarification` | Execution finishes, non-fatal anomaly, error, user abort, or ambiguity |
| `warning` | `success`, `running`, `failed` | Warning acknowledged/handled or escalated |
| `needs_clarification` | `waiting`, `running`, `cancelled` | User provides clarification or cancels |
| `success` | `waiting` (next stage) | Normal sequential flow |
| `failed` | *Terminal* or `running` (recovery retry) | Error recovery or abort |
| `cancelled` | *Terminal* | Operator cancellation |

---

## 4. Tokenization Schema (`app/schemas/tokenization.py`)

To satisfy Spec Section 7 (interactive tokenization display without fabricating IDs):

```python
class TokenUnit(BaseModel):
    index: int
    text: str
    token_id: Optional[int] = Field(
        default=None,
        description="Exact integer token ID from local tokenizer (e.g. tiktoken, HuggingFace). None if approximate."
    )
    is_approximate: bool = Field(
        default=False,
        description="True if token IDs could not be extracted from remote API and approximate regex boundaries were used."
    )
    role: Optional[str] = Field(
        default=None,
        description="Grammar/semantic role: 'action_verb', 'target_object', 'spatial_prep', 'destination', 'constraint'."
    )


class TokenizationResult(BaseModel):
    raw_text: str
    tokens: List[TokenUnit]
    tokenizer_name: str = Field(..., description="e.g. 'cl100k_base', 'llama3-tokenizer', 'regex_word_level'")
    is_live_model_tokenization: bool = Field(
        default=True,
        description="True if produced by actual tokenizer runtime, False if fallback educational approximation."
    )
```

---

## 5. Language Model Provider Interface (`app/providers/base.py`)

All LLM providers inherit from a clean, decoupled base interface.

```python
from abc import ABC, abstractmethod
from typing import Dict, Any

class ProviderStatus(BaseModel):
    provider_id: str
    name: str
    available: bool
    model_name: Optional[str] = None
    latency_ms: Optional[float] = None
    error_message: Optional[str] = None
    hardware_accelerated: bool = False


class LanguageModelProvider(ABC):
    """
    Abstract interface for AI model execution.
    Providers are responsible for language parsing and task proposal only.
    Direct low-level joint/robot commanding is prohibited.
    """

    @abstractmethod
    async def parse_instruction(
        self,
        instruction: str,
        world_context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Interprets natural language instruction into candidate task dictionary.
        Must handle retries on malformed JSON internally.
        """
        pass

    @abstractmethod
    def tokenize(self, text: str) -> TokenizationResult:
        """
        Returns structured tokens. If true tokenizer is not available,
        returns clearly marked approximate tokens (is_approximate=True).
        """
        pass

    @abstractmethod
    async def health_check(self) -> ProviderStatus:
        """
        Returns real-time availability and connectivity status.
        """
        pass
```

### 5.1 Provider Implementations Hierarchy
```
LanguageModelProvider (ABC)
├── CloudAPIProvider (OpenAI, Anthropic, Gemini via env vars; zero key exposure to client)
├── LocalInferenceProvider (Ollama / local REST endpoint)
├── NVIDIAInferenceProvider (NVIDIA NIM or OpenAI-compatible endpoint with Nemotron support)
└── DeterministicFallbackProvider (Rule-based pattern matching for baseline test commands; no external deps)
```

---

## 6. Perception & Spatial Grounding Interface (`munder_difflin_perception`)

A swappable abstraction decoupling the task planner from the physical/simulated perception source.

### 6.1 Data Models (`app/schemas/perception.py`)

```python
class Pose3D(BaseModel):
    x: float
    y: float
    z: float
    qx: float = 0.0
    qy: float = 0.0
    qz: float = 0.0
    qw: float = 1.0
    frame_id: str = "world"


class BoundingBox3D(BaseModel):
    size_x: float
    size_y: float
    size_z: float


class DetectedObject(BaseModel):
    object_id: str            # e.g. "red_cube_1"
    label: str                # e.g. "red_cube"
    pose: Pose3D
    bbox: BoundingBox3D
    confidence: float = 1.0   # 1.0 for ground truth, [0.0 - 1.0] for vision
    is_ground_truth: bool = True
    color_rgb: Optional[List[int]] = None


class WorldObservation(BaseModel):
    timestamp: str
    perception_mode: str      # "simulation_ground_truth" or "rgbd_vision"
    objects: List[DetectedObject]
    table_surface_z: float = 0.4
    reference_frame: str = "world"
```

### 6.2 Perception Provider Protocol
Both the ground-truth publisher and the RGB-D vision node publish to standard ROS 2 topic:
- **Topic:** `/perception/detected_objects` (`munder_difflin_msgs/msg/DetectedObjectArray`)
- **Mode Announcement Topic:** `/perception/mode` (`std_msgs/msg/String`)

---

## 7. REST & WebSocket API Contracts

FastAPI Backend runs on port `8000` (configurable via `APP_PORT`).

### 7.1 REST Endpoints

| Method | Endpoint | Request Body | Response Body | Description |
| :--- | :--- | :--- | :--- | :--- |
| `POST` | `/api/v1/tasks` | `{"instruction": str}` | `{"task_id": str, "status": "accepted"}` | Submit NL command |
| `GET` | `/api/v1/tasks/{id}` | None | `RoboticTask` + Stage status | Inspect current task status |
| `POST` | `/api/v1/tasks/{id}/clarify` | `{"selected_option": str, "free_text": Optional[str]}` | `{"status": "resumed"}` | Resume task after clarification |
| `POST` | `/api/v1/tasks/{id}/cancel` | None | `{"status": "cancelled"}` | Cancel active planning/execution |
| `POST` | `/api/v1/simulation/e-stop` | None | `{"status": "e_stop_confirmed"}` | Hardware/simulation emergency stop |
| `POST` | `/api/v1/simulation/reset` | None | `{"status": "resetting"}` | Reset Gazebo scene & objects |
| `GET` | `/api/v1/providers` | None | `List[ProviderStatus]` | List available AI providers |
| `POST` | `/api/v1/providers/select` | `{"provider_id": str}` | `ProviderStatus` | Switch active provider |
| `GET` | `/api/v1/environment/objects`| None | `WorldObservation` | Get current spatial scene |
| `GET` | `/api/v1/health` | None | System health payload | ROS 2, Gazebo, MoveIt 2 status |

### 7.2 WebSocket Streaming Contract
- **Endpoint:** `ws://localhost:8000/ws/pipeline`
- **Stream Format:** JSON frames with `channel` and `payload`:

```json
{
  "channel": "pipeline_event",
  "task_id": "task_001",
  "payload": {
    "event_id": "evt_9981",
    "stage": "motion_planning",
    "state": "running",
    "timestamp": "2026-10-28T00:15:00.000Z",
    "message": "Generating collision-free trajectory with MoveIt 2 OMPL...",
    "data": {
      "planner_id": "RRTConnectkConfigDefault",
      "planning_time_limit_sec": 5.0
    }
  }
}
```

- **Telemetry Endpoint:** `ws://localhost:8000/ws/telemetry`
  - Emits real-time joint positions, velocities, gripper state, and end-effector pose at 10-20 Hz.

---

## 8. ROS 2 Package Boundaries & Topic/Action Ownership

All ROS 2 nodes live in `munder_difflin/ros2_ws/src/`.

### 8.1 Package Architecture

| Package Name | Type | Responsibility |
| :--- | :--- | :--- |
| `munder_difflin_msgs` | CMake (Interfaces) | Custom `.msg`, `.srv`, `.action` definitions |
| `munder_difflin_description` | CMake / Ament | URDF / Xacro for arm, gripper, sensors, camera |
| `munder_difflin_gazebo` | CMake / Ament | Gazebo Harmonic worlds, SDF models (table, cubes, bins), spawn launch |
| `munder_difflin_moveit_config` | CMake / Ament | SRDF, kinematics solvers, OMPL config, joint limits |
| `munder_difflin_perception` | Python (`rclpy`) | Ground truth extractor + RGB-D vision node + tf2 publisher |
| `munder_difflin_planning` | C++ / Python | MoveIt 2 Python/C++ node, IK checker, collision scene manager |
| `munder_difflin_control` | Python (`rclpy`) | Grasp execution action server, trajectory executor, safety monitor |
| `munder_difflin_bringup` | Python (`launch`) | Master launch files combining simulation, controllers, and backend |

### 8.2 ROS 2 Topic & Action Interface Registry (Verified Franka Panda Primary + UR5e Fallback)

Following Oscar's environment research report (`docs/research/arm_selection.md`), **Franka Emika Panda (7-DOF) with native Franka Hand** is the primary manipulator, and **Universal Robots UR5e** is the fallback.

#### Primary Manipulator: Franka Emika Panda (`panda_arm` + `panda_hand`)
- Base Link: `panda_link0`
- End-Effector Tip: `panda_hand` (or `panda_link8`)
- Gripper Fingers: `panda_finger_joint1`, `panda_finger_joint2`

| Interface Name | Type | Direction / Owner | Description |
| :--- | :--- | :--- | :--- |
| `/joint_states` | `sensor_msgs/msg/JointState` | Published by ros2_control | Live joint positions/velocities for 7 arm joints + 2 finger joints |
| `/tf`, `/tf_static` | `tf2_msgs/msg/TFMessage` | Robot state publisher & perception | Coordinate transform tree (`world` -> `panda_link0` -> `panda_hand`) |
| `/perception/detected_objects` | `munder_difflin_msgs/msg/DetectedObjectArray` | Owned by `munder_difflin_perception` | Standardized object list & poses |
| `/planning_scene` | `moveit_msgs/msg/PlanningScene` | Owned by `munder_difflin_planning` | MoveIt 2 collision scene |
| `/munder_difflin/execute_task` | Action: `munder_difflin_msgs/action/ExecuteTask` | Server: `munder_difflin_planning` / Client: Backend | Long-running task execution action |
| `/munder_difflin/grasp` | Action: `munder_difflin_msgs/action/GraspObject` | Server: `munder_difflin_control` | Hybrid grasp action (finger close + DetachableJoint attach) |
| `/panda_arm_controller/follow_joint_trajectory` | Action: `control_msgs/action/FollowJointTrajectory` | ros2_control controller | MoveIt 2 arm trajectory execution interface |
| `/panda_hand_controller/gripper_cmd` | Action: `control_msgs/action/GripperCommand` | ros2_control controller | Parallel jaw finger position/effort command |
| `/munder_difflin/safety/emergency_stop` | Service: `std_srvs/srv/Trigger` | Server: `munder_difflin_control` | Hardware/sim emergency stop; halts controllers and locks brakes |
| `/munder_difflin/verification/verify_placement` | Service: `munder_difflin_msgs/srv/VerifyPlacement` | Server: `munder_difflin_control` | Spatial verification check post-placement |

#### Fallback Manipulator Mapping: Universal Robots UR5e
- Arm Action: `/scaled_joint_trajectory_controller/follow_joint_trajectory`
- Base Link: `base_link`
- Flange Link: `tool0`

---

## 9. Security Controls & Architecture Hardening (SEC Findings)

In direct compliance with Security Engineer Dwight's findings (`docs/project/SECURITY_FINDINGS.md`):

1. **SEC-001 (Untrusted NL Input):**
   - Natural language input capped at 500 characters.
   - Non-printable and shell control characters stripped prior to tokenization.
2. **SEC-002 & SEC-003 (Prompt Injection & Model Output Validation - CRITICAL):**
   - System prompts are strictly segregated from user inputs using OpenAI/Anthropic/NIM role separation.
   - Model outputs are gated through strict Pydantic schemas (`extra="forbid"`) without dynamic code execution or `eval()`.
3. **SEC-008 (Install Scripts):**
   - All installation and setup scripts must be idempotent, hash-check remote artifacts, and require interactive human authorization for `sudo`.
4. **SEC-011 (ROS 2 DDS Network Isolation):**
   - ROS 2 Jazzy DDS configured to localhost only (`export ROS_LOCALHOST_ONLY=1`).
   - Domain ID pinned explicitly (`export ROS_DOMAIN_ID=42`).
   - Only explicitly declared bridge topics configured in `ros_gz_bridge`.
5. **SEC-012 (Deterministic Safety Gateway - RELEASE BLOCKER):**
   - The safety interlock (`app/validation/`) is architecturally un-bypassable.
   - Rejects ungrounded objects, negative clearances, coordinates outside workspace bounds ($X, Y \in [-0.8, 0.8]\text{ m}, Z \in [0.0, 1.2]\text{ m}$), and underspecified directional commands without explicit reference frames.
6. **SEC-013 (E-Stop Verification - RELEASE BLOCKER):**
   - Dedicated endpoint `POST /api/v1/simulation/e-stop` and service `/munder_difflin/safety/emergency_stop`.
   - E-Stop confirmation is strictly verified by asserting joint velocities $|\dot{q}| < 1e-4\text{ rad/s}$ and controller state `STOPPED`. A GUI button click without controller verification is prohibited.
7. **SEC-015 (Desktop Application Hardening):**
   - For Electron/Tauri desktop packaging: `contextIsolation: true`, `nodeIntegration: false`, strict CSP restricting connections exclusively to `http://localhost:8000` and `ws://localhost:8000`.

---

## 10. Verification & Quality Gate Acceptance

Before code implementation advances, the following must hold:
1. **Unit Tests (Pam):** Pydantic schemas must pass automated tests on valid pick-and-place, ambiguous commands (`clarification.needed == True`), unknown objects, and schema serialization.
2. **Deterministic Validator:** Any instruction specifying "left" without reference frame must trigger `needs_clarification`.
3. **Safety Assertions:** An unverified raw model output string cannot be parsed into an executable MoveIt goal without passing through `RoboticTask` schema validation.
