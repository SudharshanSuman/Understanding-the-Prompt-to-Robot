"""Command pipeline over the canonical 14 stages (ADR-009), emitting stage events.

Headless (no ROS 2) the backend runs the first six stages:
instruction -> tokenization -> interpretation -> structured_task -> schema_validation -> feasibility.
The ROS 2 stages (grounding ... verification) are announced as 'waiting'. With an executor
connected they stay waiting for it; headless (no executor) a successful run closes them as
'cancelled' with reason 'headless_run_complete' (INTERFACE_CONTRACTS s3.2: no stage ends waiting).
After an upstream failure they are marked 'cancelled'.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass, field

from app.providers.chain import ProviderChain
from app.security import InputRejected, sanitize_instruction
from app.schemas import (
    HEADLESS_STAGES,
    PIPELINE_STAGES,
    ClarificationRequest,
    PipelineStageEvent,
    RoboticTask,
    StageState,
    TaskPlan,
    ValidationReport,
)
from app.tokenizer import TokenizationResult, Tokenizer, get_tokenizer
from app.validation.validator import SafetyValidator

STAGES = PIPELINE_STAGES

Emit = Callable[[PipelineStageEvent], None]

HEADLESS_CLOSEOUT = {"reason": "headless_run_complete",
                     "message": "ROS 2 simulation execution skipped in headless mode"}

_STOPPING = (StageState.FAILED, StageState.CANCELLED, StageState.NEEDS_CLARIFICATION)


@dataclass
class PipelineResult:
    run_id: str
    state: StageState
    instruction: str | None = None
    plan: TaskPlan | None = None
    task: RoboticTask | None = None
    clarification: ClarificationRequest | None = None
    report: ValidationReport | None = None
    tokens: TokenizationResult | None = None
    provider: str | None = None
    events: list[PipelineStageEvent] = field(default_factory=list)


def run_pipeline(
    command: str,
    chain: ProviderChain,
    validator: SafetyValidator,
    tokenizer: Tokenizer | None = None,
    emit: Emit | None = None,
    is_cancelled: Callable[[], bool] = lambda: False,
    run_id: str | None = None,
    executor_connected: bool = False,
) -> PipelineResult:
    result = PipelineResult(run_id=run_id or uuid.uuid4().hex, state=StageState.RUNNING)

    def event(stage: str, state: StageState, message: str = "", extra: dict | None = None, **detail) -> None:
        ev = PipelineStageEvent(run_id=result.run_id, stage=stage, state=state, message=message,
                                detail={**(extra or {}), **detail})
        result.events.append(ev)
        if emit:
            emit(ev)

    def finish(stage: str, state: StageState, message: str, **detail) -> PipelineResult:
        event(stage, state, message, **detail)
        if state in _STOPPING:
            for later in STAGES[STAGES.index(stage) + 1:]:
                event(later, StageState.CANCELLED, f"skipped: {stage} ended {state.value}")
            result.state = state
        return result

    def start(stage: str) -> bool:
        if is_cancelled():
            finish(stage, StageState.CANCELLED, "cancelled by user")
            return False
        event(stage, StageState.RUNNING)
        return True

    for stage in STAGES:
        event(stage, StageState.WAITING, "" if stage in HEADLESS_STAGES else "waiting for ROS 2")

    # 1. instruction: the raw text is untrusted until sanitized.
    if not start("instruction"):
        return result
    try:
        command = sanitize_instruction(command)
    except InputRejected as exc:
        return finish("instruction", StageState.FAILED, f"input rejected: {exc}")
    result.instruction = command
    finish("instruction", StageState.SUCCESS, "instruction accepted", instruction=command)

    # 2. tokenization: for inspection only, never decides an action.
    if not start("tokenization"):
        return result
    result.tokens = (tokenizer or get_tokenizer()).tokenize(command)
    finish("tokenization", StageState.WARNING if result.tokens.is_approximate else StageState.SUCCESS,
           result.tokens.note, tokenization=result.tokens.model_dump())

    # 3. interpretation: deterministic word checks first, so no model can guess past them.
    if not start("interpretation"):
        return result
    unknown = validator.check_references(command)
    if unknown is not None:
        result.report = unknown
        return finish("interpretation", StageState.FAILED, "; ".join(e.message for e in unknown.errors),
                      errors=[e.model_dump() for e in unknown.errors])
    clarification = validator.check_command(command)
    if clarification is not None:
        result.clarification = clarification
        return finish("interpretation", StageState.NEEDS_CLARIFICATION, clarification.question,
                      clarification=clarification.model_dump())
    parsed = chain.parse(command, validator.world)
    result.provider = parsed.provider
    attempts = [a.__dict__ for a in parsed.attempts]
    if isinstance(parsed.parsed, ClarificationRequest):
        result.clarification = parsed.parsed
        return finish("interpretation", StageState.NEEDS_CLARIFICATION, parsed.parsed.question,
                      provider=parsed.provider, attempts=attempts, clarification=parsed.parsed.model_dump())
    finish("interpretation", StageState.WARNING if parsed.used_fallback else StageState.SUCCESS,
           f"interpreted by {parsed.provider}" + (" (deterministic fallback)" if parsed.used_fallback else ""),
           provider=parsed.provider, attempts=attempts)

    # 4. structured_task: the proposal as data, not yet trusted.
    if not start("structured_task"):
        return result
    plan = parsed.parsed
    task = RoboticTask.from_plan(plan, task_id=result.run_id)
    result.plan, result.task = plan, task  # inspectable; executable only if the run ends success/warning
    finish("structured_task", StageState.SUCCESS, "task proposal built",
           plan=plan.model_dump(mode="json"), task=task.model_dump(mode="json"))

    # 5. schema_validation: strict schema re-check plus scene and request consistency.
    if not start("schema_validation"):
        return result
    plan = TaskPlan.model_validate(plan.model_dump())
    scene = validator.check_scene(plan, command)
    if not scene.ok:
        result.report = scene
        return finish("schema_validation", StageState.FAILED, "; ".join(e.message for e in scene.errors),
                      errors=[e.model_dump() for e in scene.errors])
    finish("schema_validation", StageState.SUCCESS, "task matches the schema, the scene and the request")

    # 6. feasibility: reachability (pluggable; MoveIt IK confirms at L1) and confidence.
    if not start("feasibility"):
        return result
    feasible = validator.check_feasibility(plan)
    result.report = ValidationReport(ok=feasible.ok, errors=feasible.errors,
                                     warnings=[*scene.warnings, *feasible.warnings])
    if not feasible.ok:
        return finish("feasibility", StageState.FAILED, "; ".join(e.message for e in feasible.errors),
                      errors=[e.model_dump() for e in feasible.errors])
    finish("feasibility", StageState.WARNING if result.report.warnings else StageState.SUCCESS,
           "; ".join(w.message for w in result.report.warnings) or "task is feasible",
           warnings=[w.model_dump() for w in result.report.warnings])

    result.state = StageState.WARNING if any(e.state == StageState.WARNING for e in result.events) else StageState.SUCCESS
    if not executor_connected:
        for later in STAGES[len(HEADLESS_STAGES):]:
            event(later, StageState.CANCELLED, "no executor connected", HEADLESS_CLOSEOUT)
    return result
