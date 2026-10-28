"""MD-TEST-004: task lifecycle, clarification, providers, tokenize, e-stop latch (SEC-013), and acceptance G (cancel) and
H (executor disconnected -> no motion) at API level. Live uvicorn + real HTTP; fakes only for the executor and a slow provider."""
import threading
import time

import httpx
import pytest

from tests.api.helpers import FINAL_STATUSES, submit, wait_status

pytestmark = [pytest.mark.api, pytest.mark.unit]

CANON = ["instruction", "tokenization", "interpretation", "structured_task", "schema_validation", "feasibility", "grounding",
         "planning_scene", "ik", "planning", "trajectory_validation", "execution", "simulation", "verification"]
GOOD = "Move the red cube to the platform"


# --- lifecycle --------------------------------------------------------------------------------------------------------
def test_valid_task_runs_headless_and_says_no_executor_connected(shared):
    with shared.client() as c:
        tid = submit(c, GOOD)
        body = wait_status(c, tid, FINAL_STATUSES)
    assert body["status"] == "validated_no_executor", body["status"]
    assert list(body["stages"]) == CANON and body["provider"] == "fallback"
    ok = {"success", "warning"}
    assert all(body["stages"][s] in ok for s in CANON[:6]), body["stages"]
    assert all(body["stages"][s] == "cancelled" for s in CANON[6:]), "ROS stages must not claim to have run"
    assert body["plan"]["object"] == "red_cube" and body["plan"]["destination"] == "platform"
    assert body["report"]["ok"] is True and body["task"]["task_id"] == tid


def test_events_are_ordered_and_ids_are_unique(shared):
    with shared.client() as c:
        body = wait_status(c, submit(c, GOOD), FINAL_STATUSES)
    ids = [e["event_id"] for e in body["events"]]
    assert len(set(ids)) == len(ids) and ids == [f"{body['task_id']}:{i}" for i in range(len(ids))]
    stamps = [e["timestamp"] for e in body["events"]]
    assert stamps == sorted(stamps)
    assert [e["stage"] for e in body["events"][:14]] == CANON and {e["state"] for e in body["events"][:14]} == {"waiting"}


@pytest.mark.parametrize("text,status", [
    ("Do not move the red cube to the platform", "needs_clarification"),
    ("Move the blue box to the right side of the table", "failed"),
    ("Move the red cube to the spaceship", "failed"),
    ("Move the red cube to the platform and then the blue cube to the storage box", "needs_clarification"),
    ("hello", None),
])
def test_unsafe_or_unknown_commands_never_reach_a_runnable_state(shared, text, status):
    with shared.client() as c:
        body = wait_status(c, submit(c, text), FINAL_STATUSES)
    assert body["status"] != "validated_no_executor", body
    if status:
        assert body["status"] == status
    assert body["stages"]["execution"] in {"cancelled", "waiting"}


def test_clarification_flow(shared):
    with shared.client() as c:
        tid = submit(c, "Move the box to the left")
        body = wait_status(c, tid, FINAL_STATUSES)
        assert body["status"] == "needs_clarification" and body["clarification"]["question"]
        assert c.post(f"/api/v1/tasks/{tid}/clarify", json={"selected_option": None}).status_code == 409   # nothing to merge
        assert c.post(f"/api/v1/tasks/{tid}/clarify", json={"selected_option": "no_such_option", "free_text": GOOD}).status_code == 409
        assert c.post(f"/api/v1/tasks/{tid}/clarify", json={"free_text": GOOD, "bogus": 1}).status_code == 422
        r = c.post(f"/api/v1/tasks/{tid}/clarify", json={"free_text": GOOD})
        assert r.status_code == 200 and r.json() == {"status": "resumed", "task_id": tid}
        after = wait_status(c, tid, {"validated_no_executor", "failed", "cancelled"})
        assert after["status"] == "validated_no_executor" and after["plan"]["object"] == "red_cube"
        assert len(after["clarifications"]) == 1
        assert c.post(f"/api/v1/tasks/{tid}/clarify", json={"free_text": GOOD}).status_code == 409   # no longer waiting


