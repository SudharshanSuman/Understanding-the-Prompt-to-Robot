"""X1/X3: the strict task schema. Spec section 6 example shape, extra/wrong fields rejected."""
import pytest
from pydantic import ValidationError

from tests.support.adapter import backend

pytestmark = [pytest.mark.unit]


@pytest.fixture
def s():
    return backend("app.schemas")


def _plan(**over):
    base = dict(action="pick_and_place", object="red_cube", destination="platform", confidence=0.9)
    return {**base, **over}


def test_valid_plan_with_constraints_round_trips(s):
    p = s.TaskPlan(**_plan(constraints={"avoid_objects": ["blue_cube"], "keep_upright": True}))
    assert s.TaskPlan.model_validate_json(p.model_dump_json()) == p


@pytest.mark.parametrize("drop", ["action", "object", "destination", "confidence"])
def test_missing_required_field_rejected(s, drop):
    bad = _plan()
    bad.pop(drop)
    with pytest.raises(ValidationError):
        s.TaskPlan(**bad)


@pytest.mark.parametrize("over", [
    {"extra_key": 1},                                   # unknown field
    {"action": "fly"},                                  # unknown action
    {"object": "Red Box"},                              # not a snake_case id
    {"object": "x" * 65},                               # too long
    {"destination": "red_cube", "object": "red_cube"},    # same object and destination
    {"confidence": 1.5}, {"confidence": -0.1},
    {"constraints": {"avoid_objects": ["red_cube"]}},    # target in avoid list
    {"constraints": {"avoid_objects": ["a", "a"]}},     # duplicates
    {"constraints": {"unknown": True}},
    {"object": "red_cube; rm -rf /"},                    # injection-shaped id
])
def test_bad_plan_rejected(s, over):
    with pytest.raises(ValidationError):
        s.TaskPlan(**_plan(**over))


def test_plan_is_immutable(s):
    p = s.TaskPlan(**_plan())
    with pytest.raises(ValidationError):
        p.object = "blue_cube"


def test_validation_report_ok_must_match_errors(s):
    with pytest.raises(ValidationError):
        s.ValidationReport(ok=True, errors=[s.ValidationIssue(code="X", message="m")])
    with pytest.raises(ValidationError):
        s.ValidationReport(ok=False, errors=[])


def test_clarification_requires_a_question(s):
    with pytest.raises(ValidationError):
        s.ClarificationRequest(question="", reason="r")


def test_stage_states_match_spec_section_5(s):
    from tests.support.adapter import UI_STATES
    assert {m.value for m in s.StageState} == UI_STATES
