"""WebSocket streams and SEC-006 controls (FastAPI TestClient)."""

import json

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.config import Settings
from app.main import create_app
from app.schemas import PIPELINE_STAGES
from app.tokenizer import ApproximateTokenizer

TOKEN = "w" * 40
AUTH = {"Authorization": f"Bearer {TOKEN}"}
ORIGIN = {"origin": "http://localhost:5173"}


def make_client(**overrides):
    return TestClient(create_app(Settings(api_token=TOKEN, **overrides), providers=[],
                                 tokenizer=ApproximateTokenizer()))


@pytest.fixture
def client():
    with make_client() as c:
        yield c


def login(ws):
    ws.send_text(json.dumps({"type": "auth", "token": TOKEN}))
    assert ws.receive_json() == {"channel": "system", "payload": {"type": "auth_ok"}}


def test_pipeline_events_stream_in_contract_format(client):
    with client.websocket_connect("/ws/pipeline", headers=ORIGIN) as ws:
        login(ws)
        ws.send_text(json.dumps({"type": "subscribe"}))
        assert ws.receive_json()["payload"] == {"type": "subscribed", "task_id": None}
        task_id = client.post("/api/v1/tasks", json={"instruction": "Put the red cube in the storage box"},
                              headers=AUTH).json()["task_id"]
        frames = []
        while not (frames and frames[-1]["channel"] == "task_status"
                   and frames[-1]["payload"]["status"] == "validated_no_executor"):
            frames.append(ws.receive_json())
    events = [f for f in frames if f["channel"] == "pipeline_event"]
    assert all(f["task_id"] == task_id for f in frames)
    assert set(events[0]["payload"]) == {"event_id", "stage", "state", "timestamp", "message", "data"}
    assert [e["payload"]["stage"] for e in events[:14]] == list(PIPELINE_STAGES)
    last = {e["payload"]["stage"]: e["payload"]["state"] for e in events}
    assert all(last[s] != "waiting" for s in PIPELINE_STAGES)  # every stage ends terminal
    tokenization = next(e for e in events if e["payload"]["stage"] == "tokenization"
                        and e["payload"]["state"] != "running" and e["payload"]["state"] != "waiting")
    assert tokenization["payload"]["data"]["tokenization"]["tokens"][0]["token_id"] is None


def test_subscribe_to_one_task_replays_its_past_events(client):
    task_id = client.post("/api/v1/tasks", json={"instruction": "Move the box to the left"},
                          headers=AUTH).json()["task_id"]
    stored = client.get(f"/api/v1/tasks/{task_id}", headers=AUTH).json()["events"]
    with client.websocket_connect("/ws/pipeline") as ws:
        login(ws)
        ws.send_text(json.dumps({"type": "subscribe", "task_id": task_id}))
        replay = [ws.receive_json() for _ in stored]
        assert [f["payload"] for f in replay] == stored
        assert ws.receive_json()["payload"]["type"] == "subscribed"
        ws.send_text(json.dumps({"type": "subscribe", "task_id": "task_nope"}))
        assert ws.receive_json() == {"channel": "error", "payload": {"type": "unknown_task", "task_id": "task_nope"}}


def test_tokenize_and_ping_over_websocket(client):
    with client.websocket_connect("/ws/pipeline") as ws:
        login(ws)
        ws.send_text(json.dumps({"type": "ping"}))
        assert ws.receive_json()["payload"] == {"type": "pong"}
        ws.send_text(json.dumps({"type": "tokenize", "text": "Put the red cube"}))
        frame = ws.receive_json()
        assert frame["channel"] == "tokenization" and frame["payload"]["is_live_model_tokenization"] is False


def test_bad_origin_is_refused_before_accept(client):
    with pytest.raises(WebSocketDisconnect) as err:
        with client.websocket_connect("/ws/pipeline", headers={"origin": "https://evil.com"}):
            pass
    assert err.value.code == 1008


