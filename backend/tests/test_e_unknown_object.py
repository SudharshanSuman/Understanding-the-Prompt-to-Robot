"""Spec test E: unknown object or destination -> rejected by name, no executable plan."""


import pytest

from app.schemas import ClarificationRequest, TaskConstraints, TaskPlan


def plan(**kw):
    base = dict(action="pick_and_place", object="red_cube", destination="platform", confidence=1.0)
    return TaskPlan(**{**base, **kw})


def test_unknown_object_rejected(fallback, world, validator):
    result = fallback.parse("Put the purple box on the platform", world)
    assert isinstance(result, TaskPlan) and result.object == "purple_box"
    report = validator.validate_plan(result)
    assert not report.ok and [e.code for e in report.errors] == ["UNKNOWN_OBJECT"]


def test_unknown_destination_rejected(fallback, world, validator):
    result = fallback.parse("Put the red cube on the spaceship", world)
    assert isinstance(result, TaskPlan) and result.destination == "spaceship"
    report = validator.validate_plan(result)
    assert [e.code for e in report.errors] == ["UNKNOWN_DESTINATION"]


def test_validator_rejects_bad_plans_from_any_source(validator):
    assert [e.code for e in validator.validate_plan(plan(object="table")).errors] == ["OBJECT_NOT_GRASPABLE"]
    bad = plan(constraints=TaskConstraints(avoid_objects=["ghost"]))
    assert [e.code for e in validator.validate_plan(bad).errors] == ["UNKNOWN_AVOID_OBJECT"]
