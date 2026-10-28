# Environment Report — Munder Difflin

- **Tasks:** MD-REL-001 (first audit), MD-REL-002 (post-install refresh) · **Author:** Stanley (REL) · **Audit run (UTC):** 2026-10-28T02:40:46Z (raw output in §5)
- **Method:** `scripts/audit_env.sh` — read-only (version/query commands only; no install, no sudo, no writes). Exit code 0, empty stderr.
- **Scope note:** `hive/project-spec.md` (spec §2, §17, §21) does **not** exist on disk, so the checklist follows the task text plus `docs/architecture.md` / `docs/DECISIONS.md` (Franka Panda primary, UR5e fallback, Gazebo Harmonic, MoveIt 2, `ros2_control`, FastAPI, React + Electron).
- Everything marked PRESENT was seen by the script. "Apt candidate" means `apt-cache policy` shows the package can be installed; it is **not** installed.
- **History:** the first audit (2026-10-28T00:17:20Z) was PARTIAL with the whole manipulation stack missing. The human then ran the apt install (option A of the original report). This file now shows the state after that install.

## 1. Verdict

**READY for the simulation + planning stack. Remaining gaps are optional or by decision.**

| Area | Verdict |
|---|---|
| OS / ROS 2 Jazzy / Gazebo Harmonic / `ros_gz` | READY (Ubuntu 24.04.5, Jazzy desktop 0.11.0, `gz sim` 8.15.0, ros_gz 1.0.24) |
| MoveIt 2, `ros2_control`, controllers, `gz_ros2_control` | READY — installed (MoveIt 2.12.4, ros2_control 4.48.1, ros2_controllers 4.42.1, gz_ros2_control 1.2.20). Was the BLOCKER in the first audit |
| Robot description (Panda / UR5e fallback) | READY — `moveit_resources_panda_*` 3.1.0, `ur_description` 3.5.1, `ur_simulation_gz` 2.5.0, `ur_moveit_config`, `ur_controllers` installed |
| Franka's own packages | Source checkout only, not built — `ros2_ws/src/franka_ros2` (tag v3.6.1) and `ros2_ws/src/franka_description` (tag 2.9.0) exist (Andy's work). No apt candidate exists. `colcon build` **not executed** (see RELEASE_CHECKLIST §4a) |
| NVIDIA GPU | **WARNING (accepted)** — RTX 3050 Mobile, no driver (`nouveau` loaded; no `nvidia-smi`, no `nvcc`). Human decided to skip the driver install; local GPU inference is out of scope. Gazebo uses Mesa on the AMD iGPU or software rendering |
| Python backend (FastAPI) | READY — `backend/.venv` (Python 3.12.3): fastapi 0.162.0, uvicorn 0.54.0, websockets 17.2, pydantic 2.14.1, starlette 1.10.0, pytest 9.1.1. Not on the system Python (ADR-005 isolation; the audit checks system Python so it still shows these as missing) |
| Frontend (Node) | READY — Node v20.20.2, npm 10.8.2; `frontend/package-lock.json` and `desktop/package-lock.json` exist |
| Desktop shell | **Electron (decided).** `desktop/` pins `electron` 44.9.3. Tauri / Rust are out of scope; the audit still prints their rows for information only |
| Docker | READY (29.9.2, Compose v5.1.2, user in `docker` group); no `nvidia-container-toolkit` (not needed without a GPU) |
| Resources | **WARNING** — 37 GB free of 225 GB (83% used); 15.3 GB RAM with ~5.7 GB available at audit time (machine under load) |

## 2. Present / missing / version table

Versions are exactly as the script printed them.

