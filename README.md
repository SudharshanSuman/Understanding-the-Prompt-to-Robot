# Munder Difflin

Natural-language control for a simulated robot arm. You type an instruction ("Put the red cube in
the storage box"). A language model, or a deterministic fallback, turns it into a structured task.
A safety validator checks the task, and a ROS 2 executor is meant to plan and run it in Gazebo with
MoveIt 2. A web console (or the same console in an Electron window) shows every stage live.

## Honest status (2026-10-28)

| Part | State |
|---|---|
| Backend (`backend/`, FastAPI) | Runs. Bearer-token auth, rate limits, redacted logs and responses, REST + WebSocket. |
| Pipeline: input → tokenization → interpretation → clarification → validation → feasibility | Runs without ROS. A model provider is used if its key is set; otherwise the deterministic fallback is used. |
| ROS 2 stages (grounding, planning, execution, verification) | **Not available yet.** With no executor connected, a task that passes the checks ends `validated_no_executor` and the ROS stages show *cancelled*, never *executed*. |
| Telemetry, scene poses, ROS inspector | Report `ros unavailable`. The scene view is a labelled schematic, not live Gazebo state. |
| E-stop | Works against the simulated stand-in executor and reports what was observed. With a real executor it will report the real read-back. |
| Frontend (`frontend/`, React + Vite) | Runs in a browser. Typecheck, tests and build pass. |
| Desktop (`desktop/`, Electron) | Runs the same frontend build. On Ubuntu 23.10+ it needs a one-time sudo step for the Chromium sandbox (see `desktop/README.md`). |
| ROS executor (`ros2_ws/`) | In progress (Andy). The backend plugs it in through `create_app(executor=...)`. |

"Runs" above means it was started and exercised on the dev machine (Ubuntu 24.04, Python 3.12.3,
Node 20.20.2), with the test suites listed in `docs/installation.md`.

## Quick start

Setup steps are in [docs/installation.md](docs/installation.md). Once installed:

```bash
# Browser mode: two terminals
cd backend  && MD_API_TOKEN="$(python3 -c 'import secrets;print(secrets.token_urlsafe(32))')" .venv/bin/python -m app.main
cd frontend && npm run dev        # open http://127.0.0.1:5173 and paste the same token
```

Generate the token in your own shell and paste it into the page; never commit it. The backend
binds `127.0.0.1:8000` and refuses to start without a token of at least 32 characters.

```bash
# Desktop mode: Electron starts the backend with a fresh token and connects by itself
cd frontend && npm run build
cd desktop  && npm start
```

## Docs

- [docs/installation.md](docs/installation.md): venv, npm, ROS 2 packages, the human-run sudo steps
- [docs/troubleshooting.md](docs/troubleshooting.md): known problems and their fixes
- [docs/model_configuration.md](docs/model_configuration.md): language model providers and keys (Oscar)
- [docs/architecture.md](docs/architecture.md), [docs/DECISIONS.md](docs/DECISIONS.md), [docs/INTERFACE_CONTRACTS.md](docs/INTERFACE_CONTRACTS.md)
- `frontend/README.md`, `desktop/README.md`: per-app details
