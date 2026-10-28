# Environment Report — Munder Difflin

- **Task:** MD-REL-001 · **Author:** Stanley (REL) · **Audit run (UTC):** 2026-10-28T00:17:20Z (see raw output)
- **Method:** `bash --noprofile --norc scripts/audit_env.sh` — read-only (version/query commands only; no install, no sudo, no writes). Exit code 0, empty stderr. Two consecutive runs gave identical results apart from RAM/disk numbers (idempotent).
- **Scope note:** `hive/project-spec.md` (spec §2, §17, §21) does **not exist** on disk, so the checklist follows the task text plus `docs/architecture.md` / `docs/DECISIONS.md` (Franka Panda primary, UR5e fallback, Gazebo Harmonic, MoveIt 2, `ros2_control`, FastAPI, React/Tauri-or-Electron).
- Everything marked PRESENT below was seen by the script. "Apt candidate" means `apt-cache policy` shows the package is available to install; it is **not** installed.

## 1. Verdict

**PARTIAL — simulation base is ready; the manipulation stack is not installed.**

| Area | Verdict |
|---|---|
| OS / ROS 2 Jazzy / Gazebo Harmonic / `ros_gz` | READY (Ubuntu 24.04.5, Jazzy desktop, `gz sim` 8.15.0, ros_gz 1.0.24) |
| MoveIt 2, `ros2_control`, controllers, `gz_ros2_control` | **BLOCKER** — none installed; all have apt candidates for Jazzy (one apt command) |
| Robot description (Panda / UR5e fallback) | **BLOCKER** — none installed; Panda and UR packages have apt candidates. Franka's own `franka_ros2` has **no** apt candidate (not needed if the `moveit_resources_panda` packages are used, per ADR-006) |
| NVIDIA GPU | **WARNING** — RTX 3050 Mobile detected but no NVIDIA driver (kernel uses `nouveau`; `nvidia-smi` and `nvcc` missing). Gazebo can still run on the AMD iGPU/software rendering; GPU AI/vision workloads cannot. Driver install needs a reboot and is the human's call |
| Python backend (FastAPI) | READY base (Python 3.12.3, pip, venv); `fastapi/uvicorn/websockets/pydantic` not installed — install in a venv, no sudo |
| Frontend (Node) | READY (Node v20.20.2, npm 10.8.2) |
| Desktop shell | Electron: ready (npm only). Tauri: **not ready** — no Rust, no WebKitGTK dev libs |
| Docker | READY (29.9.2, Compose v5.1.2, user in `docker` group); no `nvidia-container-toolkit` |
| Resources | **WARNING** — 39 GB free of 225 GB (83% used); 15.3 GB RAM with only ~5.7 GB available at audit time (machine under load) |

## 2. Present / missing / version table

Condensed from the raw output in §5. Versions are exactly as the script printed them.

