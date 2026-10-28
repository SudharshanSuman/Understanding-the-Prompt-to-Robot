"""TEST-ONLY launcher: the real create_app + real uvicorn, with optional fakes picked by env.

Used by tests/api/helpers.py. Nothing here is imported by the product. Fakes:
  MD_TEST_EXECUTOR   sim (default) | stuck (e-stop does not stop) | toggle (state read from MD_TEST_STATE_FILE)
  MD_TEST_PROVIDERS  none (default, fallback only) | slow (sleeps MD_TEST_SLOW_SECONDS then fails) | real (product default)
  MD_TEST_AUTH_FAILS / MD_TEST_WS_IDLE / MD_TEST_WS_AUTH   override Settings limits
"""
from __future__ import annotations

import dataclasses
import os
import threading
import time
from pathlib import Path

import uvicorn

from app.config import Settings
from app.executor import Executor, ExecutorError, ExecutorStatus, SimulatedExecutor, StopReport
from app.main import create_app, default_providers
from app.providers import LanguageModelProvider, ProviderStatus, ProviderUnavailable
from app.schemas import PipelineStageEvent, StageState


class SlowProvider(LanguageModelProvider):
    name, kind = "cloud", "cloud"

    def status(self):
        return ProviderStatus(name=self.name, kind=self.kind, configured=True, available=True, detail="slow test provider")

    def parse(self, command, world):
        time.sleep(float(os.environ.get("MD_TEST_SLOW_SECONDS", "3")))
        raise ProviderUnavailable("slow test provider gave up")


class ToggleExecutor(Executor):
    """State file: connected | disconnected | crash (execute raises RuntimeError) | drop (ExecutorError mid-run)."""

    name = "toggle_test"

    def __init__(self, state_file: str) -> None:
        self.state_file, self.log_file = Path(state_file), Path(state_file + ".log")
        self.latched = False
        self.lock = threading.Lock()

    def _state(self) -> str:
        try:
            return self.state_file.read_text().strip() or "disconnected"
        except OSError:
            return "disconnected"

    def _log(self, line: str) -> None:
        with self.lock, self.log_file.open("a") as fh:
            fh.write(line + "\n")

    def status(self) -> ExecutorStatus:
        up = self._state() != "disconnected"
        return ExecutorStatus(name=self.name, connected=up, can_execute=up and not self.latched, e_stop_latched=self.latched,
                              controller_state="STOPPED" if self.latched else "IDLE", detail=f"state={self._state()}")

    def execute(self, task, emit, is_cancelled) -> None:
        run_id = getattr(task, "task_id", "task")
        self._log(f"execute {run_id}")
        state = self._state()
        if state == "crash":
            raise RuntimeError("simulated executor bug")
        emit(PipelineStageEvent(run_id=run_id, stage="grounding", state=StageState.RUNNING, message="test executor"))
        if state == "drop":
            raise ExecutorError("executor disconnected during execution")
        deadline = time.monotonic() + float(os.environ.get("MD_TEST_EXEC_SECONDS", "8"))
        while time.monotonic() < deadline:
            if is_cancelled():
                self._log(f"cancel-seen {run_id}")
                return
            time.sleep(0.05)
        emit(PipelineStageEvent(run_id=run_id, stage="grounding", state=StageState.SUCCESS, message="test executor done"))

    def cancel(self, task_id: str) -> None:
        self._log(f"cancel {task_id}")

    def emergency_stop(self) -> StopReport:
        self.latched = True
        self._log("estop")
        return StopReport(status="e_stop_confirmed", controller_state="STOPPED", max_joint_velocity=0.0,
                          source="toggle test executor")

    def reset(self) -> ExecutorStatus:
        self.latched = False
        self._log("reset")
        return self.status()


def build():
    settings = Settings.from_env()
    over = {}
    for env, field, cast in (("MD_TEST_AUTH_FAILS", "auth_failures_per_min", int), ("MD_TEST_WS_IDLE", "ws_idle_seconds", float),
                             ("MD_TEST_WS_AUTH", "ws_auth_seconds", float)):
        if os.environ.get(env):
            over[field] = cast(os.environ[env])
    settings = dataclasses.replace(settings, **over).validate()
    kind = os.environ.get("MD_TEST_EXECUTOR", "sim")
    executor = {"sim": lambda: SimulatedExecutor(),
                "stuck": lambda: SimulatedExecutor(joint_velocities=[0.0, 0.5, 0, 0, 0, 0, 0], stop_effective=False),
                "toggle": lambda: ToggleExecutor(os.environ["MD_TEST_STATE_FILE"])}[kind]()
    mode = os.environ.get("MD_TEST_PROVIDERS", "none")
    providers = {"none": [], "slow": [SlowProvider()], "real": default_providers()}[mode]
    return settings, create_app(settings, providers=providers, executor=executor)


if __name__ == "__main__":
    cfg, application = build()
    uvicorn.run(application, host=cfg.host, port=cfg.port, server_header=False)
