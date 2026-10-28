"""L1 against the REAL simulation (ROS milestone 1: Panda in Gazebo + ros2_control + trajectory/gripper controllers).

Needs: ROS sourced (jazzy + ros2_ws/install), `MD_RUN_GAZEBO=1` (the sim is a Gazebo launch, ~1.5 GB RAM: run ONE sim at a time).
One simulation is started for the whole module (see `sim` below) and shut down by `test_zz_clean_shutdown`.
Results of the last run are in tests/reports/ros/.
"""
from __future__ import annotations

import json
import math
import time

import pytest

from tests.ros import rig as R
from tests.support import tolerances as T

pytestmark = [pytest.mark.gazebo, pytest.mark.timeout(240)]

TARGET = [0.4, -0.5, 0.0, -2.0, 0.0, 1.8, 0.785]   # inside every Panda limit


@pytest.fixture(scope="module")
def sim(repo_root):
    ws = repo_root / "ros2_ws"
    if not (ws / "install" / "setup.bash").exists():
        pytest.skip("ros2_ws is not built (colcon build in ros2_ws/)")
    other = R.sims_in_test_domain()
    if other:
        pytest.fail(f"another simulation is already running in the test ROS domain {R.DOMAIN_ID} (it would contaminate this run): {other}")
    s = R.SimProcess(ws)
    rig = None
    try:
        s.start()
        rig = R.Rig()
        s.rig = rig

        def ready():
            c = rig.list_controllers(2.0)
            return bool(s.alive() and c and c.keys() >= R.CONTROLLERS.keys() and all(st == "active" for _, st in c.values()) and rig.pos() is not None)
        if not rig.wait_for(ready, 150, step=2):
            tail = s.log_path.read_text(errors="replace")[-1500:] if s.log_path.exists() else ""
            pytest.fail(f"simulation did not become ready in 150 s (launch alive={s.alive()}). Tail of launch log:\n{tail}")
        yield s
    finally:                                   # whatever went wrong above, never leave a simulation behind
        if not getattr(s, "shut", False):
            if rig is not None:
                rig.close()
            s.shutdown()


@pytest.fixture
def rig(sim):
    if not sim.alive():       # nothing of ours sends signals mid-run, so say so instead of failing 10 tests with "server missing"
        pytest.fail(f"the simulation was terminated from outside during the run (launch exit code {sim.proc.returncode}); see tests/reports/ros/sim_launch.log")
    sim.rig.go_home()
    return sim.rig


# ---- milestone 1: the simulation is up and honest --------------------------------------------------------------------------
def test_M1_exactly_the_three_expected_controllers_are_active(rig):
    got = rig.list_controllers()
    assert got == {name: (typ, "active") for name, typ in R.CONTROLLERS.items()}, got


def test_M1_action_servers_exist_with_the_contract_names(rig):
    assert rig.arm_ac.wait_for_server(5), R.ARM_ACTION
    assert rig.hand_ac.wait_for_server(5), R.HAND_ACTION


def test_M1_joint_states_have_all_nine_joints_finite_and_at_the_initial_pose(rig):
    p = rig.wait_for(lambda: rig.pos(R.ARM + R.HAND), 10)
    assert p, "no /joint_states with the 7 arm + 2 finger joints"
    assert R.all_finite(p), p
    assert max(abs(a - b) for a, b in zip(p[:7], R.HOME)) < T.JOINT_TOL, (p[:7], R.HOME)
    assert abs(p[7] - 0.04) < 0.005 and abs(p[8] - 0.04) < 0.005, f"fingers {p[7:]} (open = 0.04)"


def test_M1_joint_states_are_published_at_a_useful_rate_and_use_sim_time(rig):
    """The header stamps must be SIMULATION time (small numbers that start near 0, not the ~1.7e9 wall clock) and advance."""
    t0, n0, s0 = time.monotonic(), len(rig.stamps), rig.stamps[-1]
    time.sleep(3.0)
    rate = (len(rig.stamps) - n0) / (time.monotonic() - t0)
    assert rate >= T.SAMPLE_HZ, f"/joint_states at {rate:.1f} Hz, need >= {T.SAMPLE_HZ}"
    assert 0 < s0 < 1e6, f"stamp {s0} looks like wall-clock time, not simulation time"
    assert rig.stamps[-1] > s0 + 0.5, f"sim time did not advance: {s0} -> {rig.stamps[-1]}"


