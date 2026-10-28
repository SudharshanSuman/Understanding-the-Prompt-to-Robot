"""MD-TEST-004: SEC-005 auth, 429 lockout, task rate limit, SEC-007 CORS, body limits. Live uvicorn, real HTTP."""
import socket
import time

import httpx
import pytest

from tests.api.helpers import ORIGIN, submit

pytestmark = [pytest.mark.api, pytest.mark.unit]


def _protected_routes():
    """Every route of the protected router (everything under /api/v1 except /health), read from the app's own router
    object so a route added there cannot dodge the sweep."""
    from fastapi.routing import APIRoute

    from app.api.routes import protected, public

    assert [r.path for r in public.routes] == ["/api/v1/health"], "a new PUBLIC route needs a deliberate review"
    out = []
    for r in protected.routes:
        assert isinstance(r, APIRoute)
        for m in sorted(r.methods - {"HEAD", "OPTIONS"}):
            out.append((m, r.path.replace("{task_id}", "task_000000000000")))
    return out


def test_route_inventory_is_what_the_report_lists():
    routes = {f"{m} {p}" for m, p in _protected_routes()}
    assert len(routes) == 15, sorted(routes)
    assert "POST /api/v1/simulation/e-stop" in routes and "POST /api/v1/tasks" in routes


BAD_AUTH = {
    "no header": {},
    "scheme only": {"Authorization": "Bearer"},
    "short token": {"Authorization": "Bearer abc"},
    "31 chars": {"Authorization": "Bearer " + "a" * 31},
    "wrong, right length": {"Authorization": "Bearer " + "x" * 43},
    "basic scheme": {"Authorization": "Basic dXNlcjpwYXNz"},
    "token without scheme": {"Authorization": "x" * 43},
}


@pytest.mark.parametrize("label", list(BAD_AUTH))
def test_every_protected_route_rejects_bad_credentials_with_a_bare_401(shared, label):
    with httpx.Client(base_url=shared.base, timeout=10) as c:
        for method, path in _protected_routes():
            r = c.request(method, path, headers=BAD_AUTH[label], json={} if method == "POST" else None)
            assert r.status_code == 401, f"{label}: {method} {path} -> {r.status_code} {r.text[:80]}"
            assert r.json() == {"detail": "unauthorized"}, (method, path, r.text)
            assert r.headers.get("www-authenticate") == "Bearer"
            assert shared.token not in r.text


def test_wrong_token_that_differs_only_in_last_character_is_rejected(shared):
    near = shared.token[:-1] + ("A" if shared.token[-1] != "A" else "B")
    with shared.client(token=near) as c:
        assert c.get("/api/v1/executor").status_code == 401


def test_valid_token_reaches_every_protected_route(shared):
    with shared.client() as c:
        for method, path in _protected_routes():
            if path.endswith("/simulation/e-stop") or path.endswith("/simulation/reset"):
                continue  # covered in the e-stop tests (they change server state)
            r = c.request(method, path, json={} if method == "POST" else None)
            assert r.status_code in {200, 202, 404, 409, 422}, f"{method} {path} -> {r.status_code}"


def test_health_is_public_and_leaks_nothing(shared):
    r = httpx.get(f"{shared.base}/api/v1/health")
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {"status", "ros2", "gazebo", "moveit", "executor_connected"}
    text = r.text + str(dict(r.headers))
    assert shared.token not in text and "/home" not in text and "uvicorn" not in r.headers.get("server", "").lower()


def test_docs_and_openapi_are_off_without_debug(shared):
    for path in ("/docs", "/redoc", "/openapi.json"):
        assert httpx.get(shared.base + path).status_code == 404, path


@pytest.mark.xfail(strict=True, reason="DEFECT API-1: the request body is read and JSON-parsed before the auth check, so an "
                                       "unauthenticated client gets 422 (and costs memory) instead of 401")
