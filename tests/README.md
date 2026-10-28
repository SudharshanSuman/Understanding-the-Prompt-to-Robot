# tests/

Plan and pass criteria: `docs/project/TEST_PLAN.md`. Layers: L0 unit (default), L1 `ros`, L2 `gazebo`.

    python3 -m venv /tmp/md-test-venv && /tmp/md-test-venv/bin/pip install pytest pytest-timeout -r backend/requirements.txt   # any venv outside the repo works
    pytest -c tests/pytest.ini tests -m unit          # L0
    source /opt/ros/jazzy/setup.bash && pytest -c tests/pytest.ini tests -m "ros and not gazebo"   # L1
    MD_RUN_GAZEBO=1 pytest -c tests/pytest.ini tests -m gazebo                                     # L2

Always read the skip summary (`-ra` is on). A skip means NOT verified.
Backend contract assumptions the tests depend on: `tests/support/adapter.py` (CA-1..CA-6).

## Live API tests (tests/api)
They start a real `uvicorn` per scenario on a random free port, so the venv needs `fastapi uvicorn websockets httpx` in addition to the backend requirements (`pip install fastapi uvicorn websockets` inside the venv only). Without them the whole folder is skipped with a named reason. Run just these with `python -m pytest -c tests/pytest.ini tests/api` (about 50 s). `tests/api/launcher.py` is test-only: it builds the real app and swaps in a fake executor or a slow fake provider through environment variables; it is never imported by the product.

## Browser tests of the React console (tests/ui)
They build the current `frontend/` source in a temp copy (`npm ci` + `npm run build`, needs node 20+, npm and the registry or its cache), serve it on `127.0.0.1:5173`, start a live backend on `127.0.0.1:18765` and drive headless Chrome over the DevTools protocol (`google-chrome` or `chromium` on PATH; the only Python package needed is `websockets`). The repo's `frontend/` and `dist/` are never touched. Screenshots land in `tests/reports/frontend/`. Run `python -m pytest -c tests/pytest.ini tests/ui` (about 25 s). Ports 5173 and 18765 must be free.
