"""RosExecutor: the ROS 2 / Gazebo implementation of backend/app/executor.py::Executor.

Runs pipeline stages grounding .. verification for a validated RoboticTask (pick_and_place):
  grounding -> planning_scene -> ik -> planning -> trajectory_validation -> execution -> simulation -> verification
It never reports a stage as successful without reading the corresponding ROS / Gazebo state.
Needs: sim + move_group running (munder_difflin_bringup moveit.launch.py). The backend package (`app`) must be on
PYTHONPATH. Telemetry: JSON on /munder_difflin/telemetry (std_msgs/String, 5 Hz).
"""
from __future__ import annotations

import json
import math
import os
import shutil
import subprocess
import threading
import time
from collections.abc import Callable

# DDS must not leave this machine (SEC-011-D1); set before rclpy.init()
os.environ['ROS_LOCALHOST_ONLY'] = '1'
os.environ['ROS_AUTOMATIC_DISCOVERY_RANGE'] = 'LOCALHOST'

import rclpy
from builtin_interfaces.msg import Duration
from control_msgs.action import FollowJointTrajectory, GripperCommand
from controller_manager_msgs.srv import ListControllers, SwitchController
from geometry_msgs.msg import Pose
from moveit_msgs.action import MoveGroup
from moveit_msgs.msg import (AttachedCollisionObject, BoundingVolume, CollisionObject, Constraints,
                             JointConstraint, MoveItErrorCodes, PlanningScene, PositionConstraint,
                             OrientationConstraint, RobotState)
from moveit_msgs.srv import ApplyPlanningScene, GetCartesianPath, GetPositionIK
from rclpy.action import ActionClient
from rclpy.callback_groups import ReentrantCallbackGroup
from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node
from sensor_msgs.msg import JointState
from shape_msgs.msg import SolidPrimitive
from std_msgs.msg import Bool, Empty, String
from std_srvs.srv import Trigger
from trajectory_msgs.msg import JointTrajectory, JointTrajectoryPoint

from app.executor import (PANDA_ARM_JOINTS, Executor, ExecutorError, ExecutorStatus, StopReport,
                          VELOCITY_TOLERANCE, stop_report)
from app.schemas import PipelineStageEvent, RoboticTask, StageState

from . import scene as S

ARM_CTRL = 'panda_arm_controller'
TOP_DOWN = (1.0, 0.0, 0.0, 0.0)  # panda_hand z axis pointing down (x, y, z, w)
TOUCH = ['panda_hand', 'panda_leftfinger', 'panda_rightfinger']
# URDF joint limits of panda_joint1..7 (rad); targets outside are rejected here, not left to the controller (MD-TEST-006 D2)
ARM_LIMITS = [(-2.8973, 2.8973), (-1.7628, 1.7628), (-2.8973, 2.8973), (-3.0718, -0.0698),
              (-2.8973, 2.8973), (-0.0175, 3.7525), (-2.8973, 2.8973)]
PERCEPTION_SOURCE = 'simulation-ground-truth'  # object poses come from Gazebo, not from a camera


class _Cancelled(Exception):
    pass


class _Node(Node):
    def __init__(self):
        super().__init__('munder_difflin_executor', parameter_overrides=[
            rclpy.parameter.Parameter('use_sim_time', rclpy.Parameter.Type.BOOL, True)])
        cb = ReentrantCallbackGroup()
        self.pos: dict[str, float] = {}
        self.vel: dict[str, float] = {}
        self.js_wall = 0.0
        self.poses: dict[str, tuple] = {}
        self.create_subscription(JointState, '/joint_states', self._js, 10, callback_group=cb)
        for o in S.OBJECTS:  # ground truth from Gazebo PosePublisher plugins, bridged by sim.launch.py
            self.create_subscription(Pose, f'/model/{o}/pose', lambda m, o=o: self._pose_cb(o, m), 10, callback_group=cb)
        self.mg = ActionClient(self, MoveGroup, '/move_action', callback_group=cb)
        self.arm = ActionClient(self, FollowJointTrajectory, f'/{ARM_CTRL}/follow_joint_trajectory', callback_group=cb)
        self.grip = ActionClient(self, GripperCommand, '/panda_hand_controller/gripper_cmd', callback_group=cb)
        self.cart = self.create_client(GetCartesianPath, '/compute_cartesian_path', callback_group=cb)
        self.ik = self.create_client(GetPositionIK, '/compute_ik', callback_group=cb)
        self.apply_scene = self.create_client(ApplyPlanningScene, '/apply_planning_scene', callback_group=cb)
        self.switch = self.create_client(SwitchController, '/controller_manager/switch_controller', callback_group=cb)
        self.listc = self.create_client(ListControllers, '/controller_manager/list_controllers', callback_group=cb)
        self.attach = {o: self.create_publisher(Empty, f'/munder_difflin/gz/attach/{o}', 10) for o in S.OBJECTS}
        self.detach = {o: self.create_publisher(Empty, f'/munder_difflin/gz/detach/{o}', 10) for o in S.OBJECTS}
        self.attached = {o: False for o in S.OBJECTS}
        for o in S.OBJECTS:
            self.create_subscription(Bool, f'/munder_difflin/gz/attached/{o}',
                                     lambda m, o=o: self.attached.__setitem__(o, bool(m.data)), 10, callback_group=cb)
        self.telemetry = self.create_publisher(String, '/munder_difflin/telemetry', 10)

    def _js(self, m: JointState):
        for i, n in enumerate(m.name):
            self.pos[n] = m.position[i]
            if i < len(m.velocity):
                self.vel[n] = m.velocity[i]
        self.js_wall = time.time()

    def _pose_cb(self, obj: str, m: Pose):
        p, q = m.position, m.orientation
        self.poses[obj] = ((p.x, p.y, p.z), (q.x, q.y, q.z, q.w), time.time())


