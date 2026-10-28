"""Spec test D (provisional mapping): the task schema is strict."""

import pytest
from pydantic import TypeAdapter, ValidationError

from app.schemas import (
    ClarificationRequest, ParsedCommand, PipelineStageEvent, StageState, TaskPlan, ValidationReport,
)

VALID = {
    "kind": "task",
    "action": "pick_and_place",
    "object": "red_cube",
    "destination": "platform",
    "constraints": {"avoid_objects": ["blue_cube"], "keep_upright": True},
    "confidence": 0.9,
}


def test_valid_plan_round_trips():
    plan = TaskPlan.model_validate(VALID)
    assert plan.constraints.keep_upright is True
    assert plan.constraints.avoid_objects == ["blue_cube"]
    assert TaskPlan.model_validate_json(plan.model_dump_json()) == plan


def test_constraints_default_to_empty():
    plan = TaskPlan.model_validate({k: v for k, v in VALID.items() if k != "constraints"})
    assert plan.constraints.avoid_objects == [] and plan.constraints.keep_upright is False


@pytest.mark.parametrize("patch", [
    {"extra_field": 1},
    {"action": "throw"},
    {"object": ""},
    {"object": "Red Box"},
    {"destination": "the platform"},
    {"confidence": 1.5},
    {"confidence": -0.1},
    {"schema_version": "2.0"},
    {"constraints": {"avoid_objects": ["red_cube"]}},          # target in avoid list
    {"constraints": {"avoid_objects": ["a", "a"]}},           # duplicates
    {"constraints": {"keep_upright": True, "speed": "fast"}},  # unknown constraint
    {"destination": "red_cube"},                                # object == destination
])
def test_invalid_plans_rejected(patch):
    with pytest.raises(ValidationError):
        TaskPlan.model_validate({**VALID, **patch})


def test_missing_required_field_rejected():
    with pytest.raises(ValidationError):
        TaskPlan.model_validate({k: v for k, v in VALID.items() if k != "destination"})


def test_parsed_command_discriminates_on_kind():
    adapter = TypeAdapter(ParsedCommand)
    assert isinstance(adapter.validate_python(VALID), TaskPlan)
    clar = adapter.validate_python({"kind": "clarification", "question": "Which box?", "reason": "two boxes"})
    assert isinstance(clar, ClarificationRequest)
    with pytest.raises(ValidationError):
        adapter.validate_python({**VALID, "kind": "unknown"})


def test_validation_report_ok_must_match_errors():
    with pytest.raises(ValidationError):
        ValidationReport(ok=True, errors=[{"code": "UNKNOWN_OBJECT", "message": "x"}])
    with pytest.raises(ValidationError):
        ValidationReport(ok=False)


def test_stage_event_states_cover_spec():
    assert {s.value for s in StageState} == {
        "waiting", "running", "success", "warning", "failed", "cancelled", "needs_clarification"}
    ev = PipelineStageEvent(run_id="r1", stage="interpretation", state="needs_clarification")
    assert ev.is_terminal and ev.timestamp.tzinfo is not None
    assert not PipelineStageEvent(run_id="r1", stage="interpretation", state="running").is_terminal
    with pytest.raises(ValidationError):
        PipelineStageEvent(run_id="r1", stage="interpretation", state="paused")


def test_robotic_task_contract_ca3():
    from app.schemas import RoboticTask, Task

    assert Task is RoboticTask
    t = RoboticTask.from_plan(TaskPlan.model_validate(VALID), task_id="task_001")
    assert (t.task_type, t.object, t.destination, t.verification_required) == (
        "pick_and_place", "red_cube", "platform", True)
    RoboticTask(task_id="t", target_object="red_cube")  # destination optional per contract
    with pytest.raises(ValidationError):
        RoboticTask(task_id="t", target_object="red_cube", speed=3)
    with pytest.raises(ValidationError):
        RoboticTask(task_id="", target_object="red_cube")