def test_unknown_task_ids_are_404_and_do_not_echo_input(shared):
    with shared.client() as c:
        for method, path in (("GET", "/tasks/nope"), ("POST", "/tasks/nope/cancel"), ("POST", "/tasks/nope/clarify")):
            r = c.request(method, "/api/v1" + path, json={"free_text": "x"} if "clarify" in path else None)
            assert r.status_code == 404 and r.json() == {"detail": "task not found"}


def test_history_is_newest_first_and_capped_at_100(shared):
    with shared.client() as c:
        first = submit(c, GOOD)
        for _ in range(104):
            tid = submit(c, GOOD)
        hist = c.get("/api/v1/tasks").json()
        assert len(hist) == 100 and hist[0]["task_id"] == tid
        assert all(h["task_id"] != first for h in hist), "oldest tasks should have been evicted"
        assert c.get(f"/api/v1/tasks/{first}").status_code == 404


def test_instruction_validation_rules(shared):
    with shared.client() as c:
        assert c.post("/api/v1/tasks", json={"instruction": ""}).status_code == 422
        assert c.post("/api/v1/tasks", json={"instruction": "x" * 65537}).status_code == 422
        assert c.post("/api/v1/tasks", json={"instruction": "a " * 3000}).status_code == 202   # accepted, then rejected by the pipeline
        long_id = c.post("/api/v1/tasks", json={"instruction": "a " * 3000}).json()["task_id"]
        body = wait_status(c, long_id, FINAL_STATUSES)
        assert body["status"] == "failed" and body["plan"] is None
        assert c.post("/api/v1/tasks", content=b"\xff\xfe", headers={"content-type": "application/json"}).status_code == 422


def test_providers_endpoints(shared):
    with shared.client() as c:
        listing = c.get("/api/v1/providers").json()
        assert [p["name"] for p in listing][-1] == "fallback"
        assert c.get("/api/v1/providers/active").json()["name"] == "auto"
        assert c.post("/api/v1/providers/select", json={"provider_id": "nope"}).status_code == 404
        assert c.post("/api/v1/providers/select", json={"provider_id": "Bad;Id"}).status_code == 422
        assert c.post("/api/v1/providers/select", json={"provider_id": "fallback"}).json()["name"] == "fallback"
        assert c.post("/api/v1/providers/select", json={"provider_id": "auto"}).json()["name"] == "auto"
        for p in listing:
            assert not p.get("available") or p["name"] == "fallback" or p["configured"]


def test_tokenize_endpoint(shared):
    with shared.client() as c:
        r = c.post("/api/v1/tokenize", json={"text": "Move the red cube"})
        body = r.json()
        assert r.status_code == 200 and body["raw_text"] == "Move the red cube" and body["tokens"]
        assert c.post("/api/v1/tokenize", json={"text": ""}).status_code == 422
        assert c.post("/api/v1/tokenize", json={"text": "w" * 200}).status_code == 422   # word longer than 64 chars


def test_ros_side_endpoints_say_unavailable_and_do_not_invent_data(shared):
    with shared.client() as c:
        for path in ("/environment/objects", "/telemetry", "/ros/inspector"):
            body = c.get("/api/v1" + path).json()
            assert body["available"] is False and body["reason"] == "ros unavailable", path
        assert c.get("/api/v1/environment/objects").json()["objects"] == []
        t = c.get("/api/v1/telemetry").json()
        assert t["joint_states"] is None and t["gripper"] is None and t["end_effector_pose"] is None
        assert c.get("/api/v1/health").json()["ros2"] == "unavailable"


# --- e-stop latch (SEC-013) --------------------------------------------------------------------------------------------
def test_estop_confirms_from_a_readback_latches_blocks_tasks_until_reset(make_server):
    srv = make_server()
    with srv.client() as c:
        r = c.post("/api/v1/simulation/e-stop")
        body = r.json()
        assert r.status_code == 200 and body["status"] == "e_stop_confirmed"
        assert body["max_joint_velocity"] == 0.0 and body["controller_state"] == "STOPPED"
        assert body["tolerance"] == pytest.approx(1e-4) and "simulated" in body["source"] and body["requires_reset"] is True
        assert c.get("/api/v1/executor").json()["e_stop_latched"] is True
        blocked = c.post("/api/v1/tasks", json={"instruction": GOOD})
        assert blocked.status_code == 409 and "latched" in blocked.json()["detail"]
        assert c.post("/api/v1/simulation/e-stop").status_code == 200, "e-stop is idempotent"
        assert c.post("/api/v1/tasks", json={"instruction": GOOD}).status_code == 409
        reset = c.post("/api/v1/simulation/reset")
        assert reset.status_code == 200 and reset.json()["e_stop_latched"] is False
        assert "ros unavailable" in reset.json()["scene_reset"], "must not claim the scene was reset"
        assert c.post("/api/v1/tasks", json={"instruction": GOOD}).status_code == 202


