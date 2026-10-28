"""REST API (FastAPI TestClient). Providers are fakes: no network call and no real key is used."""

import json

import pytest
from fastapi.testclient import TestClient

from app.config import ConfigError, Settings
from app.executor import SimulatedExecutor
from app.main import create_app
from app.providers import DeterministicFallbackProvider, LanguageModelProvider, ProviderStatus
from app.schemas import PIPELINE_STAGES
from app.tokenizer import ApproximateTokenizer

TOKEN = "api-" + "Q7f2Lw9xK3mZ8pR1vB6nC4hJ0sD5gT2yE"  # random-looking, built at runtime
AUTH = {"Authorization": f"Bearer {TOKEN}"}
FAKE_KEY = "sk-" + "ant-FAKE0123456789abcdefFAKE"  # built at runtime so secret scanners see no literal key


class FakeCloud(LanguageModelProvider):
    """Configured provider whose status detail would leak a key if responses were not redacted."""

    name, kind = "cloud", "cloud"

    def status(self):
        return ProviderStatus(name=self.name, kind=self.kind, configured=True, available=True,
                              model="fake", detail=f"using key {FAKE_KEY}")

    def parse(self, command, world):
        return DeterministicFallbackProvider().parse(command, world)


class Unconfigured(FakeCloud):
    name, kind = "nvidia", "nvidia"

    def status(self):
        return ProviderStatus(name=self.name, kind=self.kind, configured=False, available=False, detail="no key")


def make_client(executor=None, **overrides):
    settings = Settings(api_token=TOKEN, **overrides)
    app = create_app(settings, providers=[FakeCloud(), Unconfigured()], executor=executor,
                     tokenizer=ApproximateTokenizer())
    return TestClient(app)


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", FAKE_KEY)
    with make_client() as c:
        yield c


def submit(client, text):
    r = client.post("/api/v1/tasks", json={"instruction": text}, headers=AUTH)
    assert r.status_code == 202, r.text
    return r.json()["task_id"]


# --- SEC-005: auth ------------------------------------------------------------------------------
PROTECTED = [
    ("post", "/api/v1/tasks", {"instruction": "Put the red cube in the storage box"}),
    ("get", "/api/v1/tasks", None),
    ("get", "/api/v1/tasks/task_x", None),
    ("post", "/api/v1/tasks/task_x/cancel", None),
    ("post", "/api/v1/tasks/task_x/clarify", {"free_text": "x"}),
    ("post", "/api/v1/simulation/e-stop", None),
    ("post", "/api/v1/simulation/reset", None),
    ("get", "/api/v1/providers", None),
    ("get", "/api/v1/providers/active", None),
    ("post", "/api/v1/providers/select", {"provider_id": "fallback"}),
    ("post", "/api/v1/tokenize", {"text": "hi"}),
    ("get", "/api/v1/executor", None),
    ("get", "/api/v1/environment/objects", None),
    ("get", "/api/v1/telemetry", None),
    ("get", "/api/v1/ros/inspector", None),
]


@pytest.mark.parametrize("method,path,body", PROTECTED)
@pytest.mark.parametrize("headers", [{}, {"Authorization": "Bearer wrong"}, {"Authorization": TOKEN},
                                     {"Authorization": f"Basic {TOKEN}"}])
def test_unauthorised_calls_are_rejected(client, method, path, body, headers):
    r = getattr(client, method)(path, json=body, headers=headers) if body else getattr(client, method)(path, headers=headers)
    assert r.status_code == 401 and r.json() == {"detail": "unauthorized"}
    assert r.headers["www-authenticate"] == "Bearer"


def test_rejected_calls_do_not_act(client):
    client.post("/api/v1/simulation/e-stop")
    client.post("/api/v1/tasks", json={"instruction": "Put the red cube in the storage box"})
    assert client.get("/api/v1/tasks", headers=AUTH).json() == []
    assert client.get("/api/v1/executor", headers=AUTH).json()["e_stop_latched"] is False


def test_repeated_auth_failures_are_rate_limited(monkeypatch):
    with make_client(auth_failures_per_min=3) as c:
        codes = [c.get("/api/v1/tasks").status_code for _ in range(5)]
        assert codes == [401, 401, 401, 429, 429]
        assert c.get("/api/v1/tasks", headers=AUTH).status_code == 200  # a valid token is never locked out


