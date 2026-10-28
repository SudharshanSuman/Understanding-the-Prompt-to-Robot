#!/bin/bash
# Visible demo: Gazebo GUI + MoveIt (+ optional RViz) and one pick-and-place run by the real RosExecutor.
# usage: demo_pick_place.sh [object] [destination] [--rviz] [--software] [--keep]
#   default: red_cube storage_box. --software = LIBGL_ALWAYS_SOFTWARE rendering if the GPU path fails.
#   --keep leaves the sim open afterwards (Ctrl+C to quit). Runs on ROS_DOMAIN_ID=42 (override with env).
OBJ=red_cube; DST=storage_box; RVIZ=false; RENDER=auto; KEEP=0; n=0
for a in "$@"; do case "$a" in
  --rviz) RVIZ=true;; --software) RENDER=software;; --keep) KEEP=1;;
  *) n=$((n+1)); [ $n = 1 ] && OBJ="$a"; [ $n = 2 ] && DST="$a";; esac; done
source /opt/ros/jazzy/setup.bash
SRC="$(readlink -f "${BASH_SOURCE[0]}")"
WS="$(cd "$(dirname "$SRC")/../../.." && pwd)"
[ -f "$WS/install/setup.bash" ] || WS="${MD_ROS2_WS:-$HOME/munder_difflin/ros2_ws}"
source "$WS/install/setup.bash"
BE="$(cd "$WS/../backend" && pwd)"
export ROS_DOMAIN_ID="${ROS_DOMAIN_ID:-42}"
export ROS_LOCALHOST_ONLY=1 ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST   # DDS stays on this machine (SEC-011-D1)
[ -x "$(dirname "${BASH_SOURCE[0]}")/../../../../scripts/setup_pylib.sh" ] && "$(dirname "${BASH_SOURCE[0]}")/../../../../scripts/setup_pylib.sh"
LOG="$WS/logs"; mkdir -p "$LOG"
SL="$WS/src/munder_difflin_bringup/scripts/sim_lock.sh"
"$SL" acquire MD-ROS-demo || exit 3
setsid ros2 launch munder_difflin_bringup moveit.launch.py headless:=false rviz:=$RVIZ render:=$RENDER > "$LOG/demo_launch.log" 2>&1 &
LP=$!
stop() { kill -INT "-$LP" 2>/dev/null; for _ in $(seq 1 20); do kill -0 "$LP" 2>/dev/null || break; sleep 1; done
         kill -TERM "-$LP" 2>/dev/null; sleep 1; kill -KILL "-$LP" 2>/dev/null; "$SL" release; }
trap stop EXIT
echo "starting Gazebo GUI + MoveIt (log: $LOG/demo_launch.log) ..."
for _ in $(seq 1 90); do
  sleep 2
  grep -q "You can start planning now" "$LOG/demo_launch.log" && ros2 control list_controllers 2>/dev/null | grep -q "panda_hand_controller.*active" && break
  kill -0 $LP 2>/dev/null || { echo "launch died:"; tail -20 "$LOG/demo_launch.log"; exit 1; }
done
sleep 3
echo "running: pick $OBJ -> $DST"
PYTHONPATH="$BE:$WS/pylib:$PYTHONPATH" "$BE/.venv/bin/python" -m munder_difflin_control.run_task "$OBJ" "$DST" | tee "$LOG/demo_run.log"
RC=${PIPESTATUS[0]}
if [ $KEEP = 1 ]; then echo "sim left open; Ctrl+C to quit"; while kill -0 $LP 2>/dev/null; do sleep 1; done; fi
exit $RC
