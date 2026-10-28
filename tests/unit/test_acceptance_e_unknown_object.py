"""Acceptance E (and the L0 half of F): unknown or invalid things are rejected, nothing executable.
TEST_PLAN.md section 4 E/F. The pipeline has no executor, so 'no motion' == 'no validated plan'."""
import pytest

from tests.support.harness import make_fakes, parts, run

pytestmark = [pytest.mark.unit, pytest.mark.acceptance("E")]


def _not_executable(r):
    return r.plan is None or r.report is None or not r.report.ok


@pytest.mark.parametrize("command,code,named", [
    ("Put the red cube in the spaceship", "UNKNOWN_DESTINATION", "spaceship"),
    ("Pick up the purple cube and put it on the platform", "UNKNOWN_OBJECT", "purple_cube"),
    ("Move the blue box to the right side of the table", "UNKNOWN_OBJECT", "blue_box"),   # scene has a blue cube, no box
])
def test_unknown_name_is_rejected_by_name(command, code, named):
    _, _, _, schemas = parts()
    r = run(command)
    assert r.state == schemas.StageState.FAILED
    assert code in {e.code for e in r.report.errors}
    assert named in " ".join(e.message for e in r.report.errors)
    assert _not_executable(r)


def test_purple_elephant_is_not_executable():
    r = run("Pick up the purple elephant")
    assert r.state.value in {"failed", "needs_clarification"}
    assert _not_executable(r)


def test_model_cannot_smuggle_an_unknown_object_past_validation():
    """Model output is untrusted: a well-formed plan for an object that is not in the scene must fail."""
    _, _, _, schemas = parts()
    _, _, Fixed, _ = make_fakes()
    hostile = schemas.TaskPlan(action="pick_and_place", object="ghost_cube", destination="platform", confidence=0.99)
    r = run("Move the red cube to the platform", providers=[Fixed(hostile)])
    assert r.provider == "cloud"
    assert r.state == schemas.StageState.FAILED
    assert "UNKNOWN_OBJECT" in {e.code for e in r.report.errors}


def test_unknown_avoid_object_is_rejected():
    _, _, _, schemas = parts()
    _, _, Fixed, _ = make_fakes()
    plan = schemas.TaskPlan(action="pick_and_place", object="red_cube", destination="platform", confidence=0.9,
                            constraints=schemas.TaskConstraints(avoid_objects=["ghost"]))
    r = run("Move the red cube to the platform", providers=[Fixed(plan)])
    assert r.state == schemas.StageState.FAILED
    assert "UNKNOWN_AVOID_OBJECT" in {e.code for e in r.report.errors}


@pytest.mark.acceptance("F")
@pytest.mark.parametrize("command", [
    "Move the red cube to x=5 y=5 z=-1",     # raw coordinates are not a destination the robot can accept
    "Pick up the table and put it on the platform",   # not graspable
])
def test_invalid_target_is_rejected_before_execution(command):
    r = run(command)
    assert r.state.value == "failed", f"{command!r} -> {r.state}"
    assert _not_executable(r)


@pytest.mark.acceptance("F")
def test_unreachable_plan_is_rejected_at_feasibility_and_later_stages_are_cancelled():
    seen = []

    def unreachable(plan, world):
        seen.append((plan.object, plan.destination, world))
        return False

    _, _, _, schemas = parts()
    r = run("Move the red cube to the platform", reachability=unreachable)
    assert seen and seen[0][:2] == ("red_cube", "platform"), "reachability callback not given the plan"
    assert r.state == schemas.StageState.FAILED
    assert "UNREACHABLE" in {e.code for e in r.report.errors}
    assert _not_executable(r)
    last = {e.stage: e for e in r.events}
    assert last["feasibility"].state == schemas.StageState.FAILED
    for stage in ("grounding", "planning_scene", "ik", "planning", "trajectory_validation", "execution",
                  "simulation", "verification"):
        assert last[stage].state == schemas.StageState.CANCELLED, stage


@pytest.mark.acceptance("F")
def test_unknown_reachability_is_a_warning_that_says_moveit_must_confirm():
    _, _, _, schemas = parts()
    r = run("Move the red cube to the platform", reachability=lambda plan, world: None)
    assert r.state in (schemas.StageState.SUCCESS, schemas.StageState.WARNING)
    warn = [w for w in r.report.warnings if w.code == "REACHABILITY_UNCONFIRMED"]
    assert warn and "MoveIt" in warn[0].message


@pytest.mark.acceptance("F")
def test_confirmed_reachability_adds_no_reachability_warning():
    r = run("Move the red cube to the platform", reachability=lambda plan, world: True)
    assert r.report.ok and not [w for w in r.report.warnings if "REACHAB" in w.code]


@pytest.mark.acceptance("F")
def test_scene_flag_reachable_false_blocks_the_plan():
    """Default checker reads the scene's own reachable flags (config/scene.json is null = unknown today)."""
    _, _, valid, schemas = parts()
    world = valid.default_world()
    dest = world.get_destination("platform")
    world = world.model_copy(update={"destinations": [
        d.model_copy(update={"reachable": False}) if d.id == "platform" else d for d in world.destinations]})
    assert dest is not None and world.get_destination("platform").reachable is False
    r = run("Move the red cube to the platform", world=world)
    assert r.state == schemas.StageState.FAILED and "UNREACHABLE" in {e.code for e in r.report.errors}


@pytest.mark.acceptance("F")
def test_scene_has_no_poses_yet_so_reachability_is_unknown_by_default():
    """Documents the remaining gap: config/scene.json has pose=null / reachable=null for everything, so a real
    run is only ever REACHABILITY_UNCONFIRMED until the Gazebo scene / MoveIt IK supply data."""
    _, _, valid, _ = parts()
    w = valid.default_world()
    assert all(o.pose is None and o.reachable is None for o in w.objects)
    r = run("Move the red cube to the platform")
    assert "REACHABILITY_UNCONFIRMED" in {x.code for x in r.report.warnings}
