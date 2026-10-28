#!/usr/bin/env bash
# Munder Difflin environment audit. READ-ONLY and idempotent: it only runs
# version/query commands. It never installs, writes outside stdout, or uses sudo.
# Usage: bash --noprofile --norc scripts/audit_env.sh [--tsv]
#   default : human-readable report
#   --tsv   : also print machine-readable lines "ROW<TAB>category<TAB>item<TAB>status<TAB>detail"
# Status values: PRESENT | MISSING | INFO

set -u
ROS_DISTRO_WANTED="${ROS_DISTRO_WANTED:-jazzy}"
TSV=0; [ "${1:-}" = "--tsv" ] && TSV=1

# Pull in ROS only if it is not already on PATH (setup.bash is not nounset-safe).
if ! command -v ros2 >/dev/null 2>&1 && [ -f "/opt/ros/$ROS_DISTRO_WANTED/setup.bash" ]; then
  set +u
  # shellcheck disable=SC1090
  source "/opt/ros/$ROS_DISTRO_WANTED/setup.bash" >/dev/null 2>&1
  set -u
fi

have() { command -v "$1" >/dev/null 2>&1; }
first_line() { head -n1 | tr -d '\r'; }
row() { # category item status detail
  printf '%-14s %-34s %-8s %s\n' "$1" "$2" "$3" "$4"
  [ "$TSV" = 1 ] && printf 'ROW\t%s\t%s\t%s\t%s\n' "$1" "$2" "$3" "$4" >&2
  return 0
}
section() { printf '\n== %s ==\n' "$1"; }
dpkg_ver() { dpkg-query -W -f='${Version}\n' "$1" 2>/dev/null | head -n1; }
apt_cand() { local c; c="$(apt-cache policy "$1" 2>/dev/null | awk '/Candidate:/{print $2}')"; if [ -z "$c" ] || [ "$c" = "(none)" ]; then echo "no apt candidate"; else echo "apt candidate $c"; fi; }
dpkg_has() { dpkg-query -W -f='${Status}' "$1" 2>/dev/null | grep -q 'install ok installed'; }

# check_cmd category item cmd [version-args...]
check_cmd() {
  local cat="$1" item="$2" cmd="$3"; shift 3
  if have "$cmd"; then
    local v; v="$("$cmd" "${@:---version}" 2>&1 | first_line)"
    row "$cat" "$item" PRESENT "$v ($(command -v "$cmd"))"
  else
    row "$cat" "$item" MISSING "-"
  fi
}

# check_deb category item package   (apt package installed?)
check_deb() {
  if dpkg_has "$3"; then row "$1" "$2" PRESENT "$3 $(dpkg_ver "$3")"
  else row "$1" "$2" MISSING "$3 ($(apt_cand "$3"))"; fi
}

# check_rospkg category item ros-package-name  (ROS package resolvable in current env?)
check_rospkg() {
  local p=""
  have ros2 && p="$(ros2 pkg prefix "$3" 2>/dev/null)"
  if [ -n "$p" ]; then
    local v; v="$(dpkg_ver "ros-$ROS_DISTRO_WANTED-$(echo "$3" | tr '_' '-')")"
    row "$1" "$2" PRESENT "${v:+deb $v; }$p"
  else row "$1" "$2" MISSING "$3 (not found by ros2 pkg prefix; $(apt_cand "ros-$ROS_DISTRO_WANTED-$(echo "$3" | sed 's/ .*//' | tr '_' '-')"))"; fi
}

echo "Munder Difflin environment audit"
echo "Date (UTC): $(date -u +%Y-%m-%dT%H:%M:%SZ)   Host: $(hostname)   User: $(id -un)"

section "OS / hardware"
. /etc/os-release 2>/dev/null
row system "OS" INFO "${PRETTY_NAME:-unknown}"
row system "Kernel / arch" INFO "$(uname -r) / $(uname -m)"
row system "CPU" INFO "$(grep -m1 'model name' /proc/cpuinfo | cut -d: -f2- | sed 's/^ //') ($(nproc) threads)"
row system "RAM (total / available)" INFO "$(free -m | awk '/^Mem:/{print $2" MiB / "$7" MiB"}')"
row system "Swap" INFO "$(free -m | awk '/^Swap:/{print $2" MiB"}')"
row system "Disk /" INFO "$(df -hP / | awk 'NR==2{print $4" free of "$2" ("$5" used)"}')"
row system "Disk \$HOME" INFO "$(df -hP "$HOME" | awk 'NR==2{print $4" free of "$2" ("$5" used)"}')"
row system "Session type (env of caller)" INFO "${XDG_SESSION_TYPE:-unknown} / DISPLAY=${DISPLAY:-unset} / WAYLAND=${WAYLAND_DISPLAY:-unset}"

