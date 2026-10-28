# Test report: ROS milestone 1 (MD-TEST-006)

Tester: Angela. Date: 2026-10-28. Subject: `ros2 launch munder_difflin_bringup sim.launch.py` (Gazebo Harmonic server headless, ros2_control, Panda from `moveit_resources_panda_description`). Andy's logs were not used as evidence; every result below comes from my own runs.

## Verdict
Milestone 1 works (controllers, trajectory, cancel, gripper) with **2 open defects**: D1 shutdown leaves `gz sim` running, D2 an out-of-limit goal is reported SUCCEEDED. Both are real failing tests.

## How it was run
- Real simulation, no mocks. Private `ROS_DOMAIN_ID=87`, `ROS_LOCALHOST_ONLY=1`, own `GZ_PARTITION`, run id in the launch environment (used to find leaks). One sim at a time.
- Command: `source /opt/ros/jazzy/setup.bash; source ros2_ws/install/setup.bash; MD_RUN_GAZEBO=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -p pytest_timeout tests/ros -c tests/pytest.ini -q -rsx -s`
- Final run: **13 passed, 2 failed, 5 skipped in 137 s**. Without ROS sourced the whole repo suite is unchanged: 314 passed, 26 skipped, 0 failed.
- Startup to all controllers active: 11 to 60 s depending on machine load.

## Results
| Check | Result | Evidence |
|---|---|---|
| 3 controllers active (joint_state_broadcaster, panda_arm_controller, panda_hand_controller), exact types | PASS | `list_controllers` service, compared to the expected dict |
| Arm and hand action servers exist | PASS | `/panda_arm_controller/follow_joint_trajectory`, `/panda_hand_controller/gripper_cmd` |
| 9 finite joints at initial pose | PASS | arm at [0,-0.785,0,-2.356,0,1.571,0.785] within 0.02 rad, fingers 0.04 |
| `/joint_states` rate >= 10 Hz, stamps are simulation time and advance | PASS | stamps start near 0 (e.g. 6.1 s), not wall clock |
| `/clock` bridged from Gazebo and advancing | PASS | publisher is a bridge node, messages received |
| Trajectory goal: SUCCEEDED, joints follow smoothly, end within 0.02 rad | PASS | target [0.4,-0.5,0,-2.0,0,1.8,0.785]; Andy's `send_test_trajectory.py` also reported error_code 0, delta 0.4 rad |
| Every commanded joint moved | PASS | |
| **G at ROS level**: cancel mid-trajectory | PASS | cancel accepted, goal CANCELED, motion stopped 0.10 s after the request, drift 0.00037 rad, velocities at cancel about 0.09 rad/s |
| Unknown joint name / missing joints / empty trajectory | PASS | goal rejected, arm unmoved |
| NaN position in a goal | CHARACTERIZED | accepted and means "do not command this joint"; the executor must refuse non-finite values itself |
| Gripper close and reopen | PASS | real result, mimic finger follows |
| Goal beyond a joint limit | **FAIL (D2)** | below |
| Clean shutdown, no leftover gz/ros process | **FAIL (D1)** | below |

## Defects (owner: Andy)
**D1, HIGH, shutdown leaves the gz server.** Ctrl+C (SIGINT) of the launch: it exits with code 0 after about 15 s, but `gz sim -r -s -v2 munder_difflin.sdf` survives (5 of 5 runs, `tests/reports/ros/shutdown.json`):
```
shutdown: {'elapsed_s': 15.3, 'launch_exit_code': 0, 'leaked': [(412272, 'gz sim -r -s -v2 munder_difflin.sdf')]}; 6 processes before
[ERROR] [gazebo-1]: process[gazebo-1] failed to terminate '5' seconds after receiving 'SIGINT', escalating to 'SIGTERM'
[ERROR] [gazebo-1]: process has died ... ruby /opt/ros/jazzy/opt/gz_tools_vendor/bin/gz sim -r -s -v2 munder_difflin.sdf
```
The ruby wrapper dies, the real server child is orphaned (ppid = systemd --user). SIGTERM to the launch also leaves gz, robot_state_publisher and parameter_bridge alive. Andy's own earlier runs left several generations of these (ROS_DOMAIN_ID=42); I did not touch them. My rig SIGKILLs its own survivors after measuring.

**D2, MEDIUM, false success.** joint1 target 3.567 rad, URDF upper limit 2.9671:
```
beyond-limit goal: accepted, result (status, error_code, text) = (4, 0, 'Goal successfully reached!'); joint1 peak 2.967, final 2.967
```
The arm stays inside its limits but the result lies. `ros2_controllers.yaml` has no per-joint `constraints.goal` / `constraints.trajectory`, only `stopped_velocity_tolerance` and `goal_time`. Fix: add tolerances so a missed goal gives GOAL_TOLERANCE_VIOLATED. The executor must still verify by observing `/joint_states`.

## Observations (not defects)
- `scripts/smoke_test.sh` was a placeholder when checked.
- `/joint_states` effort is NaN. The hand controller uses the deprecated `position_controllers/GripperActionController`.
- External signals: in 4 of 8 full-module runs my simulation was terminated from outside (launch got SIGINT mid-test, or the gz wrapper got SIGTERM during startup). My tests send no signals during a run. Another agent's `pkill` by pattern is the likely cause but I could not prove the sender. Reported to Andy; the fixture now fails with an explicit message instead of ten "server missing" errors.

## Not executed (skipped with the reason in the skip message)
Executor-level D/E/F, backend half of G, H (no ROS executor in milestone 1); C (no MoveIt planning scene); `/munder_difflin/safety/emergency_stop` (not part of milestone 1). Gazebo GUI rendering and real-time factor were not measured.

## Files
`tests/ros/rig.py`, `tests/ros/test_sim_m1.py`, `tests/ros/test_acceptance_ros.py`, `tests/conftest.py` (`ros_node` fixture made safe), `tests/README.md`, `docs/project/TEST_PLAN.md` (section 9). Run artifacts: `tests/reports/ros/sim_launch.log`, `shutdown.json`.
