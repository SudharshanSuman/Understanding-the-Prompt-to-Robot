"""Task runs, their stage events, provider selection and event fan-out to WebSocket subscribers.

Pipelines run on worker threads; subscribers live on the event loop, so events cross over with
loop.call_soon_threadsafe. A subscription is registered and its replay snapshotted under one lock,
so no event is lost or duplicated between the replay and the live stream.
"""

from __future__ import annotations

import asyncio
import threading
import uuid
from collections import OrderedDict
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from app.executor import Executor, ExecutorError
from app.pipeline import run_pipeline
from app.providers import LanguageModelProvider, ProviderChain, ProviderStatus
from app.providers.fallback import DeterministicFallbackProvider
from app.schemas import PIPELINE_STAGES, PipelineStageEvent, StageState
from app.security import redact, secret_values
from app.tokenizer import Tokenizer
from app.validation import SafetyValidator

AUTO = "auto"
FALLBACK = "fallback"


class TaskConflict(Exception):
    """The request does not fit the task's current status; the message is safe to return."""


class TaskNotFound(Exception):
    pass


class Status:
    ACCEPTED = "accepted"
    RUNNING = "running"
    NEEDS_CLARIFICATION = "needs_clarification"
    FAILED = "failed"
    CANCELLED = "cancelled"
    NO_EXECUTOR = "validated_no_executor"  # passed feasibility; nothing connected to execute it
    EXECUTING = "executing"
    COMPLETED = "completed"


FINAL = {Status.NEEDS_CLARIFICATION, Status.FAILED, Status.CANCELLED, Status.NO_EXECUTOR, Status.COMPLETED}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class TaskRecord:
    task_id: str
    instruction: str
    status: str = Status.ACCEPTED
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)
    events: list[PipelineStageEvent] = field(default_factory=list)
    result: dict[str, Any] = field(default_factory=dict)
    provider: str | None = None
    clarifications: list[dict[str, Any]] = field(default_factory=list)
    cancel: threading.Event = field(default_factory=threading.Event)

    def stages(self) -> dict[str, str]:
        last = {s: StageState.WAITING.value for s in PIPELINE_STAGES}
        for ev in self.events:
            last[ev.stage] = ev.state.value
        return last

    def summary(self) -> dict[str, Any]:
        return {"task_id": self.task_id, "status": self.status, "instruction": self.instruction,
                "created_at": self.created_at, "updated_at": self.updated_at, "provider": self.provider}

    def detail(self) -> dict[str, Any]:
        return {**self.summary(), **self.result, "stages": self.stages(), "clarifications": self.clarifications,
                "events": [event_payload(self.task_id, i, ev) for i, ev in enumerate(self.events)]}


def event_payload(task_id: str, seq: int, ev: PipelineStageEvent) -> dict[str, Any]:
    return {"event_id": f"{task_id}:{seq}", "stage": ev.stage, "state": ev.state.value,
            "timestamp": ev.timestamp.isoformat(), "message": ev.message, "data": ev.detail}


def pipeline_frame(task_id: str, seq: int, ev: PipelineStageEvent) -> dict[str, Any]:
    return {"channel": "pipeline_event", "task_id": task_id, "payload": event_payload(task_id, seq, ev)}


@dataclass(eq=False)
class Subscription:
    loop: asyncio.AbstractEventLoop
    queue: asyncio.Queue
    task_id: str | None  # None: every task
    dropped: int = 0

    def offer(self, frame: dict[str, Any]) -> None:  # runs on the subscriber's loop
        try:
            self.queue.put_nowait(frame)
        except asyncio.QueueFull:
            self.dropped += 1