def test_estop_is_not_confirmed_when_the_readback_is_not_zero_and_the_latch_still_holds(make_server):
    srv = make_server(MD_TEST_EXECUTOR="stuck")  # controller that does not stop: joint 2 keeps 0.5 rad/s
    with srv.client() as c:
        r = c.post("/api/v1/simulation/e-stop")
        assert r.status_code == 503, "an unverified stop must not look like success"
        detail = r.json()["detail"]
        assert detail["status"] == "e_stop_unverified" and detail["max_joint_velocity"] == pytest.approx(0.5)
        assert detail["max_joint_velocity"] > detail["tolerance"] and "tolerance" in detail["detail"]
        assert "e_stop_confirmed" not in r.text
        assert c.get("/api/v1/executor").json()["e_stop_latched"] is True, "fail safe: latch even if the stop is unverified"
        assert c.post("/api/v1/tasks", json={"instruction": GOOD}).status_code == 409


def test_estop_cancels_tasks_that_are_still_running(make_server):
    srv = make_server(MD_TEST_PROVIDERS="slow", MD_TEST_SLOW_SECONDS="2")
    with srv.client() as c:
        tid = submit(c, GOOD)
        wait_status(c, tid, {"running"})
        assert c.post("/api/v1/simulation/e-stop").status_code == 200
        body = wait_status(c, tid, FINAL_STATUSES, timeout=10)
    assert body["status"] == "cancelled", body["status"]
    assert body["plan"] is None or body["stages"]["execution"] == "cancelled"


def test_estop_responds_while_the_server_is_busy_with_other_requests(make_server):
    srv = make_server(MD_TEST_PROVIDERS="slow", MD_TEST_SLOW_SECONDS="2")
    with srv.client() as c:
        ids = [submit(c, GOOD) for _ in range(8)]
        t = time.monotonic()
        r = c.post("/api/v1/simulation/e-stop")
        elapsed = time.monotonic() - t
        assert r.status_code == 200 and elapsed < 1.0, f"e-stop took {elapsed:.2f}s with 8 slow tasks running"
        for tid in ids:
            wait_status(c, tid, FINAL_STATUSES, timeout=15)


# --- acceptance G (cancel) at API level --------------------------------------------------------------------------------
def test_G_cancel_a_running_task_stops_it_and_the_final_status_comes_from_the_run(make_server):
    srv = make_server(MD_TEST_PROVIDERS="slow", MD_TEST_SLOW_SECONDS="2")
    with srv.client() as c:
        tid = submit(c, GOOD)
        wait_status(c, tid, {"running"})
        r = c.post(f"/api/v1/tasks/{tid}/cancel")
        assert r.status_code == 200 and r.json() == {"status": "cancelled", "task_id": tid}
        body = wait_status(c, tid, {"cancelled", "validated_no_executor", "failed"}, timeout=10)
        time.sleep(0.3)
        body = c.get(f"/api/v1/tasks/{tid}").json()
    assert body["status"] == "cancelled", "a cancelled task must not end up validated/executable"
    assert body["stages"]["execution"] == "cancelled" and body["stages"]["verification"] == "cancelled"
    assert c_second_cancel_is_conflict(srv, tid)


def c_second_cancel_is_conflict(srv, tid) -> bool:
    with srv.client() as c:
        return c.post(f"/api/v1/tasks/{tid}/cancel").status_code == 409


def test_G_cancelling_finished_unknown_or_waiting_tasks_is_a_clean_error(shared):
    with shared.client() as c:
        tid = submit(c, GOOD)
        wait_status(c, tid, FINAL_STATUSES)
        assert c.post(f"/api/v1/tasks/{tid}/cancel").status_code == 409
        assert c.post("/api/v1/tasks/nope/cancel").status_code == 404
        cl = submit(c, "Move it")
        wait_status(c, cl, {"needs_clarification"})
        assert c.post(f"/api/v1/tasks/{cl}/cancel").status_code == 409


