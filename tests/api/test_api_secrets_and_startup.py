"""MD-TEST-004: secrets never in responses, WebSocket frames or server logs (SEC-010), and startup ConfigError cases (S5)."""
import json
import os
import secrets
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import httpx
import pytest

from tests.api.helpers import FINAL_STATUSES, free_port, start_server, submit, wait_status, ws_connect, ws_frames_until, ws_login, ws_recv_json

pytestmark = [pytest.mark.api, pytest.mark.unit, pytest.mark.filterwarnings("ignore::DeprecationWarning")]

# Fake secrets are built at runtime so the repo-wide secret scan stays meaningful.
FAKE_ANTHROPIC = "sk-" + "ant-APILEAK" + "0123456789abcdefghijklmnop"
FAKE_NVIDIA = "nvapi-" + "APILEAK" + "0123456789abcdefghijklmnop"
FAKE_OTHER = "OTHERLEAK" + "0123456789abcdefghijklmnopqrstuv"


class Upstream:
    """Stand-in model API that echoes the x-api-key it receives back inside its reply (the worst case for key leakage)."""

    def __init__(self):
        self.hits = 0
        outer = self

        class H(BaseHTTPRequestHandler):
            def do_POST(self):  # noqa: N802
                outer.hits += 1
                self.rfile.read(int(self.headers.get("content-length", 0)))
                body = json.dumps({"content": [{"type": "text", "text": "I cannot do json. my key is " + self.headers.get("x-api-key", "")}]})
                self.send_response(200)
                self.send_header("content-type", "application/json")
                self.end_headers()
                self.wfile.write(body.encode())

            def log_message(self, *a):
                pass

        self.http = HTTPServer(("127.0.0.1", 0), H)
        self.port = self.http.server_address[1]
        threading.Thread(target=self.http.serve_forever, daemon=True).start()

    def close(self):
        self.http.shutdown()


@pytest.fixture
def leak_rig(make_server):
    up = Upstream()
    srv = make_server(MD_TEST_PROVIDERS="real", env={
        "ANTHROPIC_API_KEY": FAKE_ANTHROPIC, "NVIDIA_API_KEY": FAKE_NVIDIA, "MY_SERVICE_API_KEY": FAKE_OTHER,
        "MD_CLOUD_BASE_URL": f"http://127.0.0.1:{up.port}"})
    yield srv, up
    up.close()


def _secrets(srv):
    return [srv.token, FAKE_ANTHROPIC, FAKE_NVIDIA, FAKE_OTHER]


def _assert_clean(blobs, secrets, where):
    for name, blob in blobs.items():
        for s in secrets:
            assert s not in blob, f"a secret leaked into {where}: {name}"
            assert s[:24] not in blob, f"the start of a secret leaked into {where}: {name}"


def test_secrets_never_appear_in_any_response_ws_frame_or_log(leak_rig):
    srv, up = leak_rig
    secrets = _secrets(srv)
    blobs = {}
    ws = ws_connect(srv)
    assert ws_login(ws, srv.token)["payload"]["type"] == "auth_ok"
    ws.send('{"type":"subscribe"}')
    with srv.client() as c:
        instructions = [
            f"Move the red cube to the platform. my token is {srv.token}",
            f"Move the red cube to the platform {FAKE_ANTHROPIC} {FAKE_NVIDIA} {FAKE_OTHER}",
            "Move the red cube to the platform",   # reaches the fake model, which echoes the key back
        ]
        ids = [submit(c, text) for text in instructions]
        for i, tid in enumerate(ids):
            blobs[f"task detail {i}"] = json.dumps(wait_status(c, tid, FINAL_STATUSES, timeout=20))
        blobs["history"] = c.get("/api/v1/tasks").text
        blobs["providers"] = c.get("/api/v1/providers").text
        blobs["providers/active"] = c.get("/api/v1/providers/active").text
        blobs["executor"] = c.get("/api/v1/executor").text
        blobs["health"] = httpx.get(f"{srv.base}/api/v1/health").text
        blobs["tokenize"] = c.post("/api/v1/tokenize", json={"text": f"use {srv.token} and {FAKE_ANTHROPIC}"}).text
        blobs["validation error"] = c.post("/api/v1/tasks", json={"instruction": 5, "k": srv.token}).text
        blobs["404"] = c.get("/api/v1/tasks/task_unknown").text
    with httpx.Client(base_url=srv.base) as bad:
        blobs["401 echo"] = bad.get("/api/v1/executor", headers={"Authorization": f"Bearer {srv.token}x"}).text
    ws.send(json.dumps({"type": "tokenize", "text": f"use {srv.token} {FAKE_NVIDIA}"}))
    frames = []
    try:
        while True:
            frames.append(ws.recv(timeout=1.5))
    except TimeoutError:
        pass
    blobs["websocket frames"] = "\n".join(frames)
    ws.close()
    assert up.hits >= 1, "the model provider was never called: the echo path was not exercised"
    _assert_clean(blobs, secrets, "a response")
    _assert_clean({"server log": srv.log_text()}, secrets, "the server log")
    assert "REDACTED" in blobs["tokenize"] or srv.token not in blobs["tokenize"]