section "GPU / CUDA"
GPUS="$(lspci 2>/dev/null | grep -Ei 'vga|3d|display')"
if [ -n "$GPUS" ]; then
  while IFS= read -r l; do row gpu "PCI device" INFO "${l#*: }"; done <<<"$GPUS"
else row gpu "PCI devices" INFO "lspci unavailable"; fi
row gpu "kernel GPU driver loaded" INFO "$(lsmod | awk '/^(nvidia|nouveau) /{printf "%s ",$1}')"
row gpu "apt nvidia driver pkgs" INFO "$(dpkg -l 2>/dev/null | awk '/^ii/ && $2 ~ /^(nvidia-driver|nvidia-dkms|libnvidia-compute)/{printf "%s ",$2}')"
row gpu "ubuntu-drivers recommended" INFO "$(have ubuntu-drivers && ubuntu-drivers devices 2>/dev/null | awk '/recommended/{print $3}' | head -n1 || echo n/a)"
if have nvidia-smi; then
  row gpu "nvidia-smi" PRESENT "$(nvidia-smi --query-gpu=name,driver_version,memory.total --format=csv,noheader 2>&1 | first_line)"
  row gpu "nvidia-smi CUDA (driver max)" INFO "$(nvidia-smi 2>/dev/null | grep -o 'CUDA Version: [0-9.]*' | first_line)"
else row gpu "nvidia-smi" MISSING "-"; fi
if have nvcc; then row gpu "nvcc (CUDA toolkit)" PRESENT "$(nvcc --version 2>&1 | grep release | first_line)"
elif [ -x /usr/local/cuda/bin/nvcc ]; then row gpu "nvcc (CUDA toolkit)" PRESENT "$(/usr/local/cuda/bin/nvcc --version | grep release) (/usr/local/cuda, not on PATH)"
else row gpu "nvcc (CUDA toolkit)" MISSING "toolkit not installed (driver-only CUDA is fine for inference runtimes)"; fi
row gpu "Mesa OpenGL renderer" INFO "$(have glxinfo && glxinfo -B 2>/dev/null | grep 'OpenGL renderer' | cut -d: -f2- | sed 's/^ //' || echo 'glxinfo not installed')"
row gpu "PRIME offload hint" INFO "$(have prime-select && prime-select query 2>/dev/null || echo 'prime-select n/a')"

section "ROS 2"
if [ -d /opt/ros ]; then row ros "/opt/ros distros" INFO "$(ls /opt/ros | tr '\n' ' ')"; else row ros "/opt/ros" MISSING "-"; fi
if have ros2; then
  row ros "ros2 CLI" PRESENT "$(command -v ros2); ROS_DISTRO=${ROS_DISTRO:-unset}"
  [ "${ROS_DISTRO:-}" = "$ROS_DISTRO_WANTED" ] && row ros "Distro is $ROS_DISTRO_WANTED" PRESENT "$ROS_DISTRO" \
    || row ros "Distro is $ROS_DISTRO_WANTED" MISSING "found '${ROS_DISTRO:-unset}'"
else row ros "ros2 CLI" MISSING "-"; fi
check_deb ros "ros-$ROS_DISTRO_WANTED-desktop" "ros-$ROS_DISTRO_WANTED-desktop"
check_deb ros "ros-$ROS_DISTRO_WANTED-ros-base" "ros-$ROS_DISTRO_WANTED-ros-base"
if have colcon; then row ros colcon PRESENT "python3-colcon-common-extensions $(dpkg_ver python3-colcon-common-extensions) ($(command -v colcon))"; else row ros colcon MISSING "-"; fi
check_cmd ros rosdep rosdep --version
check_deb ros "rmw_cyclonedds_cpp" "ros-$ROS_DISTRO_WANTED-rmw-cyclonedds-cpp"
check_rospkg ros rviz2 rviz2
check_rospkg ros xacro xacro
check_rospkg ros robot_state_publisher robot_state_publisher
check_rospkg ros joint_state_publisher_gui joint_state_publisher_gui
check_rospkg ros tf2_ros tf2_ros
check_rospkg ros rosbridge_server rosbridge_server
check_rospkg ros "image_transport" image_transport
check_rospkg ros "cv_bridge" cv_bridge
check_rospkg ros "nav2_bringup (optional)" nav2_bringup

section "Gazebo"
if have gz; then
  row gazebo "gz CLI" PRESENT "$(command -v gz)"
  row gazebo "gz sim version" INFO "$(gz sim --versions 2>&1 | first_line)"