@pytest.mark.parametrize("first", [
    json.dumps({"type": "auth", "token": "wrong"}),
    json.dumps({"type": "subscribe"}),
    "not json",
    json.dumps({"type": "auth", "token": TOKEN, "extra": 1}),
])
def test_unauthenticated_socket_is_closed(client, first):
    with client.websocket_connect("/ws/pipeline") as ws:
        ws.send_text(first)
        with pytest.raises(WebSocketDisconnect) as err:
            ws.receive_json()
    assert err.value.code == 4401


def test_auth_deadline():
    with make_client(ws_auth_seconds=0.05) as c, c.websocket_connect("/ws/pipeline") as ws:
        with pytest.raises(WebSocketDisconnect) as err:
            ws.receive_json()
        assert err.value.code == 1008


def test_idle_connection_is_closed():
    with make_client(ws_idle_seconds=0.05) as c, c.websocket_connect("/ws/pipeline") as ws:
        login(ws)
        with pytest.raises(WebSocketDisconnect) as err:
            ws.receive_json()
        assert err.value.code == 1008


@pytest.mark.parametrize("bad", ['{"type": "launch_missiles"}', '{"type": "subscribe", "task_id": 5, "x": 1}',
                                 "[]", "{", '{"type": "tokenize", "text": ""}'])
def test_malformed_messages_get_an_error_not_a_crash(client, bad):
    with client.websocket_connect("/ws/pipeline") as ws:
        login(ws)
        ws.send_text(bad)
        frame = ws.receive_json()
        assert frame["channel"] == "error" and frame["payload"]["type"] == "invalid_message"
        assert bad not in json.dumps(frame) or bad in ("[]", "{")
        ws.send_text(json.dumps({"type": "ping"}))
        assert ws.receive_json()["payload"] == {"type": "pong"}  # still alive


def test_binary_frames_are_rejected(client):
    with client.websocket_connect("/ws/pipeline") as ws:
        login(ws)
        ws.send_bytes(b"\x00\x01")
        with pytest.raises(WebSocketDisconnect) as err:
            ws.receive_json()
        assert err.value.code == 1003


def test_oversized_frames_are_rejected():
    with make_client(ws_max_frame_bytes=256) as c, c.websocket_connect("/ws/pipeline") as ws:
        login(ws)
        ws.send_text(json.dumps({"type": "tokenize", "text": "a" * 1000}))
        with pytest.raises(WebSocketDisconnect) as err:
            ws.receive_json()
        assert err.value.code == 1009


def test_connection_limit():
    with make_client(ws_max_connections=1) as c, c.websocket_connect("/ws/pipeline") as first:
        login(first)
        with pytest.raises(WebSocketDisconnect) as err:
            with c.websocket_connect("/ws/pipeline") as second:
                second.receive_json()
        assert err.value.code == 1013
    with make_client(ws_max_connections=1) as c:  # slots are released on close
        for _ in range(3):
            with c.websocket_connect("/ws/pipeline") as ws:
                login(ws)


def test_outbound_frames_are_redacted(client, monkeypatch):
    fake = "nvapi-" + "SECRETSECRETSECRET123"  # built at runtime so secret scanners see no literal key
    monkeypatch.setenv("NVIDIA_API_KEY", fake)
    with client.websocket_connect("/ws/pipeline") as ws:
        login(ws)
        ws.send_text(json.dumps({"type": "tokenize", "text": f"Put {fake} here " + TOKEN}))
        raw = ws.receive_text()
    assert "SECRETSECRETSECRET" not in raw and TOKEN not in raw and "[REDACTED]" in raw


def test_telemetry_socket_reports_ros_unavailable(client):
    with client.websocket_connect("/ws/telemetry") as ws:
        login(ws)
        frame = ws.receive_json()
        assert frame["channel"] == "telemetry"
        assert frame["payload"]["available"] is False and frame["payload"]["reason"] == "ros unavailable"


def test_missing_origin_is_refused_when_required():
    with make_client(require_origin=True) as c:
        with pytest.raises(WebSocketDisconnect) as err:
            with c.websocket_connect("/ws/pipeline"):
                pass
        assert err.value.code == 1008
        with c.websocket_connect("/ws/pipeline", headers=ORIGIN) as ws:
            login(ws)
    assert Settings.from_env({"MD_API_TOKEN": TOKEN, "MD_REQUIRE_ORIGIN": "true"}).require_origin is True