def test_M1_clock_topic_is_bridged_from_gazebo(rig):
    """/clock has a ros_gz_bridge publisher and messages arrive in a plain rclpy subscriber."""
    pubs = [i.node_name for i in rig.node.get_publishers_info_by_topic("/clock")]
    assert pubs, "nobody publishes /clock"
    assert any("bridge" in n for n in pubs), f"/clock publisher is not a bridge node: {pubs}"
    assert rig.wait_for(lambda: len(rig.clock) >= 5, 15), f"only {len(rig.clock)} /clock messages in 15 s"
    c0 = rig.clock[-1]
    time.sleep(1.5)
    assert rig.clock[-1] > c0, "/clock does not advance"


# ---- the trajectory goal is really executed ---------------------------------------------------------------------------------
def test_M1_goal_succeeds_and_joint_states_follow_it_smoothly(rig):
    t0 = time.monotonic()
    gh = rig.send(rig.traj_goal(TARGET, 4.0))
    assert gh is not None and gh.accepted
    res = rig.result(gh, 25)
    assert res is not None, "no result within 25 s"
    status, code, msg = res
    assert (status, code) == (R.STATUS_SUCCEEDED, R.SUCCESSFUL), res
    time.sleep(0.5)
    assert rig.max_err(TARGET) < T.JOINT_TOL, (rig.pos(), TARGET)
    samples = rig.since(t0)
    j1 = [s[1][0] for s in samples]
    assert j1[0] < 0.05, "test premise: joint1 starts near 0"
    assert sum(1 for a, b in zip(j1, j1[1:]) if 0.02 < a < 0.38) >= 5, "joint 1 jumped instead of moving through intermediate positions"
    assert all(b >= a - 0.01 for a, b in zip(j1, j1[1:])), "joint 1 is not monotonic on a straight 0 -> 0.4 move"


def test_M1_every_arm_joint_that_was_commanded_actually_moved(rig):
    before = rig.pos()
    gh = rig.send(rig.traj_goal(TARGET, 4.0))
    assert gh is not None and gh.accepted and rig.result(gh, 25)[1] == R.SUCCESSFUL
    time.sleep(0.3)
    after = rig.pos()
    for n, b, a, t in zip(R.ARM, before, after, TARGET):
        if abs(t - b) > T.MOTION_EPS:
            assert abs(a - b) > T.MOTION_EPS, f"{n} was commanded {b:.3f}->{t:.3f} but is at {a:.3f}"


# ---- acceptance G at ROS level: cancel mid-trajectory -----------------------------------------------------------------------
def test_G_cancel_mid_trajectory_stops_the_arm_and_holds(rig):
    far = [1.0, 0.2, 0.0, -1.5, 0.0, 2.2, 0.785]
    start = rig.pos()
    gh = rig.send(rig.traj_goal(far, 10.0))
    assert gh is not None and gh.accepted
    t_cancel_at = time.monotonic() + 2.0
    rig.wait_for(lambda: time.monotonic() >= t_cancel_at, 3)
    moving_vel = rig.vel()
    assert max(abs(v) for v in moving_vel) > 5 * T.STOP_VEL, f"test premise: the arm must be moving at cancel time, velocities {moving_vel}"
    t_cancel = time.monotonic()
    code = rig.cancel(gh)
    assert code == 0, f"cancel request return_code {code} (0 = ERROR_NONE)"       # action_msgs/CancelGoal ERROR_NONE
    res = rig.result(gh, 10)
    assert res is not None and res[0] == R.STATUS_CANCELED, f"goal status {res} (4=SUCCEEDED, 5=CANCELED, 6=ABORTED)"
    stopped_at = rig.wait_for(lambda: (v := rig.vel()) and max(abs(x) for x in v) < T.STOP_VEL, T.STOP_TIMEOUT)
    latency = time.monotonic() - t_cancel
    assert stopped_at, f"joint velocities still {rig.vel()} {T.STOP_TIMEOUT}s after the cancel"
    where = rig.pos()
    assert any(abs(a - b) > T.MOTION_EPS for a, b in zip(where, start)), "the arm never moved before the cancel"
    assert any(abs(a - b) > T.MOTION_EPS for a, b in zip(where, far)), "the arm reached the far target: the cancel did nothing"
    time.sleep(1.0)
    drift = max(abs(a - b) for a, b in zip(rig.pos(), where))
    assert drift < 0.01, f"the arm kept drifting after it was stopped ({drift:.4f} rad in 1 s)"
    print(f"\nG cancel: stop observed {latency:.2f}s after the cancel request; drift after stop {drift:.5f} rad; "
          f"velocities at cancel {[round(v, 3) for v in moving_vel]}")