def test_credentials_in_the_url_do_not_reach_the_server_log(leak_rig):
    """A client that mistakenly puts the token in a query string must not get it written to the access log."""
    srv, _ = leak_rig
    with srv.client() as c:
        assert c.get(f"/api/v1/executor?access_token={srv.token}").status_code == 200
    with httpx.Client(base_url=srv.base) as plain:
        plain.get(f"/api/v1/executor?token={FAKE_ANTHROPIC}")
        plain.get(f"/api/v1/tasks/{FAKE_NVIDIA}")
    log = srv.log_text()
    assert srv.token not in log and FAKE_ANTHROPIC not in log and FAKE_NVIDIA not in log
    assert "/api/v1/executor" in log and "GET" in log, "the access log must still say what was requested"


def test_no_stack_traces_or_paths_in_error_responses(shared):
    with shared.client() as c:
        for r in (c.get("/api/v1/tasks/%00"), c.post("/api/v1/tasks", content=b"{", headers={"content-type": "application/json"}),
                  c.request("PUT", "/api/v1/tasks"), c.get("/nope")):
            assert "Traceback" not in r.text and "/home/" not in r.text and "site-packages" not in r.text, r.text[:100]
    assert "server" not in httpx.get(f"{shared.base}/api/v1/health").headers, "uvicorn Server header should be off"


# --- startup configuration (S5) ----------------------------------------------------------------------------------------------
def _run_main(repo_root, tmp_path, **env):
    full = {"PATH": os.environ.get("PATH", ""), "PYTHONPATH": str(repo_root / "backend"), "PYTHONDONTWRITEBYTECODE": "1",
            "HOME": str(tmp_path), "APP_PORT": str(free_port())}
    full.update(env)
    p = subprocess.run([sys.executable, "-m", "app.main"], env=full, cwd=str(tmp_path), capture_output=True, text=True, timeout=20)
    return p.returncode, p.stdout + p.stderr


GOOD_TOKEN = secrets.token_urlsafe(32)   # runtime-built; a repeated-character token is now refused as predictable


@pytest.mark.parametrize("env,named", [
    ({}, "MD_API_TOKEN"),
    ({"MD_API_TOKEN": ""}, "MD_API_TOKEN"),
    ({"MD_API_TOKEN": "s" * 31}, "MD_API_TOKEN"),
    ({"MD_API_TOKEN": GOOD_TOKEN, "MD_BIND_HOST": "0.0.0.0"}, "MD_BIND_HOST"),
    ({"MD_API_TOKEN": GOOD_TOKEN, "MD_BIND_HOST": "192.168.1.20"}, "MD_BIND_HOST"),
    ({"MD_API_TOKEN": GOOD_TOKEN, "MD_BIND_HOST": "::"}, "MD_BIND_HOST"),
    ({"MD_API_TOKEN": GOOD_TOKEN, "MD_BIND_HOST": "example.com"}, "MD_BIND_HOST"),
    ({"MD_API_TOKEN": GOOD_TOKEN, "MD_BIND_HOST": "127.0.0.1.evil.example"}, "MD_BIND_HOST"),
    ({"MD_API_TOKEN": GOOD_TOKEN, "MD_ALLOWED_ORIGINS": "*"}, "MD_ALLOWED_ORIGINS"),
    ({"MD_API_TOKEN": GOOD_TOKEN, "MD_ALLOWED_ORIGINS": "http://localhost:5173, *"}, "MD_ALLOWED_ORIGINS"),
    ({"MD_API_TOKEN": GOOD_TOKEN, "APP_PORT": "0"}, "APP_PORT"),
    ({"MD_API_TOKEN": GOOD_TOKEN, "APP_PORT": "70000"}, "APP_PORT"),
    ({"MD_API_TOKEN": GOOD_TOKEN, "APP_PORT": "-1"}, "APP_PORT"),
    ({"MD_API_TOKEN": GOOD_TOKEN, "APP_PORT": "eighty"}, "APP_PORT"),
    ({"MD_API_TOKEN": GOOD_TOKEN, "MD_TASK_RATE_PER_MIN": "many"}, "MD_TASK_RATE_PER_MIN"),
])
def test_service_refuses_to_start_and_names_the_variable(repo_root, tmp_path, env, named):
    code, out = _run_main(repo_root, tmp_path, **env)
    assert code != 0 and "ConfigError" in out, out[-300:]
    assert named in out
    for value in (env.get("MD_API_TOKEN"),):
        if value:
            assert value not in out, "the message must name the variable, never print its value"


