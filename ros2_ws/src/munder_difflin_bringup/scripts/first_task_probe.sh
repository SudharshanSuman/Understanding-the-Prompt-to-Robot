#!/bin/bash
# MD-ROS-002: N fresh headless MoveIt+sim starts, ONE real pick-and-place each through RosExecutor (run_task).
# usage: first_task_probe.sh <N> [prime|noprime]    noprime sets MD_NO_PRIME=1 (no reset() before the first task)
source /opt/ros/jazzy/setup.bash
HERE="$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")"
WS="$(cd "$HERE/../../.." && pwd)"; source "$WS/install/setup.bash"
export ROS_DOMAIN_ID="${ROS_DOMAIN_ID:-42}" ROS_LOCALHOST_ONLY=1 ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST
"$WS/../scripts/setup_pylib.sh" 2>/dev/null
N="${1:-8}"; MODE="${2:-noprime}"; BE="$WS/../backend"
[ "$MODE" = noprime ] && export MD_NO_PRIME=1
LOG="$WS/logs"; OUT="$LOG/first_task_probe_$MODE.log"
SL="$HERE/sim_lock.sh"; "$SL" acquire MD-ROS-002 || exit 3
export MD_PROBE_RUN="$$"
sweep() { for d in /proc/[0-9]*; do p="${d#/proc/}"; [ "$p" = "$$" ] && continue
  tr '\0' '\n' < "$d/environ" 2>/dev/null | grep -qx "MD_PROBE_RUN=$$" && kill -KILL "$p" 2>/dev/null; done; }
trap 'sweep; "$SL" release' EXIT
: > "$OUT"; pass=0
for i in $(seq 1 "$N"); do
  setsid ros2 launch munder_difflin_bringup moveit.launch.py headless:=true > "$LOG/first_task_launch_$i.log" 2>&1 &
  LP=$!
  for _ in $(seq 1 60); do sleep 2; o="$(ros2 control list_controllers 2>/dev/null)"
    echo "$o" | grep -q "panda_arm_controller.*active" && echo "$o" | grep -q "joint_state_broadcaster.*active" && break; done
  sleep 8   # move_group up
  PYTHONPATH="$BE:$WS/pylib:$PYTHONPATH" timeout 240 "$BE/.venv/bin/python" -m munder_difflin_control.run_task red_cube storage_box > "$LOG/first_task_run_$i.log" 2>&1
  rc=$?
  last="$(grep -E '^\[' "$LOG/first_task_run_$i.log" | grep -E 'failed|error|verification' | tail -2 | tr '\n' ' ' | cut -c1-260)"
  echo "start $i: rc=$rc $([ $rc = 0 ] && echo PASS || echo FAIL) | $last" | tee -a "$OUT"
  [ "$rc" = 0 ] && pass=$((pass+1))
  kill -INT "-$LP" 2>/dev/null; for _ in $(seq 1 20); do kill -0 "$LP" 2>/dev/null || break; sleep 1; done
  kill -TERM "-$LP" 2>/dev/null; sleep 1; sweep; sleep 2
done
echo "SUMMARY mode=$MODE: $pass/$N first tasks passed" | tee -a "$OUT"