# ---- limits and invalid goals -----------------------------------------------------------------------------------------------
def test_goal_beyond_joint_limits_is_refused_or_aborted_and_no_joint_leaves_its_limits(rig):
    limits = rig.joint_limits()
    assert set(R.ARM) <= set(limits), limits
    lo, hi = limits["panda_joint1"]
    before = rig.pos()
    t0 = time.monotonic()
    bad = list(R.HOME)
    bad[0] = hi + 0.6
    gh = rig.send(rig.traj_goal(bad, 4.0))
    assert gh is not None, "no answer to the goal"
    problems, outcome = [], "rejected at goal time"
    if gh.accepted:
        res = rig.result(gh, 20)
        outcome = f"accepted, result (status, error_code, text) = {res}"
        if res is None or (res[0] == R.STATUS_SUCCEEDED and res[1] == R.SUCCESSFUL):
            problems.append(f"a goal {bad[0] - hi:.2f} rad beyond the joint1 upper limit ({hi}) was ACCEPTED and reported SUCCEEDED")
    time.sleep(1.0)
    peak = {n: max(p[i] for _, p in rig.since(t0)) for i, n in enumerate(R.ARM)}
    for n in R.ARM:
        if peak[n] > limits[n][1] + 0.02:
            problems.append(f"{n} reached {peak[n]:.3f}, above its URDF limit {limits[n][1]}")
    print(f"\nbeyond-limit goal (joint1 target {bad[0]:.3f}, limit {hi}): {outcome}; joint1 peak {peak['panda_joint1']:.3f}, final {rig.pos()[0]:.3f}")
    assert not problems, "; ".join(problems) + f". ({outcome})"


@pytest.mark.parametrize("label,mutate", [
    ("unknown joint name", lambda g: g.trajectory.joint_names.__setitem__(0, "panda_joint99")),
    ("missing joints", lambda g: (g.trajectory.joint_names.pop(), g.trajectory.points[0].positions.pop(), g.trajectory.points[0].velocities.pop())),
    ("no points", lambda g: g.trajectory.points.clear()),
])
def test_invalid_goals_are_rejected_and_the_arm_does_not_move(rig, label, mutate):
    g = rig.traj_goal(TARGET, 3.0)
    mutate(g)
    before = rig.pos()
    t0 = time.monotonic()
    gh = rig.send(g)
    assert gh is not None, f"{label}: no answer"
    problems = []
    if gh.accepted:                                     # an accepted goal must at least not succeed
        res = rig.result(gh, 15)
        if res is None or res[1] == R.SUCCESSFUL:
            problems.append(f"goal was ACCEPTED and reported SUCCEEDED {res}")
    time.sleep(0.5)
    moved = max(abs(a - b) for a, b in zip(rig.pos(), before))
    if moved >= T.MOTION_EPS:
        problems.append(f"the arm moved {moved:.3f} rad: {[round(x, 3) for x in rig.pos()]} vs {[round(x, 3) for x in before]}")
    if not all(math.isfinite(x) for x in rig.pos()):
        problems.append(f"non-finite joint positions after the goal: {rig.pos()}")
    print(f"\n{label}: accepted={gh.accepted}; final {[round(x, 3) for x in rig.pos()]}")
    assert not problems, f"{label}: " + "; ".join(problems)


