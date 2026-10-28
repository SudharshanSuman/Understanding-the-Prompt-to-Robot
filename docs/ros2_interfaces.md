# ROS 2 interfaces (real graph)

**Work:** MD-ROS-001 · **Author:** Andy (Integration Engineer) · **Date:** 2026-10-28
**Source of truth:** `ros2 topic|action|service|node list -t` run against the live sim. Raw output is in
`ros2_ws/logs/graph_{topics,actions,services,nodes,controllers}.log`. Nothing below is copied from a plan.
Items marked **NOT BUILT** are in INTERFACE_CONTRACTS s8 but do not exist in the graph yet.

## 1. Stack and how to run

| Layer | What runs | Source |
| :-- | :-- | :-- |
| Simulator | Gazebo Sim 8.15.0 (Harmonic), headless server (`-s`), DART physics, 1 ms step | apt (`ros-jazzy-ros-gz`) |
| Arm + hand | Franka Panda 7-DOF + Franka Hand, names `panda_*` | apt `moveit_resources_panda_description` (upstream, not recreated) |
| Control | `gz_ros2_control/GazeboSimSystem`, `joint_state_broadcaster`, `joint_trajectory_controller`, `position_controllers/GripperActionController` | apt (`ros-jazzy-gz-ros2-control`, `ros2-controllers`) |
| Planning | MoveIt 2 `move_group`, OMPL, KDL, `moveit_simple_controller_manager` | apt (`ros-jazzy-moveit`) |
| Workspace | `ros2_ws/src/munder_difflin_{description,gazebo,moveit_config,bringup,control}` | this repo |

**Franka source path / libfranka / rosbridge (answers to MD-REL-003):**
- The Franka source path was **not** built. `franka_ros2` (v3.6.1) and `franka_description` (2.9.0) were cloned for evaluation, then dropped:
  their Panda is `fer_*` (contract needs `panda_*`) and `franka_ros2` expects `libfranka`, which apt does not provide. We fell back to the
  apt Panda packages (ADR-006 path); nothing here needs `libfranka` and no sim-only Franka build was attempted.
- Therefore `ros2_ws/munder_difflin.repos` is empty (`repositories: {}`): `vcs import` has nothing to fetch; all dependencies are apt.
- **No rosbridge is needed.** The backend reaches ROS in-process with `rclpy` through `RosExecutor` (s7). Nothing listens on a ROS-over-websocket port.

Deviation from the brief: `franka_ros2`/`franka_description` were **not** used. The apt Panda model already has the
contract names (`panda_joint1..7`, `panda_finger_joint1/2`, `panda_hand`, `panda_link0`); `franka_description`'s Panda
is `fer_*` and would need renames. No `libfranka` is involved.

```bash
source /opt/ros/jazzy/setup.bash && cd munder_difflin/ros2_ws && colcon build --symlink-install && source install/setup.bash
ros2 launch munder_difflin_bringup sim.launch.py          # Gazebo (headless) + controllers
ros2 launch munder_difflin_bringup moveit.launch.py       # the above + move_group
ros2 launch munder_difflin_bringup moveit.launch.py headless:=false rviz:=true   # GUI / RViz only when needed
munder_difflin/ros2_ws/src/munder_difflin_bringup/scripts/smoke_test.sh --moveit # PASS/FAIL smoke test
```
The workspace path contains spaces; the launch files avoid shell-split commands for that reason.
Use `ROS_DOMAIN_ID=42` (the scripts export it) to isolate from other ROS processes.

### Run it (exact commands; RELEASE_CHECKLIST 4a)
```bash
# build (once, and after pulling changes)
source /opt/ros/jazzy/setup.bash && cd munder_difflin/ros2_ws && colcon build --symlink-install
# packages: munder_difflin_description, _gazebo, _moveit_config, _bringup, _control
# 4a automated check, headless, ~1 min, prints "SMOKE: PASS" (takes hive/sim.lock; add --moveit to include MoveIt):
munder_difflin/ros2_ws/src/munder_difflin_bringup/scripts/smoke_test.sh --moveit
# visible demo for a person: Gazebo GUI + MoveIt + backend + dashboard, Ctrl+C stops everything:
munder_difflin/scripts/demo.sh              # add --software if the Gazebo window crashes on the GPU path; --rviz for RViz
munder_difflin/scripts/demo_cli.sh "Pick up the red cube and place it in the storage box"   # same, through the API, no browser
# GUI sim + one pick-and-place without backend/dashboard:
munder_difflin/ros2_ws/src/munder_difflin_bringup/scripts/demo_pick_place.sh red_cube storage_box
```
Only one simulation at a time (~5 GB RAM): the scripts take `hive/sim.lock` and refuse to start while another agent holds it.
Shutdown: Ctrl+C on `sim.launch.py`/`moveit.launch.py` ends the gz server too (`gz_server.sh` runs gz in its own process group; checked: launch exits in <1 s, no leftover process).

