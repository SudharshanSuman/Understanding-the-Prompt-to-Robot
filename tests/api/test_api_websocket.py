"""MD-TEST-004: SEC-006 WebSocket controls with a REAL client (websockets package) against live uvicorn."""
import json
import time

import pytest
from websockets.exceptions import ConnectionClosed, InvalidStatus

from tests.api.helpers import (ORIGIN, submit, wait_status, ws_close_code, ws_connect, ws_frames_until, ws_login, ws_recv_json,
                               FINAL_STATUSES)

pytestmark = [pytest.mark.api, pytest.mark.unit, pytest.mark.filterwarnings("ignore::DeprecationWarning")]

GOOD = "Move the red cube to the platform"


def _authed(srv, path="/ws/pipeline", origin=None):
    conn = ws_connect(srv, path, origin=origin)
    assert ws_login(conn, srv.token) == {"channel": "system", "payload": {"type": "auth_ok"}}
    return conn


# --- authentication ---------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("path", ["/ws/pipeline", "/ws/telemetry"])
def test_valid_first_message_auth_opens_the_stream(shared, path):
    conn = _authed(shared, path)
    conn.close()


@pytest.mark.parametrize("first", [
    '{"type":"ping"}', '{"type":"auth","token":"wrong"}', '{"type":"auth"}', '{"type":"auth","token":5}', "not json", "[]", "",
    '{"type":"auth","token":"%TOKEN%","extra":1}',
])
def test_anything_but_a_correct_auth_message_first_closes_4401(shared, first):
    conn = ws_connect(shared)
    conn.send(first.replace("%TOKEN%", shared.token))
    assert ws_close_code(conn) == 4401


def test_no_frames_are_served_before_authentication(shared):
    conn = ws_connect(shared)
    conn.send('{"type":"subscribe"}')
    seen = []
    try:
        while True:
            seen.append(conn.recv(timeout=5))
    except ConnectionClosed as exc:
        assert exc.rcvd.code == 4401
    assert seen == [], seen


def test_token_sent_in_the_url_or_headers_is_not_enough(shared):
    conn = ws_connect(shared, additional_headers={"Authorization": f"Bearer {shared.token}"})
    conn.send('{"type":"ping"}')
    assert ws_close_code(conn) == 4401


def test_auth_deadline_closes_a_silent_connection(make_server):
    srv = make_server()  # default: 5 s to authenticate
    conn = ws_connect(srv)
    start = time.monotonic()
    code = ws_close_code(conn, timeout=12)
    waited = time.monotonic() - start
    assert 4 <= waited <= 8, f"closed after {waited:.1f}s"
    assert code in {1008, 4401}, code


def test_idle_authenticated_connection_is_closed(make_server):
    srv = make_server(MD_TEST_WS_IDLE="1.5")
    conn = _authed(srv)
    start = time.monotonic()
    assert ws_close_code(conn, timeout=8) == 1008
    assert time.monotonic() - start < 6


def test_repeated_failed_ws_logins_are_locked_out_but_the_valid_token_still_works(make_server):
    """API-3 (fixed): same budget as HTTP (20 failures a minute per client); a valid token is never locked out."""
    srv = make_server()
    codes = []
    for _ in range(30):
        conn = ws_connect(srv)
        conn.send(json.dumps({"type": "auth", "token": "wrong"}))
        codes.append(ws_close_code(conn))
    assert codes[:20] == [4401] * 20, codes
    assert set(codes[20:]) == {1008}, codes[20:]          # 'too many failed logins'
    _authed(srv).close()                                    # the right token still gets in
    with srv.client() as c:
        assert c.get("/api/v1/executor").status_code == 200


def test_ws_and_http_failures_share_one_budget(make_server):
    srv = make_server()
    import httpx

    with httpx.Client(base_url=srv.base) as bad:
        for _ in range(20):
            assert bad.get("/api/v1/executor", headers={"Authorization": "Bearer nope"}).status_code == 401
    conn = ws_connect(srv)
    conn.send(json.dumps({"type": "auth", "token": "wrong"}))
    assert ws_close_code(conn) == 1008
    _authed(srv).close()


