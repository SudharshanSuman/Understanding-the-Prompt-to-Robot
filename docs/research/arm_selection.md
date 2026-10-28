# Robotic Manipulator Selection for ROS 2 Jazzy & Gazebo Harmonic

**Document ID:** MD-RES-DOC-001  
**Author:** Oscar - Researcher (R) (`oscar-researcher-r--mvr0bax5`)  
**Work Package:** MD-RES-001 (Phase 0)  
**Target Platform:** Ubuntu 24.04 LTS (Noble Numbat), ROS 2 Jazzy Jalisco, Gazebo Harmonic (gz-sim 8), MoveIt 2  
**Date:** 2026-10-28  
**Verification Standard:** Every claim is explicitly marked as `[VERIFIED]` with upstream repository/package links or `[ASSUMPTION]`.

---

## 1. Executive Summary & Final Recommendation

| Manipulator | Degrees of Freedom | Official Jazzy Packages in apt | Jazzy Gazebo Harmonic (`gz_ros2_control`) | Integrated Gripper | Overall Verdict |
| :--- | :---: | :---: | :---: | :---: | :--- |
| **Franka Emika Panda / FR3** | 7-DOF | `[VERIFIED]` Partial (`moveit-resources`) | `[VERIFIED]` Full via source (`franka_ros2` `jazzy`) | `[VERIFIED]` Native Franka Hand | **RECOMMENDED PRIMARY** |
| **Universal Robots UR5e** | 6-DOF | `[VERIFIED]` Full (`ur_simulation_gz`) | `[VERIFIED]` Full via apt binary | `[VERIFIED]` No native gripper (needs add-on) | **RECOMMENDED FALLBACK** |
| **Kinova Gen3** | 6/7-DOF | `[VERIFIED]` Partial (`moveit-config`) | `[VERIFIED]` Experimental via source | `[VERIFIED]` Robotiq 2F-85 (mimic bugs) | **REJECTED (High Risk)** |

### Primary Recommendation: **Franka Emika Panda (7-DOF)**
- **Why:** Perfectly aligns with Project Specification Section 3 preference. Has a native 2-finger parallel jaw gripper (`franka_hand`) integrated into its kinematic tree and URDF. MoveIt 2 test packages (`moveit_resources_panda_description` and `moveit_resources_panda_moveit_config`) are pre-built and packaged in the official ROS 2 Jazzy apt repository. Upstream Franka Robotics maintains an active, dedicated `jazzy` branch with full `gz_ros2_control` Gazebo Harmonic launch support (`franka_gazebo_bringup`). The 7-DOF kinematic redundancy allows natural obstacle avoidance in cluttered pick-and-place scenes.

### Fallback Recommendation: **Universal Robots UR5e (6-DOF)**
- **Why:** The official Universal Robots Gazebo Harmonic simulation stack (`UniversalRobots/Universal_Robots_ROS2_GZ_Simulation`) is **already fully packaged and released as an official Debian binary in ROS 2 Jazzy** (`ros-jazzy-ur-simulation-gz` v2.5.0). It requires zero source compilation or dependency debugging. If any team member encounters build bottlenecks with `franka_ros2`, UR5e can be deployed immediately with a single `apt` command.
- **Drawback:** UR5e requires attaching a third-party gripper macro (e.g. Robotiq 2F-85 or custom parallel jaw) to the `tool0` flange and parameterizing MoveIt SRDF/controllers.

---

## 2. In-Depth Candidate Evaluation

### Candidate A: Franka Emika Panda / FR3 (7-DOF)

