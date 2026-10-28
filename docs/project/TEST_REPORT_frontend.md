# React console verification report (MD-TEST-005)

Verifier: Angela (Tester). Target: Pam's MD-DEV-004, `frontend/` (React 19.3.1, Vite 7.3.7, TypeScript 5.9.3), as on disk on 2026-10-28 about 06:30 IST. Pam changed `Inspector.tsx`/`App.tsx` while I was testing; everything below was re-run against the code on disk at the end.
Method: the CURRENT `frontend/` source is copied to a temp directory (the repo's `frontend/` and `dist/` are never modified), built with `VITE_API_BASE` pointing at a live test backend (real uvicorn, real `create_app`), served on `http://127.0.0.1:5173` (the origin the backend allows by default) and driven in **real headless Chrome** (`google-chrome`, DevTools protocol, no mocks, no jsdom). Screenshots: `tests/reports/frontend/` (22 PNG).
Environment: Node 20.20.2, npm 10.8.2, Chrome from `/usr/bin/google-chrome`, Python 3.12 test venv (websockets 17.3). No ROS, no Gazebo.

## 1. Verdict
The console behaves as Pam's report says and, more importantly, is honest: ROS panels say "unavailable", nothing is faked as executed, the token never leaves memory, the 14 stages are in canonical order and all 7 states render. I found **two defects**: UI-1 (the "Preview tokens" button showed nothing once a task was selected; **Pam fixed it while I was testing** and I re-verified) and **UI-2: the E-STOP button was disabled while any other request was pending** (safety control). **UI-2 was fixed by Pam afterwards (`Header.tsx`/`App.tsx`) and re-verified on 2026-10-28 06:45 IST**: with `POST /tasks` held for 4 s, E-STOP is enabled, clicking it returns "Stop observed" and the latch while the submit is still pending (permanent test `test_estop_works_while_a_task_submit_is_in_flight`, screenshot `22-estop-during-pending-submit.png`). No open console defects.

## 2. Counts (real, this machine)
| Check | Command | Result |
|---|---|---|
| Install | `npm ci` (temp copy) | 151 packages, 0 vulnerabilities |
| Typecheck | `npm run typecheck` | clean |
| Unit tests | `npm test` (vitest) | **17 passed** in 5 files after the UI-1/UI-2 fixes (15 in 4 files when first run; Pam's report said 10) |
| Build | `npm run build` | OK, 40 modules, JS 251 kB (gzip 78 kB), CSS 10 kB |
| Audit | `npm audit` and `npm audit --omit=dev` | 0 vulnerabilities both |
| Browser tests | `python -m pytest -c tests/pytest.ini tests/ui` | **43 passed**, 0 xfailed (final, after UI-2 fix) |
| Whole suite | `python -m pytest -c tests/pytest.ini tests` (run twice, identical) | **314 passed, 10 skipped (ROS/Gazebo)**, 0 failed, 0 xfailed, about 71 s (final run; the earlier two runs were 313 passed + 1 xfailed) |

## 3. Requested checks
| Check | Result | Evidence |
|---|---|---|
| dist has no source maps | **Pass** | Fresh build and the committed `frontend/dist/`: no `.map` files, no `sourceMappingURL` in any file, `build.sourcemap=false` |
| dist has no secrets | **Pass** | Scanned both dists for key-shaped strings (`sk-`, `nvapi-`, AWS, PEM, `Bearer <long>`, `api_token = "..."`): none. No local paths or user names in the bundle. Only html/js/css files |
| Bundle never touches browser storage | **Pass** | The built JS contains no `localStorage`, `sessionStorage`, `indexedDB` or `document.cookie` |
| CSP | **Pass** | `<meta http-equiv="Content-Security-Policy">` present: `default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self' http://127.0.0.1:18765 ws://127.0.0.1:18765; object-src 'none'; base-uri 'none'; form-action 'none'`, no `unsafe-inline`/`unsafe-eval`/`*`, `referrer: no-referrer`. The page really runs under it: zero `securitypolicyviolation` events and zero uncaught exceptions over a connect + task run |
| Wrong token | **Pass** | "Token rejected (401)." shown, the console never opens, field is `type=password`, the rejected token is not printed as text. An unreachable URL says "Cannot reach the backend ..." |
| The 7 example commands | **Pass** | The 7 buttons are exactly the spec commands. In the browser: 1-4 -> *validated no executor* (plans red_cube->storage_box, blue_cube->table_right, red_cube->storage_box avoiding blue_cube, green_cylinder->platform); 5 and 6 -> *needs clarification* ("Where exactly is 'the left'?"); 7 "purple elephant" -> *failed* ("'purple_elephant' is not an object in the scene") |
| Clarification flow | **Pass** | Question shown, options are scene names only, Resume disabled until an answer is typed, option selection toggles `aria-checked`, restating the command resumes the **same task** to *validated no executor*, the panel closes, history updates |
| Cancel | **Pass** | With a 3 s model call: stage *Interpretation* shows **Running**, Stop is off before and on during, click -> *cancelled*, ROS stages cancelled, no "passed the safety checks" banner, Stop off again |
| E-stop, observed result | **Pass** | Confirmed: "Stop observed - max abs(joint velocity) 0 rad/s - simulated joint state (no ROS 2 connected)", Robot chip "E-stop latched (STOPPED)", a new submit is refused (409 shown in Logs, no task created), Reset clears the latch and says "ros unavailable" for the scene. Unverifiable stop (controller that keeps 0.5 rad/s): red "**Stop NOT confirmed** ... 0.5 rad/s", chip still latched, log shows `e_stop_unverified`, never "confirmed" |
| ROS panels honest, no mock data | **Pass** | Spatial Coordinates: "Poses reported: 0", names only, no coordinates. Motion Planning / ROS 2 Topics / Robot State / Verification: "ROS unavailable (ros unavailable) ... No live data is shown", `joint_states: null`, `gripper: null`, empty node/topic lists, "Not verified - no executor connected; nothing was executed". Scene view: "No live Gazebo state ... illustrative, not measured", object names from the scene config only. No joint angles, poses or success marks anywhere |
| 14 stages in canonical order | **Pass** | Buttons carry `data-stage` in the ADR-009 order with labels 01-14, five group headings (NL Processing, Safety Interlock, Spatial & Kinematics, Motion Planning, Simulation & Verification), the 8 ROS stages tagged "ROS 2" |
| All 7 states render | **Pass** | waiting, running (slow-model run), success, warning (rule-based fallback), failed (unknown object), cancelled (ROS stages, cancelled task), needs_clarification. The test records every state seen in the browser and fails if one is missing |
| Token never in DOM / localStorage | **Pass** | After connect, 6 tab visits and several tasks: not in `outerHTML`, `innerText`, `localStorage`, `sessionStorage`, cookies, IndexedDB, URL, resource names, console output; not in Logs. It appears only in the `Authorization` header of requests to the backend (and the WS auth message). Disconnect clears the field and the DOM. Only two hosts are ever contacted: the console and the backend |
| Acceptance D (UI) | **Pass** | Ambiguous command -> clarification panel, stages 4-14 *cancelled*, nothing runs |
| Acceptance E (UI) | **Pass** | "Pick up the purple cube ..." -> *failed*, `UNKNOWN_OBJECT purple_cube` visible in Structured JSON, fewer than 6 stages succeeded, nothing executed |
| Acceptance I (UI) | **Pass** | Tokenization panel: tokenizer name (`cl100k_base`), "Real tokenizer output" badge (an approximation would show a warning badge and `n/a` IDs), token table whose spans reslice the original text exactly, real token IDs, the note that tokenization does not decide physical action; every stage selectable with its events and data; Structured JSON, Algorithm Explanation (labelled educational) and Logs tabs |

## 4. Defects (route to Pam)
| ID | Severity | Defect | Repro and observed | Expected |
|---|---|---|---|---|
| UI-1 | Low-Medium | **Fixed during testing.** "Preview tokens" did nothing visible once a task was selected: `Inspector` preferred the selected task's tokenization over the preview | Select any task, type "Pick up the green cylinder", click Preview tokens: the table still showed the old task's tokens (`['Move','the','red','cube',...]`) | Preview shown with the "preview" label. Re-verified on the build after Pam's change; kept as a regression test |
| UI-2 | **Medium (safety control). FIXED and re-verified** | The E-STOP button is `disabled` while the shared `busy` flag is set, i.e. while **any** other request is in flight | In the page, delay `POST /api/v1/tasks` by 4 s (slow network or busy backend), submit a command: `button.btn--estop.disabled === true` for the whole time. Test: `test_estop_works_while_a_task_submit_is_in_flight` (permanent regression test, no longer an xfail) | E-STOP is never disabled by unrelated work. Use a separate in-flight flag for the e-stop request itself only |

## 5. Observations (not defects)
- With the backend's fallback-only provider every valid run ends *warning* in the Interpretation stage (shown as Warning with "interpreted by fallback"), never green; consistent with the backend.
- The scene schematic puts objects in a row; it says so. A long name (`green_cylinder`) nearly fills its box at 1600 px width.
- The WebSocket stops reconnecting after a 4401 (shows "unauthorized"); a rotated token needs a new connect. Reasonable.
- The built page needs the backend URL at build time (CSP `connect-src`). A console built for port 8000 will not talk to a backend on another port; documented in the README.
- Not executed: Firefox/Safari, touch/mobile layout, screen readers, the Electron desktop wrapper (`desktop.ts` is covered only by Pam's vitest), the real ROS-backed panels (nothing to show yet), a backend with tiktoken absent (the approximation badge was checked only in vitest).

## 6. Tests added (tests/ only)
`tests/ui/` (new): `cdp.py` (minimal DevTools-protocol driver, no browser-automation package), `conftest.py` (builds the current source in a temp copy, serves it, launches Chrome), `test_ui_console.py` (42 tests incl. all above) and `test_ui_scenarios.py` (slow model, unconfirmed e-stop, CSP, bundle hygiene, UI-2). Marker `ui`; skipped with a named reason without node/npm, google-chrome or websockets. `tests/api/helpers.py` gained a `port=` argument. `tests/static/test_no_secrets.py` also checks that `backend/requirements.txt` lists a WebSocket implementation (see `TEST_REPORT_api.md`).
Run: `python -m pytest -c tests/pytest.ini tests/ui` (about 25 s; the first run also does `npm ci` and a build, needs the npm registry or its cache).
