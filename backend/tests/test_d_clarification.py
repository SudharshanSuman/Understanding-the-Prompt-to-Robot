"""Spec test D: ambiguous instruction -> needs_clarification, no invented target."""


import pytest

from app.schemas import ClarificationRequest, TaskConstraints, TaskPlan


@pytest.mark.parametrize("cmd", [
    "Move the box to the left",        # two boxes + relative direction
    "Move the red cube to the left",    # relative direction only
    "Put the cube on the platform",         # two cubes
    "Put it over there",               # no object, vague place
])
def test_ambiguous_commands_need_clarification(cmd, validator, fallback, world):
    assert isinstance(validator.check_command(cmd) or fallback.parse(cmd, world), ClarificationRequest)


def test_box_to_the_left_explains_why(validator):
    clar = validator.check_command("Move the cube to the left")
    assert clar is not None
    assert set(clar.options) == {"red_cube", "blue_cube"}
    assert validator.check_command("Move the box to the left") is not None  # spec D wording


def test_missing_destination_and_no_verb_clarify(fallback, world):
    assert isinstance(fallback.parse("Pick up the red cube", world), ClarificationRequest)
    assert isinstance(fallback.parse("red cube the platform", world), ClarificationRequest)


@pytest.mark.parametrize("cmd", [
    "Place the red cube next to the storage box",
    "Put the green cylinder beside the platform",
    "Move the red cube to the left of the platform",
    "Put the red cube on top of the blue cube",
])
def test_relative_placement_needs_clarification(cmd, validator):
    assert validator.check_command(cmd) is not None


def test_multi_step_command_needs_clarification(validator, fallback, world):
    cmd = "Pick up the red cube and place it on the platform, then put the green cylinder in the storage box"
    assert isinstance(validator.check_command(cmd), ClarificationRequest)
    assert isinstance(fallback.parse(cmd, world), ClarificationRequest)


def test_two_verb_single_task_is_not_multi_step(validator):
    assert validator.check_command("Pick up the red cube, then place it on the platform") is None
