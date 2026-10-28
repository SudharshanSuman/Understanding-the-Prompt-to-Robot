#!/usr/bin/env python3
"""Send one FollowJointTrajectory goal to /panda_arm_controller and print joint_states before/after.

Exit 0 only if the action succeeded AND at least one arm joint moved by > --min-delta rad.
"""
import argparse
import sys
import time

import rclpy
from builtin_interfaces.msg import Duration
from control_msgs.action import FollowJointTrajectory
from rclpy.action import ActionClient
from rclpy.node import Node
from sensor_msgs.msg import JointState
from trajectory_msgs.msg import JointTrajectoryPoint

ARM = [f'panda_joint{i}' for i in range(1, 8)]
TARGET = [0.4, -0.5, 0.0, -2.0, 0.0, 1.8, 0.785]


class T(Node):
    def __init__(self):
        super().__init__('md_test_trajectory', parameter_overrides=[
            rclpy.parameter.Parameter('use_sim_time', rclpy.Parameter.Type.BOOL, True)])
        self.js = None
        self.create_subscription(JointState, '/joint_states', self._cb, 10)
        self.ac = ActionClient(self, FollowJointTrajectory, '/panda_arm_controller/follow_joint_trajectory')

    def _cb(self, m):
        self.js = dict(zip(m.name, m.position))

    def arm(self):
        return [self.js[j] for j in ARM]

    def spin_until(self, pred, timeout):
        t0 = time.time()
        while not pred() and time.time() - t0 < timeout:
            rclpy.spin_once(self, timeout_sec=0.1)
        return pred()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--min-delta', type=float, default=0.1)
    ap.add_argument('--duration', type=float, default=4.0)
    a = ap.parse_args()
    rclpy.init()
    n = T()
    if not n.spin_until(lambda: n.js is not None and all(j in n.js for j in ARM), 20):
        print('FAIL: no /joint_states'); return 2
    if not n.ac.wait_for_server(timeout_sec=20):
        print('FAIL: action server missing'); return 2
    before = n.arm()
    print('joint_states BEFORE:', [round(x, 4) for x in before])
    goal = FollowJointTrajectory.Goal()
    goal.trajectory.joint_names = ARM
    pt = JointTrajectoryPoint(positions=TARGET, velocities=[0.0] * 7)
    pt.time_from_start = Duration(sec=int(a.duration), nanosec=int((a.duration % 1) * 1e9))
    goal.trajectory.points = [pt]
    fut = n.ac.send_goal_async(goal)
    n.spin_until(fut.done, 10)
    gh = fut.result()
    if gh is None or not gh.accepted:
        print('FAIL: goal rejected'); return 3
    rf = gh.get_result_async()
    n.spin_until(rf.done, a.duration + 20)
    res = rf.result()
    err = res.result.error_code if res else None
    time.sleep(0.5); n.spin_until(lambda: False, 0.5)
    after = n.arm()
    print('joint_states AFTER :', [round(x, 4) for x in after])
    print('target             :', TARGET)
    delta = max(abs(x - y) for x, y in zip(before, after))
    print(f'action error_code={err} (0 = SUCCESSFUL), max joint delta={delta:.4f} rad')
    ok = err == 0 and delta > a.min_delta
    print('RESULT:', 'PASS' if ok else 'FAIL')
    rclpy.shutdown()
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
