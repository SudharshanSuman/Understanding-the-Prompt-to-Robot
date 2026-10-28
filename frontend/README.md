# Munder Difflin console (frontend)

React + TypeScript + Vite dashboard for the backend in `../backend` (REST `/api/v1`, WebSocket `/ws/pipeline`).

## Run

```bash
# 1. backend (needs MD_API_TOKEN, >= 32 chars; binds 127.0.0.1:8000)
cd ../backend && MD_API_TOKEN=<your token> .venv/bin/python -m app.main

# 2. frontend
npm ci            # exact versions from package-lock.json
npm run dev       # http://127.0.0.1:5173 (an origin the backend allows by default)
```

Open the page and enter the backend URL and the API token. The token stays in memory for that tab
only. It is never stored and never built into the bundle.

## Check and build

```bash
npm run typecheck
npm test          # vitest: stage list + tokenization panel
npm run build     # dist/, no source maps, strict CSP <meta> injected
npm run preview   # serves dist/ on 127.0.0.1:5173
npm audit
```

`VITE_API_BASE` (non-secret, default `http://127.0.0.1:8000`) sets the default backend URL and
the CSP `connect-src`. Never put a token or key in a `VITE_` variable: it would end up in the
bundle. To serve the console from another origin, add that origin to the backend's
`MD_ALLOWED_ORIGINS`.

## Desktop mode

`../desktop` wraps this same `dist/` build in Electron (see `../desktop/README.md`). There, the
preload bridge `window.mdDesktop` hands the page the backend URL and a per-launch token, and the
page connects without the Connect screen. In a normal browser the bridge is absent and nothing
changes (`src/desktop.ts`).

## Honesty rules the UI follows

- ROS-backed panels (Spatial, Motion Planning, ROS 2 Topics, Robot State, Verification) show what
  the API actually returned. Until the ROS 2 side exists, that is "ros unavailable / no executor
  connected". No mock data is shown.
- The scene view lists objects from `/environment/objects`. It is labelled a schematic with
  "No live Gazebo state". Positions are illustrative, not measured.
- An executor that is not connected shows as a warning, never as success. A run that passes the
  safety checks ends "validated no executor": the ROS 2 stages are shown as cancelled, never as
  executed.
- The e-stop shows the observed result (max joint velocity, source), not just the button press.
  "Stop NOT confirmed" is shown when the backend could not confirm the stop.
- The Algorithm tab's stage descriptions are labelled as educational.