| Component | Status | Version / detail |
|---|---|---|
| OS | PRESENT | Ubuntu 24.04.5 LTS, kernel 6.8.0-147-generic, x86_64 |
| CPU / RAM | INFO | Ryzen 7 5800H, 16 threads / 15318 MiB (5656 MiB available at run), swap 2047 MiB |
| Disk | INFO | 37G free of 225G (83% used) |
| GPU hardware | INFO | NVIDIA GA107M RTX 3050 Mobile + AMD Cezanne (Vega) |
| NVIDIA driver / `nvidia-smi`, `nvcc` | MISSING (by decision) | `nouveau` loaded; `ubuntu-drivers` recommends `nvidia-driver-595-open`; not installed (option E skipped) |
| ROS 2 | PRESENT | Jazzy; `ros-jazzy-desktop` 0.11.0, `ros-jazzy-ros-base` 0.11.0 |
| colcon / rosdep | PRESENT | colcon-common-extensions 0.3.0-100 / rosdep 0.27.0 |
| rviz2, xacro, robot_state_publisher, tf2_ros, image_transport, cv_bridge | PRESENT | 14.1.24, 2.1.1, 3.3.4, 0.36.23, 5.1.8, 4.1.0 |
| `joint_state_publisher_gui` | PRESENT | 2.4.3 (was missing) |
| `rmw_cyclonedds_cpp` | MISSING (optional) | apt candidate 2.2.4 |
| `rosbridge_server` | MISSING (optional) | apt candidate 2.7.1; architecture uses FastAPI + WebSocket, not rosbridge. **Needed only if the backend talks to ROS through rosbridge** — Andy to confirm |
| `nav2_bringup` | MISSING (optional) | apt candidate 1.3.13; not in the design |
| Gazebo (`gz sim`) | PRESENT | 8.15.0 (Harmonic) at `/opt/ros/jazzy/opt/gz_tools_vendor/bin/gz` |
| `ros_gz_sim`, `_bridge`, `_interfaces`, `_image`, `ros_gz` | PRESENT | all 1.0.24 |
| `gz_ros2_control` | PRESENT | 1.2.20 (was missing) |
| MoveIt 2 meta `ros-jazzy-moveit` | PRESENT | 2.12.4; `moveit_ros_move_group`, `_planning_interface`, `moveit_planners_ompl`, `moveit_kinematics`, `moveit_ros_visualization`, `moveit_setup_assistant`, `moveit_servo` all 2.12.4 |
| `moveit_visual_tools` | MISSING (optional) | apt candidate 4.2.0 |
| `ros2_control`, `controller_manager`, `hardware_interface`, `ros2controlcli`, `controller_manager_msgs` | PRESENT | 4.48.1 / 4.48.1 / 4.48.1 / 4.48.1 / 4.48.1 |
| `ros2_controllers` and its controllers (`joint_state_broadcaster`, `joint_trajectory_controller`, `position_`, `velocity_`, `effort_`, `gripper_`, `forward_command_`, `diff_drive_`) | PRESENT | 4.42.1 |
| Panda: `moveit_resources_panda_description` / `_moveit_config` | PRESENT | 3.1.0 |
| UR5e fallback: `ur_description`, `ur_simulation_gz`, `ur_moveit_config`, `ur_controllers`, `ur_msgs`, `ur_dashboard_msgs` | PRESENT | `ur_description` 3.5.1, `ur_simulation_gz` 2.5.0 (others installed; versions not printed by the script) |
| `ros-jazzy-ur` meta | MISSING (not needed) | apt candidate 3.9.0 — the individual UR packages are installed |
| Franka (`franka_ros2`, `franka_description`) | SOURCE ONLY | not apt; checkouts in `ros2_ws/src` (3.6.1 / 2.9.0), unbuilt. Not seen by `ros2 pkg list` until built |
| Kinova | MISSING | not in the chosen design |
| Existing ROS workspaces | INFO | `~/apriltag_ws ~/colcon_ws ~/ros2_ws ~/turtlebot3_ws` exist (not inspected or touched) |
| Python (system) | PRESENT | 3.12.3, pip 24.0, venv OK; numpy 1.26.4, scipy 1.11.4, cv2 4.6.0, PyYAML 6.0.1 |
| fastapi, uvicorn, websockets, pydantic | MISSING in system Python | by design — they live in `backend/.venv` (versions above) |
| torch, onnxruntime, `uv` | MISSING | not required |
| Node / npm | PRESENT | v20.20.2 / 10.8.2 |
| pnpm, yarn | MISSING | optional |
| Rust (`rustc`, `cargo`), Tauri CLI, WebKitGTK dev libs | MISSING (by decision) | Electron chosen; none needed |
| Electron | per-project | `desktop/package.json` pins 44.9.3; runtime libs present (`libnss3`, `libxss1`, `libasound2t64`, `libgbm1`, `libgtk-3-0t64`) |
| git, cmake, gcc/g++, make, ninja, curl, ffmpeg | PRESENT | git 2.43.0, cmake 3.28.3, gcc 13.3.0, make 4.3, ninja 1.11.1, curl 8.5.0, ffmpeg 6.1.1 |
| `gh` (GitHub CLI) | MISSING | apt candidate 2.45.0 (option B, not requested yet; needed for PRs) |
| Docker / Compose | PRESENT | 29.9.2 / v5.1.2 |
| `nvidia-container-toolkit`, podman | MISSING | not needed |
| Ports | INFO | 8000 free (backend), 9090 free, 5173/3000/11311/7400 free; **8080 in use** (owner not visible) |

