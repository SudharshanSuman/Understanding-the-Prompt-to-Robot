"""L1 rig: starts the REAL simulation (`ros2 launch munder_difflin_bringup sim.launch.py`, gz server headless) and talks to it
through plain rclpy clients. Nothing here is mocked.

Isolation (the machine is shared with other agents' sims): a private ROS_DOMAIN_ID, a private GZ_PARTITION and
ROS_LOCALHOST_ONLY=1, plus a unique MD_TEST_RUN_ID in the launch environment. The run id is how `leaked()` finds anything that
survives shutdown, without ever touching another agent's processes.
"""
from __future__ import annotations

import math
import os
import signal
import subprocess
import threading
import time
import uuid
import xml.etree.ElementTree as ET
from collections import deque
from pathlib import Path

ARM = [f"panda_joint{i}" for i in range(1, 8)]
HAND = ["panda_finger_joint1", "panda_finger_joint2"]
ARM_ACTION = "/panda_arm_controller/follow_joint_trajectory"
HAND_ACTION = "/panda_hand_controller/gripper_cmd"
CONTROLLERS = {
    "joint_state_broadcaster": "joint_state_broadcaster/JointStateBroadcaster",
    "panda_arm_controller": "joint_trajectory_controller/JointTrajectoryController",
    "panda_hand_controller": "position_controllers/GripperActionController",
}
HOME = [0.0, -0.785, 0.0, -2.356, 0.0, 1.571, 0.785]   # initial_value in the URDF ros2_control block
DOMAIN_ID = 87
REPORTS = Path(__file__).resolve().parents[1] / "reports" / "ros"

# control_msgs/FollowJointTrajectory.Result error codes
SUCCESSFUL, INVALID_GOAL, INVALID_JOINTS, OLD_HEADER_TIMESTAMP, PATH_TOLERANCE_VIOLATED, GOAL_TOLERANCE_VIOLATED = 0, -1, -2, -3, -4, -5
# action_msgs/GoalStatus
STATUS_SUCCEEDED, STATUS_CANCELED, STATUS_ABORTED = 4, 5, 6


def sims_in_test_domain() -> list[int]:
    """PIDs of any `gz sim` running with our private ROS_DOMAIN_ID (a stray earlier run would double every topic)."""
    out = []
    for d in Path("/proc").iterdir():
        if not d.name.isdigit():
            continue
        try:
            if b"gz sim" in (d / "cmdline").read_bytes().replace(b"\0", b" ") and f"ROS_DOMAIN_ID={DOMAIN_ID}".encode() in (d / "environ").read_bytes().split(b"\0"):
                out.append(int(d.name))
        except OSError:
            continue
    return out


