"""Live check of a running scripts/demo.sh (MD-DEV-008 browser path, API acceptance B, D, E, G, H, /telemetry, /ws/telemetry).

Run AFTER `scripts/demo.sh` prints '[4/4] ready' and while you hold hive/sim.lock. The demo must run with the same
ROS_DOMAIN_ID as this process (87). Independent ground truth: /model/<id>/pose and /joint_states read with rclpy here,
not through the backend. The API token is read from the demo's user-private runtime file and is never printed.

    ROS_DOMAIN_ID=87 python tests/ros/live_demo_check.py <outdir>
"""
import json
import math
import os
import sys
import time
from pathlib import Path

import httpx

REPO = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(REPO), str(REPO / "backend")]

OUT = Path(sys.argv[1])
OUT.mkdir(parents=True, exist_ok=True)
API = os.environ.get("MD_API", "http://127.0.0.1:8000")
TOKEN_FILE = Path(os.environ.get("XDG_RUNTIME_DIR", Path.home() / ".cache" / "munder_difflin")) / "munder_difflin_demo.token"
TOKEN = TOKEN_FILE.read_text().strip()
H = {"Authorization": f"Bearer {TOKEN}"}
STORAGE, PLATFORM = (0.45, -0.40), (0.30, 0.35)
R: dict = {}
FINAL = {"completed", "failed", "cancelled", "needs_clarification", "validated_no_executor"}


def api(method, path, **kw):
    return httpx.request(method, API + path, headers=H, timeout=10, **kw)


def save(name, value):
    R[name] = value
    (OUT / "results.json").write_text(json.dumps(R, indent=2, default=str))


# ---- independent ROS ground truth (rclpy, same domain as the demo) ------------------------------
import rclpy  # noqa: E402
from geometry_msgs.msg import Pose  # noqa: E402
from sensor_msgs.msg import JointState  # noqa: E402

rclpy.init()
node = rclpy.create_node("md_live_check")
poses: dict = {}
joints: dict = {}
IDS = ["red_cube", "blue_cube", "green_cylinder"]
for oid in IDS:
    node.create_subscription(Pose, f"/model/{oid}/pose", lambda m, o=oid: poses.__setitem__(o, (m.position.x, m.position.y, m.position.z)), 10)
node.create_subscription(JointState, "/joint_states", lambda m: joints.update({n: (p, v) for n, p, v in zip(m.name, m.position, list(m.velocity) + [0.0] * len(m.name))}), 50)
import threading  # noqa: E402

spin_stop = False


def _spin():
    while not spin_stop:
        rclpy.spin_once(node, timeout_sec=0.02)


threading.Thread(target=_spin, daemon=True).start()
ARM = [f"panda_joint{i}" for i in range(1, 8)]


def arm_pos():
    return [joints[j][0] for j in ARM] if all(j in joints for j in ARM) else None


def wait_pose_stable(seconds=1.0):
    t0 = time.monotonic()
    while time.monotonic() - t0 < seconds:
        time.sleep(0.05)
    return {k: v for k, v in poses.items()}


def xy_dist(p, q):
    return math.hypot(p[0] - q[0], p[1] - q[1])


# ---- sampler: 10 Hz cube pose + joints during a run --------------------------------------------
samples: list = []
sampling = False


def _sampler():
    while True:
        if sampling:
            samples.append((time.monotonic(), dict(poses), arm_pos()))
        time.sleep(0.1)


threading.Thread(target=_sampler, daemon=True).start()


def run_task(text, cancel_at_stage=None, timeout=240):
    """Submit via the API and follow it; optional cancel once a stage is running. Returns timeline and final status."""
    global sampling
    t_submit = time.monotonic()
    r = api("POST", "/api/v1/tasks", json={"instruction": text})
    if r.status_code != 202:
        return {"submit_status": r.status_code, "body": r.text[:300]}
    tid = r.json()["task_id"]
    timeline, cancelled_at, last = [], None, None
    sampling = True
    try:
        while time.monotonic() - t_submit < timeout:
            d = api("GET", f"/api/v1/tasks/{tid}").json()
            ev = d.get("events", [])
            key = (d.get("status"), len(ev))
            if key != last:
                timeline.append({"t": round(time.monotonic() - t_submit, 2), "status": d.get("status"),
                                 "events": [(e.get("stage"), e.get("state")) for e in ev[-1:]]})
                last = key
            running = [e for e in ev if e.get("state") == "running"]
            if cancel_at_stage and cancelled_at is None and any(e.get("stage") == cancel_at_stage for e in running):
                cancelled_at = time.monotonic()
                api("POST", f"/api/v1/tasks/{tid}/cancel")
            if d.get("status") in FINAL:
                break
            time.sleep(0.2)
        time.sleep(1.5)
    finally:
        sampling = False
    final = api("GET", f"/api/v1/tasks/{tid}").json()
    return {"task_id": tid, "final": final.get("status"), "events": final.get("events", []), "timeline": timeline,
            "cancel_sent_at": cancelled_at and round(cancelled_at - t_submit, 2)}


def stage_seq(events):
    return [(e.get("stage"), e.get("state")) for e in events]


# ---- 1. health, executor, telemetry, websocket ---------------------------------------------------
save("health", api("GET", "/api/v1/health").json())
save("executor", api("GET", "/api/v1/executor").json())
t = api("GET", "/api/v1/telemetry")
save("telemetry_http", {"status": t.status_code, "body": t.json() if t.status_code == 200 else t.text[:200]})

from websockets.sync.client import connect as ws_connect  # noqa: E402