## 3. Risks and notes

1. **Not yet proven to work together.** The audit shows packages installed; it does not run them. No launch, no `colcon build`, no Gazebo run has been executed by REL. Checklist §4a lists the steps and expected evidence.
2. **No display in the audit shell** (`DISPLAY` unset). Gazebo GUI, rviz2 and MoveIt visual tests need a desktop session, or `gz sim -s` / `--headless-rendering` for server-only runs. Not verified here.
3. **GPU**: `nouveau` only; Gazebo rendering falls to Mesa. Accepted by the human; revisit only if rendering is too slow.
4. **Disk is 83% used (37 GB free).** The ROS install consumed space; Docker images and a Franka build add more. Keep an eye on it before any `colcon build` (build and install dirs are git-ignored).
5. **Overlay masking.** Four other ROS workspaces live in `$HOME`. Source this project's overlay in a clean shell (`env -i` or a fresh terminal without `~/ros2_ws` sourced) so they do not shadow it.
6. **Nested git repositories.** `ros2_ws/src/franka_ros2` and `ros2_ws/src/franka_description` each contain their own `.git`. A plain `git add ros2_ws` would record them as embedded repos, not as source. They are **untracked and not committed**. Andy and the Boss need to choose one of: a `.repos` file for `vcs import`, git submodules, or ignoring them and documenting the tags. REL recommends the `.repos` file (pinned tags v3.6.1 / 2.9.0, no nested `.git` committed).
7. **Port 8080** is taken; the backend uses 8000, which is free.

## 4. Install commands still open (for the human; NOT run by REL)

```bash
# Done by the human since the first audit: option A (MoveIt, ros2_control, controllers, gz_ros2_control, Panda + UR packages, joint_state_publisher_gui).

# B. Developer tooling (not requested yet) — needed for `gh pr create`
sudo apt install -y gh

# C. Optional — only if Andy confirms a need
sudo apt install -y ros-jazzy-rosbridge-server ros-jazzy-rmw-cyclonedds-cpp ros-jazzy-moveit-visual-tools

# D (Tauri) and E (NVIDIA driver): skipped by decision.

# F. Backend — already done in backend/.venv; to recreate from the hash-pinned lock (no sudo):
python3 -m venv backend/.venv && backend/.venv/bin/pip install --require-hashes -r backend/requirements-dev.lock
```

Re-run after any install: `env -i HOME="$HOME" PATH=/usr/local/bin:/usr/bin:/bin bash --noprofile --norc scripts/audit_env.sh` and replace §5.

