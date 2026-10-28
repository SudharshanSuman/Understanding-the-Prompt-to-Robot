"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const path = require("node:path");
const lib = require("../lib.cjs");

const API = "http://127.0.0.1:41234";

test("token is per call, url-safe and long enough for the backend", () => {
  const a = lib.newToken();
  assert.match(a, /^[A-Za-z0-9_-]{43}$/);
  assert.notEqual(a, lib.newToken());
});

test("only loopback http(s) backends are accepted", () => {
  assert.equal(lib.parseBackendUrl("http://127.0.0.1:8000"), "http://127.0.0.1:8000");
  assert.equal(lib.parseBackendUrl("http://localhost:8000/"), "http://localhost:8000");
  for (const bad of ["http://10.0.0.5:8000", "https://example.com", "file:///etc/passwd", "ws://127.0.0.1:1",
    "http://user:pw@127.0.0.1:8000", "http://127.0.0.1:8000/api", "http://127.0.0.1.evil.com", "nonsense"]) {
    assert.equal(lib.parseBackendUrl(bad), null, bad);
  }
});

test("CSP header pins connect-src to the one backend and blocks the rest", () => {
  const csp = lib.buildCsp(API);
  assert.match(csp, /default-src 'self'/);
  assert.match(csp, /script-src 'self'(;|$)/);
  assert.match(csp, /connect-src 'self' http:\/\/127\.0\.0\.1:41234 ws:\/\/127\.0\.0\.1:41234;/);
  assert.match(csp, /object-src 'none'/);
  assert.match(csp, /frame-ancestors 'none'/);
  assert.doesNotMatch(csp, /unsafe-inline|unsafe-eval|\*/);
});

test("the build's meta CSP is stripped, the rest of the page kept", () => {
  const html = '<head>\n    <meta http-equiv="Content-Security-Policy" content="default-src \'self\'" />\n<title>x</title>';
  assert.equal(lib.stripMetaCsp(html), "<head>\n<title>x</title>");
});

test("app:// paths cannot escape the frontend build", () => {
  const root = path.resolve("/srv/dist");
  assert.equal(lib.resolveInside(root, "/"), path.join(root, "index.html"));
  assert.equal(lib.resolveInside(root, "/assets/a.js"), path.join(root, "assets/a.js"));
  for (const bad of ["/../secret", "/%2e%2e/secret", "/assets/../../x", "/%E0%A4%A", "/a%00b", "/.."]) {
    assert.equal(lib.resolveInside(root, bad), null, bad);
  }
});

test("only the app and the backend origin may be requested", () => {
  assert.ok(lib.requestAllowed("app://munder/index.html", API));
  assert.ok(lib.requestAllowed(`${API}/api/v1/health`, API));
  assert.ok(lib.requestAllowed("ws://127.0.0.1:41234/ws/pipeline", API));
  assert.ok(lib.requestAllowed("data:image/svg+xml,<svg/>", API));
  assert.ok(!lib.requestAllowed("data:text/html,<script>1</script>", API));
  assert.ok(!lib.requestAllowed("data:application/javascript,1", API));
  for (const bad of ["https://example.com/", "http://127.0.0.1:8001/", "app://other/x", "file:///etc/passwd",
    "devtools://devtools/x", "not a url"]) {
    assert.equal(lib.requestAllowed(bad, API), false, bad);
  }
});

test("backend child env: loopback, this origin only, origin required, debug and remote dropped", () => {
  const env = lib.backendEnv({ PATH: "/bin", DEBUG: "true", MD_ALLOW_REMOTE: "true", MD_BIND_HOST: "0.0.0.0",
    MD_ALLOWED_ORIGINS: "*", NVIDIA_API_KEY: "kept" }, { token: "t".repeat(43), port: 41234 });
  assert.equal(env.MD_BIND_HOST, "127.0.0.1");
  assert.equal(env.APP_PORT, "41234");
  assert.equal(env.MD_ALLOWED_ORIGINS, "app://munder");
  assert.equal(env.MD_REQUIRE_ORIGIN, "true");
  assert.equal(env.MD_API_TOKEN, "t".repeat(43));
  assert.equal(env.DEBUG, undefined);
  assert.equal(env.MD_ALLOW_REMOTE, undefined);
  assert.equal(env.NVIDIA_API_KEY, "kept"); // provider keys still reach the backend, by name, from the user's env
  assert.equal(env.PATH, "/bin");
});
