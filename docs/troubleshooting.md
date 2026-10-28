# Troubleshooting

Each entry was seen on the dev machine (Ubuntu 24.04) unless it says otherwise.

## Backend

**`/ws/pipeline` or `/ws/telemetry` returns 404 while REST works.**
uvicorn has no WebSocket library installed, so it answers WebSocket upgrades as plain HTTP and
nothing matches. Install from the lock file, which includes `websockets`:
`.venv/bin/pip install --require-hashes --no-deps -r requirements.lock`. Check with
`.venv/bin/python -c "import websockets"`.

**The backend exits at start-up with `ConfigError: MD_API_TOKEN ...`.**
The token is missing or shorter than 32 characters. `MD_BIND_HOST` must be a loopback address
unless `MD_ALLOW_REMOTE=true`. `MD_ALLOWED_ORIGINS='*'` needs `DEBUG=true`. The error names the
variable, never its value.

**Every request gets 401, then 429.**
The token in the page differs from the backend's. After 20 failures a minute from one client,
HTTP answers 429 and WebSocket logins close with 1008. The right token keeps working; wait a
minute or restart the backend.

**413 "request body too large".**
Bodies over 128 KB are refused, including chunked uploads. Instructions are capped well below that.

**A task ends `validated_no_executor`.**
Expected without ROS. The task passed the safety checks, but no executor is connected, so nothing
moved. The ROS stages show *cancelled*.

## Browser console

**"Cannot reach the backend" or a CORS error.**
Serve the console from `http://127.0.0.1:5173` or `http://localhost:5173` (the default allow-list),
or add your origin to `MD_ALLOWED_ORIGINS`.

**Port 5173 already in use.**
An old `vite preview` (or a UI test run) is still holding it. Stop that process by its PID. Do not
use `pkill -f`: it matches its own shell as well.

## Desktop (Electron)

**Electron aborts: "The SUID sandbox helper binary was found, but is not configured correctly".**
Ubuntu 23.10+ sets `kernel.apparmor_restrict_unprivileged_userns=1`, which blocks Chromium's
namespace sandbox. Fix it once with the AppArmor profile in `desktop/README.md` (**human, sudo**).
Do not use `--no-sandbox`: the app refuses it. `npm run smoke:unsandboxed` exists only for testing
before the fix; its output says "OS sandbox NOT verified".

**The desktop window says the backend is unavailable.**
Launch mode runs `../backend/.venv/bin/python -m app.main`, so the backend venv must exist
(installation §1). Set `MD_DESKTOP_PYTHON` to use another interpreter.

## GPU

**`nvidia-smi: command not found`; CUDA is unavailable.**
The kernel uses `nouveau` and no NVIDIA driver is installed (audit, 2026-10-28). Nothing in the
backend or console needs CUDA, and Gazebo falls back to Mesa rendering. Installing the driver is an
optional, human-run step with a reboot (installation §5). Local CUDA model inference is not
available until then.
