#!/usr/bin/env python3
"""MD-ROS-002 probe: what does the FIRST fast arm move after a fresh sim start do?

Prints one JSON line: pre-move drift of the arm (static hold), action result, per-joint worst
tracking error (controller_state reference vs feedback) and when each joint first moved.
--pre none|reset|wait:<s>  what to do before the move (reset = go to the init pose once, like RosExecutor.reset()).
"""
import argparse
import json
import time

import rclpy
from builtin_interfaces.msg import Duration
from control_msgs.action import FollowJointTrajectory
from control_msgs.msg import JointTrajectoryControllerState
from rclpy.action import ActionClient
from rclpy.node import Node
from sensor_msgs.msg import JointState
from trajectory_msgs.msg import JointTrajectoryPoint

ARM = [f'panda_joint{i}' for i in range(1, 8)]
INIT = [0.0, -0.785, 0.0, -2.356, 0.0, 1.571, 0.785]
TARGET = [0.2, -0.2, 0.0, -2.2, 0.0, 2.297, 0.785]   # the shape of the aborting first move (j2 up, j6 +0.7 rad)


class P(Node):
    def __init__(self):
        super().__init__('md_first_move_probe', parameter_overrides=[
            rclpy.parameter.Parameter('use_sim_time', rclpy.Parameter.Type.BOOL, True)])
        self.js = None
        self.cs = []
        self.create_subscription(JointState, '/joint_states', lambda m: setattr(self, 'js', dict(zip(m.name, m.position))), 10)
        self.create_subscription(JointTrajectoryControllerState, '/panda_arm_controller/controller_state', self._cs, 50)
        self.ac = ActionClient(self, FollowJointTrajectory, '/panda_arm_controller/follow_joint_trajectory')
        self.rec = False

    def _cs(self, m):
        if self.rec:
            self.cs.append((time.time(), list(m.reference.positions), list(m.feedback.positions)))

    def spin(self, secs):
        t0 = time.time()
        while time.time() - t0 < secs:
            rclpy.spin_once(self, timeout_sec=0.05)

    def until(self, pred, timeout):
        t0 = time.time()
        while not pred() and time.time() - t0 < timeout:
            rclpy.spin_once(self, timeout_sec=0.05)
        return pred()

    def arm(self):
        return [self.js[j] for j in ARM]

    def move(self, target, dur):
        g = FollowJointTrajectory.Goal()
        g.trajectory.joint_names = ARM
        pt = JointTrajectoryPoint(positions=target, velocities=[0.0] * 7)
        pt.time_from_start = Duration(sec=int(dur), nanosec=int((dur % 1) * 1e9))
        g.trajectory.points = [pt]
        f = self.ac.send_goal_async(g)
        self.until(f.done, 10)
        gh = f.result()
        if gh is None or not gh.accepted:
            return None
        rf = gh.get_result_async()
        self.until(rf.done, dur + 15)
        r = rf.result()
        return r.result.error_code if r else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--pre', default='none')
    ap.add_argument('--duration', type=float, default=1.6)
    ap.add_argument('--hold', type=float, default=3.0, help='seconds to watch the static arm before moving')
    a = ap.parse_args()
    rclpy.init()
    n = P()
    if not n.until(lambda: n.js is not None and all(j in n.js for j in ARM), 30) or not n.ac.wait_for_server(timeout_sec=30):
        print(json.dumps({'error': 'no joint_states/action server'})); return 2
    out = {'pre': a.pre}
    p0 = n.arm()
    n.spin(a.hold)
    p1 = n.arm()
    out['rest_pose'] = [round(x, 4) for x in p0]
    out['drift_during_hold'] = [round(y - x, 5) for x, y in zip(p0, p1)]
    if a.pre == 'reset':
        out['pre_result'] = n.move(INIT, 2.0)
        n.spin(1.0)
    elif a.pre.startswith('wait:'):
        n.spin(float(a.pre.split(':')[1]))
    n.cs.clear(); n.rec = True
    t_send = time.time()
    out['error_code'] = n.move(TARGET, a.duration)
    n.rec = False
    worst = [0.0] * 7
    first_move = [None] * 7
    base = n.cs[0][2] if n.cs else None
    for t, ref, fb in n.cs:
        for i in range(7):
            worst[i] = max(worst[i], abs(ref[i] - fb[i]))
            if first_move[i] is None and base and abs(fb[i] - base[i]) > 0.01:
                first_move[i] = round(t - t_send, 2)
    out['worst_err'] = [round(x, 3) for x in worst]
    out['first_moved_s'] = first_move
    out['PASS'] = out['error_code'] == 0
    print(json.dumps(out))
    rclpy.shutdown()
    return 0 if out['PASS'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
