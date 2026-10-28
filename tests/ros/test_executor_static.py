"""L1 (ros marker, NO simulation): static checks of RosExecutor, scene constants and the URDF.

Added for MD-ROS-001 (defect D3: RosExecutor() could not be constructed because _srv_estop/_srv_reset were
missing; D2: out-of-limit / non-finite targets). None of these start Gazebo, so they need no hive/sim.lock.
"""
import inspect
import json
import math
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from types import SimpleNamespace

import pytest

pytestmark = pytest.mark.ros

URDF = Path("/opt/ros/jazzy/share/moveit_resources_panda_description/urdf/panda.urdf")


@pytest.fixture(scope="module")
def rx(repo_root):
    backend = str(Path(repo_root) / "backend")
    if backend not in sys.path:
        sys.path.insert(0, backend)
    pytest.importorskip("rclpy")
    pytest.importorskip("munder_difflin_control", reason="source ros2_ws/install/setup.bash")
    from munder_difflin_control import ros_executor, scene
    return SimpleNamespace(mod=ros_executor, scene=scene)


def test_D3_ros_executor_implements_every_abstract_method_and_the_service_handlers(rx):
    cls = rx.mod.RosExecutor
    assert not getattr(cls, "__abstractmethods__", None), f"abstract methods left: {cls.__abstractmethods__}"
    src = inspect.getsource(cls.__init__)
    for handler in ("_srv_estop", "_srv_reset"):
        if f"self.{handler}" in src:
            assert callable(getattr(cls, handler, None)), f"__init__ registers self.{handler} but the class has no such method"


def test_arm_limits_lie_inside_the_urdf_limits(rx):
    joints = {}
    for j in ET.parse(URDF).getroot().iter("joint"):
        lim, soft = j.find("limit"), j.find("safety_controller")
        if lim is not None and j.get("name", "").startswith("panda_joint"):
            joints[j.get("name")] = (float(lim.get("lower")), float(lim.get("upper")),
                                     float(soft.get("soft_lower_limit")), float(soft.get("soft_upper_limit")))
    assert len(rx.mod.ARM_LIMITS) == 7 and len(joints) == 7
    for i, (lo, hi) in enumerate(rx.mod.ARM_LIMITS, start=1):
        hlo, hhi, slo, shi = joints[f"panda_joint{i}"]
        assert hlo <= lo < hi <= hhi, f"panda_joint{i}: ARM_LIMITS {lo, hi} outside hard limits {hlo, hhi}"
        # inside the soft (safety) limits too; joint4 is intentionally tighter on the upper side (-0.0698 vs 0.0175)
        assert slo - 1e-9 <= lo and hi <= shi + 1e-9, f"panda_joint{i}: ARM_LIMITS {lo, hi} outside soft limits {slo, shi}"


def _fake_self(rx):
    # _exec_traj validates before it touches any node: a bare namespace is enough to observe the refusal
    return SimpleNamespace(_retimed=rx.mod.RosExecutor._retimed, _node=None)


def _traj(rx, positions_list):
    from builtin_interfaces.msg import Duration
    from trajectory_msgs.msg import JointTrajectory, JointTrajectoryPoint
    jt = JointTrajectory(joint_names=[f"panda_joint{i}" for i in range(1, 8)])
    for k, pos in enumerate(positions_list, start=1):
        jt.points.append(JointTrajectoryPoint(positions=list(pos), time_from_start=Duration(sec=k)))
    return jt


HOME = [0.0, -0.785, 0.0, -2.356, 0.0, 1.571, 0.785]


@pytest.mark.parametrize("label,bad", [
    ("nan", [float("nan")] + HOME[1:]),
    ("inf", [float("inf")] + HOME[1:]),
    ("joint1 beyond limit", [3.5] + HOME[1:]),
    ("joint4 positive", HOME[:3] + [0.5] + HOME[4:]),
    ("joint6 negative", HOME[:5] + [-0.5] + HOME[6:]),
])
def test_D2_exec_traj_refuses_non_finite_and_out_of_limit_targets_before_sending(rx, label, bad):
    with pytest.raises(rx.mod.ExecutorError):
        rx.mod.RosExecutor._exec_traj(_fake_self(rx), _traj(rx, [HOME, bad]))


def test_exec_traj_refuses_an_empty_trajectory(rx):
    with pytest.raises(rx.mod.ExecutorError):
        rx.mod.RosExecutor._exec_traj(_fake_self(rx), _traj(rx, []))


def test_scene_ids_and_destinations_equal_config_scene_json(rx, repo_root):
    cfg = json.loads((Path(repo_root) / "config" / "scene.json").read_text())
    obj_ids = {o["id"] for o in cfg["objects"]}
    dst_ids = {d["id"] for d in cfg["destinations"]}
    graspable = set(rx.scene.OBJECTS)
    assert graspable <= obj_ids, f"graspable objects not in scene.json: {graspable - obj_ids}"
    assert set(rx.scene.STATIC) <= obj_ids, f"static bodies not in scene.json: {set(rx.scene.STATIC) - obj_ids}"
    assert set(rx.scene.DESTINATIONS) == dst_ids, f"destinations differ: {set(rx.scene.DESTINATIONS) ^ dst_ids}"


def test_destinations_are_reachable_inside_the_planning_area_and_do_not_overlap(rx):
    pts = {k: v["xy"] for k, v in rx.scene.DESTINATIONS.items()}
    for k, (x, y) in pts.items():
        assert 0.2 < math.hypot(x, y) < 0.85, f"{k} at {x, y} is outside the Panda's usable radius"
    ids = list(pts)
    for a in range(len(ids)):
        for b in range(a + 1, len(ids)):
            d = math.dist(pts[ids[a]], pts[ids[b]])
            tol = rx.scene.DESTINATIONS[ids[a]]["tol"] + rx.scene.DESTINATIONS[ids[b]]["tol"]
            assert d > tol, f"{ids[a]} and {ids[b]} acceptance zones overlap (distance {d:.3f} <= {tol:.3f})"