# --- Origin ---------------------------------------------------------------------------------------------------------------
def test_origin_not_on_the_list_is_refused_at_the_handshake(shared):
    for origin in ("https://evil.example", "null", ORIGIN + ".evil.example", "http://localhost:5174"):
        with pytest.raises(InvalidStatus) as exc:
            ws_connect(shared, origin=origin)
        assert exc.value.response.status_code == 403, origin


def test_listed_origin_and_no_origin_are_accepted(shared):
    _authed(shared, origin=ORIGIN).close()
    _authed(shared, origin=None).close()


# --- frame hygiene --------------------------------------------------------------------------------------------------------
def test_binary_frame_before_and_after_auth_closes_1003(shared):
    conn = ws_connect(shared)
    conn.send(b"\x00\x01\x02")
    assert ws_close_code(conn) == 1003
    conn = _authed(shared)
    conn.send(b"\x00\x01\x02")
    assert ws_close_code(conn) == 1003


@pytest.mark.parametrize("size", [8193, 20_000, 1_000_000])
def test_oversize_text_frame_closes_1009(shared, size):
    conn = _authed(shared)
    payload = json.dumps({"type": "tokenize", "text": "a" * size})
    start = time.monotonic()
    conn.send(payload)
    assert ws_close_code(conn) == 1009
    assert time.monotonic() - start < 3


def test_oversize_frame_before_auth_also_closes_1009(shared):
    conn = ws_connect(shared)
    conn.send("x" * 9000)
    assert ws_close_code(conn) == 1009


