"""Start a real uvicorn server (a subprocess of THIS venv) for black-box API tests, plus REST/WebSocket helpers."""
from __future__ import annotations

import json
import os
import secrets
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest

ORIGIN = "http://localhost:5173"


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Server:
    def __init__(self, proc, port, token, log_path, state_file):
        self.proc, self.port, self.token, self.log_path, self.state_file = proc, port, token, log_path, state_file
        self.base, self.ws = f"http://127.0.0.1:{port}", f"ws://127.0.0.1:{port}"

    def client(self, token="__valid__", **kw) -> httpx.Client:
        headers = dict(kw.pop("headers", {}))
        if token == "__valid__":
            token = self.token
        if token is not None:
            headers["Authorization"] = f"Bearer {token}"
        return httpx.Client(base_url=self.base, headers=headers, timeout=15, **kw)

    def log_text(self) -> str:
        return Path(self.log_path).read_text(errors="replace")

    def set_executor(self, state: str) -> None:
        Path(self.state_file).write_text(state)

    def exec_log(self) -> list[str]:
        p = Path(self.state_file + ".log")
        return p.read_text().splitlines() if p.exists() else []

    def stop(self) -> None:
        if self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(5)
            except subprocess.TimeoutExpired:
                self.proc.kill()


def start_server(repo_root: Path, tmp: Path, *, rate: str | None = "1000", env: dict | None = None, **launcher_env) -> Server:
    """Defaults: fallback-only providers, simulated executor, a high task rate (override with rate=None for the product default)."""
    backend = repo_root / "backend"
    token, port = secrets.token_urlsafe(32), free_port()
    state_file, log_path = str(tmp / f"exec-state-{port}"), tmp / f"server-{port}.log"
    e = {"PATH": os.environ.get("PATH", ""), "HOME": str(tmp), "PYTHONPATH": f"{backend}{os.pathsep}{repo_root}",
         "PYTHONDONTWRITEBYTECODE": "1", "MD_API_TOKEN": token, "APP_PORT": str(port), "MD_TEST_STATE_FILE": state_file,
         "OLLAMA_HOST": "http://127.0.0.1:9", "MD_CLOUD_BASE_URL": "http://127.0.0.1:9", "NVIDIA_BASE_URL": "http://127.0.0.1:9/v1"}
    if rate is not None:
        e["MD_TASK_RATE_PER_MIN"] = rate
    e.update({k: str(v) for k, v in launcher_env.items()})
    e.update(env or {})
    with open(log_path, "wb") as log:
        proc = subprocess.Popen([sys.executable, str(repo_root / "tests/api/launcher.py")], env=e, stdout=log, stderr=subprocess.STDOUT,
                                cwd=str(tmp))
    srv = Server(proc, port, token, log_path, state_file)
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            raise RuntimeError(f"server exited early: {srv.log_text()[-800:]}")
        try:
            if httpx.get(f"{srv.base}/api/v1/health", timeout=1).status_code == 200:
                return srv
        except httpx.HTTPError:
            time.sleep(0.1)
    srv.stop()
    raise RuntimeError("server did not become ready")


def wait_status(client: httpx.Client, task_id: str, until: set[str], timeout: float = 10.0) -> dict:
    end = time.monotonic() + timeout
    body = {}
    while time.monotonic() < end:
        body = client.get(f"/api/v1/tasks/{task_id}").json()
        if body.get("status") in until:
            return body
        time.sleep(0.05)
    raise AssertionError(f"task {task_id} stuck at {body.get('status')!r}, wanted {until}")


FINAL_STATUSES = {"needs_clarification", "failed", "cancelled", "validated_no_executor", "completed"}


def submit(client: httpx.Client, text: str) -> str:
    r = client.post("/api/v1/tasks", json={"instruction": text})
    assert r.status_code == 202, (r.status_code, r.text)
    return r.json()["task_id"]


# --- WebSocket ---------------------------------------------------------------------------------------------------
def ws_connect(server: Server, path="/ws/pipeline", origin=None, **kw):
    from websockets.sync.client import connect  # imported lazily so the module imports without it

    return connect(server.ws + path, origin=origin, open_timeout=5, max_size=None, **kw)


def ws_login(conn, token: str) -> dict:
    conn.send(json.dumps({"type": "auth", "token": token}))
    return json.loads(conn.recv(timeout=5))


def ws_recv_json(conn, timeout=5) -> dict:
    return json.loads(conn.recv(timeout=timeout))


def ws_close_code(conn, timeout=10):
    """Read until the server closes; return its close code."""
    from websockets.exceptions import ConnectionClosed

    try:
        while True:
            conn.recv(timeout=timeout)
    except ConnectionClosed as exc:
        return exc.rcvd.code if exc.rcvd else None


def ws_frames_until(conn, predicate, timeout=10.0) -> list[dict]:
    end, out = time.monotonic() + timeout, []
    while time.monotonic() < end:
        try:
            frame = ws_recv_json(conn, timeout=max(0.1, end - time.monotonic()))
        except TimeoutError:
            break
        out.append(frame)
        if predicate(frame):
            return out
    raise AssertionError(f"condition not reached; got {[f.get('channel') for f in out]}")


def need_live_stack():
    for mod in ("fastapi", "uvicorn", "websockets", "httpx"):
        pytest.importorskip(mod, reason=f"live API tests need {mod} in the test venv")
