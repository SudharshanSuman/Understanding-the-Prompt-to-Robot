import json
import math

import pytest

pytest.importorskip('rclpy')
pytest.importorskip('app.executor')

import rclpy  # noqa: E402
from builtin_interfaces.msg import Duration  # noqa: E402
from trajectory_msgs.msg import JointTrajectory, JointTrajectoryPoint  # noqa: E402

from munder_difflin_control import scene as S  # noqa: E402
from munder_difflin_control.ros_executor import ExecutorError, RosExecutor  # noqa: E402


@pytest.fixture(scope='module')
def ex():
    e = RosExecutor()
    yield e
    e._node.destroy_node()
    if rclpy.ok():
        rclpy.shutdown()


def _traj(positions):
    jt = JointTrajectory(joint_names=list(S.ARM_JOINTS))
    p = JointTrajectoryPoint(positions=list(positions), velocities=[0.0] * 7)
    p.time_from_start = Duration(sec=3)
    jt.points.append(p)
    return jt


def test_out_of_limit_target_is_rejected_before_sending(ex):   # defect D2: joint1 = 3.567 rad
    with pytest.raises(ExecutorError, match='outside its limit'):
        ex._exec_traj(_traj([3.567] + S.READY[1:]))


@pytest.mark.parametrize('bad', [float('nan'), float('inf'), -float('inf')])
def test_non_finite_target_is_rejected(ex, bad):
    with pytest.raises(ExecutorError, match='non-finite'):
        ex._exec_traj(_traj([bad] + S.READY[1:]))


def test_empty_trajectory_is_rejected(ex):
    with pytest.raises(ExecutorError, match='empty'):
        ex._exec_traj(JointTrajectory(joint_names=list(S.ARM_JOINTS)))


def test_telemetry_is_none_before_first_joint_state(ex):
    ex._node.pos.clear()
    assert ex.telemetry() is None


def test_telemetry_nan_becomes_null_and_is_strict_json(ex):
    ex._node.pos.clear()
    ex._node.pos.update({j: 0.1 for j in S.ARM_JOINTS})
    ex._node.pos['panda_joint3'] = float('nan')
    ex._node.pos['panda_finger_joint1'] = 0.04
    ex._node.pos['panda_finger_joint2'] = 0.04
    ex._node.poses['red_cube'] = ((0.45, 0.15, float('nan')), (0.0, 0.0, 0.0, 1.0), 0.0)
    t = ex.telemetry()
    assert t is not None
    assert t['joints']['panda_joint3'] is None and t['joints']['panda_joint1'] == 0.1
    assert t['fingers'] == {'panda_finger_joint1': 0.04, 'panda_finger_joint2': 0.04}
    assert t['object_poses']['red_cube']['position'][2] is None
    assert t['perception'] == 'simulation-ground-truth'
    json.dumps(t, allow_nan=False)   # strict JSON: no NaN/Infinity tokens


def test_telemetry_carries_the_visualisation_fields(ex):
    ex._node.pos.update({j: 0.0 for j in S.ARM_JOINTS})
    t = ex.telemetry()
    for key in ('sim_time', 'stage', 'phase', 'state', 'held_object', 'joints', 'fingers', 'objects',
                'object_poses', 'attached', 'e_stop_latched', 'time'):
        assert key in t
    assert set(t['joints']) == set(S.ARM_JOINTS) and len(t['joints']) == 7


def test_ros_estop_service_exists_but_reset_service_does_not(ex):   # SEC-013-D1
    names = {n for n, _ in ex._node.get_service_names_and_types()}
    assert '/munder_difflin/safety/emergency_stop' in names
    assert '/munder_difflin/safety/reset' not in names


def test_pose_values_are_finite_floats(ex):
    assert all(math.isfinite(v) for o in S.OBJECTS.values() for v in o['init'])


def test_readiness_is_non_blocking_and_all_false_without_a_sim(ex):   # MD-DEV-007
    r = ex.readiness()
    assert set(r) == {'move_action', 'arm_controller', 'gripper_controller', 'joint_states'}
    assert not any(r.values())
