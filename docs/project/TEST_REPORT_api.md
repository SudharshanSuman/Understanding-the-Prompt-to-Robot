# API service verification report (MD-TEST-004)

Verifier: Angela (Tester). Target: Pam's MD-DEV-003 (FastAPI REST + WebSocket, `backend/app/{main,config,executor,tasks}.py`, `api/`, `websocket/`), as on disk on 2026-10-28.
Method: a real `uvicorn` subprocess per scenario (random free port, never 8000/8080), real HTTP (`httpx`) and a real WebSocket client (`websockets` 17.3, installed in my test venv only). No mocks between the client and the server. Two test-only seams, both in `tests/api/launcher.py`: a fake executor (to model connected / disconnected / crashing / non-stopping executors) and a slow fake provider (to hold a task in `running`). The model APIs were never called: provider URLs point at a dead port, or at a local echo server for the key-leak test.
Environment: Python 3.12.3, fastapi 0.162.0, uvicorn 0.54.0, websockets 17.3, pytest 9, no ROS, no Gazebo, no network.

## 0. Update 2026-10-28 (MD-TEST-005 session): API-1 to API-4 are FIXED and re-verified
Pam's fixes landed at 06:18. I re-probed each (not only re-ran the tests) and turned the four strict xfails into regression tests; **123 API tests now pass, 0 xfail**. Whole suite: 313 passed, 10 skipped, 1 xfailed (a UI defect, see `TEST_REPORT_frontend.md`). Details in section 9. The text below is the original report.

## 1. Verdict
The service does what the report says for auth, lockout, rate limit, CORS, WebSocket hygiene, the e-stop latch and read-back, startup refusal and secret redaction in responses. **Four defects**, none letting an unauthenticated caller run or change anything: API-1 (an unauthenticated client can make the server buffer arbitrarily large chunked bodies), API-2 (an executor bug leaves a task `executing` forever), API-3 (no lockout on WebSocket token guessing), API-4 (a secret placed in a URL is written to the access log). All four are pinned as strict `xfail` tests that flip when fixed. Acceptance G and H pass at API level.

## 2. Counts (all real, this machine)
| Suite | Command | Result |
|---|---|---|
| Pam's backend suite | `backend/.venv/bin/python -m pytest -c backend/pytest.ini backend` | **265 passed, 1 skipped** (tiktoken absent). With tiktoken (my venv): 266 passed. Her report said 261 + 1 skip; she added tests since |
| My suite, everything | `python -m pytest -c tests/pytest.ini tests` | **255 passed, 10 skipped, 6 xfailed**, 0 failed (run twice, identical, about 52 s) |
| My suite without live API tests | `... -m "not api"` | 147 passed, 10 skipped |
| My live API tests only | `... tests/api` | **108 passed, 6 xfailed** (114 collected) |
Skips are the 10 ROS/Gazebo placeholders. The 6 xfails are API-1 (x3 params), API-2, API-3, API-4; each was also run with `--runxfail` to confirm it fails for the stated reason (see section 4).