def test_frame_at_the_limit_is_accepted(shared):
    conn = _authed(shared)
    pad = 8192 - len(json.dumps({"type": "tokenize", "text": ""}))
    conn.send(json.dumps({"type": "tokenize", "text": "a " * (pad // 2)}))
    frame = ws_recv_json(conn)
    assert frame["channel"] in {"tokenization", "error"}, frame   # a clean answer, not a close
    conn.close()


@pytest.mark.parametrize("message", [
    "not json", "[]", "null", '{"type":"nope"}', '{"type":"subscribe","task_id":5}', '{"type":"ping","extra":1}',
    '{"type":"tokenize"}', '{"type":"tokenize","text":""}', '{"type":"subscribe","task_id":"%s"}' % ("x" * 65), '{"type":"auth","token":"x"}',
])
def test_malformed_client_messages_get_an_error_frame_and_the_socket_stays_up(shared, message):
    conn = _authed(shared)
    conn.send(message)
    frame = ws_recv_json(conn)
    assert frame["channel"] == "error" and frame["payload"]["type"] in {"invalid_message", "input_rejected"}, frame
    assert message[:20] not in json.dumps(frame) or len(message) < 6, "error frames must not echo the input"
    conn.send('{"type":"ping"}')
    assert ws_recv_json(conn) == {"channel": "system", "payload": {"type": "pong"}}
    conn.close()


def test_ping_and_unknown_task_subscription(shared):
    conn = _authed(shared)
    conn.send('{"type":"ping"}')
    assert ws_recv_json(conn)["payload"] == {"type": "pong"}
    conn.send('{"type":"subscribe","task_id":"task_doesnotexist"}')
    frame = ws_recv_json(conn)
    assert frame["channel"] == "error" and frame["payload"]["type"] == "unknown_task"
    conn.close()


# --- connection cap ---------------------------------------------------------------------------------------------------------
def test_eleventh_connection_is_refused_and_a_slot_frees_on_close(make_server):
    srv = make_server()
    conns = [_authed(srv) for _ in range(10)]
    with pytest.raises(InvalidStatus) as exc:
        ws_connect(srv)
    assert exc.value.response.status_code == 403   # refused before the upgrade (close code 1013 server side)
    conns.pop().close()
    time.sleep(0.5)
    _authed(srv).close()
    for c in conns:
        c.close()


def test_unauthenticated_sockets_hold_slots_only_until_the_auth_deadline(make_server):
    srv = make_server(MD_TEST_WS_AUTH="1.5")
    idle = [ws_connect(srv) for _ in range(10)]
    with pytest.raises(InvalidStatus):
        ws_connect(srv)
    time.sleep(2.5)
    _authed(srv).close()
    for c in idle:
        try:
            c.close()
        except Exception:  # noqa: BLE001
            pass


# --- streaming a real task ---------------------------------------------------------------------------------------------------
def test_live_events_arrive_in_order_with_the_contract_shape(shared):
    conn = _authed(shared)
    conn.send('{"type":"subscribe"}')
    assert ws_recv_json(conn)["payload"] == {"type": "subscribed", "task_id": None}
    with shared.client() as c:
        tid = submit(c, GOOD)
    frames = ws_frames_until(conn, lambda f: f["channel"] == "task_status" and f["payload"]["status"] == "validated_no_executor")
    events = [f for f in frames if f["channel"] == "pipeline_event" and f["task_id"] == tid]
    assert events, frames
    for f in events:
        assert set(f["payload"]) == {"event_id", "stage", "state", "timestamp", "message", "data"}
    seqs = [int(f["payload"]["event_id"].split(":")[1]) for f in events]
    assert seqs == list(range(len(seqs))), "events must arrive in order without gaps or duplicates"
    assert [f["payload"]["stage"] for f in events[:14]][0] == "instruction"
    statuses = [f["payload"]["status"] for f in frames if f["channel"] == "task_status"]
    assert statuses[0] in {"accepted", "running"} and statuses[-1] == "validated_no_executor"
    conn.close()


def test_subscribing_late_replays_the_past_events_exactly_once(shared):
    with shared.client() as c:
        tid = submit(c, GOOD)
        done = wait_status(c, tid, FINAL_STATUSES)
    conn = _authed(shared)
    conn.send(json.dumps({"type": "subscribe", "task_id": tid}))
    frames = ws_frames_until(conn, lambda f: f["channel"] == "system" and f["payload"].get("type") == "subscribed")
    ids = [f["payload"]["event_id"] for f in frames if f["channel"] == "pipeline_event"]
    assert ids == [e["event_id"] for e in done["events"]]
    conn.close()


def test_a_subscription_to_one_task_does_not_receive_another_tasks_events(shared):
    with shared.client() as c:
        mine, other = submit(c, GOOD), submit(c, GOOD)
        wait_status(c, mine, FINAL_STATUSES), wait_status(c, other, FINAL_STATUSES)
        conn = _authed(shared)
        conn.send(json.dumps({"type": "subscribe", "task_id": mine}))
        third = submit(c, GOOD)
        wait_status(c, third, FINAL_STATUSES)
    time.sleep(0.3)
    got = []
    try:
        while True:
            got.append(ws_recv_json(conn, timeout=0.5))
    except TimeoutError:
        pass
    assert {f.get("task_id") for f in got if "task_id" in f} <= {mine}, {f.get("task_id") for f in got}
    conn.close()


def test_telemetry_stream_says_ros_unavailable(shared):
    conn = _authed(shared, "/ws/telemetry")
    first = ws_recv_json(conn)
    assert first["channel"] == "telemetry" and first["payload"]["available"] is False
    conn.close()


def test_ws_tokenize_works_and_survives_a_closed_client(shared):
    conn = _authed(shared)
    conn.send('{"type":"tokenize","text":"Move the red cube"}')
    frame = ws_recv_json(conn)
    assert frame["channel"] == "tokenization" and frame["payload"]["raw_text"] == "Move the red cube"
    conn.send('{"type":"subscribe"}')
    conn.close()
    with shared.client() as c:   # publishing to a dead subscriber must not break the server
        assert wait_status(c, submit(c, GOOD), FINAL_STATUSES)["status"] == "validated_no_executor"