def test_unauthenticated_post_with_invalid_body_gets_401_not_a_validation_error(shared):
    r = httpx.post(f"{shared.base}/api/v1/tasks", content=b"not json", headers={"content-type": "application/json"})
    assert r.status_code == 401 and r.json() == {"detail": "unauthorized"}


# --- lockout and rate limits ---------------------------------------------------------------------------------------
def test_repeated_auth_failures_give_429_but_the_valid_token_is_never_locked_out(make_server):
    srv = make_server()  # default: 20 failures per minute per client
    statuses = []
    with httpx.Client(base_url=srv.base, timeout=10) as bad:
        for _ in range(30):
            statuses.append(bad.get("/api/v1/executor", headers={"Authorization": "Bearer " + "z" * 43}).status_code)
        assert statuses[:20] == [401] * 20, statuses
        assert set(statuses[20:]) == {429}, statuses
        r = bad.get("/api/v1/executor", headers={"Authorization": "Bearer " + "z" * 43})
        assert r.status_code == 429 and r.json() == {"detail": "too many requests"}
    with srv.client() as good:
        assert good.get("/api/v1/executor").status_code == 200, "valid token must not be locked out"
        assert good.post("/api/v1/tokenize", json={"text": "move the red cube"}).status_code == 200
    assert httpx.get(f"{srv.base}/api/v1/health").status_code == 200


def test_task_submission_is_limited_to_10_per_minute_but_reads_and_estop_are_not(make_server):
    srv = make_server(rate=None)  # product default
    with srv.client() as c:
        codes = [c.post("/api/v1/tasks", json={"instruction": "Move the red cube to the platform"}).status_code for _ in range(12)]
        assert codes == [202] * 10 + [429] * 2, codes
        limited = c.post("/api/v1/tasks", json={"instruction": "Move the red cube to the platform"})
        assert limited.status_code == 429 and "token" not in limited.text.lower()
        assert c.get("/api/v1/tasks").status_code == 200
        assert len(c.get("/api/v1/tasks").json()) == 10
        assert c.get("/api/v1/executor").status_code == 200
        assert c.post("/api/v1/simulation/e-stop").status_code == 200, "e-stop must not be rate limited"


def test_invalid_submissions_do_not_burn_the_rate_limit(make_server):
    srv = make_server(rate=None)
    with srv.client() as c:
        for _ in range(15):
            assert c.post("/api/v1/tasks", json={"instruction": ""}).status_code == 422
        assert c.post("/api/v1/tasks", json={"instruction": "Move the red cube to the platform"}).status_code == 202


# --- CORS (SEC-007) ------------------------------------------------------------------------------------------------
def test_cors_allows_only_the_listed_origin_and_never_credentials(shared):
    ok = httpx.get(f"{shared.base}/api/v1/health", headers={"Origin": ORIGIN})
    assert ok.headers.get("access-control-allow-origin") == ORIGIN
    assert "access-control-allow-credentials" not in ok.headers
    for origin in ("https://evil.example", "null", ORIGIN + ".evil.example", "http://localhost:5174", "http://localhost:5173/"):
        r = httpx.get(f"{shared.base}/api/v1/health", headers={"Origin": origin})
        assert "access-control-allow-origin" not in r.headers, origin
    assert "*" not in ok.headers.get("access-control-allow-origin", "")


def test_cors_preflight_is_limited_to_get_post_and_the_two_headers(shared):
    def pre(origin, method, headers):
        return httpx.options(f"{shared.base}/api/v1/tasks", headers={
            "Origin": origin, "Access-Control-Request-Method": method, "Access-Control-Request-Headers": headers})

    good = pre(ORIGIN, "POST", "authorization,content-type")
    assert good.status_code == 200 and good.headers["access-control-allow-origin"] == ORIGIN
    assert set(good.headers["access-control-allow-methods"].replace(" ", "").split(",")) == {"GET", "POST"}
    assert "access-control-allow-credentials" not in good.headers
    for method in ("DELETE", "PUT", "PATCH"):
        r = pre(ORIGIN, method, "authorization")
        assert r.status_code == 400 and "access-control-allow-origin" not in r.headers or method not in r.headers.get("access-control-allow-methods", ""), method
    assert pre(ORIGIN, "POST", "x-evil-header").status_code == 400
    evil = pre("https://evil.example", "POST", "authorization")
    assert evil.status_code == 400 and "access-control-allow-origin" not in evil.headers