else row gazebo "gz CLI / gz sim" MISSING "-"; fi
have ign && row gazebo "ign (legacy Fortress CLI)" INFO "$(ign gazebo --versions 2>&1 | first_line)"
for p in gz-sim8 gz-harmonic gz-sim9 gz-ionic; do
  dpkg_has "$p" && row gazebo "apt $p" PRESENT "$(dpkg_ver "$p")"
done
dpkg -l 2>/dev/null | awk '/^ii/ && $2 ~ /^(libgz-sim[0-9]+-dev|gz-[a-z]+$)/{print $2" "$3}' | head -n 5 | while read -r n v; do row gazebo "apt $n" INFO "$v"; done
check_deb gazebo "ros_gz_sim"        "ros-$ROS_DISTRO_WANTED-ros-gz-sim"
check_deb gazebo "ros_gz_bridge"     "ros-$ROS_DISTRO_WANTED-ros-gz-bridge"
check_deb gazebo "ros_gz_interfaces" "ros-$ROS_DISTRO_WANTED-ros-gz-interfaces"
check_deb gazebo "ros_gz_image"      "ros-$ROS_DISTRO_WANTED-ros-gz-image"
check_deb gazebo "ros_gz (meta)"     "ros-$ROS_DISTRO_WANTED-ros-gz"
check_rospkg gazebo "ros_gz_sim (resolvable)" ros_gz_sim
check_deb gazebo "gz_ros2_control"   "ros-$ROS_DISTRO_WANTED-gz-ros2-control"
check_rospkg gazebo "gz_ros2_control (resolvable)" gz_ros2_control

section "MoveIt 2 / ros2_control / controllers"
check_deb moveit "moveit (meta)"      "ros-$ROS_DISTRO_WANTED-moveit"
check_rospkg moveit moveit_ros_move_group moveit_ros_move_group
check_rospkg moveit moveit_ros_planning_interface moveit_ros_planning_interface
check_rospkg moveit moveit_planners_ompl moveit_planners_ompl
check_rospkg moveit moveit_kinematics moveit_kinematics
check_rospkg moveit moveit_ros_visualization moveit_ros_visualization
check_rospkg moveit moveit_setup_assistant moveit_setup_assistant
check_rospkg moveit moveit_servo moveit_servo
check_rospkg moveit moveit_visual_tools "moveit_visual_tools (optional)"
check_rospkg control ros2_control ros2_control
check_rospkg control controller_manager controller_manager
check_rospkg control hardware_interface hardware_interface
check_rospkg control ros2_controllers ros2_controllers
check_rospkg control joint_state_broadcaster joint_state_broadcaster
check_rospkg control joint_trajectory_controller joint_trajectory_controller
check_rospkg control position_controllers position_controllers
check_rospkg control velocity_controllers velocity_controllers
check_rospkg control effort_controllers effort_controllers
check_rospkg control gripper_controllers gripper_controllers
check_rospkg control forward_command_controller forward_command_controller
check_rospkg control diff_drive_controller diff_drive_controller
check_rospkg control ros2controlcli ros2controlcli
check_rospkg control controller_manager_msgs controller_manager_msgs

section "Existing robot packages"
if have ros2; then
  found="$(ros2 pkg list 2>/dev/null | grep -Ei 'franka|^ur_|^ur$|universal_robots|kinova|kortex|panda|xarm|ufactory|fanuc|abb|robotiq|so_arm|so100|lerobot|turtlebot|moveit_resources' | sort | tr '\n' ' ')"
  [ -n "$found" ] && row robots "robot packages in ros2 pkg list" PRESENT "$found" || row robots "robot packages in ros2 pkg list" MISSING "no franka/ur/kinova/xarm/etc. found"
fi
for p in franka ur- kinova xarm moveit-resources-panda-moveit-config; do
  n="$(dpkg -l 2>/dev/null | awk -v p="ros-$ROS_DISTRO_WANTED-$p" '/^ii/ && index($2,p)==1{print $2}' | head -n 5 | tr '\n' ' ')"
  [ -n "$n" ] && row robots "apt ros-$ROS_DISTRO_WANTED-$p*" PRESENT "$n" || row robots "apt ros-$ROS_DISTRO_WANTED-$p*" MISSING "none installed"