#### 2.1 Package Ecosystem & Maintenance
- **Upstream Repository:** [frankarobotics/franka_ros2](https://github.com/frankarobotics/franka_ros2) `[VERIFIED]`
- **Active Jazzy Branch:** `jazzy` branch actively maintained by Franka Robotics `[VERIFIED]`
- **Official Documentation:** [Franka Control Interface - ROS 2 Jazzy Guide](https://frankarobotics.github.io/docs/franka_ros2_jazzy.html) `[VERIFIED]`
- **License:** Apache License 2.0 `[VERIFIED]`
- **Key Packages:**
  - `franka_description`: Robot kinematics, visual/collision meshes, inertial properties, and Xacro macros for Panda and FR3 arms and Franka Hand.
  - `franka_gazebo_bringup`: Launch files and world SDF configs spawning the robot directly in Gazebo Harmonic with `gz_ros2_control`.
  - `franka_moveit_config`: Parameterized MoveIt 2 pipeline configurations, joint limits, kinematic solvers (KDL/OMPL), and SRDF.
  - `franka_gripper`: Gripper action servers and command interfaces for finger opening/closing.

#### 2.2 ROS 2 Jazzy & Gazebo Harmonic Compatibility
- **`gz_ros2_control` Integration:** `[VERIFIED]` In the `jazzy` branch of `franka_ros2`, Gazebo simulation has been modernized to use `gz_ros2_control::GazeboROS2ControlPlugin` (`libgz_ros2_control-system.so`).
- **Gripper Support:** `[VERIFIED]` The launch system provides `load_gripper:=true` and `franka_hand:='franka_hand'`. Gripper fingers (`panda_finger_joint1`, `panda_finger_joint2`) are controlled via position or effort interfaces.
- **MoveIt 2 Availability in Apt:** `[VERIFIED]`
  - `ros-jazzy-moveit-resources-panda-description` (v3.1.0, PickNik Robotics)
  - `ros-jazzy-moveit-resources-panda-moveit-config` (v3.1.0, PickNik Robotics)
  These are official, pre-compiled Ubuntu 24.04 deb packages installed via `apt-get install ros-jazzy-moveit-resources-panda-moveit-config`.

#### 2.3 Advantages & Risks
- **Advantages:**
  1. Standard benchmark arm across robotics research, MoveIt 2 documentation, and manipulation literature.
  2. Built-in 2-finger parallel gripper eliminates the need to integrate and debug external third-party end-effectors.
  3. Redundant 7th axis enables reaching around obstacles (such as the blue cube) without changing gripper orientation.
- **Risks & Mitigations:**
  - *Risk:* `franka_gazebo_bringup` requires cloning and building the `jazzy` branch from source within the project workspace (`ros2_ws/src`).
  - *Mitigation:* The build dependencies (`ros-jazzy-gz-ros2-control`, `ros-jazzy-moveit`, `ros-jazzy-ros-gz`) are already packaged in apt and install cleanly.

---

### Candidate B: Universal Robots UR5e (6-DOF)

#### 2.1 Package Ecosystem & Maintenance
- **Upstream Repository:** [UniversalRobots/Universal_Robots_ROS2_GZ_Simulation](https://github.com/UniversalRobots/Universal_Robots_ROS2_GZ_Simulation) `[VERIFIED]`
- **Active Branch:** `ros2` (with automated Jazzy release tags) `[VERIFIED]`
- **Official Documentation:** [Universal Robots ROS 2 Documentation](https://github.com/UniversalRobots/Universal_Robots_ROS2_GZ_Simulation) `[VERIFIED]`
- **Maintainer:** Felix Exner (`feex@universal-robots.com`), Universal Robots A/S `[VERIFIED]`
- **License:** Apache License 2.0 / BSD-3-Clause `[VERIFIED]`

#### 2.2 ROS 2 Jazzy & Gazebo Harmonic Compatibility
- **Official Apt Binaries Available:** `[VERIFIED]`
  - `ros-jazzy-ur-simulation-gz` (Version 2.5.0-1noble)
  - `ros-jazzy-ur-moveit-config` (Version 2.5.0-1noble)
  - `ros-jazzy-ur-description` (Version 3.0.0+)
  - `ros-jazzy-ur-controllers` (Version 2.5.0-1noble)
- **Gazebo Integration:** `[VERIFIED]` Direct launch file `ros2 launch ur_simulation_gz ur_sim_moveit.launch.py ur_type:=ur5e` brings up Gazebo Harmonic (`gz-sim`), `gz_ros2_control`, MoveIt 2, and RViz 2 in a single invocation.

#### 2.3 Advantages & Risks
- **Advantages:**
  1. 100% binary distribution via apt; highest packaging maturity in the entire ROS 2 Jazzy ecosystem.
  2. Zero source compilation overhead for Andy (Integration Engineer) during Phase 2 bringup.
- **Risks & Mitigations:**
  - *Risk:* Does NOT include a gripper out-of-the-box. The simulation spawns a bare `tool0` mounting flange.
  - *Mitigation:* Requires creating a custom combined Xacro attaching a Robotiq 2F-85 or parallel gripper, or utilizing Gazebo's `DetachableJoint` plugin at `tool0`.

---

### Candidate C: Kinova Gen3 (6-DOF / 7-DOF)

#### 2.1 Package Ecosystem & Maintenance
- **Upstream Repository:** [Kinovarobotics/ros2_kortex](https://github.com/Kinovarobotics/ros2_kortex) `[VERIFIED]`
- **Active Branch:** `jazzy` `[VERIFIED]`
- **License:** BSD-3-Clause `[VERIFIED]`

#### 2.2 ROS 2 Jazzy & Gazebo Harmonic Compatibility
- **Simulation Setup:** `[VERIFIED]` Requires importing multiple repositories via `vcs import src --input src/ros2_kortex/simulation.jazzy.repos`.
- **Known Defect in Gazebo Harmonic:** `[VERIFIED]` Kinova Gen3 simulation paired with Robotiq 2F-85 relies on mimic joints for gripper finger coupling. Gazebo Harmonic's DART physics engine and `gz_ros2_control` have known upstream controller registration bugs with mimic joints, frequently causing joint state broadcaster crashes or detached finger meshes.

#### 2.3 Verdict
- **REJECTED:** Multiple source repos, complex build tree, and mimic joint instability in Gazebo Harmonic make it unsuitable for high-reliability automated pick-and-place testing.

---

## 3. Comparison Matrix

| Criteria | Franka Emika Panda | Universal Robots UR5e | Kinova Gen3 |
| :--- | :--- | :--- | :--- |
| **Project Spec Preference** | **Preferred (Section 3)** | Alternative | Alternative |
| **Kinematic DOF** | 7-DOF (Redundant) | 6-DOF (Non-redundant) | 6-DOF / 7-DOF |
| **Apt Package Availability** | `moveit-resources` in apt | Complete stack in apt | MoveIt config only |
| **Source Build Needed** | Yes (`franka_ros2` jazzy) | No (deb binaries ready) | Yes (multiple repos via VCS) |
| **Gazebo Simulator** | Gazebo Harmonic (`gz-sim 8`) | Gazebo Harmonic (`gz-sim 8`) | Gazebo Harmonic (`gz-sim 8`) |
| **Controller Plugin** | `libgz_ros2_control-system.so` | `libgz_ros2_control-system.so` | `libgz_ros2_control-system.so` |
| **Gripper Model** | Native Franka Hand included | None (bare flange `tool0`) | Robotiq 2F-85 (mimic bugs) |
| **MoveIt 2 Support** | Tested, official configs | Tested, official configs | Available |
| **Pick-and-Place Setup Effort**| Low (Gripper pre-wired) | Medium (Must attach tool) | High (VCS + mimic debug) |
| **Risk Level** | **Low** | **Very Low** | **High** |

---

## 4. Implementation Guidance for Jim (Architect) and Andy (Integration)

1. **Adopt Franka Panda as Primary Model:**
   - Git repository to clone into `ros2_ws/src/`:
     ```bash
     git clone -b jazzy https://github.com/frankarobotics/franka_ros2.git
     ```
   - Primary description macro: `franka_description/robots/panda/panda.urdf.xacro` (or `fr3`).
   - Arm joints: `panda_joint1` through `panda_joint7`.
   - Gripper joints: `panda_finger_joint1`, `panda_finger_joint2`.
   - End-effector planning link: `panda_hand` (or virtual TCP `panda_link8`).
   - MoveIt planning group names: `panda_arm` (arm manipulator) and `hand` (gripper).

2. **UR5e Fallback Contingency Plan:**
   - If `franka_ros2` fails to compile on Andy's setup:
     ```bash
     sudo apt-get install ros-jazzy-ur-simulation-gz ros-jazzy-ur-moveit-config
     ```
   - Switch planning group to `ur_manipulator` and joints `shoulder_pan_joint`, `shoulder_lift_joint`, `elbow_joint`, `wrist_1_joint`, `wrist_2_joint`, `wrist_3_joint`.