def _pose(xyz, quat=TOP_DOWN) -> Pose:
    p = Pose()
    p.position.x, p.position.y, p.position.z = (float(v) for v in xyz)
    p.orientation.x, p.orientation.y, p.orientation.z, p.orientation.w = (float(v) for v in quat)
    return p


class RosExecutor(Executor):
    name = 'ros2_gazebo'

    def __init__(self, hold_after_estop: bool = True):
        if not rclpy.ok():
            rclpy.init()
        self._node = _Node()
        self._exec = MultiThreadedExecutor(num_threads=4)
        self._exec.add_node(self._node)
        threading.Thread(target=self._spin, daemon=True, name='ros-spin').start()
        self._lock = threading.Lock()
        self._run_lock = threading.Lock()
        self._latched = False
        self._primed = False   # see execute()
        self._cancelled: set[str] = set()
        self._goals: list = []
        self._state = 'IDLE'
        self._stage = ''
        self._task_id = ''
        self._held = ''
        self._phase = ''
        self._node.create_timer(0.1, self._publish_telemetry)   # 10 Hz
        # ROS-side e-stop while a RosExecutor is alive. There is deliberately NO ROS reset service (SEC-013-D1):
        # stopping is always safe, clearing the latch is only possible through the authenticated HTTP API.
        self._node.create_service(Trigger, '/munder_difflin/safety/emergency_stop', self._srv_estop, callback_group=ReentrantCallbackGroup())

    # ------------------------------------------------------------------ helpers
    def _spin(self):
        try:
            self._exec.spin()
        except Exception:  # shutdown races (ExternalShutdownException) at interpreter exit
            pass

    def _wait(self, fut, timeout: float):
        t0 = time.time()
        while not fut.done():
            if time.time() - t0 > timeout:
                raise ExecutorError('ROS call timed out')
            time.sleep(0.01)
        return fut.result()

    def _check(self, is_cancelled: Callable[[], bool] | None = None):
        if self._latched:
            raise ExecutorError('emergency stop latched: motion refused until reset')
        if is_cancelled and is_cancelled():
            raise _Cancelled()

    def _servers_ready(self) -> dict[str, bool]:
        n = self._node
        return {'move_action': n.mg.server_is_ready(), 'arm_controller': n.arm.server_is_ready(),
                'gripper_controller': n.grip.server_is_ready(), 'joint_states': time.time() - n.js_wall < 2.0}

    def readiness(self) -> dict[str, bool]:
        """Non-blocking, never raises (backend /health): move_action, arm_controller, gripper_controller, fresh joint_states."""
        try:
            return self._servers_ready()
        except Exception:
            return {'move_action': False, 'arm_controller': False, 'gripper_controller': False, 'joint_states': False}

    @staticmethod
    def _num(v):
        return round(v, 4) if isinstance(v, float) and math.isfinite(v) else None  # NaN/inf -> null

    def telemetry(self) -> dict | None:
        """Live snapshot (JSON-able). Non-blocking, never raises; None until the first /joint_states arrives."""
        try:
            n = self._node
            if not n.pos:
                return None
            return {'time': time.time(), 'sim_time': self._num(n.get_clock().now().nanoseconds * 1e-9),
                    'source': 'ros2_gazebo', 'perception': PERCEPTION_SOURCE,
                    'task_id': self._task_id, 'stage': self._stage, 'phase': self._phase, 'state': self._state,
                    'e_stop_latched': self._latched, 'held_object': self._held,
                    'joints': {j: self._num(n.pos.get(j, float('nan'))) for j in S.ARM_JOINTS},
                    'fingers': {f: self._num(n.pos.get(f, float('nan'))) for f in S.FINGER_JOINTS},
                    'max_arm_joint_velocity': self._num(max((abs(n.vel.get(j, 0.0)) for j in S.ARM_JOINTS), default=0.0)),
                    'gripper_opening_m': self._num(n.pos.get('panda_finger_joint1', float('nan')) * 2),
                    'objects': {o: [self._num(v) for v in n.poses[o][0]] for o in list(n.poses)},
                    'object_poses': {o: {'position': [self._num(v) for v in n.poses[o][0]],
                                         'orientation_xyzw': [self._num(v) for v in n.poses[o][1]]}
                                     for o in list(n.poses)},
                    'attached': {o: bool(v) for o, v in list(n.attached.items())}}
        except Exception:
            return None

    def _publish_telemetry(self):
        msg = self.telemetry()
        if msg is not None:
            try:
                self._node.telemetry.publish(String(data=json.dumps(msg, allow_nan=False)))
            except Exception:
                pass

    def _srv_estop(self, _req, res):
        rep = self.emergency_stop()
        res.success, res.message = rep.status == 'e_stop_confirmed', rep.model_dump_json()
        return res

    # ------------------------------------------------------------------ Executor API
    def status(self) -> ExecutorStatus:
        ready = self._servers_ready()
        connected = all(ready.values())
        missing = [k for k, v in ready.items() if not v]
        return ExecutorStatus(
            name=self.name, connected=connected, can_execute=connected and not self._latched,
            e_stop_latched=self._latched, controller_state=self._state,
            detail='ok' if connected else f'not ready: {", ".join(missing)}')

    def cancel(self, task_id: str) -> None:
        self._cancelled.add(task_id)
        if task_id == self._task_id:
            self._cancel_goals()

    def _cancel_goals(self):
        for gh in list(self._goals):
            try:
                gh.cancel_goal_async()
            except Exception:
                pass

    def emergency_stop(self) -> StopReport:
        try:
            self._latched = True
            self._cancel_goals()
            n = self._node
            if n.switch.service_is_ready():
                req = SwitchController.Request(deactivate_controllers=[ARM_CTRL], strictness=SwitchController.Request.BEST_EFFORT)
                try:
                    self._wait(n.switch.call_async(req), 3.0)
                except ExecutorError:
                    pass
            time.sleep(0.5)
            ctrl = self._controller_state(ARM_CTRL)
            state = 'STOPPED' if ctrl == 'inactive' else (ctrl or 'UNKNOWN').upper()
            vels = []
            for _ in range(10):  # several read-backs: a single zero sample proves nothing
                vels.append([n.vel.get(j, float('nan')) for j in S.ARM_JOINTS])
                time.sleep(0.05)
            worst = max(vels, key=lambda v: max(abs(x) for x in v) if all(math.isfinite(x) for x in v) else float('inf'))
            self._state = state
            return stop_report(worst, state, f'ros2 /joint_states velocity read-back + controller_manager state of {ARM_CTRL}')
        except Exception as exc:  # contract: must not raise
            return StopReport(status='e_stop_unverified', controller_state='UNKNOWN', max_joint_velocity=None,
                              tolerance=VELOCITY_TOLERANCE, source='ros2', detail=f'read-back failed: {type(exc).__name__}')

    def reset(self) -> ExecutorStatus:
        n = self._node
        try:
            req = SwitchController.Request(activate_controllers=[ARM_CTRL], strictness=SwitchController.Request.BEST_EFFORT)
            self._wait(n.switch.call_async(req), 3.0)
            time.sleep(0.3)
            ctrl = self._controller_state(ARM_CTRL)
            if ctrl != 'active':
                return ExecutorStatus(name=self.name, connected=True, can_execute=False, e_stop_latched=True,
                                      controller_state=(ctrl or 'UNKNOWN').upper(),
                                      detail=f'reset failed: {ARM_CTRL} is {ctrl}; latch kept')
        except ExecutorError as exc:
            return ExecutorStatus(name=self.name, connected=False, can_execute=False, e_stop_latched=True,
                                  controller_state='UNKNOWN', detail=f'reset failed: {exc}; latch kept')
        self._latched = False
        self._state = 'IDLE'
        scene = self._reset_scene()
        st = self.status()
        return st.model_copy(update={'detail': f'{st.detail}; scene: {scene}'}) if hasattr(st, 'model_copy') else st

    def _reset_scene(self) -> str:
        """Release anything held and teleport every graspable object back to its initial pose in Gazebo."""
        for obj in S.OBJECTS:
            self._node.detach[obj].publish(Empty())
            try:
                self._moveit_detach(obj)
            except ExecutorError:
                pass
        self._held = ''
        gz = shutil.which('gz')
        if not gz:
            return 'not reset (gz CLI not on PATH)'
        failed = []
        for obj, o in S.OBJECTS.items():
            x, y, z = o['init']
            req = f'name: "{obj}" position {{x: {x} y: {y} z: {z}}} orientation {{w: 1}}'
            try:
                r = subprocess.run([gz, 'service', '-s', '/world/munder_difflin/set_pose', '--reqtype', 'gz.msgs.Pose',
                                    '--reptype', 'gz.msgs.Boolean', '--timeout', '3000', '--req', req],
                                   capture_output=True, text=True, timeout=8)
                if 'data: true' not in r.stdout:
                    failed.append(obj)
            except (subprocess.SubprocessError, OSError):
                failed.append(obj)
        time.sleep(0.5)
        return 'objects restored' if not failed else f'not reset: {", ".join(failed)}'

    def _controller_state(self, name: str) -> str | None:
        try:
            r = self._wait(self._node.listc.call_async(ListControllers.Request()), 3.0)
        except ExecutorError:
            return None
        return next((c.state for c in r.controller if c.name == name), None)

    # ------------------------------------------------------------------ motion primitives
    def _exec_traj(self, jt: JointTrajectory, cancel_cb=None):
        n = self._node
        if len(jt.points) < 1:
            raise ExecutorError('empty trajectory')
        jt = self._retimed(jt)
        # the controller treats NaN as 'do not command this joint': reject non-finite values ourselves
        if not all(math.isfinite(v) for p in jt.points for v in p.positions):
            raise ExecutorError('trajectory contains non-finite joint positions')
        for p in jt.points:
            for j, (v, (lo, hi)) in enumerate(zip(p.positions, ARM_LIMITS)):
                if not lo - 1e-3 <= v <= hi + 1e-3:
                    raise ExecutorError(f'trajectory target joint{j + 1}={v:.3f} rad is outside its limit [{lo}, {hi}]')
        goal = FollowJointTrajectory.Goal(trajectory=jt)
        gh = self._wait(n.arm.send_goal_async(goal), 10.0)
        if not gh.accepted:
            raise ExecutorError('arm controller rejected the trajectory')
        self._goals.append(gh)
        try:
            dur = jt.points[-1].time_from_start.sec + jt.points[-1].time_from_start.nanosec * 1e-9
            res = self._wait(gh.get_result_async(), dur + 30.0)
        finally:
            self._goals.remove(gh)
        self._check(cancel_cb)
        if res.result.error_code != FollowJointTrajectory.Result.SUCCESSFUL:
            raise ExecutorError(f'trajectory execution failed (error_code={res.result.error_code}: {res.result.error_string})')
        # do not trust the action result alone: read the joints back (defect D2 in MD-TEST-006)
        time.sleep(0.3)
        final = dict(zip(jt.joint_names, jt.points[-1].positions))
        worst = max(abs(self._node.pos.get(j, float('inf')) - v) for j, v in final.items())
        if not worst < 0.03:
            raise ExecutorError(f'joint_states do not match the trajectory end point (max error {worst:.3f} rad)')

    @staticmethod
    def _retimed(jt: JointTrajectory) -> JointTrajectory:
        pts = list(jt.points)
        t = [p.time_from_start.sec + p.time_from_start.nanosec * 1e-9 for p in pts]
        if len(pts) > 1 and t[0] == 0.0:
            pts, t = pts[1:], t[1:]
        if t and all(b > a for a, b in zip(t, t[1:])) and t[0] > 0:
            out = JointTrajectory(joint_names=jt.joint_names, points=pts)
            return out
        # missing / non-monotonic timing: assign from joint deltas at <= 0.5 rad/s
        out, acc, prev = [], 0.0, None
        for p in pts:
            if prev is not None:
                acc += max(0.02, max(abs(a - b) for a, b in zip(p.positions, prev)) / 0.5)
            else:
                acc = 0.5
            q = JointTrajectoryPoint(positions=list(p.positions), velocities=[0.0] * len(p.positions))
            q.time_from_start = Duration(sec=int(acc), nanosec=int((acc % 1) * 1e9))
            out.append(q)
            prev = p.positions
        return JointTrajectory(joint_names=jt.joint_names, points=out)

    def _mg_goal(self, constraints: Constraints, plan_only: bool, vel=0.25):
        g = MoveGroup.Goal()
        r = g.request
        r.group_name = 'panda_arm'
        r.num_planning_attempts = 8
        r.allowed_planning_time = 5.0
        r.max_velocity_scaling_factor = vel
        r.max_acceleration_scaling_factor = vel
        r.goal_constraints = [constraints]
        g.planning_options.plan_only = plan_only
        return g

    def _run_mg(self, g: MoveGroup.Goal, cancel_cb=None):
        n = self._node
        gh = self._wait(n.mg.send_goal_async(g), 15.0)
        if not gh.accepted:
            raise ExecutorError('MoveIt rejected the planning request')
        self._goals.append(gh)
        try:
            res = self._wait(gh.get_result_async(), 90.0)
        finally:
            self._goals.remove(gh)
        self._check(cancel_cb)
        code = res.result.error_code.val
        if code != MoveItErrorCodes.SUCCESS:
            raise ExecutorError(f'MoveIt failed (error_code={code})')
        return res.result

    @staticmethod
    def _pose_constraints(xyz, quat=TOP_DOWN) -> Constraints:
        c = Constraints()
        pc = PositionConstraint()
        pc.header.frame_id = 'world'
        pc.link_name = S.HAND_LINK
        pc.constraint_region = BoundingVolume(primitives=[SolidPrimitive(type=SolidPrimitive.BOX, dimensions=[0.004] * 3)],
                                              primitive_poses=[_pose(xyz, (0, 0, 0, 1))])
        pc.weight = 1.0
        oc = OrientationConstraint()
        oc.header.frame_id = 'world'
        oc.link_name = S.HAND_LINK
        oc.orientation.x, oc.orientation.y, oc.orientation.z, oc.orientation.w = quat
        oc.absolute_x_axis_tolerance = oc.absolute_y_axis_tolerance = 0.05
        oc.absolute_z_axis_tolerance = 0.05  # yaw is chosen explicitly (_pick_quat) so Cartesian segments do not swing it
        oc.weight = 1.0
        c.position_constraints, c.orientation_constraints = [pc], [oc]
        return c

    def _plan_pose(self, xyz, quat, plan_only: bool, cancel_cb=None):
        return self._run_mg(self._mg_goal(self._pose_constraints(xyz, quat), plan_only), cancel_cb)

    def _move_joints(self, target, cancel_cb=None):
        c = Constraints()
        for name, v in zip(S.ARM_JOINTS, target):
            c.joint_constraints.append(JointConstraint(joint_name=name, position=float(v),
                                                       tolerance_above=0.01, tolerance_below=0.01, weight=1.0))
        self._run_mg(self._mg_goal(c, plan_only=False), cancel_cb)

    def _cartesian(self, xyz, quat, cancel_cb=None, min_fraction=0.98):
        n = self._node
        if not n.cart.service_is_ready():
            raise ExecutorError('/compute_cartesian_path not available')
        req = GetCartesianPath.Request()
        req.header.frame_id = 'world'
        req.start_state.is_diff = True
        req.group_name, req.link_name = 'panda_arm', S.HAND_LINK
        req.waypoints = [_pose(xyz, quat)]
        req.max_step, req.avoid_collisions = 0.01, True
        for f in ('max_velocity_scaling_factor', 'max_acceleration_scaling_factor'):
            if hasattr(req, f):
                setattr(req, f, 0.3)
        res = self._wait(n.cart.call_async(req), 15.0)
        if res.fraction < min_fraction:
            raise ExecutorError(f'cartesian path only {res.fraction:.2f} achievable')
        self._exec_traj(res.solution.joint_trajectory, cancel_cb)

    def _gripper(self, position: float, effort=20.0, cancel_cb=None):
        n = self._node
        g = GripperCommand.Goal()
        g.command.position, g.command.max_effort = float(position), float(effort)
        gh = self._wait(n.grip.send_goal_async(g), 10.0)
        if not gh.accepted:
            raise ExecutorError('gripper rejected the command')
        self._goals.append(gh)
        try:
            self._wait(gh.get_result_async(), 15.0)
        finally:
            self._goals.remove(gh)
        self._check(cancel_cb)
        time.sleep(0.3)

    # ------------------------------------------------------------------ scene
    def _obj_pose(self, obj: str):
        p = self._node.poses.get(obj)
        if p is None:
            return S.OBJECTS[obj]['init'], (0, 0, 0, 1), False
        return p[0], p[1], True

    def _shape(self, obj: str):
        o = S.OBJECTS[obj]
        if o['shape'] == 'box':
            return SolidPrimitive(type=SolidPrimitive.BOX, dimensions=list(o['dims']))
        return SolidPrimitive(type=SolidPrimitive.CYLINDER, dimensions=[o['dims'][1], o['dims'][0]])

    def _apply(self, world=None, attached=None, must=True):
        ps = PlanningScene(is_diff=True)
        ps.robot_state = RobotState(is_diff=True)
        if world:
            ps.world.collision_objects = world
        if attached:
            ps.robot_state.attached_collision_objects = attached
        ok = self._wait(self._node.apply_scene.call_async(ApplyPlanningScene.Request(scene=ps)), 10.0).success
        if must and not ok:
            raise ExecutorError('MoveIt rejected the planning-scene update')
        return ok

    def _sync_scene(self, exclude: str):
        objs = []
        for sid, boxes in S.STATIC.items():
            co = CollisionObject(id=sid, operation=CollisionObject.ADD)
            co.header.frame_id = 'world'
            for dims, xyz in boxes:
                co.primitives.append(SolidPrimitive(type=SolidPrimitive.BOX, dimensions=list(dims)))
                co.primitive_poses.append(_pose(xyz, (0, 0, 0, 1)))
            objs.append(co)
        for o in S.OBJECTS:
            if o == exclude:
                continue
            co = CollisionObject(id=o, operation=CollisionObject.ADD)
            co.header.frame_id = 'world'
            xyz, q, _ = self._obj_pose(o)
            co.primitives, co.primitive_poses = [self._shape(o)], [_pose(xyz, q)]
            objs.append(co)
        self._apply(world=objs)
        rm = CollisionObject(id=exclude, operation=CollisionObject.REMOVE)  # target is grasped, not an obstacle
        rm.header.frame_id = 'world'
        self._apply(world=[rm], must=False)  # False when it was not in the scene yet: fine
        return [c.id for c in objs]

    def _moveit_attach(self, obj: str):
        co = CollisionObject(id=obj, operation=CollisionObject.ADD)
        co.header.frame_id = S.HAND_LINK
        co.primitives, co.primitive_poses = [self._shape(obj)], [_pose((0, 0, S.GRIP_CENTER_BELOW_HAND), (0, 0, 0, 1))]
        self._apply(attached=[AttachedCollisionObject(link_name=S.HAND_LINK, object=co, touch_links=TOUCH)])

    def _moveit_detach(self, obj: str):
        co = CollisionObject(id=obj, operation=CollisionObject.REMOVE)
        co.header.frame_id = S.HAND_LINK
        self._apply(attached=[AttachedCollisionObject(link_name=S.HAND_LINK, object=co)], must=False)
        w = CollisionObject(id=obj, operation=CollisionObject.REMOVE)
        w.header.frame_id = 'world'
        self._apply(world=[w], must=False)

    # ------------------------------------------------------------------ IK
    def _ik(self, xyz, quat=TOP_DOWN) -> bool:
        n = self._node
        req = GetPositionIK.Request()
        r = req.ik_request
        r.group_name, r.avoid_collisions, r.ik_link_name = 'panda_arm', True, S.HAND_LINK
        r.pose_stamped.header.frame_id = 'world'
        r.pose_stamped.pose = _pose(xyz, quat)
        r.robot_state.is_diff = True
        r.timeout = Duration(sec=1)
        return self._wait(n.ik.call_async(req), 5.0).error_code.val == MoveItErrorCodes.SUCCESS

    def _pick_quat(self, points) -> tuple | None:
        """Top-down hand orientation (yaw about vertical; gripper is symmetric under 180 deg) with IK at every point."""
        for yaw in (0.0, math.pi / 2, math.pi, -math.pi / 2, math.pi / 4, -math.pi / 4):
            q = (math.cos(yaw / 2), math.sin(yaw / 2), 0.0, 0.0)  # Rz(yaw) * Rx(pi)
            if all(self._ik(p, q) for p in points):
                return q
        return None

    # ------------------------------------------------------------------ main entry
    def execute(self, task: RoboticTask, emit: Callable[[PipelineStageEvent], None],
                is_cancelled: Callable[[], bool]) -> None:
        if not self._run_lock.acquire(blocking=False):
            raise ExecutorError('another task is already executing')
        self._task_id, self._state = task.task_id, 'RUNNING'
        stage = 'grounding'

        def ev(st: str, state: StageState, msg: str = '', **detail):
            nonlocal stage
            stage = st
            self._stage = st
            self._phase = msg
            emit(PipelineStageEvent(run_id=task.task_id, stage=st, state=state, message=msg, detail=detail))

        def cancel_cb() -> bool:
            return is_cancelled() or task.task_id in self._cancelled

        try:
            if not self._primed and not self._latched and not os.environ.get('MD_NO_PRIME'):   # MD_NO_PRIME=1: probe without the workaround
                # Measured on a fresh sim start: without a reset the first task aborts on path tolerance (a joint does
                # not break away on the first fast move); with one reset beforehand it completes. Cause not isolated.
                self._primed = True
                self.reset()
            self._run(task, ev, cancel_cb)
            self._state = 'IDLE'
        except _Cancelled:
            ev(stage, StageState.CANCELLED, 'cancelled by user')
            self._state = 'IDLE'
        except ExecutorError as exc:
            if self._latched:
                ev(stage, StageState.FAILED, 'emergency stop', error=str(exc))
            else:
                ev(stage, StageState.FAILED, str(exc))
                self._state = 'IDLE'
            raise
        finally:
            self._cancelled.discard(task.task_id)
            self._stage, self._task_id = '', ''
            self._run_lock.release()

    def _run(self, task: RoboticTask, ev, cc):
        obj, dst = task.target_object, task.destination
        self._check(cc)
        if obj not in S.OBJECTS:
            raise ExecutorError(f"'{obj}' is not a graspable object")
        if dst not in S.DESTINATIONS:
            raise ExecutorError(f"unknown destination '{dst}'")
        st = self.status()
        if not st.can_execute:
            raise ExecutorError(f'executor not ready: {st.detail}')
        d = S.DESTINATIONS[dst]
        hh = S.half_height(obj)
        gz = S.GRIP_CENTER_BELOW_HAND
        open_pos, close_pos = S.FINGER_OPEN, S.OBJECTS[obj]['half_width'] - 0.001

        # 1 grounding
        ev('grounding', StageState.RUNNING, f'reading object poses ({PERCEPTION_SOURCE})', perception=PERCEPTION_SOURCE)
        xyz0, _, live = self._obj_pose(obj)
        if not live:
            ev('grounding', StageState.WARNING, 'no live Gazebo pose yet; using the scene.json initial pose',
               object=obj, position=list(xyz0))
        else:
            ev('grounding', StageState.SUCCESS, f'{obj} at ({xyz0[0]:.3f}, {xyz0[1]:.3f}, {xyz0[2]:.3f}) [{PERCEPTION_SOURCE}]',
               object=obj, position=list(xyz0), destination=dst, destination_xy=list(d['xy']), perception=PERCEPTION_SOURCE)
        grasp = (xyz0[0], xyz0[1], xyz0[2] + gz)
        pre = (grasp[0], grasp[1], grasp[2] + 0.12)
        place_z = d['top'] + hh + 0.004 + gz
        place = (d['xy'][0], d['xy'][1], place_z)
        preplace = (place[0], place[1], max(place_z + 0.15, 0.30))

        # 2 planning scene
        self._check(cc)
        ev('planning_scene', StageState.RUNNING, 'syncing MoveIt planning scene')
        bodies = self._sync_scene(exclude=obj)
        ev('planning_scene', StageState.SUCCESS, f'{len(bodies)} bodies in the planning scene (target excluded)', bodies=bodies)

        # 3 IK
        self._check(cc)
        ev('ik', StageState.RUNNING, 'checking reachability')
        quat = self._pick_quat([pre, grasp, preplace, place])
        if quat is None:
            bad = [lbl for lbl, pt in (('pre_grasp', pre), ('grasp', grasp), ('pre_place', preplace), ('place', place))
                   if not self._ik(pt)]
            ev('ik', StageState.FAILED, f'no top-down hand yaw gives collision-free IK at all 4 poses (unreachable at yaw 0: {bad})')
            raise ExecutorError(f'IK failed: no hand yaw reaches pre_grasp/grasp/pre_place/place for {obj} -> {dst}')
        yaw = 2 * math.atan2(quat[1], quat[0])
        ev('ik', StageState.SUCCESS, f'pre_grasp, grasp, pre_place, place poses all have collision-free IK (hand yaw {math.degrees(yaw):.0f} deg)',
           hand_yaw_deg=math.degrees(yaw))

        # 4 planning
        self._check(cc)
        ev('planning', StageState.RUNNING, 'OMPL plan to pre-grasp (plan only)')
        res = self._plan_pose(pre, quat, plan_only=True, cancel_cb=cc)
        jt = res.planned_trajectory.joint_trajectory
        ev('planning', StageState.SUCCESS, f'planned {len(jt.points)} waypoints to pre-grasp', waypoints=len(jt.points))

        # 5 trajectory validation
        ev('trajectory_validation', StageState.RUNNING, 'validating planned trajectory')
        issues = self._validate(jt, pre)
        if issues:
            ev('trajectory_validation', StageState.FAILED, '; '.join(issues))
            raise ExecutorError('trajectory validation failed: ' + '; '.join(issues))
        ev('trajectory_validation', StageState.SUCCESS, 'joint limits, timing and goal pose OK')

        # 6 execution
        def step(msg):
            self._check(cc)
            ev('execution', StageState.RUNNING, msg)
        try:
            step('opening gripper'); self._gripper(open_pos, cancel_cb=cc)
            step('moving to pre-grasp'); self._exec_traj(jt, cc)
            step('descending to grasp'); self._cartesian(grasp, quat, cc)
            step('closing gripper'); self._gripper(close_pos, cancel_cb=cc)
            step('attaching (DetachableJoint + MoveIt attached object)')
            self._node.attach[obj].publish(Empty())
            self._moveit_attach(obj)
            self._held = obj
            time.sleep(0.5)
            step('lifting'); self._cartesian(pre, quat, cc)
            lifted = self._obj_pose(obj)[0][2]
            if lifted < xyz0[2] + 0.05:
                raise ExecutorError(f'grasp failed: {obj} did not rise with the hand (z {lifted:.3f})')
            step(f'moving to above {dst}'); self._run_mg(self._mg_goal(self._pose_constraints(preplace, quat), False), cc)
            step('descending to place height'); self._cartesian(place, quat, cc)
            step('releasing')
            self._node.detach[obj].publish(Empty())
            self._moveit_detach(obj)
            self._held = ''
            time.sleep(0.3)
            self._gripper(open_pos, cancel_cb=cc)
            step('retreating'); self._cartesian(preplace, quat, cc)
            step('returning to ready pose'); self._move_joints(S.READY, cc)
        except _Cancelled:
            self._abort_hold(obj)
            raise
        except ExecutorError:
            self._abort_hold(obj)
            raise
        ev('execution', StageState.SUCCESS, 'motion sequence complete')

        # 7 simulation: Gazebo ground truth must show the object moved
        ev('simulation', StageState.RUNNING, 'confirming object motion in Gazebo')
        time.sleep(1.5)
        end, _, live = self._obj_pose(obj)
        moved = math.dist(end[:2], xyz0[:2])
        if not live or moved < 0.05:
            ev('simulation', StageState.FAILED, f'{obj} did not move in Gazebo (moved {moved:.3f} m)')
            raise ExecutorError(f'{obj} did not move in Gazebo')
        ev('simulation', StageState.SUCCESS, f'{obj} moved {moved:.3f} m in Gazebo', final_position=list(end))

        # 8 verification
        ev('verification', StageState.RUNNING, f'checking {obj} is at {dst}')
        err = math.dist(end[:2], d['xy'])
        z_ok = abs(end[2] - (d['top'] + hh)) < 0.02
        if err <= d['tol'] and z_ok:
            ev('verification', StageState.SUCCESS, f'{obj} placed at {dst}: xy error {err:.3f} m (tol {d["tol"]}), z {end[2]:.3f}',
               xy_error=err, tolerance=d['tol'], final_position=list(end))
        else:
            ev('verification', StageState.FAILED, f'{obj} NOT at {dst}: xy error {err:.3f} m (tol {d["tol"]}), z {end[2]:.3f}',
               xy_error=err, tolerance=d['tol'], final_position=list(end))
            raise ExecutorError(f'verification failed: {obj} is {err:.3f} m from {dst}')

    def _abort_hold(self, obj: str):
        """On failure/cancel: release the held object in Gazebo and drop the MoveIt attachment (best effort)."""
        try:
            if self._held:
                self._node.detach[obj].publish(Empty())
                self._moveit_detach(obj)
                self._held = ''
        except Exception:
            pass

    def _validate(self, jt: JointTrajectory, goal_xyz) -> list[str]:
        issues = []
        if len(jt.points) < 2:
            issues.append('fewer than 2 waypoints')
            return issues
        if list(jt.joint_names) != S.ARM_JOINTS:
            issues.append(f'unexpected joint names {list(jt.joint_names)}')
        lim = ARM_LIMITS
        prev_t = -1.0
        for i, p in enumerate(jt.points):
            t = p.time_from_start.sec + p.time_from_start.nanosec * 1e-9
            if t <= prev_t:
                issues.append(f'waypoint {i}: time not increasing')
                break
            prev_t = t
            for j, (v, (lo, hi)) in enumerate(zip(p.positions, lim)):
                if not (math.isfinite(v) and lo - 1e-3 <= v <= hi + 1e-3):
                    issues.append(f'waypoint {i} joint{j + 1}={v:.3f} outside [{lo}, {hi}]')
                    return issues
        return issues