def test_task_submission_is_rate_limited():
    with make_client(task_rate_per_min=2) as c:
        codes = [c.post("/api/v1/tasks", json={"instruction": "Put the red cube in the storage box"},
                        headers=AUTH).status_code for _ in range(3)]
        assert codes == [202, 202, 429]


def test_health_is_public_and_leaks_nothing(client):
    r = client.get("/api/v1/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "ros2": "unavailable", "gazebo": "unavailable",
                        "moveit": "unavailable", "executor_connected": False}


def test_docs_are_off_by_default(client):
    assert client.get("/docs").status_code == 404 and client.get("/openapi.json").status_code == 404


# --- tasks --------------------------------------------------------------------------------------
def test_submit_runs_to_feasibility_then_reports_no_executor(client):
    task_id = submit(client, "Put the green cylinder in the storage box, keep it upright")
    body = client.get(f"/api/v1/tasks/{task_id}", headers=AUTH).json()
    assert body["status"] == "validated_no_executor"
    assert body["task"]["target_object"] == "green_cylinder" and body["task"]["constraints"]["keep_upright"]
    stages = body["stages"]
    assert list(stages) == list(PIPELINE_STAGES)
    assert stages["feasibility"] in ("success", "warning")
    assert all(stages[s] == "cancelled" for s in PIPELINE_STAGES[6:])  # never faked as executed
    last = body["events"][-1]
    assert last["data"]["reason"] == "headless_run_complete" and last["message"] == "no executor connected"
    assert set(last) == {"event_id", "stage", "state", "timestamp", "message", "data"}


def test_history_lists_newest_first(client):
    first = submit(client, "Put the red cube in the storage box")
    second = submit(client, "Move the box to the left")
    history = client.get("/api/v1/tasks", headers=AUTH).json()
    assert [h["task_id"] for h in history] == [second, first]
    assert history[0]["status"] == "needs_clarification"


def test_unknown_object_fails_with_its_name(client):
    task_id = submit(client, "Pick up the purple elephant")
    body = client.get(f"/api/v1/tasks/{task_id}", headers=AUTH).json()
    assert body["status"] == "failed" and body["task"] is None
    assert any(e["code"] == "UNKNOWN_OBJECT" and "purple_elephant" in e["message"] for e in body["report"]["errors"])


def test_clarify_validates_options_and_resumes(client):
    task_id = submit(client, "Move the box to the left")
    options = client.get(f"/api/v1/tasks/{task_id}", headers=AUTH).json()["clarification"]["options"]
    bad = client.post(f"/api/v1/tasks/{task_id}/clarify", json={"selected_option": "not_an_option",
                                                               "free_text": "x"}, headers=AUTH)
    assert bad.status_code == 409
    no_text = client.post(f"/api/v1/tasks/{task_id}/clarify", json={"selected_option": options[0]}, headers=AUTH)
    assert no_text.status_code == 409
    r = client.post(f"/api/v1/tasks/{task_id}/clarify",
                    json={"selected_option": options[0], "free_text": "Put the red cube on the platform"}, headers=AUTH)
    assert r.json() == {"status": "resumed", "task_id": task_id}
    body = client.get(f"/api/v1/tasks/{task_id}", headers=AUTH).json()
    assert body["status"] == "validated_no_executor" and body["task"]["destination"] == "platform"
    assert body["clarifications"][0]["selected_option"] == options[0]


def test_clarify_only_when_waiting_for_one(client):
    task_id = submit(client, "Put the red cube in the storage box")
    assert client.post(f"/api/v1/tasks/{task_id}/clarify", json={"free_text": "x"}, headers=AUTH).status_code == 409


def test_cancel_finished_task_is_a_conflict_and_unknown_is_404(client):
    task_id = submit(client, "Put the red cube in the storage box")
    assert client.post(f"/api/v1/tasks/{task_id}/cancel", headers=AUTH).status_code == 409
    assert client.post("/api/v1/tasks/task_nope/cancel", headers=AUTH).status_code == 404
    assert client.get("/api/v1/tasks/task_nope", headers=AUTH).status_code == 404


def test_cancel_before_start_stops_the_run(client):
    manager = client.app.state.manager
    record = manager.create("Put the red cube in the storage box")
    assert client.post(f"/api/v1/tasks/{record.task_id}/cancel", headers=AUTH).json()["status"] == "cancelled"
    manager.run(record.task_id, record.instruction)
    assert manager.get(record.task_id).status == "cancelled" and record.events == []