def test_G_cancel_reaches_a_connected_executor_and_it_stops(make_server):
    srv = make_server(MD_TEST_EXECUTOR="toggle", MD_TEST_EXEC_SECONDS="20")
    srv.set_executor("connected")
    with srv.client() as c:
        tid = submit(c, GOOD)
        wait_status(c, tid, {"executing"}, timeout=10)
        assert c.post(f"/api/v1/tasks/{tid}/cancel").status_code == 200
        body = wait_status(c, tid, {"cancelled", "completed", "failed"}, timeout=10)
    assert body["status"] == "cancelled"
    log = srv.exec_log()
    assert f"cancel {tid}" in log and f"cancel-seen {tid}" in log, log


# --- acceptance H (executor disconnected) at API level -----------------------------------------------------------------
def test_H_disconnected_executor_is_reported_and_no_motion_is_started(make_server):
    srv = make_server(MD_TEST_EXECUTOR="toggle")
    srv.set_executor("disconnected")
    with srv.client() as c:
        ex = c.get("/api/v1/executor").json()
        assert ex["connected"] is False and ex["can_execute"] is False
        assert httpx.get(f"{srv.base}/api/v1/health").json()["executor_connected"] is False
        for _ in range(3):
            body = wait_status(c, submit(c, GOOD), FINAL_STATUSES)
            assert body["status"] == "validated_no_executor"
            assert body["stages"]["execution"] == "cancelled"
    assert not [line for line in srv.exec_log() if line.startswith("execute")], "execute() must never be called"


def test_H_executor_that_connects_then_disconnects_blocks_new_motion(make_server):
    srv = make_server(MD_TEST_EXECUTOR="toggle", MD_TEST_EXEC_SECONDS="0.3")
    with srv.client() as c:
        srv.set_executor("connected")
        ok = wait_status(c, submit(c, GOOD), FINAL_STATUSES, timeout=10)
        assert ok["status"] == "completed" and len([x for x in srv.exec_log() if x.startswith("execute")]) == 1
        srv.set_executor("disconnected")
        blocked = wait_status(c, submit(c, GOOD), FINAL_STATUSES)
        assert blocked["status"] == "validated_no_executor"
        assert len([x for x in srv.exec_log() if x.startswith("execute")]) == 1, "no new motion while disconnected"


def test_H_executor_that_drops_mid_run_fails_the_task_with_a_safe_message(make_server):
    srv = make_server(MD_TEST_EXECUTOR="toggle")
    srv.set_executor("drop")
    with srv.client() as c:
        body = wait_status(c, submit(c, GOOD), FINAL_STATUSES, timeout=10)
    assert body["status"] == "failed" and "disconnected" in body["error"]
    assert "Traceback" not in str(body) and "/home" not in str(body)


def test_H_executor_bug_does_not_leave_the_task_executing_forever(make_server):
    """API-2 (fixed): any exception from the executor ends the task as failed, with no traceback."""
    srv = make_server(MD_TEST_EXECUTOR="toggle")
    srv.set_executor("crash")
    with srv.client() as c:
        tid = submit(c, GOOD)
        body = wait_status(c, tid, {"failed", "cancelled", "completed"}, timeout=5)
        assert body["status"] == "failed" and body["error"] == "internal error (RuntimeError)"
        assert "simulated executor bug" not in str(body) and "Traceback" not in str(body), "internal detail leaked"
        assert c.post("/api/v1/simulation/e-stop").status_code == 200, "e-stop must still work after an executor bug"
        assert c.post("/api/v1/simulation/reset").status_code == 200
        srv.set_executor("disconnected")
        assert wait_status(c, submit(c, GOOD), FINAL_STATUSES)["status"] == "validated_no_executor"


def test_H_status_updates_survive_concurrent_submissions(shared):
    results = []

    def go():
        with shared.client() as c:
            results.append(wait_status(c, submit(c, GOOD), FINAL_STATUSES)["status"])

    threads = [threading.Thread(target=go) for _ in range(20)]
    [t.start() for t in threads]
    [t.join(30) for t in threads]
    assert results == ["validated_no_executor"] * 20