def test_nan_in_a_goal_means_unspecified_so_the_executor_must_never_send_it(rig):
    """Characterisation of joint_trajectory_controller (Jazzy): NaN in a point's positions is ACCEPTED and means 'do not command this
    joint' (the joint keeps its place; the goal still SUCCEEDS). It is not an error, so nothing downstream may rely on the controller to
    reject NaN: the validator/executor must refuse non-finite values itself (SEC-013 and trajectory_validation stage)."""
    g = rig.traj_goal(TARGET, 3.0)
    g.trajectory.points[0].positions[2] = float("nan")          # joint 3 target would have been 0.0 (its current value is 0.0)
    g.trajectory.points[0].positions[0] = 0.5                   # a joint that does move, to prove the goal ran
    gh = rig.send(g)
    assert gh is not None and gh.accepted
    res = rig.result(gh, 15)
    assert res is not None and res[:2] == (R.STATUS_SUCCEEDED, R.SUCCESSFUL), res
    time.sleep(0.4)
    p = rig.pos()
    assert R.all_finite(p) and abs(p[0] - 0.5) < T.JOINT_TOL and abs(p[2]) < 0.05, p


# ---- the gripper ------------------------------------------------------------------------------------------------------------
def test_gripper_closes_and_reopens_with_a_real_result(rig):
    from control_msgs.action import GripperCommand
    assert rig.hand_ac.wait_for_server(5)

    def command(width):
        goal = GripperCommand.Goal()
        goal.command.position = width
        goal.command.max_effort = 20.0
        gh = rig.future(rig.hand_ac.send_goal_async(goal), 10)
        assert gh is not None and gh.accepted, f"gripper goal {width} not accepted"
        r = rig.future(gh.get_result_async(), 20)
        assert r is not None, f"no gripper result for {width}"
        return r

    r = command(0.01)
    time.sleep(0.3)
    f = rig.pos(["panda_finger_joint1"])[0]
    assert abs(f - 0.01) < 0.004, f"finger joint 1 at {f} after commanding 0.01 (result reached_goal={r.result.reached_goal} stalled={r.result.stalled})"
    assert r.result.reached_goal or r.result.stalled
    r = command(0.04)
    time.sleep(0.3)
    f = rig.pos(["panda_finger_joint1"])[0]
    assert abs(f - 0.04) < 0.004, f"finger joint 1 at {f} after reopening"
    assert abs(rig.pos(["panda_finger_joint2"])[0] - f) < 0.004, "mimic finger joint 2 does not follow joint 1"


# ---- named gaps (not executable on milestone 1) -----------------------------------------------------------------------------
def test_emergency_stop_service_exists(rig):
    from std_srvs.srv import Trigger
    c = rig.node.create_client(Trigger, "/munder_difflin/safety/emergency_stop")
    if not c.wait_for_service(2):
        pytest.skip("NOT IMPLEMENTED: /munder_difflin/safety/emergency_stop (INTERFACE_CONTRACTS s8.2, SEC-013) is not part of milestone 1")
    pytest.fail("the e-stop service now exists: write the SEC-013 test (velocities < 1e-4 rad/s and controller STOPPED) before accepting it")


# ---- clean shutdown (keep last) ---------------------------------------------------------------------------------------------
def test_zz_clean_shutdown_leaves_no_gz_or_ros_process(sim):
    before = sim.leaked()
    assert before, "test premise: the simulation processes should be running and carry our run id"
    sim.rig.close()
    sim.shut = True
    report = sim.shutdown(grace=30)
    (R.REPORTS / "shutdown.json").write_text(json.dumps({"processes_before": len(before), **report}, indent=1))
    print(f"\nshutdown: {report}; {len(before)} processes before")
    assert report["leaked"] == [], f"processes survived Ctrl+C of the launch: {report['leaked']}"
    assert report["launch_exit_code"] in (0, -2, 130), f"launch exit code {report['launch_exit_code']}"
    assert report["elapsed_s"] < 25, f"shutdown took {report['elapsed_s']} s"