def test_cancel_mid_run_cancels_remaining_stages(client):
    manager = client.app.state.manager
    record = manager.create("Put the red cube in the storage box")
    original = manager._emit

    def emit_then_cancel(rec, ev):
        original(rec, ev)
        if ev.stage == "interpretation" and ev.state.value == "running":
            manager.cancel(rec.task_id)
    manager._emit = emit_then_cancel
    manager.run(record.task_id, record.instruction)
    stages = record.stages()
    assert record.status == "cancelled" and stages["structured_task"] == "cancelled"
    assert stages["schema_validation"] == "cancelled"


def test_bad_input_is_rejected_without_echo(client):
    huge = "a " * 40000
    r = client.post("/api/v1/tasks", json={"instruction": huge}, headers=AUTH)
    assert r.status_code == 422 and "a a a" not in r.text
    r = client.post("/api/v1/tasks", json={"instruction": "x", "run_as": "root"}, headers=AUTH)
    assert r.status_code == 422 and "root" not in r.text
    task_id = submit(client, "Put the red cube\x00 in the box")
    assert client.get(f"/api/v1/tasks/{task_id}", headers=AUTH).json()["status"] == "failed"


def test_oversized_body_is_refused(client):
    r = client.post("/api/v1/tasks", content=b"{" + b" " * 200_000 + b"}",
                    headers={**AUTH, "Content-Type": "application/json"})
    assert r.status_code == 413


# --- e-stop (SEC-013) ---------------------------------------------------------------------------
def test_e_stop_reports_observed_state_and_latches(client):
    r = client.post("/api/v1/simulation/e-stop", headers=AUTH)
    body = r.json()
    assert r.status_code == 200 and body["status"] == "e_stop_confirmed"
    assert body["controller_state"] == "STOPPED" and body["max_joint_velocity"] < body["tolerance"]
    assert "simulated" in body["source"] and body["requires_reset"] is True
    blocked = client.post("/api/v1/tasks", json={"instruction": "Put the red cube in the storage box"}, headers=AUTH)
    assert blocked.status_code == 409 and "reset" in blocked.json()["detail"]
    reset = client.post("/api/v1/simulation/reset", headers=AUTH).json()
    assert reset["status"] == "resetting" and reset["e_stop_latched"] is False
    assert "ros unavailable" in reset["scene_reset"]
    submit(client, "Put the red cube in the storage box")


def test_e_stop_that_cannot_be_confirmed_is_not_reported_as_stopped():
    with make_client(executor=SimulatedExecutor(joint_velocities=[0.5] * 7, stop_effective=False)) as c:
        r = c.post("/api/v1/simulation/e-stop", headers=AUTH)
        assert r.status_code == 503
        assert r.json()["detail"]["status"] == "e_stop_unverified"
        assert c.get("/api/v1/executor", headers=AUTH).json()["e_stop_latched"] is True


def test_e_stop_is_not_rate_limited():
    with make_client(task_rate_per_min=1) as c:
        assert all(c.post("/api/v1/simulation/e-stop", headers=AUTH).status_code == 200 for _ in range(15))


# --- providers ----------------------------------------------------------------------------------
def test_provider_list_never_contains_keys(client):
    r = client.get("/api/v1/providers", headers=AUTH)
    assert r.status_code == 200 and FAKE_KEY not in r.text and "[REDACTED]" in r.text
    ids = [p["provider_id"] for p in r.json()]
    assert ids == ["cloud", "nvidia", "fallback"]


def test_select_provider(client):
    assert client.get("/api/v1/providers/active", headers=AUTH).json()["provider_id"] == "auto"
    assert client.post("/api/v1/providers/select", json={"provider_id": "fallback"},
                       headers=AUTH).json()["provider_id"] == "fallback"
    task_id = submit(client, "Put the red cube in the storage box")
    assert client.get(f"/api/v1/tasks/{task_id}", headers=AUTH).json()["provider"] == "fallback"
    assert client.post("/api/v1/providers/select", json={"provider_id": "cloud"}, headers=AUTH).status_code == 200
    task_id = submit(client, "Put the red cube in the storage box")
    assert client.get(f"/api/v1/tasks/{task_id}", headers=AUTH).json()["provider"] == "cloud"
    assert client.post("/api/v1/providers/select", json={"provider_id": "nvidia"}, headers=AUTH).status_code == 409
    assert client.post("/api/v1/providers/select", json={"provider_id": "nope"}, headers=AUTH).status_code == 404
    assert client.post("/api/v1/providers/select", json={"provider_id": "../x"}, headers=AUTH).status_code == 422


