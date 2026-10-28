#!/bin/bash
# One-command VISIBLE demo: Gazebo GUI + MoveIt + backend (RosExecutor) + dashboard. Ctrl+C stops everything cleanly.
# usage: scripts/demo.sh [--software] [--rviz] [--no-gui] [--open]
#   --software  force LIBGL_ALWAYS_SOFTWARE rendering (use if the Gazebo window crashes on the GPU path)
#   --rviz      also open RViz     --no-gui  headless sim (no Gazebo window)     --open  open the dashboard in the browser
# Then in the dashboard type e.g. "Pick up the red cube and place it in the storage box".
# One sim at a time (hive/sim.lock). Only processes started here are signalled, never by name pattern.
RENDER=auto; RVIZ=false; HEADLESS=false; OPEN=0
for a in "$@"; do case "$a" in
  --software) RENDER=software;; --rviz) RVIZ=true;; --no-gui) HEADLESS=true;; --open) OPEN=1;;
  *) echo "unknown option $a"; exit 2;; esac; done
HERE="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/.." && pwd)"   # munder_difflin/
WS="$HERE/ros2_ws"; BE="$HERE/backend"; FE="$HERE/frontend"
[ -f "$WS/install/setup.bash" ] || { echo "build first: cd $WS && colcon build --symlink-install"; exit 1; }
set +u; source /opt/ros/jazzy/setup.bash; source "$WS/install/setup.bash"
export ROS_DOMAIN_ID="${ROS_DOMAIN_ID:-42}"
export ROS_LOCALHOST_ONLY=1 ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST   # DDS stays on this machine (SEC-011-D1)
"$(dirname "${BASH_SOURCE[0]}")/setup_pylib.sh"
LOG="$WS/logs"; mkdir -p "$LOG"
SL="$WS/src/munder_difflin_bringup/scripts/sim_lock.sh"
"$SL" acquire MD-ROS-demo || exit 3
PIDS=()
export MD_DEMO_RUN="demo-$$-$RANDOM"   # marks every process this run starts (children inherit it); the final sweep matches on it, never on a name
run_pids() { local d; for d in /proc/[0-9]*; do tr '\0' '\n' < "$d/environ" 2>/dev/null | grep -qx "MD_DEMO_RUN=$MD_DEMO_RUN" && echo "${d#/proc/}"; done; }
stop_all() {
  trap '' INT TERM
  echo; echo "stopping demo ..."
  for ((i=${#PIDS[@]}-1; i>=0; i--)); do kill -INT "-${PIDS[$i]}" 2>/dev/null; done
  for _ in $(seq 1 25); do alive=0; for p in "${PIDS[@]}"; do kill -0 "$p" 2>/dev/null && alive=1; done; [ $alive = 0 ] && break; sleep 1; done
  for p in "${PIDS[@]}"; do kill -TERM "-$p" 2>/dev/null; done; sleep 1
  for p in "${PIDS[@]}"; do kill -KILL "-$p" 2>/dev/null; done
  # gz runs in its own process groups (GUI + server); sweep whatever of this run is still alive
  left="$(run_pids | grep -vx -e $$ | tr '\n' ' ')"
  if [ -n "$left" ]; then kill -TERM $left 2>/dev/null; sleep 3; kill -KILL $left 2>/dev/null; fi
  rm -f "$TOKEN_FILE"; "$SL" release; echo "stopped."
}
TOKEN_DIR="${XDG_RUNTIME_DIR:-$HOME/.cache/munder_difflin}"; mkdir -p -m 700 "$TOKEN_DIR"
TOKEN_FILE="$TOKEN_DIR/munder_difflin_demo.token"
trap stop_all EXIT; trap 'exit 130' INT TERM

# 1. Gazebo GUI + MoveIt
echo "[1/4] Gazebo $([ "$HEADLESS" = true ] && echo headless || echo GUI) + MoveIt  (log: $LOG/demo_launch.log)"
setsid ros2 launch munder_difflin_bringup moveit.launch.py headless:=$HEADLESS rviz:=$RVIZ render:=$RENDER > "$LOG/demo_launch.log" 2>&1 &
PIDS+=($!); LP=$!
for _ in $(seq 1 120); do
  sleep 2
  kill -0 $LP 2>/dev/null || { echo "launch died; see $LOG/demo_launch.log (try --software)"; tail -15 "$LOG/demo_launch.log"; exit 1; }
  grep -q "You can start planning now" "$LOG/demo_launch.log" && ros2 control list_controllers 2>/dev/null | grep -q "panda_hand_controller.*active" && break
done
ros2 control list_controllers 2>/dev/null | grep -q "panda_hand_controller.*active" || { echo "controllers did not become active"; exit 1; }

# Gazebo opens with a far-away default camera: frame the arm and the table (GUI only; best effort)
if [ "$HEADLESS" != true ]; then
  CAM="$(python3 - <<'PY'
import math
C = (1.25, -0.95, 0.85); T = (0.40, -0.05, 0.10)
d = [T[i] - C[i] for i in range(3)]
yaw = math.atan2(d[1], d[0]); pitch = math.atan2(-d[2], math.hypot(d[0], d[1]))
cy, sy, cp, sp = math.cos(yaw / 2), math.sin(yaw / 2), math.cos(pitch / 2), math.sin(pitch / 2)
print(f'pose: {{position: {{x: {C[0]} y: {C[1]} z: {C[2]}}} orientation: {{x: {-sy * sp:.5f} y: {cy * sp:.5f} z: {sy * cp:.5f} w: {cy * cp:.5f}}}}}')
PY
)"
  timeout 15 gz service -s /gui/move_to/pose --reqtype gz.msgs.GUICamera --reptype gz.msgs.Boolean --timeout 3000 --req "$CAM" > /dev/null 2>&1 || echo "(could not frame the Gazebo camera; use the mouse)"
fi

# 2. backend with the RosExecutor (token is generated per run, printed once, kept only in a user-private runtime file)
echo "[2/4] backend"
TOKEN="$("$BE/.venv/bin/python" -c 'import secrets; print(secrets.token_urlsafe(36))')"
umask 077; printf '%s' "$TOKEN" > "$TOKEN_FILE"; umask 022
MD_API_TOKEN="$TOKEN" PYTHONPATH="$BE:$WS/pylib:$PYTHONPATH" setsid "$BE/.venv/bin/python" -m munder_difflin_control.backend_with_ros > "$LOG/demo_backend.log" 2>&1 &
PIDS+=($!); BP=$!
API="http://127.0.0.1:${APP_PORT:-8000}"
ready=0
for _ in $(seq 1 90); do   # the action servers appear a few seconds after the controllers; wait for the executor, not a fixed time
  sleep 2
  kill -0 $BP 2>/dev/null || { echo "backend died; see $LOG/demo_backend.log"; tail -15 "$LOG/demo_backend.log"; exit 1; }
  printf "Authorization: Bearer %s" "$TOKEN" | curl -s -m 3 -H @- "$API/api/v1/executor" | grep -q '"connected":true' && { ready=1; break; }
done
[ $ready = 1 ] || { echo "executor never became ready; see $LOG/demo_backend.log"; exit 1; }

# 3. frontend (built dist via vite preview)
echo "[3/4] dashboard"
( cd "$FE" && { [ -d dist ] || npm run build > "$LOG/demo_frontend_build.log" 2>&1; } )
( cd "$FE" && exec setsid npm run preview > "$LOG/demo_frontend.log" 2>&1 ) &
PIDS+=($!)
for _ in $(seq 1 30); do sleep 1; curl -s -m 2 -o /dev/null http://127.0.0.1:5173/ && break; done

echo "[4/4] ready"
echo "------------------------------------------------------------"
echo " Dashboard : http://127.0.0.1:5173   (backend $API)"
echo " API token : $TOKEN"
echo "   (shown once; paste it into the page. CLI use: scripts/demo_cli.sh \"<instruction>\")"
echo " Try       : Pick up the red cube and place it in the storage box"
echo "             Move the red cube to the storage box without touching the blue cube"
echo " Stop      : Ctrl+C"
echo "------------------------------------------------------------"
[ $OPEN = 1 ] && xdg-open http://127.0.0.1:5173 > /dev/null 2>&1
while kill -0 $LP 2>/dev/null && kill -0 $BP 2>/dev/null; do sleep 2; done
echo "a component exited; see logs in $LOG"
