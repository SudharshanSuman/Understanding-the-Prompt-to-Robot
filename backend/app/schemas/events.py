"""Pipeline stage events streamed to the UI."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


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
    """Canonical 14 stages (project-spec s5, INTERFACE_CONTRACTS s3.1, ADR-009), in order."""

    INSTRUCTION = "instruction"
    TOKENIZATION = "tokenization"
    INTERPRETATION = "interpretation"
    STRUCTURED_TASK = "structured_task"
    SCHEMA_VALIDATION = "schema_validation"
    FEASIBILITY = "feasibility"
    GROUNDING = "grounding"
    PLANNING_SCENE = "planning_scene"
    IK = "ik"
    PLANNING = "planning"
    TRAJECTORY_VALIDATION = "trajectory_validation"
    EXECUTION = "execution"
    SIMULATION = "simulation"
    VERIFICATION = "verification"


PIPELINE_STAGES: tuple[str, ...] = tuple(s.value for s in PipelineStage)
# Stages the backend runs without ROS 2; the rest stay 'waiting' until ROS 2 is connected.
HEADLESS_STAGES: tuple[str, ...] = PIPELINE_STAGES[:6]


def _now() -> datetime:
    return datetime.now(timezone.utc)


class PipelineStageEvent(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    run_id: str = Field(min_length=1)
    stage: str = Field(min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9_]*$")
    state: StageState
    message: str = ""
    detail: dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=_now)

    @property
    def is_terminal(self) -> bool:
        return self.state in TERMINAL_STATES
