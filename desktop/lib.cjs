// Pure helpers for the Electron main process; no Electron imports, so `node --test` can cover them.
"use strict";

const crypto = require("node:crypto");
const path = require("node:path");

const APP_SCHEME = "app";
const APP_HOST = "munder";
const APP_ORIGIN = `${APP_SCHEME}://${APP_HOST}`;

const MIME = {
  ".html": "text/html; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".svg": "image/svg+xml",
  ".png": "image/png",
  ".ico": "image/x-icon",
  ".json": "application/json",
  ".woff2": "font/woff2",
};

/** Per-launch API token: 32 random bytes, kept in memory only (backend needs >= 32 chars). */
function newToken() {
  return crypto.randomBytes(32).toString("base64url");
}

function isLoopbackHost(host) {
  return host === "localhost" || host === "[::1]" || /^127(\.\d{1,3}){3}$/.test(host);
}

/** A backend URL the desktop app may talk to: plain http(s) on a loopback address, nothing else. */
function parseBackendUrl(raw) {
  let u;
  try { u = new URL(raw); } catch { return null; }
  if (!["http:", "https:"].includes(u.protocol) || !isLoopbackHost(u.hostname)) return null;
  if (u.username || u.password || (u.pathname !== "/" && u.pathname !== "")) return null;
  return u.origin;
}

function wsOrigin(apiOrigin) {
  return apiOrigin.replace(/^http/, "ws");
}

/** The CSP sent as an HTTP header on every app:// response (replaces the build's <meta> policy). */
function buildCsp(apiOrigin) {
  return [
    "default-src 'self'",
    "script-src 'self'",
    "style-src 'self'",
    "img-src 'self' data:",
    `connect-src 'self' ${apiOrigin} ${wsOrigin(apiOrigin)}`,
    "object-src 'none'",
    "base-uri 'none'",
    "form-action 'none'",
    "frame-ancestors 'none'",
  ].join("; ");
}

/** The browser build carries a <meta> CSP pinned to its build-time API URL; the header is authoritative here. */
function stripMetaCsp(html) {
  return html.replace(/\s*<meta http-equiv="Content-Security-Policy"[^>]*>/i, "");
}

/** Map an app:// path to a file under root, or null if it escapes root or is malformed. */
function resolveInside(root, urlPath) {
  let decoded;
  try { decoded = decodeURIComponent(urlPath); } catch { return null; }
  if (decoded.includes("\0")) return null;
  const rel = decoded === "/" || decoded === "" ? "index.html" : decoded.replace(/^\/+/, "");
  const base = path.resolve(root);
  const file = path.resolve(base, rel);
  return file.startsWith(base + path.sep) ? file : null;
}

function mimeType(file) {
  return MIME[path.extname(file).toLowerCase()] ?? "application/octet-stream";
}

/** Only the app's own pages and the one backend origin may be fetched; everything else is cancelled. */
function requestAllowed(rawUrl, apiOrigin) {
  if (rawUrl.startsWith("data:")) return rawUrl.startsWith("data:image/"); // matches img-src 'self' data: (SEC-015-D3)
  let u;
  try { u = new URL(rawUrl); } catch { return false; }
  if (u.protocol === `${APP_SCHEME}:`) return u.host === APP_HOST;
  return u.origin === apiOrigin || u.origin === wsOrigin(apiOrigin);
}

/** Environment for the backend child: loopback bind, this app's origin only, debug and remote off. */
function backendEnv(baseEnv, { token, port }) {
  const env = { ...baseEnv };
  for (const name of ["DEBUG", "MD_ALLOW_REMOTE", "ELECTRON_RUN_AS_NODE"]) delete env[name];
  return {
    ...env,
    MD_API_TOKEN: token,
    MD_BIND_HOST: "127.0.0.1",
    APP_PORT: String(port),
    MD_ALLOWED_ORIGINS: APP_ORIGIN,
    MD_REQUIRE_ORIGIN: "true",
    PYTHONUNBUFFERED: "1",
  };
}

module.exports = {
  APP_SCHEME, APP_HOST, APP_ORIGIN, newToken, isLoopbackHost, parseBackendUrl, buildCsp, stripMetaCsp,
  resolveInside, mimeType, requestAllowed, backendEnv,
};