## 3. Checks requested, result per item
| Check | Result | Evidence |
|---|---|---|
| Auth on every `/api/v1` route (none / short / wrong / wrong scheme / no scheme) | **Pass** | All 15 protected routes x 7 bad-credential forms -> 401 with body exactly `{"detail":"unauthorized"}` and `WWW-Authenticate: Bearer`. The route list is read from the app's own router, and the test fails if a second public route appears. Token differing in the last character only: 401. Only `/health` is public and it returns just 5 status fields |
| 429 lockout | **Pass** | 20 wrong tokens -> 401 each, the 21st onwards -> 429. The valid token still gets 200 while the client is locked out, `/health` too |
| Task rate limit | **Pass** | 10 x 202 then 429 (message does not mention the token). Reads and e-stop are not limited. Invalid bodies (422) do not consume the budget |
| Origin / CORS | **Pass** | Listed origin echoed, no `Allow-Credentials`, no `*`. Evil origin, `null`, suffix and port variants, trailing slash: no `Allow-Origin`. Preflight: methods GET+POST only; DELETE/PUT/PATCH and unlisted headers -> 400. CORS headers do not make an unauthenticated call succeed |
| WebSocket first-message auth | **Pass** | 8 bad first messages (wrong/missing/typed-wrong token, extra field, junk, empty, ping first) -> close 4401; zero frames before auth; token in header or URL is not accepted; silent socket closed after 5.0 s with **code 1008** (the report says 4401: cosmetic) |
| WS Origin | **Pass** | Four bad origins -> HTTP 403 at the handshake; listed origin and no-Origin accepted |
| Oversize / binary frames | **Pass** | Binary before or after auth -> 1003. Text frame of 8193 B, 20 kB, 1 MB -> 1009 within 3 s, also before auth. A frame of exactly 8192 B is served |
| Malformed WS messages | **Pass** | 10 shapes -> an `error` frame, socket stays up, input not echoed, ping still works |
| Connection cap | **Pass** | 11th connection refused (HTTP 403 at upgrade); closing one frees a slot; unauthenticated sockets give their slot back after the auth deadline |
| E-stop latch | **Pass** | `e_stop_confirmed` only with a read-back of 0.0 rad/s and controller STOPPED; then `GET /executor` shows latched, `POST /tasks` -> 409 until `/simulation/reset`, idempotent, reset does not claim the scene was reset |
| E-stop needs measured zero velocity | **Pass** | Executor that does not stop (joint at 0.5 rad/s) -> HTTP 503, `e_stop_unverified`, velocity and tolerance reported, no "confirmed" anywhere, **latch still set** (fail safe) |
| E-stop under load | **Pass** (API only) | With 8 slow tasks running, `POST /e-stop` answered 200 in under 1 s and the running tasks ended `cancelled`. Not executed: with a real ROS executor (SEC-013.6) |
| Secrets in responses | **Pass** | API token, Anthropic-style key, NVIDIA-style key and a generic `*_API_KEY` env value were put in instructions, tokenize calls (HTTP and WS), bad bearer headers, bad bodies; a stand-in model echoed the key it received. Nothing appeared in task detail, history, providers, executor, health, error bodies or WS frames; the upstream echo path was confirmed exercised |
| Secrets in server log | **Partly** | Clean for everything above. **Fails** when a secret is in the URL: API-4 |
| Startup ConfigError | **Pass** | Through the real `python -m app.main`: no token, empty, 31 chars, `0.0.0.0`, `192.168.1.20`, `::`, `example.com`, `127.0.0.1.evil.example`, `*` origin (alone or in a list), port 0 / 70000 / -1 / `eighty`, rate `many` -> non-zero exit, `ConfigError`, the variable named, the token value never printed. `127.0.0.1` and `localhost` start; `MD_ALLOW_REMOTE=true` and `DEBUG=true` behave as documented (checked on `Settings`, not by binding to the LAN). Docs are 404 unless DEBUG |
| 413 on large bodies | **Partly** | 200 kB with Content-Length -> 413; absurd or malformed Content-Length (`99999999999`, `-1`, `abc`, `1e9`) -> 413/400 at once. **Chunked uploads bypass the limit: API-1** |
| Acceptance G (cancel) | **Pass** | Running task cancelled -> 200, ends `cancelled`, execution/verification stages `cancelled`, second cancel 409, unknown 404, finished 409, waiting-for-clarification 409. With a connected executor: cancel reaches `executor.cancel`, the executor sees `is_cancelled`, status `cancelled` |
| Acceptance H (executor disconnected) | **Pass** | `GET /executor` and `/health` say disconnected; 3 tasks end `validated_no_executor`; `execute()` never called. Connected then disconnected: the first runs and completes, the next does not run. Executor dropping mid-run (ExecutorError) -> `failed`, safe message. Executor raising any other exception: **API-2** |

## 4. Defects (route to Pam; repros run from `munder_difflin/`, venv with fastapi, uvicorn, httpx)