def test_cors_headers_do_not_make_an_unauthenticated_call_succeed(shared):
    r = httpx.get(f"{shared.base}/api/v1/tasks", headers={"Origin": ORIGIN})
    assert r.status_code == 401


# --- body size (413) -----------------------------------------------------------------------------------------------
def test_body_over_128kb_with_content_length_gets_413_without_reading_it(shared):
    with shared.client() as c:
        r = c.post("/api/v1/tasks", content=b'{"instruction":"' + b"a" * 200_000 + b'"}', headers={"content-type": "application/json"})
        assert r.status_code == 413 and r.json() == {"detail": "request body too large"}
        just_under = c.post("/api/v1/tasks", content=b'{"instruction":"' + b"a " * 40_000 + b'"}', headers={"content-type": "application/json"})
        assert just_under.status_code in {202, 422}, "a body under 128 KB is not a 413"


def test_absurd_and_malformed_content_length_values_are_refused_at_once(shared):
    for value in ("99999999999", "-1", "abc", "1e9"):
        with socket.create_connection(("127.0.0.1", shared.port), timeout=5) as s:
            s.sendall((f"POST /api/v1/tasks HTTP/1.1\r\nHost: x\r\nAuthorization: Bearer {shared.token}\r\n"
                       f"Content-Type: application/json\r\nContent-Length: {value}\r\n\r\n").encode())
            s.settimeout(5)
            head = s.recv(200).decode(errors="replace")
        assert " 413 " in head.split("\r\n")[0] or " 400 " in head.split("\r\n")[0], (value, head[:60])


@pytest.mark.xfail(strict=True, reason="DEFECT API-1: the 128 KB cap only looks at Content-Length; a chunked upload (no "
                                       "Content-Length) is read completely (100 MiB took the server from 53 to 254 MB RSS)")
@pytest.mark.parametrize("authenticated", [True, False])
def test_chunked_body_over_the_limit_is_also_refused(shared, authenticated):
    """Content-Length is absent for chunked uploads; the 128 KB cap must still hold."""
    def chunks():
        for _ in range(40):  # 40 x 128 KiB = 5 MiB
            yield b"a" * 131_072

    start = time.monotonic()
    with shared.client(token="__valid__" if authenticated else None) as c:
        r = c.post("/api/v1/tasks", content=chunks(), headers={"content-type": "application/json"})
    assert r.status_code == 413, f"got {r.status_code} after {time.monotonic() - start:.2f}s"


def test_deeply_nested_json_is_a_clean_4xx_not_a_crash(shared):
    with shared.client() as c:
        r = c.post("/api/v1/tasks", content=b"[" * 50_000 + b"]" * 50_000, headers={"content-type": "application/json"})
        assert r.status_code in {400, 413, 422}, r.status_code
        assert c.get("/api/v1/executor").status_code == 200, "server must still be up"


def test_validation_errors_never_echo_the_input(shared):
    marker = "SECRETISH-MARKER-0123456789"
    with shared.client() as c:
        for body in ({"instruction": marker, "extra": marker}, {"instruction": 5}, {"wrong": marker}):
            r = c.post("/api/v1/tasks", json=body)
            assert r.status_code == 422 and marker not in r.text
        r = c.post("/api/v1/tasks", content=('{"instruction": "' + marker).encode(), headers={"content-type": "application/json"})
        assert r.status_code == 422 and marker not in r.text