| Component | Status | Version / detail |
|---|---|---|
| OS | PRESENT | Ubuntu 24.04.5 LTS, kernel 6.8.0-147-generic, x86_64 |
| CPU / RAM | INFO | Ryzen 7 5800H, 16 threads / 15318 MiB (5661 MiB available at run), swap 2047 MiB |
| Disk | INFO | 39G free of 225G (83% used) |
| GPU hardware | INFO | NVIDIA GA107M RTX 3050 Mobile + AMD Cezanne (Vega) |
| NVIDIA driver / `nvidia-smi` | **MISSING** | `nouveau` loaded; only `libnvidia-compute-580:i386` installed; `ubuntu-drivers` recommends `nvidia-driver-595-open` |
| CUDA toolkit (`nvcc`) | **MISSING** | apt candidate `nvidia-cuda-toolkit` 12.0.140 (older than driver-side CUDA; only needed if building CUDA code) |
| ROS 2 | PRESENT | Jazzy; `ros-jazzy-desktop` 0.11.0, `ros-jazzy-ros-base` 0.11.0 |
| colcon / rosdep | PRESENT | colcon-common-extensions 0.3.0-100 / rosdep 0.27.0 |
| rviz2, xacro, robot_state_publisher, tf2_ros, image_transport, cv_bridge | PRESENT | rviz2 14.1.24, xacro 2.1.1, rsp 3.3.4, tf2_ros 0.36.23, image_transport 5.1.8, cv_bridge 4.1.0 |
| `rmw_cyclonedds_cpp` | MISSING | apt candidate 2.2.4 (optional; only if we pick Cyclone DDS) |
| `joint_state_publisher_gui` | MISSING | apt candidate 2.4.3 (dev convenience) |
| `rosbridge_server` | MISSING | apt candidate 2.7.1 (only if the UI talks rosbridge; architecture uses FastAPI + WebSocket) |
| Gazebo (`gz sim`) | PRESENT | 8.15.0 (Harmonic) at `/opt/ros/jazzy/opt/gz_tools_vendor/bin/gz` |
| `ros_gz_sim`, `_bridge`, `_interfaces`, `_image`, `ros_gz` | PRESENT | all 1.0.24 |
| `gz_ros2_control` | **MISSING** | apt candidate 1.2.20 |
| MoveIt 2 (`ros-jazzy-moveit` + `moveit_*` packages, `moveit_servo`, setup assistant) | **MISSING** | apt candidate 2.12.4 |
| `moveit_visual_tools` | MISSING | apt candidate 4.2.0 (optional) |
| `ros2_control`, `controller_manager`, `hardware_interface`, `ros2controlcli` | **MISSING** | apt candidate 4.48.1 |
| `ros2_controllers` (`joint_state_broadcaster`, `joint_trajectory_controller`, `position/velocity/effort_controllers`, `gripper_controllers`, `forward_command_controller`, `diff_drive_controller`) | **MISSING** | apt candidate 4.42.1 |
| Panda: `moveit_resources_panda_description` / `_moveit_config` | **MISSING** | apt candidates 3.1.0 |
| UR5e fallback: `ur_description`, `ur_simulation_gz`, `ros-jazzy-ur` | **MISSING** | apt candidates 3.5.1 / 2.5.0 / 3.9.0 |
| Franka (`franka_ros2`, `franka_description`) | MISSING | **no apt candidate** — would need a source build; not needed for the planned sim path |
| Kinova | MISSING | Gen3 MoveIt configs have apt candidates (0.2.6); not in the chosen design |
| Existing ROS workspaces | INFO | `~/apriltag_ws ~/colcon_ws ~/ros2_ws ~/turtlebot3_ws` exist (not inspected or touched) |
| Python | PRESENT | 3.12.3, pip 24.0, venv OK; numpy 1.26.4, scipy 1.11.4, cv2 4.6.0, PyYAML 6.0.1 |
| fastapi, uvicorn, websockets, pydantic, torch, onnxruntime, `uv` | MISSING | install per project in a venv |
| Node / npm | PRESENT | v20.20.2 / 10.8.2 |
| pnpm, yarn | MISSING | optional |
| Rust (`rustc`, `cargo`), Tauri CLI | **MISSING** | apt has rustc/cargo 1.75.0; Tauri 2 normally needs a newer Rust (not verified here) |
| Tauri build deps | MISSING (5) | `libwebkit2gtk-4.1-dev`, `librsvg2-dev`, `libayatana-appindicator3-dev`, `libsoup-3.0-dev`, `libjavascriptcoregtk-4.1-dev` all have apt candidates. Present: `libgtk-3-dev`, `libssl-dev`, `build-essential`, `pkg-config` |
| Electron | MISSING (global) | normal — it is a per-project npm dependency. Runtime libs present (`libnss3`, `libxss1`, `libasound2t64`, `libgbm1`) |
| git, cmake, gcc/g++, make, ninja, curl, ffmpeg | PRESENT | git 2.43.0, cmake 3.28.3, gcc 13.3.0, make 4.3, ninja 1.11.1, curl 8.5.0, ffmpeg 6.1.1 |
| `gh` (GitHub CLI) | MISSING | apt candidate 2.45.0 (needed for the PR workflow) |
| Docker / Compose | PRESENT | 29.9.2 / v5.1.2, daemon reachable, user in `docker` group |
| `nvidia-container-toolkit`, podman | MISSING | no apt candidate for the toolkit in the current sources; only needed for GPU containers |
| Ports | INFO | 8000 free (backend), 9090 free (rosbridge), 5173/3000/11311/7400 free; **8080 in use** (owner not visible) |

## 3. Risks and notes for Andy / Oscar / Jim