| ID | Severity | Defect | Repro and observed | Expected / suggestion |
|---|---|---|---|---|
| API-1 | **Medium** (loopback only) | Request body is read and JSON-parsed **before** the auth check, and the 128 KB cap checks only `Content-Length` | `POST /api/v1/tasks` with **no token**, `Transfer-Encoding: chunked`, 100 MiB of `a`: server takes 0.36 s, RSS 53 -> 254 MB, answers **422** (JSON decode error). Same with a valid token. Unauthenticated `POST` with the body `not json` -> 422, not 401. (Valid JSON bodies do get 401.) Tests: `test_chunked_body_over_the_limit_is_also_refused[True/False]`, `test_unauthenticated_post_with_invalid_body_gets_401_not_a_validation_error` | Count bytes while the body streams and refuse at 128 KB (pure ASGI middleware, not `call_next`); authenticate before parsing (an ASGI-level token check, or a route class that checks auth first) |
| API-2 | **Medium** | `TaskManager.run` catches only `ExecutorError` from `executor.execute`; any other exception escapes the background task | Executor whose `execute()` raises `RuntimeError`: `GET /tasks/{id}` stays `executing` forever (still `executing` after 5 s; never becomes `failed`). The real ROS executor (Andy) will have such bugs. Test: `test_H_executor_bug_does_not_leave_the_task_executing_forever` | `except Exception` -> status `failed`, `error: "internal error (<Type>)"`, same as the pipeline branch just above it |
| API-3 | **Low-Medium** | Failed WebSocket authentications are counted (`guard.failures.hit`) but the result is never used, so there is no lockout on `/ws` | 40 consecutive wrong tokens over `/ws/pipeline`: every one answered 4401 (HTTP locks out after 20). A 43-character random token is not guessable in practice, so this is defence in depth. Test: `test_repeated_failed_ws_logins_are_rate_limited_like_http` | Before accepting, check the failure budget for the client and refuse/close (1008) when exceeded; keep the valid token usable as on HTTP |
| API-4 | **Low-Medium** | uvicorn's access log is not covered by the redaction filter (`install_log_redaction` only touches root-logger handlers) | `GET /api/v1/executor?access_token=<valid token>` -> the full token is in the server log (`... "GET /api/v1/executor?access_token=... HTTP/1.1" 200 OK`). Same for `GET /api/v1/tasks/<nvapi-style key>` -> 404 line with the key. Only happens if a client puts a secret in the URL, but then it is in the log. Test: `test_credentials_in_the_url_do_not_reach_the_server_log` | Run uvicorn with `access_log=False`, or attach `RedactingFilter` to the `uvicorn.access` logger/handlers, or log method + status only |

## 5. Observations (not defects, for Pam/Jim/Dwight)
- `MD_API_TOKEN` is checked for length only: 32 x `a` and 32 spaces both start the service (the spaces token can never be presented, because the header value is stripped). Consider a minimum-entropy check or a `secrets.token_urlsafe`-style format.
- `MD_TASK_RATE_PER_MIN=0` or `-5` is accepted and makes every submit return 429. Should be a ConfigError.
- Unauthenticated WebSocket sockets count toward the 10-connection cap for up to 5 s, so another local process can keep the UI out by opening 10 idle sockets repeatedly. Bound to loopback, so low risk.
- The WS auth timeout closes with 1008, the report says 4401.
- Latent, for the real executor: `max(abs(v) for v in velocities)` ignores a NaN that comes after a 0.0 (`max([0.0, nan]) == 0.0`). `SimulatedExecutor` cannot hit it, but a read-back from `/joint_states` that contains NaN must be treated as unverified, not as the max of the finite ones.
- A task accepted while the executor is disconnected returns 202 and then ends `validated_no_executor`; the request is not refused up front. That is consistent with Pam's design and nothing moves, but a UI must show that status, not "accepted".
- Task store is in memory (100 kept); lost on restart (known).

