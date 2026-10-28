#!/bin/bash
# MD-ROS-002: N fresh headless sim starts, one fast first move each; prints PASS/FAIL per start.
# usage: first_move_probe.sh <N> [pre: none|reset|wait:<s>] [duration_s]     needs hive/sim.lock (taken here)
source /opt/ros/jazzy/setup.bash
WS="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/../../.." && pwd)"
source "$WS/install/setup.bash"
export ROS_DOMAIN_ID="${ROS_DOMAIN_ID:-42}" ROS_LOCALHOST_ONLY=1 ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST
HERE="$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")"
"$WS/../scripts/setup_pylib.sh" 2>/dev/null
N="${1:-8}"; PRE="${2:-none}"; DUR="${3:-1.6}"
LOG="$WS/logs"; mkdir -p "$LOG"; OUT="$LOG/first_move_probe_${PRE//:/_}.log"
SL="$HERE/sim_lock.sh"; "$SL" acquire MD-ROS-002 || exit 3
export MD_PROBE_RUN="$$"
sweep() { for d in /proc/[0-9]*; do p="${d#/proc/}"; [ "$p" = "$$" ] && continue
  tr '\0' '\n' < "$d/environ" 2>/dev/null | grep -qx "MD_PROBE_RUN=$$" && kill -KILL "$p" 2>/dev/null; done; }
trap 'sweep; "$SL" release' EXIT
: > "$OUT"; pass=0
for i in $(seq 1 "$N"); do
  setsid ros2 launch munder_difflin_bringup sim.launch.py headless:=true > "$LOG/first_move_launch_$i.log" 2>&1 &
  LP=$!
  ok=0
  for _ in $(seq 1 60); do sleep 2; o="$(ros2 control list_controllers 2>/dev/null)"
    echo "$o" | grep -q "panda_arm_controller.*active" && echo "$o" | grep -q "joint_state_broadcaster.*active" && { ok=1; break; }; done
  if [ "$ok" = 1 ]; then r="$(python3 "$HERE/first_move_probe.py" --pre "$PRE" --duration "$DUR" 2>&1 | tail -1)"; else r='{"error":"controllers not active"}'; fi
  echo "start $i: $r" | tee -a "$OUT"
  echo "$r" | grep -q '"PASS": true' && pass=$((pass+1))
  kill -INT "-$LP" 2>/dev/null; for _ in $(seq 1 20); do kill -0 "$LP" 2>/dev/null || break; sleep 1; done
  kill -TERM "-$LP" 2>/dev/null; sleep 1; sweep; sleep 2
done
echo "SUMMARY pre=$PRE dur=$DUR: $pass/$N first moves passed" | tee -a "$OUT"
