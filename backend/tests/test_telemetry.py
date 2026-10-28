"""MD-DEV-007 part 3: telemetry comes from the executor (RosExecutor on the ROS side), never invented."""

import json
import math

import pytest
from fastapi.testclient import TestClient

import app.main as main_module
from app.config import Settings
from app.executor import SimulatedExecutor
from app.main import create_app
from app.tokenizer import ApproximateTokenizer

TOKEN = "tm-" + "Rz5Wq1Ke8Yb3Nv7Jc0Hx4Ft6Lm2Pd9As"  # random-looking, built at runtime
AUTH = {"Authorization": f"Bearer {TOKEN}"}


class LiveExecutor(SimulatedExecutor):
    name = "fake_live"

    def __init__(self, snapshot):
        super().__init__()
        self.snapshot = snapshot

    def telemetry(self):
        if isinstance(self.snapshot, Exception):
            raise self.snapshot
        return self.snapshot


SNAPSHOT = {"task_id": "task_1", "stage": "execution", "e_stop_latched": False,
            "joints": {"panda_joint1": 0.1, "panda_joint2": math.nan}, "max_arm_joint_velocity": math.inf,
            "objects": {"red_cube": [0.45, 0.15, 0.02]}}


def client_for(executor):
    return TestClient(create_app(Settings(api_token=TOKEN), providers=[], executor=executor,
                                 tokenizer=ApproximateTokenizer()))


def login(ws):
    ws.send_text(json.dumps({"type": "auth", "token": TOKEN}))
    assert ws.receive_json()["payload"] == {"type": "auth_ok"}


def test_rest_telemetry_is_the_executors_snapshot_with_nan_as_null():
    with client_for(LiveExecutor(SNAPSHOT)) as c:
        body = c.get("/api/v1/telemetry", headers=AUTH).json()
    assert body["available"] is True and body["source"] == "fake_live"
    assert body["data"]["joints"] == {"panda_joint1": 0.1, "panda_joint2": None}
    assert body["data"]["max_arm_joint_velocity"] is None
    assert body["data"]["objects"]["red_cube"] == [0.45, 0.15, 0.02]


@pytest.mark.parametrize("snapshot", [None, RuntimeError("ros down"), "not a dict"])
def test_no_or_broken_snapshot_reads_ros_unavailable(snapshot):
    with client_for(LiveExecutor(snapshot)) as c:
        body = c.get("/api/v1/telemetry", headers=AUTH).json()
    assert body["available"] is False and body["reason"] == "ros unavailable" and body["joint_states"] is None


def test_default_executor_has_no_live_telemetry():
    assert SimulatedExecutor().telemetry() is None


def test_ws_telemetry_streams_live_snapshots(monkeypatch):
    monkeypatch.setattr("app.websocket.handlers.TELEMETRY_PERIOD_S", 0.01)
    executor = LiveExecutor(dict(SNAPSHOT, stage="planning"))
    with client_for(executor) as c, c.websocket_connect("/ws/telemetry") as ws:
        login(ws)
        first = ws.receive_json()
        assert first["channel"] == "telemetry" and first["payload"]["data"]["stage"] == "planning"
        executor.snapshot = dict(SNAPSHOT, stage="verification")
        for _ in range(50):  # pushed without the client asking
            frame = ws.receive_json()
            if frame["payload"]["data"]["stage"] == "verification":
                break
        else:
            pytest.fail("telemetry was not streamed")
        assert frame["payload"]["data"]["joints"]["panda_joint2"] is None


def test_ws_telemetry_unavailable_is_sent_once_not_every_tick(monkeypatch):
    monkeypatch.setattr("app.websocket.handlers.TELEMETRY_PERIOD_S", 0.01)
    with client_for(SimulatedExecutor()) as c, c.websocket_connect("/ws/telemetry") as ws:
        login(ws)
        assert ws.receive_json()["payload"]["available"] is False
        ws.send_text(json.dumps({"type": "ping"}))
        assert ws.receive_json()["payload"] == {"type": "pong"}  # no repeated stub frames in between


def test_main_passes_the_executor_and_keeps_the_validated_bind(monkeypatch):
    seen = {}
    monkeypatch.setattr("uvicorn.run", lambda app, **kw: seen.update(app=app, **kw))
    monkeypatch.setenv("MD_API_TOKEN", TOKEN)
    monkeypatch.delenv("MD_BIND_HOST", raising=False)
    executor = LiveExecutor(SNAPSHOT)
    main_module.main(executor)
    assert seen["app"].state.manager.executor is executor
    assert seen["host"] == "127.0.0.1" and seen["port"] == 8000 and seen["server_header"] is False


def test_ws_telemetry_period_matches_the_ros_rate():
    from app.websocket.handlers import TELEMETRY_PERIOD_S
    assert TELEMETRY_PERIOD_S == 0.2  # RosExecutor publishes at 5 Hz; the console draws each frame as received