## 2. Arm audit values (fills `[TBD-arm-audit]` in INTERFACE_CONTRACTS s8)

| Placeholder | Real value | Verified by |
| :-- | :-- | :-- |
| arm controller | `panda_arm_controller` (`joint_trajectory_controller/JointTrajectoryController`) | `graph_controllers.log` |
| arm action | `/panda_arm_controller/follow_joint_trajectory` (`control_msgs/action/FollowJointTrajectory`) | `graph_actions.log` |
| gripper controller | `panda_hand_controller` (`position_controllers/GripperActionController`, joint `panda_finger_joint1`; `panda_finger_joint2` mimics it) | `graph_controllers.log` |
| gripper action | `/panda_hand_controller/gripper_cmd` (`control_msgs/action/GripperCommand`); `position` = per-finger travel in m (0.0 closed .. 0.04 open) | `graph_actions.log` |
| arm joints | `panda_joint1..7`, ready pose `[0, -0.785, 0, -2.356, 0, 1.571, 0.785]` | `m1_trajectory.log` |
| planning groups | `panda_arm` (chain `panda_link0`..`panda_link8`), `panda_hand` (renamed from upstream `hand`) | `config/panda.srdf` |
| base / tool frame | `world` = base of `panda_link0`; tool link `panda_hand` (TCP 0.1034 m below its origin) | URDF |
| MoveIt action | `/move_action` (`moveit_msgs/action/MoveGroup`) | `graph_actions.log` |

## 3. Actions (real)
| Action | Type | Server |
| :-- | :-- | :-- |
| `/panda_arm_controller/follow_joint_trajectory` | `control_msgs/action/FollowJointTrajectory` | `panda_arm_controller` |
| `/panda_hand_controller/gripper_cmd` | `control_msgs/action/GripperCommand` | `panda_hand_controller` |
| `/move_action` | `moveit_msgs/action/MoveGroup` | `move_group` |
| `/execute_trajectory` | `moveit_msgs/action/ExecuteTrajectory` | `move_group` |

## 4. Topics (real, application-relevant; full list in `graph_topics.log`)
| Topic | Type | Notes |
| :-- | :-- | :-- |
| `/joint_states` | `sensor_msgs/msg/JointState` | 7 arm + 2 finger joints, position + velocity |
| `/dynamic_joint_states` | `control_msgs/msg/DynamicJointState` | |
| `/tf`, `/tf_static` | `tf2_msgs/msg/TFMessage` | robot_state_publisher |
| `/clock` | `rosgraph_msgs/msg/Clock` | sim time; all nodes use `use_sim_time:=true` |
| `/robot_description`, `/robot_description_semantic` | `std_msgs/msg/String` | |
| `/panda_arm_controller/controller_state` | `control_msgs/msg/JointTrajectoryControllerState` | |
| `/panda_arm_controller/joint_trajectory` | `trajectory_msgs/msg/JointTrajectory` | |
| `/planning_scene`, `/monitored_planning_scene`, `/planning_scene_world` | `moveit_msgs/msg/PlanningScene*` | |
| `/model/{red_cube,blue_cube,green_cylinder}/pose` | `geometry_msgs/msg/Pose` | Gazebo ground truth, 20 Hz (stand-in for perception) |
| `/munder_difflin/gz/attach/<id>`, `/munder_difflin/gz/detach/<id>` | `std_msgs/msg/Empty` | ROS -> Gazebo DetachableJoint commands, ids: `red_cube`, `blue_cube`, `green_cylinder` |
| `/munder_difflin/gz/attached/<id>` | `std_msgs/msg/Bool` | Gazebo -> ROS attach state |
| `/munder_difflin/telemetry` | `std_msgs/msg/String` (JSON) | only while a `RosExecutor` is alive, 10 Hz, shape in s11 |