class SimProcess:
    def __init__(self, workspace: Path, launch_file: str = "sim.launch.py", package: str = "munder_difflin_bringup"):
        self.workspace, self.launch_file, self.package = workspace, launch_file, package
        self.run_id = uuid.uuid4().hex
        self.proc: subprocess.Popen | None = None
        self.log_path = REPORTS / "sim_launch.log"
        self.env = {**os.environ, "ROS_DOMAIN_ID": str(DOMAIN_ID), "ROS_LOCALHOST_ONLY": "1",
                    "GZ_PARTITION": f"md_test_{self.run_id[:8]}", "MD_TEST_RUN_ID": self.run_id}
        # same environment for our own rclpy node: it must not see anybody else's graph
        self.env.pop("ROS_AUTOMATIC_DISCOVERY_RANGE", None)

    def start(self) -> None:
        REPORTS.mkdir(parents=True, exist_ok=True)
        self._log = open(self.log_path, "wb")
        self.proc = subprocess.Popen(["ros2", "launch", self.package, self.launch_file], env=self.env, stdin=subprocess.DEVNULL,
                                     stdout=self._log, stderr=subprocess.STDOUT, start_new_session=True)

    def alive(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def leaked(self) -> list[tuple[int, str]]:
        """Live (non-zombie) processes whose environment carries our run id. Excludes this pytest process by construction."""
        needle = f"MD_TEST_RUN_ID={self.run_id}".encode()
        found = []
        for d in Path("/proc").iterdir():
            if not d.name.isdigit() or int(d.name) == os.getpid():
                continue
            try:
                if needle not in (d / "environ").read_bytes().split(b"\0"):
                    continue
                stat = (d / "stat").read_text()
                if stat.rsplit(")", 1)[1].split()[0] == "Z":
                    continue
                found.append((int(d.name), (d / "cmdline").read_bytes().replace(b"\0", b" ").decode(errors="replace")[:110]))
            except OSError:
                continue
        return found

    def shutdown(self, grace: float = 30.0) -> dict:
        """Ctrl+C the launch (SIGINT to the launch process only, exactly what a user does), wait, then report what survived."""
        t0 = time.monotonic()
        exit_code = None
        if self.alive():
            os.kill(self.proc.pid, signal.SIGINT)
            try:
                exit_code = self.proc.wait(grace)
            except subprocess.TimeoutExpired:
                exit_code = "timeout"
        elif self.proc is not None:
            exit_code = self.proc.returncode
        deadline = time.monotonic() + 10
        while self.leaked() and time.monotonic() < deadline:
            time.sleep(0.25)
        left = self.leaked()
        for pid, _ in left:           # leave the machine clean even when the test fails
            try:
                os.kill(pid, signal.SIGKILL)
            except OSError:
                pass
        if self.proc is not None and self.proc.poll() is None:
            try:
                os.killpg(self.proc.pid, signal.SIGKILL)
            except OSError:
                pass
        try:
            self._log.close()
        except Exception:
            pass
        return {"elapsed_s": round(time.monotonic() - t0, 1), "launch_exit_code": exit_code, "leaked": left}


class Rig:
    """An rclpy node on its own context + background executor, with a /joint_states history."""

    def __init__(self):
        import rclpy
        from control_msgs.action import FollowJointTrajectory, GripperCommand
        from controller_manager_msgs.srv import ListControllers
        from rclpy.action import ActionClient
        from rclpy.context import Context
        from rclpy.executors import SingleThreadedExecutor
        from rcl_interfaces.srv import GetParameters
        from rosgraph_msgs.msg import Clock
        from sensor_msgs.msg import JointState

        self.rclpy = rclpy
        self.ctx = Context()
        rclpy.init(context=self.ctx, domain_id=DOMAIN_ID)
        self.node = rclpy.create_node("md_l1_tester", context=self.ctx)
        self.ex = SingleThreadedExecutor(context=self.ctx)
        self.ex.add_node(self.node)
        self.lock = threading.Lock()
        self.latest: dict[str, tuple[float, float]] = {}
        self.history: deque = deque(maxlen=60000)          # (monotonic_time, {name: (pos, vel)})
        self.stamps: deque = deque(maxlen=60000)           # header stamps (sim time, s)
        self.clock: deque = deque(maxlen=200)
        self.node.create_subscription(JointState, "/joint_states", self._on_js, 50)
        from rclpy.qos import qos_profile_sensor_data     # best-effort matches reliable and best-effort publishers alike
        self.node.create_subscription(Clock, "/clock", lambda m: self.clock.append(m.clock.sec + m.clock.nanosec * 1e-9), qos_profile_sensor_data)
        self.arm_ac = ActionClient(self.node, FollowJointTrajectory, ARM_ACTION)
        self.hand_ac = ActionClient(self.node, GripperCommand, HAND_ACTION)
        self.lc = self.node.create_client(ListControllers, "/controller_manager/list_controllers")
        self.rsp_params = self.node.create_client(GetParameters, "/robot_state_publisher/get_parameters")
        self._FJT, self._GC, self._LC, self._GP = FollowJointTrajectory, GripperCommand, ListControllers, GetParameters
        self._stop = False
        self.thread = threading.Thread(target=self._spin, daemon=True)
        self.thread.start()

    def _spin(self):
        while not self._stop and self.rclpy.ok(context=self.ctx):
            self.ex.spin_once(timeout_sec=0.05)

    def _on_js(self, m):
        t = time.monotonic()
        vel = list(m.velocity) + [float("nan")] * (len(m.name) - len(m.velocity))
        d = {n: (p, v) for n, p, v in zip(m.name, m.position, vel)}
        with self.lock:
            self.latest = d
            self.history.append((t, d))
            self.stamps.append(m.header.stamp.sec + m.header.stamp.nanosec * 1e-9)

    def close(self):
        self._stop = True
        self.thread.join(5)
        try:
            self.ex.shutdown()
            self.node.destroy_node()
            self.rclpy.shutdown(context=self.ctx)
        except Exception:
            pass

    # ---- helpers -------------------------------------------------------------------------------
    def wait_for(self, pred, timeout: float, step: float = 0.05):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            v = pred()
            if v:
                return v
            time.sleep(step)
        return pred()

    def future(self, fut, timeout: float):
        return self.wait_for(lambda: fut.done(), timeout) and fut.result()

    def pos(self, names=ARM) -> list[float] | None:
        with self.lock:
            return [self.latest[n][0] for n in names] if all(n in self.latest for n in names) else None

    def vel(self, names=ARM) -> list[float] | None:
        with self.lock:
            return [self.latest[n][1] for n in names] if all(n in self.latest for n in names) else None

    def since(self, t0: float, names=ARM) -> list[tuple[float, list[float]]]:
        with self.lock:
            return [(t, [d[n][0] for n in names]) for t, d in self.history if t >= t0 and all(n in d for n in names)]

    def list_controllers(self, timeout=10.0) -> dict[str, tuple[str, str]] | None:
        if not self.lc.wait_for_service(timeout):
            return None
        r = self.future(self.lc.call_async(self._LC.Request()), timeout)
        return {c.name: (c.type, c.state) for c in r.controller} if r else None

    def joint_limits(self, timeout=10.0) -> dict[str, tuple[float, float]]:
        """Read the limits from the robot_description the simulation was really launched with."""
        from rcl_interfaces.msg import ParameterType
        assert self.rsp_params.wait_for_service(timeout), "robot_state_publisher parameter service missing"
        req = self._GP.Request(names=["robot_description"])
        r = self.future(self.rsp_params.call_async(req), timeout)
        assert r and r.values and r.values[0].type == ParameterType.PARAMETER_STRING
        root = ET.fromstring(r.values[0].string_value)
        out = {}
        for j in root.iter("joint"):
            lim = j.find("limit")
            if j.get("type") == "revolute" and lim is not None:
                out[j.get("name")] = (float(lim.get("lower")), float(lim.get("upper")))
        return out

    def traj_goal(self, positions, secs: float, names=ARM, velocities=None):
        from builtin_interfaces.msg import Duration
        from trajectory_msgs.msg import JointTrajectoryPoint
        g = self._FJT.Goal()
        g.trajectory.joint_names = list(names)
        pt = JointTrajectoryPoint(positions=list(positions), velocities=list(velocities if velocities is not None else [0.0] * len(positions)))
        pt.time_from_start = Duration(sec=int(secs), nanosec=int((secs % 1) * 1e9))
        g.trajectory.points = [pt]
        return g

    def send(self, goal, timeout=10.0):
        """Returns the goal handle (accepted or rejected) or None on timeout."""
        assert self.arm_ac.wait_for_server(timeout), "arm action server missing"
        return self.future(self.arm_ac.send_goal_async(goal), timeout)

    def result(self, gh, timeout):
        r = self.future(gh.get_result_async(), timeout)
        return (r.status, r.result.error_code, r.result.error_string) if r else None

    def cancel(self, gh, timeout=10.0):
        r = self.future(gh.cancel_goal_async(), timeout)
        return r.return_code if r else None

    def go_home(self, secs=5.0):
        gh = self.send(self.traj_goal(HOME, secs))
        assert gh is not None and gh.accepted, "could not command the arm home"
        res = self.result(gh, secs + 15)
        assert res and res[1] == SUCCESSFUL, f"arm did not return home: {res}"
        time.sleep(0.3)

    def max_err(self, target, names=ARM) -> float:
        p = self.pos(names)
        return max(abs(a - b) for a, b in zip(p, target))


def all_finite(xs) -> bool:
    return all(isinstance(x, float) and math.isfinite(x) for x in xs)