class TaskManager:
    def __init__(
        self,
        validator: SafetyValidator,
        executor: Executor,
        providers: Sequence[LanguageModelProvider] = (),
        tokenizer: Tokenizer | None = None,
        max_tasks: int = 100,
        secrets: Callable[[], list[str]] = secret_values,
    ) -> None:
        self.secrets = secrets
        self.validator = validator
        self.executor = executor
        self.tokenizer = tokenizer
        self.fallback = DeterministicFallbackProvider()
        self.providers: dict[str, LanguageModelProvider] = {p.name: p for p in providers}
        self.active_provider = AUTO
        self.max_tasks = max_tasks
        self._tasks: OrderedDict[str, TaskRecord] = OrderedDict()
        self._subs: list[Subscription] = []
        self._lock = threading.RLock()

    # --- providers -------------------------------------------------------------------------
    def provider_statuses(self) -> list[ProviderStatus]:
        return [p.status() for p in (*self.providers.values(), self.fallback)]

    def active_status(self) -> ProviderStatus:
        if self.active_provider == AUTO:
            order = ", ".join([*self.providers, FALLBACK])
            return ProviderStatus(name=AUTO, kind="fallback", configured=True, available=True,
                                  detail=f"tries {order} in order; the deterministic fallback always runs last")
        return self._provider(self.active_provider).status()

    def select_provider(self, provider_id: str) -> ProviderStatus:
        if provider_id != AUTO:
            status = self._provider(provider_id).status()
            if not status.configured:
                raise TaskConflict(f"provider '{provider_id}' is not configured on the server")
        self.active_provider = provider_id
        return self.active_status()

    def _provider(self, provider_id: str) -> LanguageModelProvider:
        if provider_id == FALLBACK:
            return self.fallback
        if provider_id not in self.providers:
            raise TaskNotFound(f"unknown provider '{provider_id}'")
        return self.providers[provider_id]

    def _chain(self) -> ProviderChain:
        if self.active_provider == AUTO:
            return ProviderChain(list(self.providers.values()), self.fallback)
        if self.active_provider == FALLBACK:
            return ProviderChain([], self.fallback)
        return ProviderChain([self.providers[self.active_provider]], self.fallback)

    # --- tasks -----------------------------------------------------------------------------
    def create(self, instruction: str) -> TaskRecord:
        if self.executor.status().e_stop_latched:
            raise TaskConflict("e-stop is latched: reset is required before new tasks")
        record = TaskRecord(task_id=f"task_{uuid.uuid4().hex[:12]}", instruction=self.scrub(instruction)[:2048])
        with self._lock:
            self._tasks[record.task_id] = record
            while len(self._tasks) > self.max_tasks:
                self._tasks.popitem(last=False)
        return record

    def get(self, task_id: str) -> TaskRecord:
        with self._lock:
            if task_id not in self._tasks:
                raise TaskNotFound("task not found")
            return self._tasks[task_id]

    def history(self) -> list[dict[str, Any]]:
        with self._lock:
            return [r.summary() for r in reversed(self._tasks.values())]

    def scrub(self, text: str) -> str:
        """Redact secrets before text is tokenized (which would split them past later redaction) or sent to a model."""
        return redact(text, self.secrets())

    def run(self, task_id: str, instruction: str) -> None:
        """Run the pipeline for a task (worker thread). Never raises."""
        instruction = self.scrub(instruction)
        record = self.get(task_id)
        if record.status == Status.CANCELLED:  # cancelled before it started
            return
        self._set_status(record, Status.RUNNING)
        executor_ok = self.executor.status().can_execute
        try:
            result = run_pipeline(instruction, self._chain(), self.validator, self.tokenizer,
                                  emit=lambda ev: self._emit(record, ev), is_cancelled=record.cancel.is_set,
                                  run_id=record.task_id, executor_connected=executor_ok)
        except Exception as exc:  # a bug must not leave the task 'running' forever
            record.result = {"error": f"internal error ({type(exc).__name__})"}
            self._set_status(record, Status.FAILED)
            return
        record.provider = result.provider
        record.result = {
            "task": result.task.model_dump(mode="json") if result.task else None,
            "plan": result.plan.model_dump(mode="json") if result.plan else None,
            "clarification": result.clarification.model_dump(mode="json") if result.clarification else None,
            "report": result.report.model_dump(mode="json") if result.report else None,
        }
        if result.state == StageState.NEEDS_CLARIFICATION:
            return self._set_status(record, Status.NEEDS_CLARIFICATION)
        if result.state == StageState.CANCELLED or record.cancel.is_set():
            return self._set_status(record, Status.CANCELLED)
        if result.state == StageState.FAILED:
            return self._set_status(record, Status.FAILED)
        if not executor_ok:
            return self._set_status(record, Status.NO_EXECUTOR)
        self._set_status(record, Status.EXECUTING)
        try:
            self.executor.execute(result.task, lambda ev: self._emit(record, ev), record.cancel.is_set)
        except ExecutorError as exc:
            record.result["error"] = str(exc)
            return self._set_status(record, Status.FAILED)
        self._set_status(record, Status.CANCELLED if record.cancel.is_set() else Status.COMPLETED)

    def clarify(self, task_id: str, selected_option: str | None, free_text: str | None) -> str:
        """Validate a clarification answer and return the instruction to re-run."""
        record = self.get(task_id)
        if record.status != Status.NEEDS_CLARIFICATION:
            raise TaskConflict(f"task is '{record.status}', not waiting for clarification")
        options = (record.result.get("clarification") or {}).get("options") or []
        if selected_option is not None and selected_option not in options:
            raise TaskConflict("selected_option is not one of the offered options")
        if not free_text:
            raise TaskConflict("restate the full command in free_text; an option alone cannot be merged safely")
        free_text = self.scrub(free_text)
        record.clarifications.append({"selected_option": selected_option, "free_text": free_text[:2048]})
        record.instruction = free_text[:2048]
        with self._lock:
            record.events.clear()
            record.result = {}
        self._set_status(record, Status.ACCEPTED)
        return free_text

    def cancel(self, task_id: str) -> None:
        record = self.get(task_id)
        if record.status in FINAL:
            raise TaskConflict(f"task is already '{record.status}'")
        record.cancel.set()
        self.executor.cancel(task_id)
        if record.status == Status.ACCEPTED:  # not started yet: it will stop at its first stage
            self._set_status(record, Status.CANCELLED)

    def cancel_all_active(self) -> None:
        with self._lock:
            active = [r for r in self._tasks.values() if r.status not in FINAL]
        for record in active:
            record.cancel.set()
            self.executor.cancel(record.task_id)

    def _set_status(self, record: TaskRecord, status: str) -> None:
        with self._lock:
            record.status, record.updated_at = status, _now()
            frame = {"channel": "task_status", "task_id": record.task_id,
                     "payload": {"status": status, "timestamp": record.updated_at}}
            self._publish(record.task_id, frame)

    # --- events ----------------------------------------------------------------------------
    def _emit(self, record: TaskRecord, ev: PipelineStageEvent) -> None:
        with self._lock:
            record.events.append(ev)
            self._publish(record.task_id, pipeline_frame(record.task_id, len(record.events) - 1, ev))

    def _publish(self, task_id: str, frame: dict[str, Any]) -> None:
        for sub in self._subs:
            if sub.task_id is None or sub.task_id == task_id:
                sub.loop.call_soon_threadsafe(sub.offer, frame)

    def subscribe(self, queue: asyncio.Queue, task_id: str | None) -> Subscription:
        """Register on the running loop; queues the task's past events first (replay)."""
        sub = Subscription(asyncio.get_running_loop(), queue, task_id)
        with self._lock:
            if task_id is not None:
                for seq, ev in enumerate(self.get(task_id).events):
                    sub.offer(pipeline_frame(task_id, seq, ev))
            self._subs.append(sub)
        return sub

    def unsubscribe(self, sub: Subscription | None) -> None:
        with self._lock:
            if sub in self._subs:
                self._subs.remove(sub)