## 5. Services (real, application-relevant; full list in `graph_services.log`)
| Service | Type |
| :-- | :-- |
| `/compute_ik`, `/compute_fk` | `moveit_msgs/srv/GetPositionIK`, `GetPositionFK` |
| `/compute_cartesian_path` | `moveit_msgs/srv/GetCartesianPath` |
| `/apply_planning_scene`, `/get_planning_scene` | `moveit_msgs/srv/ApplyPlanningScene`, `GetPlanningScene` |
| `/plan_kinematic_path`, `/check_state_validity` | `moveit_msgs/srv/GetMotionPlan`, `GetStateValidity` |
| `/controller_manager/{list_controllers,switch_controller,list_hardware_interfaces,...}` | `controller_manager_msgs/srv/*` |
| `/munder_difflin/safety/emergency_stop` | `std_srvs/srv/Trigger` (success = stop confirmed; `message` = JSON `StopReport`). Exists only while a `RosExecutor` is alive. |
| ~~`/munder_difflin/safety/reset`~~ | **Removed (SEC-013-D1).** Stopping is always safe; clearing the e-stop latch is only possible through the authenticated HTTP API (`POST /api/v1/simulation/reset` -> `executor.reset()`). |

## 6. Contract items NOT BUILT (INTERFACE_CONTRACTS s8)
`munder_difflin_msgs`, `/munder_difflin/execute_task`, `/munder_difflin/grasp`, `/munder_difflin/verification/verify_placement`,
`/perception/detected_objects`, and the packages `munder_difflin_perception|planning` do **not** exist. The pipeline
stages are instead implemented in-process by `RosExecutor` (s7), using Gazebo ground-truth poses where perception would
be. If the Architect wants these as ROS actions/services, that is a separate work item.

## 7. Backend Executor (`munder_difflin_control.ros_executor.RosExecutor`)
Implements `backend/app/executor.py::Executor`: `status()`, `execute()`, `cancel()`, `emergency_stop()`, `reset()`.
- Use: `app.main.main(RosExecutor())`, i.e. `python -m munder_difflin_control.backend_with_ros` (honours MD_BIND_HOST/MD_ALLOW_REMOTE/APP_PORT). `RosExecutor.telemetry()` returns the live snapshot (non-blocking, NaN -> null).
- Perception: object poses are Gazebo ground truth and are labelled `simulation-ground-truth` in the grounding events and in telemetry (`perception`).
- Joint targets outside the URDF limits, or non-finite, are rejected by the executor before sending; after each trajectory the executor reads `/joint_states` back and fails if they do not match the end point (MD-TEST-006 D2). The controller also has per-joint goal tolerances (0.02 rad), so a missed goal ends `GOAL_TOLERANCE_VIOLATED`.
- (old) Use: `create_app(executor=RosExecutor())` Needs ROS sourced, the
  sim + `move_group` running, `backend/` on `PYTHONPATH`, and the backend venv (Python 3.12, same as ROS). The venv has
  no `yaml`/`numpy`, which `rclpy` needs: put `ros2_ws/pylib` (symlinks to the system `yaml`, `numpy`, `lark`) on
  `PYTHONPATH` **instead of** `/usr/lib/python3/dist-packages`, whose `typing_extensions` breaks pydantic.
  Example: `MD_API_TOKEN=<32+ chars> PYTHONPATH=<backend>:<ros2_ws>/pylib <backend>/.venv/bin/python -m munder_difflin_control.backend_with_ros` (after sourcing ROS and `install/setup.bash`).
- `execute()` emits `PipelineStageEvent` for stages `grounding, planning_scene, ik, planning, trajectory_validation,
  execution, simulation, verification` (`run_id` = `task_id`). A failed stage emits `failed` and raises `ExecutorError`.
- `execution` sequence: open gripper, pre-grasp (OMPL), Cartesian descend, close, attach (DetachableJoint + MoveIt attached
  object), lift (checks the object rose >= 5 cm), move above destination, Cartesian descend, detach, open, retreat, ready pose.
- `verification` is read from Gazebo ground truth: object xy within the destination tolerance and z at the support height.
  Tolerances: `storage_box` 0.09 m, others 0.05 m (see `scene.py`).
- `emergency_stop()`: latches, cancels active goals, deactivates `panda_arm_controller`, then reads `/joint_states`
  velocities 10x and returns `stop_report(...)` (`e_stop_confirmed` only if all < 1e-4 rad/s and controller `inactive`).
  While latched, `execute()` raises `ExecutorError`. `reset()` re-activates the controller and clears the latch only if the controller is `active`.
- `cancel(task_id)` cancels the active goal; `execute()` then emits a `cancelled` event and returns.
- Telemetry JSON: `{time, task_id, stage, state, e_stop_latched, held_object, joints{panda_joint1..7}, max_arm_joint_velocity, gripper_opening_m, objects{id:[x,y,z]}}`.

