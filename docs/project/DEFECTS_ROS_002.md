# MD-ROS-002 live-run defects (Angela, Tester)

Status: open. Evidence is in the tester scratchpad (p2_status.txt, ros_tests.out, import_probe2.out).

## D-ROS-1: `scripts/demo.sh --no-gui` does not stop on SIGINT (medium, owner: Andy)
- Repro: start `scripts/demo.sh --no-gui` (ROS_DOMAIN_ID=87), wait for `[4/4] ready`, send SIGINT to the demo PID, wait 120 s.
- Observed: the demo PID is still alive. Still running: `gz sim -r -s -v2 munder_difflin.sdf`, `move_group`, two `parameter_bridge` processes, the backend and `vite preview` on 5173.
- Impact: the next simulator on the same domain runs beside the leftover one (two sims on domain 87 at once, seen at 14:02). Breaks "Ctrl+C leaves 0 leftover processes" (god item 5).
- Workaround used: SIGTERM then SIGKILL to the PIDs we started (never pkill).

## D-ROS-2: `go_home` aborts after an earlier test leaves joint1 at its limit (medium, owner: Andy, test side: Angela)
- Correction: an earlier version blamed an out-of-limit HOME. Not so. `HOME = [0.0, -0.785, 0.0, -2.356, 0.0, 1.571, 0.785]` (tests/ros/rig.py:30) is in limits.
- Repro: `tests/ros` pytest, session sim fixture. The beyond-limit goal test (joint1 target 3.567) leaves joint1 at 2.967 (its limit). The next `Rig.go_home()` (tests/ros/rig.py:258, 5 s budget) then aborts.
- Observed: `(6, -5, 'Aborted due to goal_time_tolerance exceeding by 1.010000 seconds')`. Six setup errors come from this one cause.
- Open: the trajectory duration from joint1 2.967 to 0 in 5 s is not enough for the time tolerance. Needs a longer home move or a reset before the home move. Not yet tested.
- Earlier run (moveit runA): `plan_execute_test` MoveIt error_code -4 after a 1.605 rad first move.
- Note: the run mixed old and new `ros2_ws` code (edits 13:55-14:00).

## T-ROS-3: live API check could not import rclpy (fixed on tester side)
- Cause: `scripts/` runner did not source ROS 2 before running the venv Python.
- Fix: `ros_env.sh` + `live_api.sh` in the tester scratchpad (sources /opt/ros/jazzy and ros2_ws/install).
- Verified: rclpy imports; the script reaches the HTTP calls.
