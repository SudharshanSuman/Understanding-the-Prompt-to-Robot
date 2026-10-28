#!/bin/bash
# Idempotent. Creates ros2_ws/pylib: links to the system python packages the backend venv needs next to rclpy
# (yaml, numpy, lark). They are links, not copies, and git-ignored, so a fresh clone needs this once.
# Never add /usr/lib/python3/dist-packages to PYTHONPATH instead: its typing_extensions breaks pydantic.
WS="$(cd "$(dirname "${BASH_SOURCE[0]}")/../ros2_ws" && pwd)"
SYS=/usr/lib/python3/dist-packages
mkdir -p "$WS/pylib"
touch "$WS/pylib/COLCON_IGNORE"   # else colcon crawls the linked system packages and chokes on numpy/setup.py
for m in yaml _yaml numpy lark; do
  src="$(ls -d "$SYS/$m" "$SYS/$m".*.so 2>/dev/null | head -1)"
  [ -n "$src" ] || { echo "setup_pylib: $SYS/$m not found (install the Ubuntu package python3-${m#_})" >&2; continue; }
  dst="$WS/pylib/$(basename "$src")"
  [ -L "$dst" ] && [ "$(readlink "$dst")" = "$src" ] || ln -sfn "$src" "$dst"
done