done
dpkg_has "ros-$ROS_DISTRO_WANTED-ur" && row robots "apt ros-$ROS_DISTRO_WANTED-ur (meta)" PRESENT "$(dpkg_ver "ros-$ROS_DISTRO_WANTED-ur")" || row robots "apt ros-$ROS_DISTRO_WANTED-ur (meta)" MISSING "$(apt_cand "ros-$ROS_DISTRO_WANTED-ur")"
for p in moveit-resources-panda-description ur-simulation-gz ur-description; do
  dpkg_has "ros-$ROS_DISTRO_WANTED-$p" && row robots "apt ros-$ROS_DISTRO_WANTED-$p" PRESENT "$(dpkg_ver "ros-$ROS_DISTRO_WANTED-$p")" || row robots "apt ros-$ROS_DISTRO_WANTED-$p" MISSING "$(apt_cand "ros-$ROS_DISTRO_WANTED-$p")"
done
row robots "apt Franka packages" INFO "franka_ros2/franka_description: $(apt_cand "ros-$ROS_DISTRO_WANTED-franka-description") (source build needed if none)"
row robots "apt Kinova Gen3 moveit config" INFO "$(apt_cand "ros-$ROS_DISTRO_WANTED-kinova-gen3-7dof-robotiq-2f-85-moveit-config")"

WS="$(ls -d "$HOME"/*_ws 2>/dev/null | sort -u | tr '\n' ' ')"
row robots "colcon workspaces in \$HOME" INFO "${WS:-none found}"

section "Python"
check_cmd python python3 python3 --version
check_cmd python pip pip3 --version
python3 -c 'import venv' 2>/dev/null && row python "venv module" PRESENT "ok" || row python "venv module" MISSING "python3-venv"
check_cmd python uv uv --version
for m in numpy scipy cv2 yaml fastapi uvicorn websockets pydantic torch onnxruntime; do
  v="$(python3 -c "import $m,sys; print(getattr($m,'__version__','ok'))" 2>/dev/null)"
  [ -n "$v" ] && row python "module $m" PRESENT "$v" || row python "module $m" MISSING "-"
done

section "Node / desktop shell"
check_cmd node node node --version
check_cmd node npm npm --version
check_cmd node pnpm pnpm --version
check_cmd node yarn yarn --version
check_cmd shell rustc rustc --version
check_cmd shell cargo cargo --version
if have cargo && cargo tauri --version >/dev/null 2>&1; then row shell "tauri-cli (cargo)" PRESENT "$(cargo tauri --version)"; else row shell "tauri-cli (cargo)" MISSING "-"; fi
NG="$(npm ls -g --depth=0 2>/dev/null)"
for p in electron @tauri-apps/cli; do
  echo "$NG" | grep -q " $p@" && row shell "npm global $p" PRESENT "$(echo "$NG" | grep " $p@" | sed 's/.*@//')" || row shell "npm global $p" MISSING "(per-project dependency is normal)"
done
for p in libwebkit2gtk-4.1-dev libgtk-3-dev librsvg2-dev libayatana-appindicator3-dev libssl-dev build-essential pkg-config libsoup-3.0-dev libjavascriptcoregtk-4.1-dev; do
  check_deb tauri-deps "$p" "$p"
done
for p in libgtk-3-0t64 libnss3 libxss1 libasound2t64 libgbm1; do check_deb electron-deps "$p" "$p"; done

section "Build tools / VCS / containers"
check_cmd tools git git --version
check_cmd tools cmake cmake --version
check_cmd tools gcc gcc --version
check_cmd tools g++ g++ --version
check_cmd tools make make --version
check_cmd tools ninja ninja --version
check_cmd tools curl curl --version
check_cmd tools gh gh --version
check_cmd tools ffmpeg ffmpeg -version
check_cmd container docker docker --version
if have docker; then
  row container "docker daemon" INFO "$(docker info --format 'server {{.ServerVersion}}, runtimes: {{range $k,$v := .Runtimes}}{{$k}} {{end}}' 2>&1 | first_line)"
  row container "user in docker group" INFO "$(id -nG | tr ' ' '\n' | grep -qx docker && echo yes || echo no)"
fi
check_cmd container docker-compose docker compose version
dpkg_has nvidia-container-toolkit && row container "nvidia-container-toolkit" PRESENT "$(dpkg_ver nvidia-container-toolkit)" || row container "nvidia-container-toolkit" MISSING "-"
check_cmd container podman podman --version

section "Network / ports (informational)"
for port in 8000 9090 11311 8080 5173 3000 7400; do
  if ss -ltn 2>/dev/null | awk '{print $4}' | grep -q ":$port\$"; then row ports "TCP $port" INFO "in use ($(ss -ltnp 2>/dev/null | awk -v p=":$port" '$4 ~ p"$"{print $NF}' | head -n1))"; else row ports "TCP $port" INFO "free"; fi
done

echo
echo "Audit finished (read-only; nothing was installed or modified)."
exit 0