## 8. Scene (world frame, table top z = 0, +x forward, +y robot-left)
Model names equal `config/scene.json` ids. Poses below are the initial layout (`munder_difflin_gazebo/worlds/munder_difflin.sdf`, `munder_difflin_control/scene.py`).
| id | Shape | Centre (x, y) | Notes |
| :-- | :-- | :-- | :-- |
| `table` | box 1.1 x 1.0 x 0.4 | (0.30, 0.00) | static, top z = 0 |
| `platform` | box 0.14 x 0.14 x 0.005 | (0.30, 0.35) | static, yellow |
| `red_cube` | box 0.04, 0.05 kg | (0.45, 0.15) | graspable |
| `blue_cube` | box 0.04, 0.05 kg | (0.35, -0.12) | graspable |
| `green_cylinder` | r 0.025, h 0.08, 0.06 kg | (0.55, -0.05) | graspable |
| `storage_box` | open box, inner 0.24 x 0.24, walls 0.08 high | (0.45, -0.40) | static |
| `table_left` / `table_right` | logical zones (no model) | (0.55, 0.28) / (0.65, -0.15) | destinations from scene.json |

Grasp mechanism (ADR-007, hybrid): the fingers close on the object (physical, friction 1.5) **and** a Gazebo
`DetachableJoint` between `panda_hand` and the object is created on `attach` and removed on `detach`; MoveIt also treats it as an attached object.

## 9. Verification status (evidence in `ros2_ws/logs/`)
| Claim | Evidence | Verified by tester? |
| :-- | :-- | :-- |
| Controllers active, trajectory changes `/joint_states` | `m1_controllers.log`, `m1_trajectory.log`; repeated by `smoke_test.sh --moveit`: `m7_smoke.log` (`SMOKE: PASS`) | not yet |
| Scene models spawned with scene.json ids | `m3_state.log` | not yet |
| MoveIt plan + execute moves the arm | `m3_plan_execute.log` | not yet |
| Executor: pick `red_cube` -> `storage_box`, verification success | `m5f_executor.log` | not yet |
| Executor: e-stop during motion confirmed (arm 0.67 rad/s before, 8e-11 after), execute refused, reset works | `m5f_executor.log`, `m7_executor.log` (prints the pre-stop velocity); telemetry stream `m7_telemetry_stream.log` | not yet |
| Executor: cancel mid-run emits `cancelled` | `m5f_executor.log` | not yet |

Not measured: Gazebo real-time factor, RAM of the sim processes, repeatability across runs, other object/destination pairs, grasp failure injection.

## 10. Visible demo (MD-ROS-002), measured 2026-10-28

