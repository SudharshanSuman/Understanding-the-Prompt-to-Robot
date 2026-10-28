// Smoke test, run as the Electron main process: `npm run smoke` (or `npm run smoke:unsandboxed`, see README).
// Launches the real app + backend with a throwaway profile, checks the security properties from the page,
// runs one task end to end, quits, then scans the profile for the token. Prints JSON; exit 0 only if all pass.
"use strict";

const { app } = require("electron");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");

const profile = fs.mkdtempSync(path.join(os.tmpdir(), "md-desktop-smoke-"));
app.setPath("userData", profile);
const { start } = require("../main.cjs");

const results = [];
const check = (name, ok, detail) => results.push({ name, ok: ok === null ? null : Boolean(ok), ...(detail === undefined ? {} : { detail }) });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function waitFor(wc, expr, ms) {
  const deadline = Date.now() + ms;
  while (Date.now() < deadline) {
    if (await wc.executeJavaScript(expr).catch(() => false)) return true;
    await sleep(200);
  }
  return false;
}

function filesUnder(dir) {
  const out = [];
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const p = path.join(dir, entry.name);
    if (entry.isDirectory()) out.push(...filesUnder(p));
    else if (entry.isFile()) out.push(p);
  }
  return out;
}

function seccompMode(pid) {
  try { return /^Seccomp:\s*(\d)/m.exec(fs.readFileSync(`/proc/${pid}/status`, "utf8"))?.[1] ?? "unknown"; }
  catch { return "unknown"; }
}

function nsOf(pid) {
  try { return fs.readlinkSync(`/proc/${pid}/ns/pid`); } catch { return "unknown"; }
}

async function run() {
  const osSandbox = !process.argv.includes("--no-sandbox");
  const started = await start({ allowNoOsSandbox: true });
  if (!started) throw new Error("app did not start");
  const { win, token, backend } = started;
  app.on("will-quit", (e) => e.preventDefault()); // keep running after the window closes; app.exit() ends it
  const wc = win.webContents;
  check("backend launched with a per-launch token", backend && typeof token === "string" && token.length >= 32);

  await new Promise((r) => (wc.isLoading() ? wc.once("did-finish-load", r) : r()));
  check("loads app://munder", wc.getURL().startsWith("app://munder/"), wc.getURL());
  check("auto-connects through the preload bridge",
    await waitFor(wc, `[...document.querySelectorAll(".chip")].length > 0`, 15000));

  const page = await wc.executeJavaScript(`(async () => ({
    require: typeof window.require, process: typeof window.process, module: typeof window.module,
    bridgeKeys: Object.keys(window.mdDesktop || {}),
    metaCsp: !!document.querySelector('meta[http-equiv="Content-Security-Policy"]'),
    headerCsp: (await fetch("/index.html")).headers.get("content-security-policy"),
    traversal: (await fetch("/../../backend/app/config.py")).status,
    external: await fetch("https://example.com/").then(() => "fetched", () => "blocked"),
    otherPort: await fetch("http://127.0.0.1:1/").then(() => "fetched", () => "blocked"),
    popup: window.open("https://example.com/") === null ? "denied" : "opened",
    inlineScript: (() => { try { return eval("1") === 1 ? "eval allowed" : "?"; } catch { return "eval blocked"; } })(),
  }))()`);
  check("no Node globals in the page", page.require === "undefined" && page.process === "undefined" && page.module === "undefined", page);
  check("bridge exposes only session()", JSON.stringify(page.bridgeKeys) === '["session"]', page.bridgeKeys);
  check("CSP comes as an HTTP header, meta CSP removed", !page.metaCsp && /connect-src 'self' http:\/\/127\.0\.0\.1:\d+ ws:/.test(page.headerCsp ?? ""), page.headerCsp);
  check("eval blocked by CSP", page.inlineScript === "eval blocked", page.inlineScript);
  check("path traversal on app:// returns 404", page.traversal === 404, page.traversal);
  check("remote fetch blocked", page.external === "blocked");
  check("other localhost port blocked", page.otherPort === "blocked");
  check("window.open denied", page.popup === "denied");

  await wc.executeJavaScript(`location.href = "https://example.com/"`).catch(() => undefined);
  await sleep(800);
  check("navigation away denied", wc.getURL().startsWith("app://munder/"), wc.getURL());

  await wc.executeJavaScript(`(() => {
    const el = document.querySelector("#cmd");
    Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value").set.call(el, "Pick up the red cube and place it in the storage box");
    el.dispatchEvent(new Event("input", { bubbles: true }));
    [...document.querySelectorAll("button")].find((b) => b.textContent.trim() === "Submit").click();
  })()`);
  check("a task runs end to end and ends 'nothing was executed'",
    await waitFor(wc, `document.body.innerText.includes("nothing was executed")`, 15000));

  const leaks = await wc.executeJavaScript(`(() => {
    const t = ${JSON.stringify(token)};
    return { dom: document.documentElement.outerHTML.includes(t),
             local: JSON.stringify({ ...localStorage }).includes(t), session: JSON.stringify({ ...sessionStorage }).includes(t) };
  })()`);
  check("token not in DOM or web storage", !leaks.dom && !leaks.local && !leaks.session, leaks);

  // Linux sandbox has two layers: seccomp-bpf syscall filtering, and namespaces (or the SUID helper).
  const renderer = wc.getOSProcessId();
  const seccomp = seccompMode(renderer);
  check("renderer seccomp-bpf filter active", seccomp === "2", `Seccomp: ${seccomp}`);
  const ownNs = nsOf("self") !== nsOf(renderer);
  check("renderer in its own PID/user namespace (namespace sandbox layer)", osSandbox ? ownNs : null,
    osSandbox ? { ownNamespace: ownNs } : "OS sandbox NOT verified: this run used --no-sandbox, so the namespace layer is off (Linux sandbox setup in README not done)");

  const exited = new Promise((r) => (backend.exitCode !== null ? r() : backend.once("exit", r)));
  win.close();
  await Promise.race([exited, sleep(5000)]);
  check("backend stopped when the app closed", backend.exitCode !== null || backend.signalCode !== null);

  await sleep(500); // let Chromium flush its profile files
  const hits = filesUnder(profile).filter((f) => fs.readFileSync(f).includes(token));
  check("token never written to the profile directory", hits.length === 0, hits.map((f) => path.relative(profile, f)));
}

run().catch((err) => check("smoke run", false, String(err?.stack ?? err))).finally(() => {
  const failed = results.filter((r) => r.ok === false);
  const unverified = results.filter((r) => r.ok === null);
  if (process.argv.includes("--no-sandbox")) console.log("WARNING: OS sandbox NOT verified (run used --no-sandbox)");
  console.log(JSON.stringify({ os_sandbox: process.argv.includes("--no-sandbox") ? "NOT verified" : "on", passed: results.length - failed.length - unverified.length, failed: failed.length,
    not_verified: unverified.length, results }, null, 2));
  fs.rmSync(profile, { recursive: true, force: true });
  app.exit(failed.length ? 1 : 0);
});