ws_frames = []
try:
    with ws_connect(API.replace("http", "ws") + "/ws/telemetry", open_timeout=10) as ws:
        ws.send(json.dumps({"type": "auth", "token": TOKEN}))
        t0 = time.monotonic()
        while time.monotonic() - t0 < 4.0:
            try:
                msg = json.loads(ws.recv(timeout=1.0))
            except TimeoutError:
                continue
            ws_frames.append((time.monotonic(), msg.get("channel"), (msg.get("payload") or {}).get("type")))
except Exception as exc:  # noqa: BLE001
    ws_frames.append(("error", repr(exc)[:200]))
tel = [t_ for t_, ch, _ in ws_frames if isinstance(t_, float) and ch == "telemetry"]
gaps = [round(b - a, 3) for a, b in zip(tel, tel[1:])]
save("ws_telemetry", {"frames": len(tel), "channels": sorted({str(c) for _, c, *_ in ws_frames}),
                      "mean_interval_s": round(sum(gaps) / len(gaps), 3) if gaps else None,
                      "max_interval_s": max(gaps) if gaps else None, "first_payload": None})

# ---- 2. acceptance B via API: red cube to storage box, independent checks ------------------------
time.sleep(2)
before = wait_pose_stable(1.0)
R["poses_before_B"] = before
b = run_task("Pick up the red cube and place it in the storage box")
after = wait_pose_stable(1.0)
b["poses_after"] = after
b["red_xy_to_storage_m"] = round(xy_dist(after["red_cube"], STORAGE), 4) if "red_cube" in after else None
b["red_z_m"] = round(after["red_cube"][2], 4) if "red_cube" in after else None
b["blue_moved_m"] = round(xy_dist(before["blue_cube"], after["blue_cube"]), 4) if "blue_cube" in before else None
lifts = [p["red_cube"][2] for _, p, _ in samples if "red_cube" in p]
b["red_max_z_during_run_m"] = round(max(lifts), 4) if lifts else None
b["samples"] = len(samples)
v = [i for i, (st, sv) in enumerate(stage_seq(b.get("events", []))) if st == "verification" and sv == "success"]
b["verification_success_before_final"] = bool(v)
b["pass_B"] = (b["final"] == "completed" and b["red_xy_to_storage_m"] is not None and b["red_xy_to_storage_m"] <= 0.09
               and b["blue_moved_m"] is not None and b["blue_moved_m"] < 0.01 and b["verification_success_before_final"])
save("B_red_to_box", b)

# ---- 3. acceptance D and E: refused instructions, no motion --------------------------------------
for key, text in [("D_move_it", "Move it"), ("D_pick_cube_ambiguous", "Pick up the cube"),
                  ("E_unknown_object", "Pick up the purple elephant"), ("E_unknown_destination", "Put the red cube in the spaceship")]:
    p0 = arm_pos()
    res = run_task(text, timeout=60)
    p1 = arm_pos()
    moved = max(abs(a - b_) for a, b_ in zip(p0, p1)) if p0 and p1 else None
    res["max_joint_delta_rad"] = round(moved, 4) if moved is not None else None
    res["no_motion"] = moved is not None and moved < 0.01
    save(key, res)

# ---- 4. acceptance G: cancel mid-motion (blue cube to platform) ----------------------------------
gb0 = wait_pose_stable(0.5)
g = run_task("Pick up the blue cube and place it on the platform", cancel_at_stage="execution", timeout=200)
gb1 = wait_pose_stable(1.0)
g["blue_to_platform_m"] = round(xy_dist(gb1["blue_cube"], PLATFORM), 4) if "blue_cube" in gb1 else None
g["blue_moved_m"] = round(xy_dist(gb0["blue_cube"], gb1["blue_cube"]), 4) if "blue_cube" in gb0 else None
g["cancel_sent"] = g.get("cancel_sent_at") is not None
g["pass_G"] = g["cancel_sent"] and g["final"] == "cancelled" and (g["blue_to_platform_m"] is None or g["blue_to_platform_m"] > 0.05)
save("G_cancel", g)

# ---- 5. acceptance H: kill only the simulator this demo started, then submit -------------------
def demo_gz_pids():
    """gz sim processes whose environment carries this demo's MD_DEMO_RUN marker (set by scripts/demo.sh)."""
    found = {}
    for d in Path("/proc").glob("[0-9]*"):
        try:
            env = (d / "environ").read_bytes().split(b"\0")
            cmd = (d / "cmdline").read_bytes().replace(b"\0", b" ").decode(errors="replace")
        except OSError:
            continue
        marks = [e.decode() for e in env if e.startswith(b"MD_DEMO_RUN=")]
        if marks and "gz sim" in cmd and "--" not in cmd.split("gz sim")[-1][:0]:
            found[int(d.name)] = (marks[0], cmd[:120])
    return found


pids = demo_gz_pids()
save("H_gz_pids_found", {str(k): v[1] for k, v in pids.items()})
if pids:
    for pid in pids:
        os.kill(pid, 15)   # SIGTERM to the one process this demo started
    time.sleep(8)
    ex = api("GET", "/api/v1/executor").json()
    tel_h = api("GET", "/api/v1/telemetry")
    h_run = run_task("Pick up the red cube and place it in the storage box", timeout=40)
    save("H_after_kill", {"executor": ex, "telemetry_status": tel_h.status_code,
                          "telemetry_body": tel_h.json() if tel_h.status_code == 200 else tel_h.text[:200],
                          "submit_result": {k: h_run.get(k) for k in ("final", "submit_status", "body")},
                          "pass_H": (ex.get("connected") is False) and h_run.get("final") != "completed"})
else:
    save("H_after_kill", {"skipped": "no gz sim process carrying this demo's marker was found"})

spin_stop = True
rclpy.shutdown()
print("written", OUT / "results.json")
