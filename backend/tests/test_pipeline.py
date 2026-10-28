"""Pipeline stage events over the canonical 14 stages: success, clarification, failure and cancel paths."""

import pytest

from app.pipeline import STAGES, run_pipeline
from app.schemas import HEADLESS_STAGES, PIPELINE_STAGES, PipelineStage, StageState
from app.tokenizer import ApproximateTokenizer

TOK = ApproximateTokenizer()
ROS_STAGES = PIPELINE_STAGES[len(HEADLESS_STAGES):]


def last_states(result):
    return {e.stage: e.state for e in result.events}


def test_stage_list_is_the_canonical_14():
    assert STAGES == tuple(s.value for s in PipelineStage) and len(STAGES) == 14
    assert HEADLESS_STAGES == ("instruction", "tokenization", "interpretation", "structured_task",
                               "schema_validation", "feasibility")


def test_happy_path(chain, validator):
    seen = []
    r = run_pipeline("Put the green cylinder in the storage box, keep it upright", chain, validator, TOK,
                     emit=seen.append)
    assert r.plan.constraints.keep_upright and r.report.ok and r.task.target_object == "green_cylinder"
    assert seen == r.events and all(e.run_id == r.run_id for e in seen)
    assert [(e.stage, e.state) for e in seen[:14]] == [(s, StageState.WAITING) for s in PIPELINE_STAGES]
    states = last_states(r)
    assert states["instruction"] == states["structured_task"] == states["schema_validation"] == StageState.SUCCESS
    assert states["interpretation"] == StageState.WARNING  # deterministic fallback is flagged
    assert states["feasibility"] == StageState.WARNING  # reachability must still be confirmed by MoveIt IK
    # headless: no stage ends waiting; ROS 2 stages close as cancelled (INTERFACE_CONTRACTS s3.2)
    assert all(states[s] == StageState.CANCELLED for s in ROS_STAGES)
    assert all(e.detail["reason"] == "headless_run_complete" for e in r.events[-len(ROS_STAGES):])
    assert all(e.is_terminal for e in r.events if e.stage in states and e is r.events[-1]) and r.state == StageState.WARNING


def test_ros_stages_wait_for_a_connected_executor(chain, validator):
    r = run_pipeline("Put the red cube in the storage box", chain, validator, TOK, executor_connected=True)
    assert all(last_states(r)[s] == StageState.WAITING for s in ROS_STAGES)


def test_ambiguous_command_stops_for_clarification(chain, validator):
    r = run_pipeline("Move the box to the left", chain, validator, TOK)
    assert r.state == StageState.NEEDS_CLARIFICATION and r.plan is None
    states = last_states(r)
    assert states["interpretation"] == StageState.NEEDS_CLARIFICATION
    assert all(states[s] == StageState.CANCELLED for s in STAGES[3:])


def test_unknown_destination_fails_at_interpretation(chain, validator):
    r = run_pipeline("Put the red cube on the spaceship", chain, validator, TOK)
    assert r.state == StageState.FAILED and r.plan is None
    states = last_states(r)
    assert states["interpretation"] == StageState.FAILED
    assert states["schema_validation"] == states["feasibility"] == StageState.CANCELLED
    assert [e.code for e in r.report.errors] == ["UNKNOWN_DESTINATION"]


def test_unreachable_fails_at_feasibility(world):
    from app.validation import SafetyValidator
    from app.providers import ProviderChain

    v = SafetyValidator(world, reachability=lambda p, w: False)
    r = run_pipeline("Move the red cube to the platform", ProviderChain([]), v, TOK)
    states = last_states(r)
    assert states["schema_validation"] == StageState.SUCCESS and states["feasibility"] == StageState.FAILED
    assert r.state == StageState.FAILED and not r.report.ok
    assert all(states[s] == StageState.CANCELLED for s in ROS_STAGES)


@pytest.mark.parametrize("cancel_at", range(len(HEADLESS_STAGES)))
def test_cancel_at_each_headless_stage(chain, validator, cancel_at):
    calls = iter([False] * cancel_at + [True] + [False] * 20)
    r = run_pipeline("Put the green cylinder in the storage box", chain, validator, TOK,
                     is_cancelled=lambda: next(calls))
    assert r.state == StageState.CANCELLED
    assert last_states(r)[HEADLESS_STAGES[cancel_at]] == StageState.CANCELLED
    assert r.report is None or not r.report.ok or cancel_at == len(HEADLESS_STAGES)


def test_empty_command_fails_at_instruction(chain, validator):
    r = run_pipeline("   ", chain, validator, TOK)
    assert r.state == StageState.FAILED and last_states(r)["instruction"] == StageState.FAILED
    assert all(last_states(r)[s] in (StageState.FAILED, StageState.CANCELLED) for s in STAGES)
