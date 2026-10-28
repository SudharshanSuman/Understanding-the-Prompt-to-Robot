# MD-DEV-008 verification: prompt-to-arm flow, scene view, replay (Tester)

**Tester:** Angela (angela-tester-t--mvr0ft79) · **Date:** 2026-10-28 · **Work:** MD-DEV-008
**Status:** PARTIAL. Step 1 (no simulation, fake executor) run. Step 2 (live RosExecutor path, demo.sh) NOT run: waiting for `hive/sim.lock` (held by Andy, MD-ROS-demo).

## Step 1: browser checks, fake executor (no sim)

**Setup:** console built from current source (`tests/ui/conftest.py` fixture, `VITE_API_BASE` = API port 18765), served on port **4174** (5173 is held by Andy's demo), backend started with `MD_ALLOWED_ORIGINS=http://127.0.0.1:4174,http://localhost:4174` and the default simulated executor (reports no telemetry, `ros unavailable`). Headless Chrome via DevTools.

**Command:**
```
MD_UI_CONSOLE_PORT=4174 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -p pytest_timeout tests/ui/test_ui_viz.py -c tests/pytest.ini -p no:cacheprovider -v
```
**Result:** `8 passed, 7 warnings in 18.04s` (the warnings are a websockets deprecation in `tests/ui/cdp.py`, not product code). Test file: `tests/ui/test_ui_viz.py`.

| Test | What it checks | Result | Observed |
|---|---|---|---|
| M1 | Flow section and scene view without telemetry | PASS | Scene text: "No live Gazebo state — ros unavailable … illustrative, not measured". No badge, no 3D canvas. |
| M2 | Submit "Pick up the red cube and place it in the storage box" | PASS | 12 tokens; `flow-token--action` (Pick, place), `--object` (red, cube), `--destination` (storage, box). 13 stage tiles. Outcome `no_executor`: "Passed the safety checks, but no executor is connected: nothing was executed". |
| M3 | "make me a sandwich on the moon" | PASS | Outcome `needs_clarification`: "nothing was sent to the robot". Interpretation tile = "Needs clarification". |
| M4 | Replay | PASS (with defect D-V1) | "Replay last run" disabled before any run. After a run it is enabled; banner "Replay of the recorded run (47%). Not live."; "Stop replay" shown. |
| M5 | Reduced motion (`Emulation.setEmulatedMedia prefers-reduced-motion: reduce`) | PASS | All 12 `.flow-token` `animation-name` = `none` (without reduce: `flow-in`). |
| M6 | Console errors, uncaught exceptions, CSP violations | PASS | `console: []`, `exceptions: []`. |
| M7 | Scene fallback when no telemetry | PASS | Same text as M1; no `.arm3d` canvas. |
| M8 | No `eval(` / `new Function(` in built JS | PASS | 0 hits in `dist/assets/*.js`. |

**Not observed in step 1:**
- The `approximate` badge on tokens: `approx: false` in every run. The condition that shows it was not hit by these prompts, so it is untested.
- The 3D arm and the "simulation telemetry" badge: need a live RosExecutor (step 2).
- The "ROS unavailable" status shown in the top bar: observed as `ROS 2 unavailable`, `GAZEBO unavailable`, `ROBOT No executor connected`.

**Evidence:** screenshots and raw values in `docs/project/viz_screenshots/`:
- `01_empty_state.png`, `02_after_submit.png`, `03_rejected_or_clarify.png`, `04_replay.png`
- `observed.json` (every value the tests read)

## Defects (sent to Pam, MD-DEV-008)

**D-V1 (functional, medium): Replay does not drive the Prompt→Arm flow.**
- What happened: during replay at 47%, the Prompt → Arm panel shows `TOKENS waiting`, `TASK not interpreted yet`, and every stage tile reads `Waiting`. The right-hand Pipeline column shows the recorded stages as SUCCESS/WARNING.
- Expected: replay repeats the recorded run in the flow panel (tokens and stage tiles), as the banner "Replay of the recorded run … Not live" implies.
- Repro: start the console (port 4174, fake executor), submit "Pick up the red cube and place it in the storage box", press "Replay last run", look at `.flow` after a few seconds.
- Evidence: `docs/project/viz_screenshots/04_replay.png`; `observed.json` key `flow_replay` (tokens `[]`, stages `[]` at 9%).

**D-V2 (wording, low): stages that never ran are labelled "Cancelled".**
- What happened: after a `needs_clarification` or `no_executor` outcome, the tiles from Structured task to Verification read "Cancelled". Nothing cancelled them.
- Expected: a neutral label such as "Not run" or "Skipped".
- Evidence: `observed.json` keys `flow_after_submit` and `flow_rejected` (stages with state `cancelled`).

## Not yet verified (step 2, after Andy releases the lock)
- Live path via `scripts/demo.sh`, RosExecutor, red cube to storage box: tokens, stage lights, outcome, 3D arm in step with Gazebo (screenshots of both).
- Replay of a real run (the arm repeats the recorded motion).
- Scene falls back to "No live Gazebo state" when the backend stops.
- `/ws/telemetry` at 5 Hz, `/telemetry`.
- Acceptance A, B, C, F, G, H, D2.
- God's question: `GET /api/v1/health` reports ros2/gazebo/moveit "unavailable" while `executor_connected` is true. Is the health check wrong?
- Pam's rebuilt `frontend/dist` (not yet rebuilt when this report was written).