## 6. Secret scan (X4) and `.scantmp`
- `munder_difflin/.scantmp/` (fake-key fixtures from 05:52) **no longer exists**; I did not create or delete it, and nothing in my tests ever wrote there (my fixtures live in the session scratch directory). By its timestamp and contents it was a secret-scanner experiment from another agent (Pam's report suspected the same); no owner could be confirmed from the filesystem. Nothing to delete.
- The failure that remained when I ran the whole suite was different: `tests/static/test_no_secrets.py` flagged the **deliberate fake keys** in `backend/tests/test_api.py` / `test_websocket.py` (`nvapi-SECRET...`, `sk-ant-FAKE...`) and the AWS documentation example key in `.claude/skills/robotics-security/SKILL.md`. Decision: the scan now ignores a match that spells out that it is a placeholder (`fake`, `example`, `secret`, `dummy`, `placeholder`, `notreal`, `leakcheck`, `apileak`) and still fails on anything else; a self-test proves a realistic key is still flagged. This is a deliberate rule, not a skip of any directory.

## 7. Not executed / limits
- Real ROS 2 executor: e-stop under load with a real controller (SEC-013.6), real cancel latency, real disconnect detection. All executor behaviour here is from a fake with the same interface.
- No call to a real model API; the key-echo upstream is a local stand-in.
- TLS, binding to a non-loopback address (checked as config only), and multi-machine use.
- Idle timeout was tested with a 1.5 s override (the 300 s default was not waited out); the 5 s auth deadline was tested at its real value.
- `Origin` is not required on WebSocket upgrades (non-browser clients); they still need the token. By design.

## 8. Tests added (tests/ only)
`tests/api/` (new): `launcher.py` (test-only server entry with fakes), `helpers.py`, `conftest.py`, `test_api_auth_cors_limits.py`, `test_api_tasks_and_executor.py` (includes G and H), `test_api_websocket.py`, `test_api_secrets_and_startup.py`. Marker `api` added to `pytest.ini`; they need `fastapi uvicorn websockets httpx` in the venv and skip with a named reason otherwise. `tests/static/test_no_secrets.py` updated as in section 6.
Run: `python -m pytest -c tests/pytest.ini tests` (all) or `... tests/api` (live service only, about 50 s).

## 9. Re-verification of the fixes (2026-10-28, after 06:18)
| ID | Result | Evidence |
|---|---|---|
| API-1 | **Fixed** | Unauthenticated chunked upload of 100 MiB -> **401** in 0.21 s, server RSS 53 -> 53 MB (was 422 and 53 -> 254 MB). Authenticated chunked 100 MiB -> **413** in 0.09 s, RSS unchanged. Unauthenticated `not json` body -> 401. `RequestGate` runs before routing; 12 path tricks (`//api/...`, `/API/...`, `%2f`, `..`, `;x=1`, trailing slash, health look-alikes) never reach a handler without the token (401/404/405 only) |
| API-2 | **Fixed** | Executor raising `RuntimeError` -> task `failed`, `error: "internal error (RuntimeError)"`, the exception text is not leaked, e-stop and reset still work afterwards, the next task with the executor disconnected ends `validated_no_executor` |
| API-3 | **Fixed** | 30 wrong WebSocket logins: the first 20 close 4401, the rest close 1008 ("too many failed logins"); the **valid token still gets in** and HTTP still works. WebSocket and HTTP failures share one budget |
| API-4 | **Fixed** | `GET /api/v1/executor?access_token=<token>` and a key in the URL path: the secrets no longer appear in the server log, and the access line (method and path) is still logged |
| Observation: token strength | **Fixed (mostly)** | `MD_API_TOKEN` of 32 x `a`, 32 spaces, `ab` x 20, `abc123` x 8, `t` x 40 -> ConfigError naming the variable, value not echoed. Residual: a 10-character repeated pattern (`0123456789` x 4) and a low-entropy passphrase are still accepted |
| Observation: task rate | **Fixed** | `MD_TASK_RATE_PER_MIN` of 0 or -5 -> ConfigError |
| Observation: WS auth timeout code | open, cosmetic | still 1008 (the report says 4401) |
| Observation: NaN in the e-stop read-back | open, for the real executor | `max(abs(v))` skips a NaN that follows a 0.0 |

**Live-uvicorn WebSocket check (requested in MD-TEST-005).** Every WebSocket test in `tests/api/test_api_websocket.py` (41 tests) and the live-event tests drive a real `uvicorn` subprocess with a real `websockets` client, not the in-process TestClient: auth, origin, frame limits, connection cap, replay, live events, telemetry, tokenize. All pass. Pam's note that `/ws` answered 404 on real uvicorn without a WebSocket library is guarded by `test_backend_requirements_include_a_websocket_implementation` (requirements must list `websockets`, `wsproto` or `uvicorn[standard]`); I did not reproduce the 404 itself because my venv has the library installed.

Counts now: API tests 123 passed; whole suite 313 passed, 10 skipped, 1 xfailed; backend suite 287 passed, 1 skipped.
