#!/bin/bash
# Shared simulation lock (hive/sim.lock): only one sim at a time (RAM). usage: sim_lock.sh acquire|release [work-id]
HIVE="${HIVE_ROOT:-$HOME/Documents/Robotic Operation with Prompt Engineering/hive}"
LOCK="$HIVE/sim.lock"
ME="${AGENT_ID:-$USER}"
case "$1" in
  acquire)
    if [ -f "$LOCK" ]; then
      age=$(( $(date +%s) - $(stat -c %Y "$LOCK") ))
      holder="$(cat "$LOCK" 2>/dev/null)"
      if [ "$age" -lt 7200 ] && ! grep -q "\"agent\":\"$ME\"" "$LOCK"; then
        echo "sim.lock is held (age ${age}s): $holder" >&2; exit 1
      fi
    fi
    printf '{"agent":"%s","domain":%s,"time":"%s","work":"%s"}\n' "$ME" "${ROS_DOMAIN_ID:-42}" "$(date -Is)" "${2:-MD-ROS}" > "$LOCK" ;;
  release) grep -q "\"agent\":\"$ME\"" "$LOCK" 2>/dev/null && rm -f "$LOCK" ;;
  *) echo "usage: $0 acquire|release [work]" >&2; exit 2 ;;
esac
