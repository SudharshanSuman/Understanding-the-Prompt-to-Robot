"""MD-DEV-002: spec scene from config, unknown-object reporting, plan-vs-request checks, reachability hook."""

import json

import pytest

from app.pipeline import run_pipeline
from app.providers import LanguageModelProvider, ProviderChain, ProviderStatus
from app.schemas import StageState, TaskConstraints, TaskPlan
from app.tokenizer import ApproximateTokenizer
from app.validation import SafetyValidator, WorldModel, default_world

TOK = ApproximateTokenizer()


def run(cmd, validator, providers=()):
    return run_pipeline(cmd, ProviderChain(list(providers)), validator, TOK)


def executable(r):
    return r.plan is not None and r.report is not None and r.report.ok


class Fixed(LanguageModelProvider):
    name, kind = "cloud", "cloud"

    def __init__(self, result):
        self.result = result

    def status(self):
        return ProviderStatus(name=self.name, kind=self.kind, configured=True, available=True)

    def parse(self, command, world):
        return self.result


def plan(**kw):
    base = dict(action="pick_and_place", object="red_cube", destination="storage_box", confidence=0.9)
    return TaskPlan(**{**base, **kw})


def test_scene_is_the_spec_scene_from_config(world):
    assert world.object_ids() == {"red_cube", "blue_cube", "green_cylinder", "storage_box", "platform", "table"}
    assert world.destination_ids() == {"storage_box", "platform", "table_left", "table_right"}
    assert all(o.reachable is None and o.pose is None for o in world.objects)


def test_scene_path_can_be_overridden(tmp_path, monkeypatch):
    scene = {"objects": [{"id": "mug", "type": "mug", "pose": {"x": 0.4, "y": 0.0, "z": 0.8}, "reachable": True}],
             "destinations": [{"id": "tray", "reachable": True}]}
    path = tmp_path / "scene.json"
    path.write_text(json.dumps(scene))
    monkeypatch.setenv("MD_SCENE_CONFIG", str(path))
    world = default_world()
    assert world.object_ids() == {"mug"} and world.objects[0].pose.x == 0.4


@pytest.mark.parametrize("cmd,expected", [
    ("Pick up the red cube and place it inside the storage box", ("red_cube", "storage_box", [])),
    ("Move the red cube to the storage box without touching the blue cube", ("red_cube", "storage_box", ["blue_cube"])),
    ("Move the blue cube to the right side of the table", ("blue_cube", "table_right", [])),
    ("Pick up the green cylinder and place it on the platform", ("green_cylinder", "platform", [])),
    ("Move the red cube to the box", ("red_cube", "storage_box", [])),
])
def test_spec_commands_give_executable_plans(cmd, expected, validator):
    r = run(cmd, validator)
    assert executable(r), (r.state, r.clarification, r.report)
    assert (r.plan.object, r.plan.destination, r.plan.constraints.avoid_objects) == expected


def test_unconfirmed_reachability_is_a_warning_for_moveit(validator):
    r = run("Move the blue cube to the right side of the table", validator)
    assert [w.code for w in r.report.warnings] == ["REACHABILITY_UNCONFIRMED"]
    assert "MoveIt IK" in r.report.warnings[0].message


def test_pluggable_reachability_rejects(world):
    v = SafetyValidator(world, reachability=lambda p, w: p.destination != "table_right")
    r = run("Move the blue cube to the right side of the table", v)
    assert r.state == StageState.FAILED and [e.code for e in r.report.errors] == ["UNREACHABLE"]
    assert executable(run("Move the blue cube to the platform", v))


def test_scene_reachable_flags_are_used():
    scene = default_world().model_dump()
    for o in scene["objects"]:
        o["reachable"] = True
    for d in scene["destinations"]:
        d["reachable"] = d["id"] != "table_left"
    v = SafetyValidator(WorldModel.model_validate(scene))
    assert run("Move the red cube to the platform", v).report.warnings == []
    assert [e.code for e in run("Move the red cube to the left side", v).report.errors] == ["UNREACHABLE"]


@pytest.mark.parametrize("cmd,name", [
    ("Pick up the purple elephant", "purple_elephant"),
    ("Pick up the purple box and put it on the platform", "purple_box"),
    ("Bring the ball to the platform", "ball"),
])
def test_unknown_object_reported_by_name(cmd, name, validator):
    r = run(cmd, validator)
    assert r.state == StageState.FAILED and r.clarification is None
    assert r.report.errors[0].code == "UNKNOWN_OBJECT" and name in r.report.errors[0].message


@pytest.mark.parametrize("cmd", ["Pick up the thing on the left", "Move it", "Pick up the cube", "hello"])
def test_underspecified_commands_still_clarify(cmd, validator):
    assert run(cmd, validator).state == StageState.NEEDS_CLARIFICATION


@pytest.mark.parametrize("cmd", [
    "Do not move the red cube to the storage box",
    "Never pick the red cube and put it on the platform",
    "Don't put the red cube on the platform",
])
def test_negated_commands_are_not_executable(cmd, validator):
    assert run(cmd, validator).state == StageState.NEEDS_CLARIFICATION


@pytest.mark.parametrize("cmd", [
    "Move the red cube to the storage box and then move the blue cube to the platform",
    "Move the red cube to the storage box, then to the platform",
])
def test_multi_step_commands_are_not_truncated(cmd, validator):
    assert run(cmd, validator).state == StageState.NEEDS_CLARIFICATION


@pytest.mark.parametrize("cmd,bad,code", [
    ("Move the red cube to the platform", plan(object="blue_cube", destination="platform"), "PLAN_MISMATCH"),
    ("Move the red cube to the platform", plan(destination="storage_box"), "PLAN_MISMATCH"),
    ("Move the red cube to the platform without touching the blue cube", plan(destination="platform"),
     "CONSTRAINT_DROPPED"),
    ("Move the red cube to the platform keeping it upright", plan(destination="platform"), "CONSTRAINT_DROPPED"),
])
def test_model_plan_must_match_the_request(cmd, bad, code, validator):
    r = run(cmd, validator, [Fixed(bad)])
    assert r.provider == "cloud" and r.state == StageState.FAILED
    assert code in {e.code for e in r.report.errors}


def test_matching_model_plan_is_accepted(validator):
    good = plan(destination="platform", constraints=TaskConstraints(avoid_objects=["blue_cube"]))
    r = run("Move the red cube to the platform without touching the blue cube", validator, [Fixed(good)])
    assert r.provider == "cloud" and executable(r)


@pytest.mark.parametrize("exc", [RuntimeError("x"), TimeoutError("t"), ValueError("v"), KeyError("k")])
def test_unexpected_provider_exception_falls_back(exc, validator):
    class Boom(Fixed):
        def parse(self, command, world):
            raise exc

    r = run("Move the red cube to the platform", validator, [Boom(None)])
    assert r.provider == "fallback" and executable(r)
    parsing = [e for e in r.events if e.stage == "interpretation"][-1]
    assert parsing.detail["attempts"][0]["outcome"] == "failed"