def test_token_never_appears_in_responses(client):
    r = client.post("/api/v1/tasks", json={"instruction": f"Put the red cube in the box {TOKEN}"}, headers=AUTH)
    detail = client.get(f"/api/v1/tasks/{r.json()['task_id']}", headers=AUTH)
    assert TOKEN not in detail.text and TOKEN not in client.get("/api/v1/tasks", headers=AUTH).text


# --- tokenization and ROS stubs -----------------------------------------------------------------
def test_tokenize_endpoint(client):
    r = client.post("/api/v1/tokenize", json={"text": "Put the red cube"}, headers=AUTH).json()
    assert r["is_live_model_tokenization"] is False and all(t["token_id"] is None for t in r["tokens"])
    assert client.post("/api/v1/tokenize", json={"text": "   "}, headers=AUTH).status_code == 422


@pytest.mark.parametrize("path", ["/api/v1/environment/objects", "/api/v1/telemetry", "/api/v1/ros/inspector"])
def test_ros_stubs_say_ros_is_unavailable(client, path):
    body = client.get(path, headers=AUTH).json()
    assert body["available"] is False and body["reason"] == "ros unavailable"


def test_environment_lists_configured_scene_not_perception(client):
    body = client.get("/api/v1/environment/objects", headers=AUTH).json()
    assert body["objects"] == [] and "red_cube" in body["scene_config"]["objects"]


# --- SEC-007: CORS ------------------------------------------------------------------------------
def test_cors_allows_only_listed_origins(client):
    evil = client.get("/api/v1/health", headers={"Origin": "https://evil.com"})
    assert "access-control-allow-origin" not in evil.headers
    good = client.get("/api/v1/health", headers={"Origin": "http://localhost:5173"})
    assert good.headers["access-control-allow-origin"] == "http://localhost:5173"
    assert "access-control-allow-credentials" not in good.headers
    pre = client.options("/api/v1/tasks", headers={"Origin": "http://localhost:5173",
                                                   "Access-Control-Request-Method": "DELETE"})
    assert pre.status_code == 400


# --- SEC S5: startup checks ---------------------------------------------------------------------
@pytest.mark.parametrize("env,needle", [
    ({}, "MD_API_TOKEN"),
    ({"MD_API_TOKEN": "short"}, "MD_API_TOKEN"),
    ({"MD_API_TOKEN": TOKEN, "MD_BIND_HOST": "0.0.0.0"}, "MD_BIND_HOST"),
    ({"MD_API_TOKEN": TOKEN, "MD_ALLOWED_ORIGINS": "*"}, "MD_ALLOWED_ORIGINS"),
    ({"MD_API_TOKEN": TOKEN, "APP_PORT": "abc"}, "APP_PORT"),
])
def test_startup_refuses_bad_config(env, needle):
    with pytest.raises(ConfigError, match=needle) as err:
        Settings.from_env(env)
    assert TOKEN not in str(err.value)


def test_startup_defaults_are_local():
    s = Settings.from_env({"MD_API_TOKEN": TOKEN})
    assert s.host == "127.0.0.1" and s.port == 8000 and "*" not in s.allowed_origins
    assert TOKEN not in repr(s)
    assert Settings.from_env({"MD_API_TOKEN": TOKEN, "MD_BIND_HOST": "0.0.0.0", "MD_ALLOW_REMOTE": "true"}).host == "0.0.0.0"
    assert Settings.from_env({"MD_API_TOKEN": TOKEN, "DEBUG": "true"}).allowed_origins == ("*",)


def test_pasted_key_is_redacted_before_tokenizing_and_parsing(client, monkeypatch):
    fake = "nvapi-" + "SECRET-SECRET-SECRET-123"
    monkeypatch.setenv("NVIDIA_API_KEY", fake)
    r = client.post("/api/v1/tokenize", json={"text": f"Put {fake} away"}, headers=AUTH)
    assert "SECRET" not in r.text
    task_id = submit(client, f"Put the red cube in the storage box {fake}")
    assert "SECRET" not in client.get(f"/api/v1/tasks/{task_id}", headers=AUTH).text


# --- MD-TEST-004 regressions (API-1, API-2, API-4) -------------------------------------------------------------------
def test_unauthenticated_bad_body_is_401_before_any_parsing(client):
    r = client.post("/api/v1/tasks", content=b"not json", headers={"content-type": "application/json"})
    assert r.status_code == 401 and r.json() == {"detail": "unauthorized"}


