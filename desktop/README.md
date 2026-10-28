# Munder Difflin desktop (Electron)

A desktop window around the **same** frontend build (`../frontend/dist`). There is no second UI.
Electron starts the local backend itself, or connects to one you already run.

## Browser mode vs desktop mode

```bash
# Browser mode (unchanged): you start the backend and type its token into the page
cd backend && MD_API_TOKEN=<your token, >= 32 chars> .venv/bin/python -m app.main
cd frontend && npm ci && npm run dev            # http://127.0.0.1:5173

# Desktop mode: Electron starts the backend with a fresh token, then connects to it automatically
cd frontend && npm ci && npm run build          # desktop serves frontend/dist
cd desktop && npm ci && npm start

# Desktop mode, connecting to a backend you started yourself (loopback only; you type its token)
MD_ALLOWED_ORIGINS=app://munder MD_API_TOKEN=<token> backend/.venv/bin/python -m app.main   # in backend/
MD_DESKTOP_BACKEND_URL=http://127.0.0.1:8000 npm start                                      # in desktop/
```

Desktop settings (names only; none is a secret):

| Variable | Default | Meaning |
|---|---|---|
| `MD_DESKTOP_PYTHON` | `../backend/.venv/bin/python` | Python used to launch the backend |
| `MD_DESKTOP_BACKEND_URL` | unset (launch mode) | Connect to this loopback backend instead of launching one |
| `MD_DESKTOP_DEVTOOLS` | unset | `1` enables DevTools (development only) |

Provider keys (for example `NVIDIA_API_KEY`) reach the launched backend from your environment, as in browser mode.

## How it is locked down (SEC-015)

- **Token**: 32 random bytes made fresh at each launch. It goes to the backend in the child's
  environment (never in its command line, never in a file) and to the page through the preload
  bridge `window.mdDesktop.session()`. The main process answers only the app's own main frame. The
  page keeps the token in memory.
- **Backend**: binds `127.0.0.1` on a free port. It allows only the origin `app://munder`, Origin
  is required (`MD_REQUIRE_ORIGIN=true`), and `DEBUG` and `MD_ALLOW_REMOTE` are removed from its
  environment. It is stopped when the app quits.
- **Renderer**: `contextIsolation` on, `nodeIntegration` off, `sandbox` on (plus
  `app.enableSandbox()`), `webSecurity` on, no `<webview>`, every permission request denied, no
  menu.
- **No remote content**: pages load from `app://munder/` (a custom protocol serving
  `frontend/dist` only; path traversal returns 404). Every request to anything other than
  `app://munder` and the one backend origin is cancelled. Navigation away and new windows are
  denied.
- **CSP as an HTTP header** on every `app://` response (`script-src 'self'`, `connect-src` pinned to
  the backend, `object-src 'none'`, `frame-ancestors 'none'`). The build's `<meta>` CSP is removed
  in desktop mode, because a header-delivered policy also supports `frame-ancestors` (SEC-014.6).
- **No `--no-sandbox`**: `npm start` refuses to run with it.

## Linux sandbox setup (one-time, needs sudo)

Ubuntu 23.10+ blocks unprivileged user namespaces (`kernel.apparmor_restrict_unprivileged_userns=1`).
On those systems Electron aborts at start with *"The SUID sandbox helper binary was found, but is
not configured correctly"*. There are two fixes; pick one:

```bash
# A (recommended): an AppArmor profile that allows user namespaces for this Electron binary only.
# The path is this checkout's; change it if the repo moves. Developers do not run this: the human does.
sudo tee /etc/apparmor.d/munder-difflin-electron >/dev/null <<'P'
abi <abi/4.0>,
include <tunables/global>
profile munder-difflin-electron "/home/sudharshan/Documents/Robotic Operation with Prompt Engineering/munder_difflin/desktop/node_modules/electron/dist/electron" flags=(unconfined) {
  userns,
  include if exists <local/munder-difflin-electron>
}
P
sudo apparmor_parser -r /etc/apparmor.d/munder-difflin-electron

# B: make the helper SUID root (undone by every `npm ci`)
sudo chown root:root node_modules/electron/dist/chrome-sandbox && sudo chmod 4755 node_modules/electron/dist/chrome-sandbox
```

## Tests

```bash
npm test                    # node --test: CSP, path traversal, request filter, backend env, URL checks
npm run smoke               # launches the real app + backend with a throwaway profile; prints JSON
npm run smoke:unsandboxed   # same with Chromium's --no-sandbox, ONLY until the setup above is done
                            # prints "OS sandbox NOT verified" and marks the namespace check not verified
```

The smoke test checks these things:
- no Node globals in the page, and the bridge exposes only `session()`;
- the CSP arrives as a header, and `eval` is blocked;
- traversal, remote fetches, other localhost ports, popups and navigation away are blocked;
- one task runs end to end ("nothing was executed");
- the token is not in the DOM, web storage or any file of the profile;
- the backend stops on close;
- the renderer's seccomp filter is on and it runs in its own namespace.

The namespace check is reported "not verified" when the run used `--no-sandbox`. The smoke test
opens a real window: it needs a display (X11 or Wayland), or `xvfb-run npm run smoke` on a machine
without one.

## Packaging

Nothing is packaged or published. `electron-builder --dir` is not set up on purpose. The desktop
app needs the Python backend and its virtualenv, which an unpacked Electron build cannot carry in a
way that is offline-safe and reproducible. Adding the builder would also bring a large set of
download-at-build-time dependencies. Run from the repo with `npm start`.
