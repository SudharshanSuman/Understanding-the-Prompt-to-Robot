#!/bin/bash
# Smoke test: headless sim + MoveIt up, controllers active, one trajectory moves the joints. Exit 0 = PASS.
# usage: smoke_test.sh [--moveit]   (default: sim only, ~40 s; --moveit also starts move_group and runs plan_execute_test.py)
# (no set -u: ROS setup.bash is not nounset-safe)
source /opt/ros/jazzy/setup.bash
WS="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"   # <repo>/ros2_ws when run from src/
[ -f "$WS/install/setup.bash" ] || WS="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/../../.." && pwd)"
source "$WS/install/setup.bash"
export ROS_DOMAIN_ID="${ROS_DOMAIN_ID:-42}"
LOG="${SMOKE_LOG_DIR:-$WS/logs}"; mkdir -p "$LOG"
LAUNCH=sim.launch.py; [ "$1" = "--moveit" ] && LAUNCH=moveit.launch.py
SL="$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/sim_lock.sh"
"$SL" acquire MD-ROS-smoke || exit 3
# own session: an async job in a non-interactive shell ignores SIGINT, and we only ever signal OUR process group
setsid ros2 launch munder_difflin_bringup "$LAUNCH" > "$LOG/smoke_launch.log" 2>&1 &
LP=$!
cleanup() {
  kill -INT "-$LP" 2>/dev/null   # whole group we started; never a name pattern
  for _ in $(seq 1 20); do kill -0 "$LP" 2>/dev/null || break; sleep 1; done
  kill -TERM "-$LP" 2>/dev/null; sleep 1; kill -KILL "-$LP" 2>/dev/null
  "$SL" release
}
trap cleanup EXIT
echo "waiting for controllers (<= 120 s)..."
ok=0
for _ in $(seq 1 60); do
  sleep 2
  out="$(ros2 control list_controllers 2>/dev/null)"
  if echo "$out" | grep -q "joint_state_broadcaster.*active" && echo "$out" | grep -q "panda_arm_controller.*active" \
     && echo "$out" | grep -q "panda_hand_controller.*active"; then ok=1; break; fi
done
[ "$ok" = 1 ] || { echo "FAIL: controllers did not become active"; tail -20 "$LOG/smoke_launch.log"; exit 1; }
echo "$out"
python3 "$WS/src/munder_difflin_bringup/scripts/send_test_trajectory.py" | tee "$LOG/smoke_trajectory.log" || { echo "SMOKE: FAIL (trajectory)"; exit 2; }
if [ "$LAUNCH" = moveit.launch.py ]; then
  sleep 5
  python3 "$WS/src/munder_difflin_bringup/scripts/plan_execute_test.py" | tee "$LOG/smoke_plan.log" || { echo "SMOKE: FAIL (moveit)"; exit 3; }
fi
echo "SMOKE: PASS"
