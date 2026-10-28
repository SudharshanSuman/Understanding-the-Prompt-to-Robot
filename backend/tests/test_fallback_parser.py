"""Deterministic fallback parser: supported single pick-and-place commands."""


import pytest

from app.schemas import ClarificationRequest, TaskConstraints, TaskPlan


def plan(**kw):
    base = dict(action="pick_and_place", object="red_cube", destination="platform", confidence=1.0)
    return TaskPlan(**{**base, **kw})


def test_full_command_parses(fallback, world, validator):
    result = fallback.parse(
        "Pick up the red cube and place it on the platform. Avoid the blue cube and keep it upright.", world)
    assert isinstance(result, TaskPlan)
    assert (result.object, result.destination) == ("red_cube", "platform")
    assert result.constraints == TaskConstraints(avoid_objects=["blue_cube"], keep_upright=True)
    assert validator.validate_plan(result).ok


def test_parser_is_deterministic(fallback, world):
    cmd = "Put the green cylinder in the storage box"
    assert fallback.parse(cmd, world) == fallback.parse(cmd, world)


def test_no_upright_by_default(fallback, world):
    result = fallback.parse("Move the blue cube to the left side of the table", world)
    assert isinstance(result, TaskPlan)
    assert result.constraints.keep_upright is False and result.destination == "table_left"


def test_low_confidence_is_warning_not_error(validator):
    report = validator.validate_plan(plan(confidence=0.3))
    assert report.ok and "LOW_CONFIDENCE" in {w.code for w in report.warnings}