1. **The headless run had no display** (`DISPLAY` unset in the audit shell). Gazebo GUI, rviz2 and MoveIt visual tests need a desktop session — not verified here.
2. **GPU**: with `nouveau` only, Gazebo rendering uses Mesa on whichever GPU the system picks. Installing the NVIDIA driver changes the graphics stack on a hybrid laptop and needs a reboot — recommend the human does this deliberately, not as part of a bulk install.
3. **Disk is 83% used.** MoveIt + ros2_control + Panda/UR packages are expected to be on the order of 1–2 GB (estimate, not measured). Docker images and any simulator add more.
4. **Existing installs untouched.** Several ROS workspaces already live in `$HOME`; installing apt packages system-wide does not modify them, but a later `colcon build` against a different overlay could mask them. Keep this project's workspace separate.
5. **Git root**: `munder_difflin/` sits inside the home-directory git repository. Do not `git add` from here until the project has its own repo.
6. **Port 8080** is taken; the backend design uses 8000, which is free.
7. **Tauri vs Electron** is still open in `architecture.md`. Electron works today with npm only; Tauri needs ~6 apt packages plus a Rust toolchain (the usual rustup installer is a `curl | sh` pattern that Security finding SEC-008 forbids, so it needs a checksum-verified route).

## 4. Install commands needed (for the human to authorise — NOT run by this audit)

```bash
# A. Required for the simulation + planning stack (system, needs sudo)
sudo apt update
sudo apt install -y \
  ros-jazzy-moveit ros-jazzy-ros2-control ros-jazzy-ros2-controllers \
  ros-jazzy-gz-ros2-control \
  ros-jazzy-moveit-resources-panda-description ros-jazzy-moveit-resources-panda-moveit-config \
  ros-jazzy-ur-description ros-jazzy-ur-simulation-gz \
  ros-jazzy-joint-state-publisher-gui

# B. Developer tooling
sudo apt install -y gh

# C. Optional — only if the team chooses these
sudo apt install -y ros-jazzy-rosbridge-server ros-jazzy-rmw-cyclonedds-cpp ros-jazzy-moveit-visual-tools

# D. Only if Tauri (not Electron) is chosen
sudo apt install -y libwebkit2gtk-4.1-dev librsvg2-dev libayatana-appindicator3-dev \
  libsoup-3.0-dev libjavascriptcoregtk-4.1-dev
#    Rust toolchain: apt provides 1.75.0; a newer one needs a checksum-verified download (see SEC-008).

# E. GPU (human decision; reboot required) — driver recommended by ubuntu-drivers
sudo apt install -y nvidia-driver-595-open && sudo reboot
#    (candidate version for this package was not queried; CUDA toolkit not needed unless building CUDA code)

# F. Backend (no sudo, per-project venv; keep it separate from ROS system packages per ADR-005)
python3 -m venv backend/.venv && backend/.venv/bin/pip install fastapi uvicorn websockets pydantic
```

After A, re-run `bash --noprofile --norc scripts/audit_env.sh` and replace §5 with the new output.

## 5. Raw output of `scripts/audit_env.sh`

Captured with `env -i HOME="$HOME" PATH=/usr/local/bin:/usr/bin:/bin XDG_SESSION_TYPE=x11 bash --noprofile --norc scripts/audit_env.sh`:

```text
Munder Difflin environment audit
Date (UTC): 2026-10-28T00:17:20Z   Host: Zoro   User: sudharshan

== OS / hardware ==
system         OS                                 INFO     Ubuntu 24.04.5 LTS
system         Kernel / arch                      INFO     6.8.0-147-generic / x86_64
system         CPU                                INFO     AMD Ryzen 7 5800H with Radeon Graphics (16 threads)
system         RAM (total / available)            INFO     15318 MiB / 5661 MiB
system         Swap                               INFO     2047 MiB
system         Disk /                             INFO     39G free of 225G (83% used)
system         Disk $HOME                         INFO     39G free of 225G (83% used)
system         Session type (env of caller)       INFO     x11 / DISPLAY=unset / WAYLAND=unset

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
ros            joint_state_publisher_gui          MISSING  joint_state_publisher_gui (not found by ros2 pkg prefix; apt candidate 2.4.3-1noble.20260912.164400)
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
gazebo         gz_ros2_control                    MISSING  ros-jazzy-gz-ros2-control (apt candidate 1.2.20-1noble.20261006.040504)
gazebo         gz_ros2_control (resolvable)       MISSING  gz_ros2_control (not found by ros2 pkg prefix; apt candidate 1.2.20-1noble.20261006.040504)

== MoveIt 2 / ros2_control / controllers ==
moveit         moveit (meta)                      MISSING  ros-jazzy-moveit (apt candidate 2.12.4-1noble.20260921.025955)
moveit         moveit_ros_move_group              MISSING  moveit_ros_move_group (not found by ros2 pkg prefix; apt candidate 2.12.4-1noble.20260915.202214)
moveit         moveit_ros_planning_interface      MISSING  moveit_ros_planning_interface (not found by ros2 pkg prefix; apt candidate 2.12.4-1noble.20260915.203504)
moveit         moveit_planners_ompl               MISSING  moveit_planners_ompl (not found by ros2 pkg prefix; apt candidate 2.12.4-1noble.20260915.201618)
moveit         moveit_kinematics                  MISSING  moveit_kinematics (not found by ros2 pkg prefix; apt candidate 2.12.4-1noble.20260915.201542)
moveit         moveit_ros_visualization           MISSING  moveit_ros_visualization (not found by ros2 pkg prefix; apt candidate 2.12.4-1noble.20260915.204804)
moveit         moveit_setup_assistant             MISSING  moveit_setup_assistant (not found by ros2 pkg prefix; apt candidate 2.12.4-1noble.20260921.023050)
moveit         moveit_servo                       MISSING  moveit_servo (not found by ros2 pkg prefix; apt candidate 2.12.4-1noble.20261006.040508)
moveit         moveit_visual_tools                MISSING  moveit_visual_tools (optional) (not found by ros2 pkg prefix; apt candidate 4.2.0-1noble.20260921.022155)
control        ros2_control                       MISSING  ros2_control (not found by ros2 pkg prefix; apt candidate 4.48.1-1noble.20261006.040510)
control        controller_manager                 MISSING  controller_manager (not found by ros2 pkg prefix; apt candidate 4.48.1-1noble.20261006.035021)
control        hardware_interface                 MISSING  hardware_interface (not found by ros2 pkg prefix; apt candidate 4.48.1-1noble.20260924.184843)
control        ros2_controllers                   MISSING  ros2_controllers (not found by ros2 pkg prefix; apt candidate 4.42.1-1noble.20260924.191822)
control        joint_state_broadcaster            MISSING  joint_state_broadcaster (not found by ros2 pkg prefix; apt candidate 4.42.1-1noble.20260924.190601)
control        joint_trajectory_controller        MISSING  joint_trajectory_controller (not found by ros2 pkg prefix; apt candidate 4.42.1-1noble.20260924.190511)
control        position_controllers               MISSING  position_controllers (not found by ros2 pkg prefix; apt candidate 4.42.1-1noble.20260924.191112)
control        velocity_controllers               MISSING  velocity_controllers (not found by ros2 pkg prefix; apt candidate 4.42.1-1noble.20260924.191108)
control        effort_controllers                 MISSING  effort_controllers (not found by ros2 pkg prefix; apt candidate 4.42.1-1noble.20260924.191111)
control        gripper_controllers                MISSING  gripper_controllers (not found by ros2 pkg prefix; apt candidate 4.42.1-1noble.20260924.190425)
control        forward_command_controller         MISSING  forward_command_controller (not found by ros2 pkg prefix; apt candidate 4.42.1-1noble.20260924.190606)
control        diff_drive_controller              MISSING  diff_drive_controller (not found by ros2 pkg prefix; apt candidate 4.42.1-1noble.20260924.190414)
control        ros2controlcli                     MISSING  ros2controlcli (not found by ros2 pkg prefix; apt candidate 4.48.1-1noble.20261006.035651)
control        controller_manager_msgs            MISSING  controller_manager_msgs (not found by ros2 pkg prefix; apt candidate 4.48.1-1noble.20260911.100117)

== Existing robot packages ==
robots         robot packages in ros2 pkg list    MISSING  no franka/ur/kinova/xarm/etc. found
robots         apt ros-jazzy-franka*              MISSING  none installed
robots         apt ros-jazzy-ur-*                 MISSING  none installed
robots         apt ros-jazzy-kinova*              MISSING  none installed
robots         apt ros-jazzy-xarm*                MISSING  none installed
robots         apt ros-jazzy-moveit-resources-panda-moveit-config* MISSING  none installed
robots         apt ros-jazzy-ur (meta)            MISSING  apt candidate 3.9.0-1noble.20261006.044441
robots         apt ros-jazzy-moveit-resources-panda-description MISSING  apt candidate 3.1.0-1noble.20260225.235702
robots         apt ros-jazzy-ur-simulation-gz     MISSING  apt candidate 2.5.0-1noble.20261006.043651
robots         apt ros-jazzy-ur-description       MISSING  apt candidate 3.5.1-1noble.20260920.234208
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
