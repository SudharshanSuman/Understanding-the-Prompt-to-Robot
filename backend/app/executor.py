"""Execution side of the pipeline: an abstract Executor the ROS 2 orchestrator plugs into.

Until the ROS 2 side exists, SimulatedExecutor stands in. It cannot execute tasks (the
pipeline stops after feasibility with "no executor connected") and it never claims motion.
Its e-stop reports only what it observes in its own joint state (SEC-013), labelled as simulated.
"""

from __future__ import annotations

import math
import threading
from abc import ABC, abstractmethod
from collections.abc import Callable, Sequence
from typing import Literal

from pydantic import BaseModel, ConfigDict

from app.schemas import PipelineStageEvent, RoboticTask

VELOCITY_TOLERANCE = 1e-4  # rad/s; INTERFACE_CONTRACTS s9 SEC-013
PANDA_ARM_JOINTS = 7


class ExecutorError(RuntimeError):
    pass


class ExecutorStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    connected: bool  # True only when a real ROS 2 execution backend is reachable
    can_execute: bool
    e_stop_latched: bool
    controller_state: str
    detail: str = ""


class StopReport(BaseModel):
    """What was observed after an e-stop. 'e_stop_confirmed' only when the read-back says stopped."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["e_stop_confirmed", "e_stop_unverified"]
    controller_state: str
    max_joint_velocity: float | None  # rad/s, read back after the stop; None when nothing could be read
    tolerance: float = VELOCITY_TOLERANCE
    source: str
    requires_reset: bool = True
    detail: str = ""


def stop_report(velocities: Sequence[float], controller_state: str, source: str) -> StopReport:
    """Judge an e-stop from the joint-velocity read-back. Real executors should use this too.

    Confirmed only if every velocity is a finite number below tolerance and the controller says STOPPED.
    NaN or inf means the read-back cannot be trusted: unverified, and max_joint_velocity is left empty
    (max() would silently skip a NaN that follows a 0.0).
    """
    values = [float(v) for v in velocities]
    if not all(math.isfinite(v) for v in values):
        return StopReport(status="e_stop_unverified", controller_state=controller_state, max_joint_velocity=None,
                          source=source, detail="joint velocity read-back contained NaN or inf")
    observed = max((abs(v) for v in values), default=None)
    stopped = observed is not None and observed < VELOCITY_TOLERANCE and controller_state == "STOPPED"
    return StopReport(
        status="e_stop_confirmed" if stopped else "e_stop_unverified",
        controller_state=controller_state,
        max_joint_velocity=observed,
        source=source,
        detail="" if stopped else "joint velocities did not read back below tolerance",
    )


class Executor(ABC):
    name: str = "executor"

    @abstractmethod
    def status(self) -> ExecutorStatus: ...

    @abstractmethod
    def execute(self, task: RoboticTask, emit: Callable[[PipelineStageEvent], None],
                is_cancelled: Callable[[], bool]) -> None:
        """Run the ROS 2 stages (grounding ... verification) for a validated task, emitting stage events."""

    @abstractmethod
    def cancel(self, task_id: str) -> None: ...

    @abstractmethod
    def emergency_stop(self) -> StopReport:
        """Stop all motion, latch, and report the observed state. Must not raise."""

    @abstractmethod
    def reset(self) -> ExecutorStatus:
        """Clear the e-stop latch; motion commands are refused until this is called."""

    def telemetry(self) -> dict | None:
        """Latest live robot/scene snapshot (JSON-able), or None when there is no live data. Must not block or raise."""
        return None

    def readiness(self) -> dict[str, bool] | None:
        """Per-part readiness, e.g. {'move_action', 'arm_controller', 'gripper_controller', 'joint_states'} (fresh),
        or None when the executor does not report it. Must not block or raise."""
        return None


class SimulatedExecutor(Executor):
    """No-ROS stand-in. Holds an in-memory joint state; never executes a task."""

    name = "simulated_no_ros"

    def __init__(self, joint_velocities: Sequence[float] | None = None, stop_effective: bool = True) -> None:
        self._lock = threading.Lock()
        self._velocities = list(joint_velocities or [0.0] * PANDA_ARM_JOINTS)
        self._stop_effective = stop_effective  # tests model a controller that fails to stop
        self._latched = False
        self._controller_state = "IDLE"

    def status(self) -> ExecutorStatus:
        with self._lock:
            return ExecutorStatus(
                name=self.name, connected=False, can_execute=False, e_stop_latched=self._latched,
                controller_state=self._controller_state,
                detail="no executor connected: ROS 2 orchestrator not available; tasks stop after feasibility")

    def execute(self, task, emit, is_cancelled) -> None:
        raise ExecutorError("no executor connected: the simulated stand-in cannot execute tasks")

    def cancel(self, task_id: str) -> None:
        return None  # nothing is ever running here

    def emergency_stop(self) -> StopReport:
        with self._lock:
            self._latched = True
            if self._stop_effective:
                self._velocities = [0.0] * len(self._velocities)
                self._controller_state = "STOPPED"
            return stop_report(self._velocities, self._controller_state, "simulated joint state (no ROS 2 connected)")

    def reset(self) -> ExecutorStatus:
        with self._lock:
            self._latched = False
            self._controller_state = "IDLE"
        return self.status()
