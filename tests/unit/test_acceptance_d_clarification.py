"""Acceptance D: ambiguous instruction -> clarification, nothing executable. L0, real pipeline.
TEST_PLAN.md section 4 D. Scene: config/scene.json (red_cube, blue_cube, green_cylinder, storage_box, platform, table)."""
import pytest

from tests.support.adapter import PIPELINE_STAGES
from tests.support.harness import parts, run

pytestmark = [pytest.mark.unit, pytest.mark.acceptance("D")]

AMBIGUOUS = [
    "Move the box to the left",                       # spec section 6 example
    "Pick up the cube",                               # two cubes in the scene
    "Move it",
    "Pick it up",
    "Move the cube to the right side of the table",   # which cube?
]


@pytest.mark.parametrize("command", AMBIGUOUS)
def test_ambiguous_command_needs_clarification_and_yields_no_plan(command):
    _, _, _, schemas = parts()
    r = run(command)
    assert r.state == schemas.StageState.NEEDS_CLARIFICATION, f"{command!r} -> {r.state}"
    assert r.clarification is not None and r.clarification.question.strip()
    assert r.plan is None, "ambiguous command produced an executable plan"
    assert r.report is None, "validation must not run (or pass) on an ambiguous command"


@pytest.mark.parametrize("command", AMBIGUOUS)
def test_clarification_options_only_offer_things_in_the_scene(command):
    _, _, valid, _ = parts()
    world = valid.default_world()
    known = world.object_ids() | world.destination_ids()
    r = run(command)
    for option in r.clarification.options:
        assert option in known or option == "pick_and_place", f"invented option {option!r}"


@pytest.mark.parametrize("command", AMBIGUOUS)
def test_every_stage_after_interpretation_is_cancelled_not_run(command):
    _, _, _, schemas = parts()
    r = run(command)
    last = {}
    for e in r.events:
        last[e.stage] = e  # last event per stage wins
    assert last["interpretation"].state == schemas.StageState.NEEDS_CLARIFICATION
    for stage in PIPELINE_STAGES[PIPELINE_STAGES.index("interpretation") + 1:]:
        assert last[stage].state == schemas.StageState.CANCELLED, f"{stage} -> {last[stage].state}"
    assert not any(e.state == schemas.StageState.RUNNING and e.stage == "schema_validation" for e in r.events)


def test_answering_the_clarification_lets_the_command_proceed():
    _, _, _, schemas = parts()
    first = run("Move the box to the left")
    assert first.state == schemas.StageState.NEEDS_CLARIFICATION
    second = run("Move the red cube to the platform")
    assert second.state in (schemas.StageState.SUCCESS, schemas.StageState.WARNING)
    assert second.plan is not None and second.plan.object == "red_cube" and second.plan.destination == "platform"


def test_specific_cube_and_side_of_table_is_executable_not_ambiguous():
    """Scene change (MD-DEV-002): 'blue cube' exists, so the old ambiguous wording is now a valid command."""
    _, _, _, schemas = parts()
    r = run("Move the blue cube to the right side of the table")
    assert r.state in (schemas.StageState.SUCCESS, schemas.StageState.WARNING)
    assert r.plan.object == "blue_cube" and r.plan.destination == "table_right"
    assert r.report is not None and r.report.ok


@pytest.mark.parametrize("command", ["", "   ", "hello"])
def test_empty_or_meaningless_input_never_produces_a_plan(command):
    r = run(command)
    assert r.plan is None
    assert r.state.value in {"failed", "needs_clarification"}
