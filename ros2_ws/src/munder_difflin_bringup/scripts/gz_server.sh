#!/bin/bash
# Run `gz sim` in its own process group and take the whole group down on SIGINT/SIGTERM.
# (`gz` is a ruby wrapper that forks the real server; killing only the wrapper left an orphan, defect D1.)
# usage: gz_server.sh <render: auto|software> <gz sim args...>
RENDER="$1"; shift
if [ "$RENDER" = "software" ]; then
  export LIBGL_ALWAYS_SOFTWARE=1 MESA_GL_VERSION_OVERRIDE=3.3 MESA_GLSL_VERSION_OVERRIDE=330
fi
[ "$(ps -o pgid= -p $$ | tr -d ' ')" = "$$" ] || exec setsid "$0" "$RENDER" "$@"   # become group leader
descendants() {  # all descendant PIDs of $1 (the GUI-mode server and GUI run in their own process groups)
  local c; for c in $(pgrep -P "$1" 2>/dev/null); do echo "$c"; descendants "$c"; done
}
cleanup() {
  trap '' TERM INT
  local pids; pids="$( { descendants $$; pgrep -g $$; } 2>/dev/null | grep -vx $$ | sort -u | tr '\n' ' ')"   # collect before signalling: orphans lose their parent
  kill -TERM -- "-$$" $pids 2>/dev/null
  for _ in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20; do
    sleep 0.5; alive=""; for p in $pids; do kill -0 "$p" 2>/dev/null && alive=1; done; [ -z "$alive" ] && break
  done
  kill -KILL -- "-$$" $pids 2>/dev/null
  exit 0
}
trap cleanup TERM INT
gz sim "$@" &
wait $!
cleanup