@pytest.mark.parametrize("auth", [True, False])
def test_chunked_body_over_the_cap_is_413(client, auth):
    def chunks():
        for _ in range(8):  # 8 x 64 KiB = 512 KiB, no Content-Length
            yield b"a" * 65_536
    r = client.post("/api/v1/tasks", content=chunks(), headers={"content-type": "application/json", **(AUTH if auth else {})})
    assert r.status_code == (413 if auth else 401)
    small = client.post("/api/v1/tasks", content=iter([b'{"instruction": "Move the box to the left"}']),
                        headers={"content-type": "application/json", **AUTH})
    assert small.status_code == 202  # a chunked body under the cap still works


def test_cors_headers_survive_the_gate(client):
    r = client.post("/api/v1/tasks", json={"instruction": "x"}, headers={"origin": "http://localhost:5173"})
    assert r.status_code == 401 and r.headers["access-control-allow-origin"] == "http://localhost:5173"


class BuggyExecutor(SimulatedExecutor):
    def status(self):
        return super().status().model_copy(update={"connected": True, "can_execute": True})

    def execute(self, task, emit, is_cancelled):
        raise RuntimeError("bug in the executor")


def test_executor_bug_fails_the_task_instead_of_hanging():
    with make_client(executor=BuggyExecutor()) as c:
        task_id = submit(c, "Put the red cube in the storage box")
        detail = c.get(f"/api/v1/tasks/{task_id}", headers=AUTH).json()
    assert detail["status"] == "failed", detail["status"]
    assert "internal error (RuntimeError)" in json.dumps(detail)


def test_uvicorn_access_log_is_redacted():
    import logging
    with make_client():
        rec = logging.LogRecord("uvicorn.access", logging.INFO, __file__, 1, '%s - "%s %s HTTP/%s" %d',
                                ("127.0.0.1:5", "GET", f"/api/v1/executor?access_token={TOKEN}&k={FAKE_KEY}", "1.1", 200), None)
        assert logging.getLogger("uvicorn.access").filter(rec)
        line = rec.getMessage()
    assert TOKEN not in line and "FAKE0123456789" not in line and "[REDACTED]" in line and line.endswith("200")


# --- MD-DEV-008: config hardening and e-stop read-back --------------------------------------------------------------
@pytest.mark.parametrize("weak", ["a" * 32, " " * 32, "ab" * 20, "abcdefgh" * 5, "0123456" * 6, "0123456789" * 4, "Kq8zT1wLm3Pb" * 3])
def test_trivially_weak_tokens_are_refused_at_startup(weak):
    with pytest.raises(ConfigError) as err:
        Settings.from_env({"MD_API_TOKEN": weak})
    assert "MD_API_TOKEN" in str(err.value) and weak not in str(err.value)


def test_a_generated_token_is_accepted():
    import secrets
    for _ in range(50):
        assert Settings.from_env({"MD_API_TOKEN": secrets.token_urlsafe(32)}).api_token
        assert Settings.from_env({"MD_API_TOKEN": secrets.token_hex(16)}).api_token


def test_weak_token_check_comes_after_the_other_checks():
    with pytest.raises(ConfigError, match="MD_BIND_HOST"):
        Settings.from_env({"MD_API_TOKEN": "t" * 40, "MD_BIND_HOST": "0.0.0.0"})


@pytest.mark.parametrize("rate", ["0", "-5"])
def test_task_rate_must_be_positive(rate):
    with pytest.raises(ConfigError, match="MD_TASK_RATE_PER_MIN"):
        Settings.from_env({"MD_API_TOKEN": TOKEN, "MD_TASK_RATE_PER_MIN": rate})


@pytest.mark.parametrize("bad", [[0.0, float("nan")], [float("nan"), 0.0], [0.0, float("inf")], [float("-inf")]])
def test_non_finite_read_back_is_never_a_confirmed_stop(bad):
    from app.executor import stop_report
    report = stop_report(bad, "STOPPED", "test")
    assert report.status == "e_stop_unverified" and report.max_joint_velocity is None
    assert "NaN or inf" in report.detail
    json.dumps(report.model_dump())  # stays valid JSON (no NaN literal)
    assert stop_report([0.0, 0.0], "STOPPED", "test").status == "e_stop_confirmed"