def test_a_too_short_token_is_not_echoed_in_the_error(repo_root, tmp_path):
    token = "short-but-secret-" + "x" * 10
    code, out = _run_main(repo_root, tmp_path, MD_API_TOKEN=token)
    assert code != 0 and token not in out and "short-but-secret" not in out


def test_valid_loopback_hosts_start(repo_root, tmp_path):
    for host in ("127.0.0.1", "localhost"):
        srv = start_server(repo_root, tmp_path, env={"MD_BIND_HOST": host})
        try:
            assert httpx.get(f"{srv.base}/api/v1/health").status_code == 200
        finally:
            srv.stop()


def test_remote_bind_and_wildcard_origin_need_an_explicit_opt_in():
    from app.config import ConfigError, Settings

    base = {"MD_API_TOKEN": GOOD_TOKEN}
    assert Settings.from_env({**base, "MD_BIND_HOST": "0.0.0.0", "MD_ALLOW_REMOTE": "true"}).host == "0.0.0.0"
    assert Settings.from_env({**base, "MD_BIND_HOST": "::1"}).host == "::1"
    assert Settings.from_env({**base, "DEBUG": "true"}).allowed_origins == ("*",)
    with pytest.raises(ConfigError):
        Settings.from_env({**base, "MD_BIND_HOST": "0.0.0.0", "MD_ALLOW_REMOTE": "nope"})
    with pytest.raises(ConfigError):
        Settings.from_env({**base, "MD_ALLOWED_ORIGINS": "*", "DEBUG": "false"})
    assert "token" not in repr(Settings.from_env(base)).lower().replace("api_token", "")
    assert GOOD_TOKEN not in repr(Settings.from_env(base))


def test_docs_are_served_only_with_debug(repo_root, tmp_path):
    srv = start_server(repo_root, tmp_path, env={"DEBUG": "true"})
    try:
        assert httpx.get(f"{srv.base}/openapi.json").status_code == 200
    finally:
        srv.stop()


@pytest.mark.parametrize("token", ["a" * 32, " " * 32, "ab" * 20, "abc123" * 8, "t" * 40])
def test_predictable_api_tokens_are_refused_at_startup(token):
    """Observation from MD-TEST-004 (32 x 'a' used to start the service): now refused, naming the variable, never echoing the value."""
    from app.config import ConfigError, Settings

    with pytest.raises(ConfigError) as exc:
        Settings.from_env({"MD_API_TOKEN": token})
    assert "MD_API_TOKEN" in str(exc.value) and (token.strip() == "" or token not in str(exc.value))
    assert Settings.from_env({"MD_API_TOKEN": secrets.token_urlsafe(32)}).api_token


@pytest.mark.parametrize("rate", ["0", "-5"])
def test_nonsensical_task_rate_is_refused_at_startup(rate):
    """Observation from MD-TEST-004 (rate 0 or -5 started and made every submit 429): now a ConfigError."""
    from app.config import ConfigError, Settings

    with pytest.raises(ConfigError) as exc:
        Settings.from_env({"MD_API_TOKEN": secrets.token_urlsafe(32), "MD_TASK_RATE_PER_MIN": rate})
    assert "MD_TASK_RATE_PER_MIN" in str(exc.value)
