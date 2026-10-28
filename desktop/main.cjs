// Electron main process: serves the frontend build over app://, launches (or connects to) the local
// backend, and hands the per-launch token to the page through the preload bridge. See README.md.
"use strict";

const { app, BrowserWindow, Menu, dialog, ipcMain, protocol, session } = require("electron");
const { spawn } = require("node:child_process");
const fs = require("node:fs/promises");
const net = require("node:net");
const path = require("node:path");
const lib = require("./lib.cjs");

const FRONTEND_DIST = path.resolve(__dirname, "../frontend/dist");
const BACKEND_DIR = path.resolve(__dirname, "../backend");
const HEALTH_TIMEOUT_MS = 20_000;
const SANDBOX_OFF_SWITCHES = ["--no-sandbox", "--disable-seccomp-filter-sandbox", "--no-zygote-sandbox"];

// Must run before `ready`: app:// is a standard, secure origin (app://munder) the backend can allow-list.
protocol.registerSchemesAsPrivileged([
  { scheme: lib.APP_SCHEME, privileges: { standard: true, secure: true, supportFetchAPI: true } },
]);
app.enableSandbox();

let backend = null; // child process when we launched it
let current = null; // { apiBase, token }: token is null in connect mode (user enters it)

function freePort() {
  return new Promise((resolve, reject) => {
    const srv = net.createServer();
    srv.unref();
    srv.on("error", reject);
    srv.listen(0, "127.0.0.1", () => {
      const { port } = srv.address();
      srv.close(() => resolve(port));
    });
  });
}

async function waitForHealth(apiBase, child) {
  const deadline = Date.now() + HEALTH_TIMEOUT_MS;
  while (Date.now() < deadline) {
    if (child.exitCode !== null || child.signalCode !== null) throw new Error(`backend exited (${child.exitCode ?? child.signalCode})`);
    try {
      const res = await fetch(`${apiBase}/api/v1/health`);
      if (res.ok) return;
    } catch { /* not listening yet */ }
    await new Promise((r) => setTimeout(r, 200));
  }
  throw new Error(`backend did not answer ${apiBase}/api/v1/health within ${HEALTH_TIMEOUT_MS / 1000} s`);
}

async function launchBackend() {
  const python = process.env.MD_DESKTOP_PYTHON || path.join(BACKEND_DIR, ".venv/bin/python");
  const port = await freePort();
  const token = lib.newToken();
  const apiBase = `http://127.0.0.1:${port}`;
  // The token goes to the child through its environment only: never argv (visible in ps), never a file.
  const child = spawn(python, ["-m", "app.main"], {
    cwd: BACKEND_DIR, env: lib.backendEnv(process.env, { token, port }), stdio: ["ignore", "pipe", "pipe"],
  });
  child.on("error", (err) => console.error(`[backend] failed to start: ${err.message}`));
  for (const stream of [child.stdout, child.stderr]) {
    stream.on("data", (chunk) => process.stderr.write(`[backend] ${chunk}`)); // backend logs are redacted
  }
  backend = child;
  await waitForHealth(apiBase, child);
  return { apiBase, token };
}

function stopBackend() {
  if (!backend || backend.exitCode !== null) return;
  const child = backend;
  child.kill("SIGTERM");
  setTimeout(() => { if (child.exitCode === null) child.kill("SIGKILL"); }, 3000).unref();
}

async function backendSession() {
  const external = process.env.MD_DESKTOP_BACKEND_URL;
  if (!external) return launchBackend();
  const apiBase = lib.parseBackendUrl(external);
  if (!apiBase) throw new Error("MD_DESKTOP_BACKEND_URL must be an http(s) URL on a loopback address");
  return { apiBase, token: null };
}

function lockDown(apiBase) {
  const csp = lib.buildCsp(apiBase);
  protocol.handle(lib.APP_SCHEME, async (req) => {
    const url = new URL(req.url);
    const file = url.host === lib.APP_HOST ? lib.resolveInside(FRONTEND_DIST, url.pathname) : null;
    let body;
    try { body = file && await fs.readFile(file); } catch { body = null; }
    if (!body) return new Response("not found", { status: 404, headers: { "content-security-policy": csp } });
    if (path.basename(file) === "index.html") body = lib.stripMetaCsp(body.toString("utf8"));
    return new Response(body, {
      headers: {
        "content-type": lib.mimeType(file),
        "content-security-policy": csp,
        "x-content-type-options": "nosniff",
        "cache-control": "no-store",
      },
    });
  });

  const ses = session.defaultSession;
  ses.webRequest.onBeforeRequest((details, cb) => cb({ cancel: !lib.requestAllowed(details.url, apiBase) }));
  ses.setPermissionRequestHandler((_wc, _perm, cb) => cb(false));
  ses.setPermissionCheckHandler(() => false);

  ipcMain.handle("md:session", (event) => {
    const frame = event.senderFrame;
    if (!frame || frame !== event.sender.mainFrame || !frame.url.startsWith(`${lib.APP_ORIGIN}/`)) {
      throw new Error("refused");
    }
    return { apiBase: current.apiBase, token: current.token };
  });
}

app.on("web-contents-created", (_e, wc) => {
  wc.setWindowOpenHandler(() => ({ action: "deny" }));
  const stayInApp = (e, url) => { if (!url.startsWith(`${lib.APP_ORIGIN}/`)) e.preventDefault(); };
  wc.on("will-navigate", stayInApp);
  wc.on("will-redirect", stayInApp);
  wc.on("will-attach-webview", (e) => e.preventDefault());
});

function createWindow() {
  const win = new BrowserWindow({
    width: 1600, height: 1000, show: false, backgroundColor: "#0f1115", title: "Munder Difflin",
    webPreferences: {
      preload: path.join(__dirname, "preload.cjs"),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
      webSecurity: true,
      allowRunningInsecureContent: false,
      webviewTag: false,
      spellcheck: false,
      devTools: process.env.MD_DESKTOP_DEVTOOLS === "1",
    },
  });
  win.once("ready-to-show", () => win.show());
  void win.loadURL(`${lib.APP_ORIGIN}/index.html`);
  return win;
}

/** Start the app. `allowNoOsSandbox` exists for the smoke test only (see test/smoke.cjs). */
async function start({ allowNoOsSandbox = false } = {}) {
  // Chromium consumes these switches, so app.commandLine.hasSwitch() does not see them: read argv.
  if (!allowNoOsSandbox && process.argv.some((a) => SANDBOX_OFF_SWITCHES.includes(a))) {
    console.error("Refusing to run with --no-sandbox. See desktop/README.md (Linux sandbox setup).");
    app.exit(1);
    return null;
  }
  app.on("window-all-closed", () => app.quit());
  app.on("will-quit", stopBackend);
  process.on("exit", stopBackend);
  await app.whenReady();
  Menu.setApplicationMenu(null);
  try {
    current = await backendSession();
  } catch (err) {
    dialog.showErrorBox("Munder Difflin: backend unavailable", String(err.message ?? err));
    stopBackend();
    app.exit(1);
    return null;
  }
  lockDown(current.apiBase);
  return { win: createWindow(), apiBase: current.apiBase, token: current.token, backend };
}

module.exports = { start };
