"""REST endpoints (INTERFACE_CONTRACTS s7.1). Everything except /health needs the bearer token (SEC-005)."""

from __future__ import annotations

import math
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from app.api.security import client_key, require_token
from app.executor import Executor, ExecutorStatus
from app.providers import ProviderStatus
from app.schemas import TokenizationResult
from app.security import MAX_RAW_CHARS, InputRejected, sanitize_instruction
from app.tasks import TaskConflict, TaskManager, TaskNotFound
from app.tokenizer import get_tokenizer

ROS_UNAVAILABLE = {"available": False, "reason": "ros unavailable",
                   "detail": "ROS 2 is not connected to this backend; nothing here is live data"}
TELEMETRY_UNAVAILABLE = {**ROS_UNAVAILABLE, "joint_states": None, "gripper": None, "end_effector_pose": None}


def _finite(value):
    """NaN/inf are not JSON and must never read as data: they become null."""
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, dict):
        return {str(k): _finite(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_finite(v) for v in value]
    return value


def telemetry_payload(executor: Executor) -> dict:
    """The executor's live snapshot, or the honest 'ros unavailable' stub. A failing executor is unavailable."""
    try:
        snapshot = executor.telemetry()
    except Exception:
        snapshot = None
    if not isinstance(snapshot, dict):
        return dict(TELEMETRY_UNAVAILABLE)
    return {"available": True, "source": executor.name, "data": _finite(snapshot)}


class _Body(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SubmitTask(_Body):
    instruction: str = Field(min_length=1, max_length=MAX_RAW_CHARS)


class Clarify(_Body):
    selected_option: Optional[str] = Field(default=None, max_length=128)
    free_text: Optional[str] = Field(default=None, max_length=MAX_RAW_CHARS)


class SelectProvider(_Body):
    provider_id: str = Field(min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9_]*$")


class TokenizeText(_Body):
    text: str = Field(min_length=1, max_length=MAX_RAW_CHARS)


def manager(request: Request) -> TaskManager:
    return request.app.state.manager


def _not_found(exc: TaskNotFound) -> HTTPException:
    return HTTPException(status_code=404, detail=str(exc))


def _conflict(exc: TaskConflict) -> HTTPException:
    return HTTPException(status_code=409, detail=str(exc))


def _rate_limited(request: Request) -> None:
    if not request.app.state.task_limiter.hit(client_key(request)):
        raise HTTPException(status_code=429, detail="too many task submissions; try again in a minute")


public = APIRouter(prefix="/api/v1")
protected = APIRouter(prefix="/api/v1", dependencies=[Depends(require_token)])


def ros_parts(executor: Executor, status: ExecutorStatus) -> dict[str, str]:
    """ros2/gazebo/moveit as 'available', 'unavailable' or 'unknown', only from what the executor reports.

    With per-part readiness: ROS 2 is up when any part answers; Gazebo when fresh /joint_states arrive (the sim's
    ros2_control publishes them); MoveIt when its move_group action server is ready. Without it: a connected
    executor means every part is ready; live telemetry alone proves ROS 2 only; otherwise nothing is up.
    """
    try:
        ready = executor.readiness()
    except Exception:
        ready = None
    if isinstance(ready, dict):
        up = lambda ok: "available" if ok else "unavailable"  # noqa: E731
        return {"ros2": up(any(ready.values())), "gazebo": up(ready.get("joint_states") is True),
                "moveit": up(ready.get("move_action") is True)}
    if status.connected:
        return {"ros2": "available", "gazebo": "available", "moveit": "available"}
    if telemetry_payload(executor)["available"]:
        return {"ros2": "available", "gazebo": "unknown", "moveit": "unknown"}
    return {"ros2": "unavailable", "gazebo": "unavailable", "moveit": "unavailable"}


@public.get("/health")
def health(request: Request) -> dict:
    """Unauthenticated: reports only what is up, never keys, paths or configuration."""
    executor = manager(request).executor
    status = executor.status()
    return {"status": "ok", **ros_parts(executor, status), "executor_connected": status.connected}


# --- tasks ----------------------------------------------------------------------------------
@protected.post("/tasks", status_code=202)
def submit_task(body: SubmitTask, request: Request, background: BackgroundTasks) -> dict:
    _rate_limited(request)
    tasks = manager(request)
    try:
        record = tasks.create(body.instruction)
    except TaskConflict as exc:
        raise _conflict(exc) from None
    background.add_task(tasks.run, record.task_id, body.instruction)
    return {"task_id": record.task_id, "status": "accepted"}


@protected.get("/tasks")
def task_history(request: Request) -> list[dict]:
    return manager(request).history()


@protected.get("/tasks/{task_id}")
def task_status(task_id: str, request: Request) -> dict:
    try:
        return manager(request).get(task_id).detail()
    except TaskNotFound as exc:
        raise _not_found(exc) from None


@protected.post("/tasks/{task_id}/clarify")
def clarify_task(task_id: str, body: Clarify, request: Request, background: BackgroundTasks) -> dict:
    _rate_limited(request)
    tasks = manager(request)
    try:
        instruction = tasks.clarify(task_id, body.selected_option, body.free_text)
    except TaskNotFound as exc:
        raise _not_found(exc) from None
    except TaskConflict as exc:
        raise _conflict(exc) from None
    background.add_task(tasks.run, task_id, instruction)
    return {"status": "resumed", "task_id": task_id}


@protected.post("/tasks/{task_id}/cancel")
def cancel_task(task_id: str, request: Request) -> dict:
    try:
        manager(request).cancel(task_id)
    except TaskNotFound as exc:
        raise _not_found(exc) from None
    except TaskConflict as exc:
        raise _conflict(exc) from None
    return {"status": "cancelled", "task_id": task_id}


# --- e-stop / simulation (SEC-013) ----------------------------------------------------------
@protected.post("/simulation/e-stop")
def emergency_stop(request: Request):
    """Not rate limited. Reports the observed stop; 503 when the stop could not be confirmed."""
    tasks = manager(request)
    report = tasks.executor.emergency_stop()
    tasks.cancel_all_active()
    body = report.model_dump()
    if report.status != "e_stop_confirmed":
        raise HTTPException(status_code=503, detail=body)
    return body


@protected.post("/simulation/reset")
def reset_simulation(request: Request) -> dict:
    status = manager(request).executor.reset()
    return {"status": "resetting", "e_stop_latched": status.e_stop_latched, "scene_reset": scene_reset(status)}


def scene_reset(status: ExecutorStatus) -> str:
    """The executor's own scene-reset result ('...; scene: <result>'); never claims a reset it did not report."""
    _, sep, scene = status.detail.partition("; scene: ")
    if sep and scene:
        return scene
    if not status.connected:
        return "ros unavailable: Gazebo scene not reset"
    return "not reported by the executor: Gazebo scene state unknown"


@protected.get("/executor", response_model=ExecutorStatus)
def executor_status(request: Request) -> ExecutorStatus:
    return manager(request).executor.status()


# --- providers ------------------------------------------------------------------------------
@protected.get("/providers", response_model=list[ProviderStatus])
def list_providers(request: Request) -> list[ProviderStatus]:
    return manager(request).provider_statuses()


@protected.get("/providers/active", response_model=ProviderStatus)
def active_provider(request: Request) -> ProviderStatus:
    return manager(request).active_status()


@protected.post("/providers/select", response_model=ProviderStatus)
def select_provider(body: SelectProvider, request: Request) -> ProviderStatus:
    try:
        return manager(request).select_provider(body.provider_id)
    except TaskNotFound as exc:
        raise _not_found(exc) from None
    except TaskConflict as exc:
        raise _conflict(exc) from None


# --- tokenization ---------------------------------------------------------------------------
@protected.post("/tokenize", response_model=TokenizationResult)
def tokenize(body: TokenizeText, request: Request) -> TokenizationResult:
    tasks = manager(request)
    try:
        text = sanitize_instruction(tasks.scrub(body.text))
    except InputRejected as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    return (tasks.tokenizer or get_tokenizer()).tokenize(text)


# --- ROS-side stubs: honest 'ros unavailable' until the ROS 2 orchestrator is connected -----
@protected.get("/environment/objects")
def environment_objects(request: Request) -> dict:
    tasks = manager(request)
    world = tasks.validator.world
    scene = {"objects": sorted(world.object_ids()), "destinations": sorted(world.destination_ids())}
    live = telemetry_payload(tasks.executor)
    data = live.get("data") or {}
    positions = data.get("objects") if isinstance(data.get("objects"), dict) else None
    if not live["available"] or positions is None:
        return {**ROS_UNAVAILABLE, "perception_mode": "unavailable", "objects": [], "scene_config": scene}
    objects = [{"id": str(k), "position": v} for k, v in sorted(positions.items())
               if isinstance(v, list) and len(v) == 3 and all(isinstance(n, (int, float)) for n in v)]
    perception = data.get("perception") if isinstance(data.get("perception"), str) else "unknown"
    return {"available": True, "source": live["source"], "time": data.get("time"), "perception_mode": perception,
            "objects": objects, "scene_config": scene}


@protected.get("/telemetry")
def telemetry(request: Request) -> dict:
    return telemetry_payload(manager(request).executor)


@protected.get("/ros/inspector")
def ros_inspector() -> dict:
    return {**ROS_UNAVAILABLE, "nodes": [], "topics": [], "actions": [], "services": []}