Run `scripts/demo.sh` (Gazebo GUI + MoveIt + backend with `RosExecutor` + dashboard on http://127.0.0.1:5173), then type an
instruction in the dashboard or run `scripts/demo_cli.sh "<instruction>"`. Ctrl+C stops everything, removes the token file
and releases `hive/sim.lock`. Options: `--software` (Mesa software rendering), `--rviz`, `--no-gui`, `--open`.
The API token is generated per run, printed once, and kept only in `$XDG_RUNTIME_DIR/munder_difflin_demo.token` (mode 0600).

| item | result (evidence in `ros2_ws/logs/`) |
|---|---|
| GUI renders on this machine (AMD Vega iGPU, Mesa, no `--software` needed) | yes: `demo_shot5_cam.png`, `demo_shot7_motion.png` |
| real-time factor with the GUI open | 1.0001 to 1.0008 (`demo_rtf2.log`); 0.67 in the first seconds after launch |
| RAM (resident) | gz sim gui 483 MB, gz sim server 221 MB, move_group 95 MB, backend 131 MB; whole machine 10 to 11.3 GB of 15.3 GB used with other work running |
| "Pick up the red cube and place it in the storage box" through the API | completed, ~19 to 25 s, `red_cube placed at storage_box: xy error 0.000 m, z 0.030` (`demo_cli_run10.log`) |
| "Move the red cube to the storage box without touching the blue cube" | completed, blue_cube still at (0.35, -0.12) (`demo_cli_run10b.log`) |
| `executor_test all` (pick, e-stop, cancel) | PASS (`m8_executor.log`) |
| clean shutdown | `demo.sh` stops in ~27 to 32 s with 0 leftover processes; token file and lock removed |

Changes made while bringing the demo up (each found by running it):
- DetachableJoint plugins failed to initialise (`Link panda_hand not found`): gz lumps `panda_hand` into `panda_link7` when it
  converts the URDF, so `parent_link` is now `panda_link7`. The earlier passing grasps were friction only.
- `POST /simulation/reset` now restores the three objects (Gazebo `set_pose`), releases anything held and re-activates the arm
  controller. The route shows the executor `reset()` result after `; scene: ` (e.g. `ok; scene: objects restored`).
- `gz_server.sh` kills all descendants (in GUI mode the server and GUI live in their own process groups); `demo.sh` ends with a
  sweep over processes carrying its run marker. Never by name.
- The camera is moved to frame the arm and table after start (`gz service /gui/move_to/pose`).
- Controller path tolerance 0.15 to 0.60 rad per joint; arm planning speed scaling 0.4 to 0.25.
- Defect D2: a goal outside the joint limits (joint1 = 3.567 rad) is now aborted by the controller (`error_code -4`, status 6),
  not reported SUCCEEDED (`d2_probe.log`); `RosExecutor` also rejects non-finite or out-of-limit targets and reads the joints back.

Known issue, cause not isolated: on a fresh sim start the first fast arm move aborts on the path tolerance because one joint
(panda_joint2 or panda_joint6, varying per run) does not break away for about a second (`ctrl_state_first_task.log`). A
`reset()` beforehand avoids it (tried: waiting 60 s, slower speed, a warm-up wiggle, a retry; none helped). `RosExecutor` therefore
calls `reset()` once before the first task of a session. After the change, 2 of 2 fresh starts completed the first task (plus 1 with an explicit reset before it).

## 11. Telemetry shape (`RosExecutor.telemetry()`, topic `/munder_difflin/telemetry`, GET `/api/v1/telemetry`)

Non-blocking, never raises, 10 Hz on the topic. `None` (API: `available:false`) until the first `/joint_states`. Strict JSON:
NaN/Inf are sent as `null`. Frame: world (arm base on the table top, z up). Units: rad, m, s.

```
{ "time": <wall s>, "sim_time": <Gazebo s>,
  "source": "ros2_gazebo", "perception": "simulation-ground-truth",
  "task_id": "...", "stage": "grounding|planning_scene|ik|planning|trajectory_validation|execution|simulation|verification|",
  "phase": "<last stage message, e.g. 'lifting', 'moving to above storage_box'>",
  "state": "IDLE|RUNNING|STOPPED", "e_stop_latched": false, "held_object": "red_cube" | "",
  "joints":  { "panda_joint1": rad, ... "panda_joint7": rad },
  "fingers": { "panda_finger_joint1": m, "panda_finger_joint2": m },      # 0.04 open, ~0.02 closed on a cube
  "max_arm_joint_velocity": rad/s, "gripper_opening_m": m,
  "objects": { "red_cube": [x, y, z], ... },                              # kept for older clients
  "object_poses": { "red_cube": {"position": [x,y,z], "orientation_xyzw": [x,y,z,w]}, "blue_cube": ..., "green_cylinder": ... },
  "attached": { "red_cube": false, ... } }                                # Gazebo DetachableJoint state
```
Recorded sample of a real pick-and-place: `ros2_ws/logs/telemetry_sample_pick_place.jsonl` (one JSON object per line).

## 12. Security-related run settings (SEC-011-D1, SEC-013-D1)
- All run scripts (`demo.sh`, `smoke_test.sh`, `demo_pick_place.sh`), `sim.launch.py`, `backend_with_ros` and `RosExecutor` set
  `ROS_LOCALHOST_ONLY=1` and `ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST` before ROS starts (DDS stays on this machine).
  Not covered: Gazebo's own transport (gz-transport, UDP multicast on the local network by default) is separate from DDS.
- No ROS reset service (s5). What remains: any local process can still call `/munder_difflin/safety/emergency_stop` (stop only) and
  publish to the gz attach/detach topics or `/panda_arm_controller/...` on this machine; the boundary is the local user.
- `ros2_ws/pylib` (git-ignored) is created by `scripts/setup_pylib.sh` (idempotent; called by the run scripts). It holds links to
  system `yaml`, `numpy`, `lark` plus a `COLCON_IGNORE` so colcon does not crawl them.

## 13. Tests without a simulator
`colcon test --packages-select munder_difflin_control`: 11 tests (readiness is non-blocking, out-of-limit and non-finite target rejection, empty trajectory,
telemetry None / NaN->null / strict JSON / field set, e-stop service present and reset service absent). Needs the ROS environment
sourced and the repo's `backend/` (found automatically, or set `MD_BACKEND_DIR`). `rosdep install --simulate --from-paths src --ignore-src` exits 0.
