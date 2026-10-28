#!/usr/bin/env python3
"""MoveIt 2 plan + execute test: move panda_hand above red_cube via the /move_action (MoveGroup) action.

PASS only if move_group reports SUCCESS and /joint_states shows the hand TCP ended near the goal
(joint positions changed). Run with the sim + move_group up (moveit.launch.py).
"""
import sys
import time

import rclpy
from geometry_msgs.msg import Pose
from moveit_msgs.action import MoveGroup
from moveit_msgs.msg import (BoundingVolume, CollisionObject, Constraints, MoveItErrorCodes, OrientationConstraint,
                             PlanningScene, PositionConstraint)
from rclpy.action import ActionClient
from rclpy.node import Node
from sensor_msgs.msg import JointState
from shape_msgs.msg import SolidPrimitive

ARM = [f'panda_joint{i}' for i in range(1, 8)]


class T(Node):
    def __init__(self):
        super().__init__('md_plan_test', parameter_overrides=[
            rclpy.parameter.Parameter('use_sim_time', rclpy.Parameter.Type.BOOL, True)])
        self.js = None
        self.create_subscription(JointState, '/joint_states', lambda m: setattr(self, 'js', dict(zip(m.name, m.position))), 10)
        self.ac = ActionClient(self, MoveGroup, '/move_action')
        self.scene_pub = self.create_publisher(PlanningScene, '/planning_scene', 10)

    def wait(self, pred, t):
        t0 = time.time()
        while not pred() and time.time() - t0 < t:
            rclpy.spin_once(self, timeout_sec=0.1)
        return pred()

    def arm(self):
        return [self.js[j] for j in ARM]


def main():
    rclpy.init()
    n = T()
    if not n.wait(lambda: n.js is not None and ARM[0] in n.js, 20) or not n.ac.wait_for_server(timeout_sec=30):
        print('FAIL: no joint_states or /move_action'); return 2
    # table below robot base (top at z=-0.01 so link0 is not in start-state collision)
    co = CollisionObject(); co.header.frame_id = 'world'; co.id = 'table'
    prim = SolidPrimitive(type=SolidPrimitive.BOX, dimensions=[1.1, 1.0, 0.4])
    p = Pose(); p.position.x, p.position.y, p.position.z = 0.3, 0.0, -0.21; p.orientation.w = 1.0
    co.primitives, co.primitive_poses, co.operation = [prim], [p], CollisionObject.ADD
    ps = PlanningScene(is_diff=True); ps.world.collision_objects = [co]
    for _ in range(5):
        n.scene_pub.publish(ps); n.wait(lambda: False, 0.2)

    before = n.arm()
    print('joint_states BEFORE:', [round(x, 3) for x in before])
    goal_pose = (0.45, 0.15, 0.30)  # hand origin above red_cube (0.45, 0.15)
    g = MoveGroup.Goal()
    r = g.request
    r.group_name = 'panda_arm'; r.num_planning_attempts = 5; r.allowed_planning_time = 5.0
    r.max_velocity_scaling_factor = 0.3; r.max_acceleration_scaling_factor = 0.3
    c = Constraints()
    pc = PositionConstraint(); pc.header.frame_id = 'world'; pc.link_name = 'panda_hand'
    box = SolidPrimitive(type=SolidPrimitive.BOX, dimensions=[0.01, 0.01, 0.01])
    bp = Pose(); bp.position.x, bp.position.y, bp.position.z = goal_pose; bp.orientation.w = 1.0
    pc.constraint_region = BoundingVolume(primitives=[box], primitive_poses=[bp]); pc.weight = 1.0
    oc = OrientationConstraint(); oc.header.frame_id = 'world'; oc.link_name = 'panda_hand'
    oc.orientation.x = 1.0; oc.orientation.w = 0.0  # hand z-axis pointing down
    oc.absolute_x_axis_tolerance = oc.absolute_y_axis_tolerance = 0.1; oc.absolute_z_axis_tolerance = 3.14; oc.weight = 1.0
    c.position_constraints, c.orientation_constraints = [pc], [oc]
    r.goal_constraints = [c]
    g.planning_options.plan_only = False
    fut = n.ac.send_goal_async(g); n.wait(fut.done, 15)
    gh = fut.result()
    if gh is None or not gh.accepted:
        print('FAIL: MoveGroup goal rejected'); return 3
    rf = gh.get_result_async(); n.wait(rf.done, 60)
    res = rf.result()
    code = res.result.error_code.val if res else None
    time.sleep(1.0); n.wait(lambda: False, 1.0)
    after = n.arm()
    print('joint_states AFTER :', [round(x, 3) for x in after])
    delta = max(abs(a - b) for a, b in zip(before, after))
    print(f'MoveIt error_code={code} (1 = SUCCESS), max joint delta={delta:.3f} rad')
    ok = code == MoveItErrorCodes.SUCCESS and delta > 0.1
    print('RESULT:', 'PASS' if ok else 'FAIL')
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
