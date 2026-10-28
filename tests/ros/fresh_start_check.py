"""Fresh-start first-task check (MD-ROS-002, god's request): N times, a new simulation, then the FIRST task only.

Each run: start moveit.launch.py (SimProcess, own domain), wait until controllers and move_group are up, then
run `python -m munder_difflin_control.run_task red_cube storage_box` (one RosExecutor, one pick-and-place).
PASS per run = run_task prints RESULT: PASS. Leaks and shutdown time are recorded. Needs hive/sim.lock held by the caller.

    ROS_DOMAIN_ID=87 python tests/ros/fresh_start_check.py <outdir> [N]
"""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
from tests.ros import rig as R  # noqa: E402

OUT = Path(sys.argv[1])
OUT.mkdir(parents=True, exist_ok=True)
N = int(sys.argv[2]) if len(sys.argv) > 2 else 6
results = []

for i in range(1, N + 1):
    t0 = time.monotonic()
    s = R.SimProcess(REPO / "ros2_ws", launch_file="moveit.launch.py")
    s.start()
    rig = R.Rig()
    rec = {"run": i}
    try:
        ok = rig.wait_for(lambda: (c := rig.list_controllers(2.0)) and c.keys() >= R.CONTROLLERS.keys()
                          and all(st == "active" for _, st in c.values()) and s.alive(), 180, step=2)
        rec["ready"] = bool(ok)
        rec["ready_s"] = round(time.monotonic() - t0, 1)
        time.sleep(15)   # move_group and the executor action servers come up after the controllers
        p = subprocess.run([sys.executable, "-m", "munder_difflin_control.run_task", "red_cube", "storage_box"],
                           env={**s.env, "PYTHONPATH": f"{REPO / 'backend'}:{REPO / 'ros2_ws' / 'pylib'}"},
                           cwd=str(REPO / "backend"), capture_output=True, text=True, timeout=400)
        (OUT / f"run{i}_task.txt").write_text(p.stdout + "\n--stderr--\n" + p.stderr[-3000:])
        rec["rc"] = p.returncode
        rec["result"] = "PASS" if "RESULT: PASS" in p.stdout else "FAIL"
        rec["failure"] = next((ln for ln in p.stdout.splitlines() if ln.startswith("FAILED")), None)
    except Exception as exc:  # noqa: BLE001
        rec["result"] = f"ERROR {type(exc).__name__}: {str(exc)[:200]}"
    finally:
        rig.close()
        rec["shutdown"] = s.shutdown()
    results.append(rec)
    (OUT / "fresh_start.json").write_text(json.dumps(results, indent=2, default=str))
    print(json.dumps(rec, default=str), flush=True)

passes = sum(1 for r in results if r.get("result") == "PASS")
print(f"FRESH_START {passes}/{N} PASS", flush=True)