## 5. Raw output of `scripts/audit_env.sh`

Captured with `env -i HOME="$HOME" PATH=/usr/local/bin:/usr/bin:/bin bash --noprofile --norc scripts/audit_env.sh` (exit 0, stderr empty):

```text
Munder Difflin environment audit
Date (UTC): 2026-10-28T02:40:46Z   Host: Zoro   User: sudharshan

== OS / hardware ==
system         OS                                 INFO     Ubuntu 24.04.5 LTS
system         Kernel / arch                      INFO     6.8.0-147-generic / x86_64
system         CPU                                INFO     AMD Ryzen 7 5800H with Radeon Graphics (16 threads)
system         RAM (total / available)            INFO     15318 MiB / 5656 MiB
system         Swap                               INFO     2047 MiB
system         Disk /                             INFO     37G free of 225G (83% used)
system         Disk $HOME                         INFO     37G free of 225G (83% used)
system         Session type (env of caller)       INFO     unknown / DISPLAY=unset / WAYLAND=unset

== GPU / CUDA ==
gpu            PCI device                         INFO     NVIDIA Corporation GA107M [GeForce RTX 3050 Mobile] (rev a1)
gpu            PCI device                         INFO     Advanced Micro Devices, Inc. [AMD/ATI] Cezanne [Radeon Vega Series / Radeon Vega Mobile Series] (rev c5)
gpu            kernel GPU driver loaded           INFO     nouveau 
gpu            apt nvidia driver pkgs             INFO     libnvidia-compute-580:i386 
gpu            ubuntu-drivers recommended         INFO     nvidia-driver-595-open
gpu            nvidia-smi                         MISSING  -
gpu            nvcc (CUDA toolkit)                MISSING  toolkit not installed (driver-only CUDA is fine for inference runtimes)
gpu            Mesa OpenGL renderer               INFO     
gpu            PRIME offload hint                 INFO     prime-select n/a

== ROS 2 ==
ros            /opt/ros distros                   INFO     jazzy 
ros            ros2 CLI                           PRESENT  /opt/ros/jazzy/bin/ros2; ROS_DISTRO=jazzy
ros            Distro is jazzy                    PRESENT  jazzy
ros            ros-jazzy-desktop                  PRESENT  ros-jazzy-desktop 0.11.0-1noble.20261006.040109
ros            ros-jazzy-ros-base                 PRESENT  ros-jazzy-ros-base 0.11.0-1noble.20261006.035407
ros            colcon                             PRESENT  python3-colcon-common-extensions 0.3.0-100 (/usr/bin/colcon)
ros            rosdep                             PRESENT  0.27.0 (/usr/bin/rosdep)
ros            rmw_cyclonedds_cpp                 MISSING  ros-jazzy-rmw-cyclonedds-cpp (apt candidate 2.2.4-1noble.20260911.095700)
ros            rviz2                              PRESENT  deb 14.1.24-1noble.20260915.204213; /opt/ros/jazzy
ros            xacro                              PRESENT  deb 2.1.1-1noble.20260519.011123; /opt/ros/jazzy
ros            robot_state_publisher              PRESENT  deb 3.3.4-1noble.20260915.184559; /opt/ros/jazzy
ros            joint_state_publisher_gui          PRESENT  deb 2.4.3-1noble.20260912.164400; /opt/ros/jazzy
ros            tf2_ros                            PRESENT  deb 0.36.23-1noble.20260915.173839; /opt/ros/jazzy
ros            rosbridge_server                   MISSING  rosbridge_server (not found by ros2 pkg prefix; apt candidate 2.7.1-1noble.20261006.035306)
ros            image_transport                    PRESENT  deb 5.1.8-1noble.20260912.165731; /opt/ros/jazzy
ros            cv_bridge                          PRESENT  deb 4.1.0-1noble.20260911.143610; /opt/ros/jazzy
ros            nav2_bringup (optional)            MISSING  nav2_bringup (not found by ros2 pkg prefix; apt candidate 1.3.13-1noble.20261006.042503)

== Gazebo ==
gazebo         gz CLI                             PRESENT  /opt/ros/jazzy/opt/gz_tools_vendor/bin/gz
gazebo         gz sim version                     INFO     8.15.0
gazebo         ros_gz_sim                         PRESENT  ros-jazzy-ros-gz-sim 1.0.24-1noble.20261006.035056
gazebo         ros_gz_bridge                      PRESENT  ros-jazzy-ros-gz-bridge 1.0.24-1noble.20260920.234644
gazebo         ros_gz_interfaces                  PRESENT  ros-jazzy-ros-gz-interfaces 1.0.24-1noble.20260911.110630
gazebo         ros_gz_image                       PRESENT  ros-jazzy-ros-gz-image 1.0.24-1noble.20260921.023911
gazebo         ros_gz (meta)                      PRESENT  ros-jazzy-ros-gz 1.0.24-1noble.20261006.041805
gazebo         ros_gz_sim (resolvable)            PRESENT  deb 1.0.24-1noble.20261006.035056; /opt/ros/jazzy
gazebo         gz_ros2_control                    PRESENT  ros-jazzy-gz-ros2-control 1.2.20-1noble.20261006.040504
gazebo         gz_ros2_control (resolvable)       PRESENT  deb 1.2.20-1noble.20261006.040504; /opt/ros/jazzy

== MoveIt 2 / ros2_control / controllers ==
moveit         moveit (meta)                      PRESENT  ros-jazzy-moveit 2.12.4-1noble.20260921.025955
moveit         moveit_ros_move_group              PRESENT  deb 2.12.4-1noble.20260915.202214; /opt/ros/jazzy
moveit         moveit_ros_planning_interface      PRESENT  deb 2.12.4-1noble.20260915.203504; /opt/ros/jazzy
moveit         moveit_planners_ompl               PRESENT  deb 2.12.4-1noble.20260915.201618; /opt/ros/jazzy
moveit         moveit_kinematics                  PRESENT  deb 2.12.4-1noble.20260915.201542; /opt/ros/jazzy
moveit         moveit_ros_visualization           PRESENT  deb 2.12.4-1noble.20260915.204804; /opt/ros/jazzy
moveit         moveit_setup_assistant             PRESENT  deb 2.12.4-1noble.20260921.023050; /opt/ros/jazzy
moveit         moveit_servo                       PRESENT  deb 2.12.4-1noble.20261006.040508; /opt/ros/jazzy
moveit         moveit_visual_tools                MISSING  moveit_visual_tools (optional) (not found by ros2 pkg prefix; apt candidate 4.2.0-1noble.20260921.022155)
control        ros2_control                       PRESENT  deb 4.48.1-1noble.20261006.040510; /opt/ros/jazzy
control        controller_manager                 PRESENT  deb 4.48.1-1noble.20261006.035021; /opt/ros/jazzy
control        hardware_interface                 PRESENT  deb 4.48.1-1noble.20260924.184843; /opt/ros/jazzy
control        ros2_controllers                   PRESENT  deb 4.42.1-1noble.20260924.191822; /opt/ros/jazzy
control        joint_state_broadcaster            PRESENT  deb 4.42.1-1noble.20260924.190601; /opt/ros/jazzy
control        joint_trajectory_controller        PRESENT  deb 4.42.1-1noble.20260924.190511; /opt/ros/jazzy
control        position_controllers               PRESENT  deb 4.42.1-1noble.20260924.191112; /opt/ros/jazzy
control        velocity_controllers               PRESENT  deb 4.42.1-1noble.20260924.191108; /opt/ros/jazzy
control        effort_controllers                 PRESENT  deb 4.42.1-1noble.20260924.191111; /opt/ros/jazzy
control        gripper_controllers                PRESENT  deb 4.42.1-1noble.20260924.190425; /opt/ros/jazzy
control        forward_command_controller         PRESENT  deb 4.42.1-1noble.20260924.190606; /opt/ros/jazzy
control        diff_drive_controller              PRESENT  deb 4.42.1-1noble.20260924.190414; /opt/ros/jazzy
control        ros2controlcli                     PRESENT  deb 4.48.1-1noble.20261006.035651; /opt/ros/jazzy
control        controller_manager_msgs            PRESENT  deb 4.48.1-1noble.20260911.100117; /opt/ros/jazzy

== Existing robot packages ==
robots         robot packages in ros2 pkg list    PRESENT  moveit_resources_panda_description moveit_resources_panda_moveit_config ur_controllers ur_dashboard_msgs ur_description ur_moveit_config ur_msgs ur_simulation_gz 
robots         apt ros-jazzy-franka*              MISSING  none installed
robots         apt ros-jazzy-ur-*                 PRESENT  ros-jazzy-ur-controllers ros-jazzy-ur-dashboard-msgs ros-jazzy-ur-description ros-jazzy-ur-moveit-config ros-jazzy-ur-msgs 
robots         apt ros-jazzy-kinova*              MISSING  none installed
robots         apt ros-jazzy-xarm*                MISSING  none installed
robots         apt ros-jazzy-moveit-resources-panda-moveit-config* PRESENT  ros-jazzy-moveit-resources-panda-moveit-config 
robots         apt ros-jazzy-ur (meta)            MISSING  apt candidate 3.9.0-1noble.20261006.044441
robots         apt ros-jazzy-moveit-resources-panda-description PRESENT  3.1.0-1noble.20260225.235702
robots         apt ros-jazzy-ur-simulation-gz     PRESENT  2.5.0-1noble.20261006.043651
robots         apt ros-jazzy-ur-description       PRESENT  3.5.1-1noble.20260920.234208
robots         apt Franka packages                INFO     franka_ros2/franka_description: no apt candidate (source build needed if none)
robots         apt Kinova Gen3 moveit config      INFO     apt candidate 0.2.6-1noble.20261006.043712
robots         colcon workspaces in $HOME         INFO     /home/sudharshan/apriltag_ws /home/sudharshan/colcon_ws /home/sudharshan/ros2_ws /home/sudharshan/turtlebot3_ws 

== Python ==
python         python3                            PRESENT  Python 3.12.3 (/usr/bin/python3)
python         pip                                PRESENT  pip 24.0 from /usr/lib/python3/dist-packages/pip (python 3.12) (/usr/bin/pip3)
python         venv module                        PRESENT  ok
python         uv                                 MISSING  -
python         module numpy                       PRESENT  1.26.4
python         module scipy                       PRESENT  1.11.4
python         module cv2                         PRESENT  4.6.0
python         module yaml                        PRESENT  6.0.1
python         module fastapi                     MISSING  -
python         module uvicorn                     MISSING  -
python         module websockets                  MISSING  -
python         module pydantic                    MISSING  -
python         module torch                       MISSING  -
python         module onnxruntime                 MISSING  -

== Node / desktop shell ==
node           node                               PRESENT  v20.20.2 (/usr/bin/node)
node           npm                                PRESENT  10.8.2 (/usr/bin/npm)
node           pnpm                               MISSING  -
node           yarn                               MISSING  -
shell          rustc                              MISSING  -
shell          cargo                              MISSING  -
shell          tauri-cli (cargo)                  MISSING  -
shell          npm global electron                MISSING  (per-project dependency is normal)
shell          npm global @tauri-apps/cli         MISSING  (per-project dependency is normal)
tauri-deps     libwebkit2gtk-4.1-dev              MISSING  libwebkit2gtk-4.1-dev (apt candidate 2.52.6-0ubuntu0.24.04.1)
tauri-deps     libgtk-3-dev                       PRESENT  libgtk-3-dev 3.24.41-4ubuntu1.3
tauri-deps     librsvg2-dev                       MISSING  librsvg2-dev (apt candidate 2.58.0+dfsg-1ubuntu0.1)
tauri-deps     libayatana-appindicator3-dev       MISSING  libayatana-appindicator3-dev (apt candidate 0.5.93-1build3)
tauri-deps     libssl-dev                         PRESENT  libssl-dev 3.0.13-0ubuntu3.16
tauri-deps     build-essential                    PRESENT  build-essential 12.10ubuntu1
tauri-deps     pkg-config                         PRESENT  pkg-config 1.8.1-2build1
tauri-deps     libsoup-3.0-dev                    MISSING  libsoup-3.0-dev (apt candidate 3.4.4-5ubuntu0.9)
tauri-deps     libjavascriptcoregtk-4.1-dev       MISSING  libjavascriptcoregtk-4.1-dev (apt candidate 2.52.6-0ubuntu0.24.04.1)
electron-deps  libgtk-3-0t64                      PRESENT  libgtk-3-0t64 3.24.41-4ubuntu1.3
electron-deps  libnss3                            PRESENT  libnss3 2:3.98-1ubuntu0.3
electron-deps  libxss1                            PRESENT  libxss1 1:1.2.3-1build3
electron-deps  libasound2t64                      PRESENT  libasound2t64 1.2.11-1ubuntu0.3
electron-deps  libgbm1                            PRESENT  libgbm1 25.2.8-0ubuntu0.24.04.4

== Build tools / VCS / containers ==
tools          git                                PRESENT  git version 2.43.0 (/usr/bin/git)
tools          cmake                              PRESENT  cmake version 3.28.3 (/usr/bin/cmake)
tools          gcc                                PRESENT  gcc (Ubuntu 13.3.0-6ubuntu2~24.04.1) 13.3.0 (/usr/bin/gcc)
tools          g++                                PRESENT  g++ (Ubuntu 13.3.0-6ubuntu2~24.04.1) 13.3.0 (/usr/bin/g++)
tools          make                               PRESENT  GNU Make 4.3 (/usr/bin/make)
tools          ninja                              PRESENT  1.11.1 (/usr/bin/ninja)
tools          curl                               PRESENT  curl 8.5.0 (x86_64-pc-linux-gnu) libcurl/8.5.0 OpenSSL/3.0.13 zlib/1.3 brotli/1.1.0 zstd/1.5.5 libidn2/2.3.7 libpsl/0.21.2 (+libidn2/2.3.7) libssh/0.10.6/openssl/zlib nghttp2/1.59.0 librtmp/2.3 OpenLDAP/2.6.10 (/usr/bin/curl)
tools          gh                                 MISSING  -
tools          ffmpeg                             PRESENT  ffmpeg version 6.1.1-3ubuntu5 Copyright (c) 2000-2023 the FFmpeg developers (/usr/bin/ffmpeg)
container      docker                             PRESENT  Docker version 29.9.2, build a82e528 (/usr/local/bin/docker)
container      docker daemon                      INFO     server 29.9.2, runtimes: io.containerd.runc.v2 runc 
container      user in docker group               INFO     yes
container      docker-compose                     PRESENT  Docker Compose version v5.1.2 (/usr/local/bin/docker)
container      nvidia-container-toolkit           MISSING  -
container      podman                             MISSING  -

== Network / ports (informational) ==
ports          TCP 8000                           INFO     free
ports          TCP 9090                           INFO     free
ports          TCP 11311                          INFO     free
ports          TCP 8080                           INFO     in use (0.0.0.0:*)
ports          TCP 5173                           INFO     free
ports          TCP 3000                           INFO     free
ports          TCP 7400                           INFO     free

Audit finished (read-only; nothing was installed or modified).
```
