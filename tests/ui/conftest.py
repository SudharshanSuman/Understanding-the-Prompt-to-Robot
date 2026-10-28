"""Fixtures for browser tests of the React console: build the CURRENT frontend source in a temp copy (the repo's frontend/
and dist/ are never touched), serve it on the origin the backend allows by default, run a live backend, drive headless Chrome."""
import functools
import http.server
import os
import shutil
import subprocess
import threading

import pytest

from tests.api.helpers import free_port, start_server
from tests.ui.cdp import Chrome, find_chrome

API_PORT = 18765          # baked into the build's CSP connect-src (VITE_API_BASE)
CONSOLE_PORT = int(os.environ.get("MD_UI_CONSOLE_PORT", "5173"))  # default: the origin in the backend's default allow-list; other ports need MD_ALLOWED_ORIGINS on the backend
CONSOLE = f"http://127.0.0.1:{CONSOLE_PORT}/"
API = f"http://127.0.0.1:{API_PORT}"
STATES = {"waiting", "running", "success", "warning", "failed", "cancelled", "needs_clarification"}


@pytest.fixture(scope="session", autouse=True)
def _ui_stack():
    pytest.importorskip("websockets")
    pytest.importorskip("httpx")
    if not shutil.which("npm") or not shutil.which("node"):
        pytest.skip("UI tests need node and npm")
    if not find_chrome():
        pytest.skip("UI tests need google-chrome or chromium")


@pytest.fixture(scope="session")
def seen_states():
    """Every stage state observed in the browser over the whole run (acceptance I: all 7 states appear)."""
    return set()


@pytest.fixture(scope="session")
def dist(repo_root, tmp_path_factory):
    work = tmp_path_factory.mktemp("frontend")
    shutil.copytree(repo_root / "frontend", work / "fe", ignore=shutil.ignore_patterns("node_modules", "dist"))
    env = {**os.environ, "VITE_API_BASE": API}
    for cmd in (["npm", "ci", "--no-fund", "--no-audit"], ["npm", "run", "build"]):
        r = subprocess.run(cmd, cwd=work / "fe", env=env, capture_output=True, text=True, timeout=300)
        assert r.returncode == 0, f"{' '.join(cmd)} failed:\n{r.stdout[-800:]}\n{r.stderr[-800:]}"
    return work / "fe" / "dist"


@pytest.fixture(scope="session")
def console_server(dist):
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(dist))
    handler.log_message = lambda *a, **k: None
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", CONSOLE_PORT), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield CONSOLE
    httpd.shutdown()


@pytest.fixture(scope="session")
def chrome(tmp_path_factory):
    c = Chrome(find_chrome(), tmp_path_factory.mktemp("chrome"), free_port())
    yield c
    c.stop()


@pytest.fixture
def backend(repo_root, tmp_path):
    """Factory for the live backend on the fixed API port; stopped at teardown."""
    started = []

    def factory(**kw):
        srv = start_server(repo_root, tmp_path, port=API_PORT, **kw)
        started.append(srv)
        return srv

    yield factory
    for s in started:
        s.stop()


class Console:
    """One page connected to one backend. Thin helpers over the DOM; assertions stay in the tests."""

    def __init__(self, page, srv, seen):
        self.page, self.srv, self.seen = page, srv, seen

    def connect(self, token=None):
        p = self.page
        p.goto(CONSOLE)
        p.wait_for("!!document.querySelector('#token')", desc="connect form")
        p.type_into("#token", token or self.srv.token)
        p.click("button[type=submit]")

    def connected(self, timeout=10):
        self.page.wait_for("!!document.querySelector('.header')", timeout=timeout, desc="console after connect")

    def snapshot(self) -> dict:
        d = self.page.js("""(() => {
          const stages = [...document.querySelectorAll('button.stage')].map(b => ({id: b.dataset.stage, state: b.dataset.state,
              label: b.getAttribute('aria-label'), msg: b.querySelector('.stage-msg')?.textContent || ''}));
          const t = s => document.querySelector(s)?.textContent?.trim() ?? null;
          return {stages, status: t('.panel.right h2 .status'), banner: t('.panel.right .banner'),
            chips: Object.fromEntries([...document.querySelectorAll('.chip')].map(c => [c.querySelector('.chip-label')?.textContent,
              c.querySelector('.chip-value')?.textContent ?? c.querySelector('select')?.selectedOptions[0]?.textContent])),
            estop: t('.estop-result'), clarify: t('.clarify'), error: t('.connect .error')};
        })()""")
        self.seen.update(s["state"] for s in d["stages"])
        return d

    FINAL = ["validated no executor", "needs clarification", "failed", "cancelled", "completed"]

    def press_submit(self, timeout=20):
        """Click Submit and wait until THIS task (not the previously selected one) has reached a final status."""
        p = self.page
        before = p.js("document.querySelectorAll('.history li').length")
        p.click("button.btn--primary", "Submit")
        p.wait_for(f"document.querySelectorAll('.history li').length > {before} || {before} >= 100", timeout=timeout, desc="task added to history")
        p.wait_for(f"{self.FINAL!r}.includes(document.querySelector('.panel.right h2 .status')?.textContent.trim())", timeout=timeout,
                   desc="final status")
        p.wait_for("[...document.querySelectorAll('button.stage')].every(b => b.dataset.state !== 'running')", timeout=timeout)
        p.pump(0.15)   # let the last stream frames land
        return self.snapshot()

    def submit(self, text, timeout=20):
        self.page.type_into("#cmd", text)
        assert self.page.js("document.querySelector('#cmd').value") == text
        return self.press_submit(timeout)

    def tab(self, name):
        self.page.click("button[role=tab]", name)
        return self.page.js("document.querySelector('#tabpanel').innerText")


@pytest.fixture
def make_console(chrome, console_server, seen_states):
    pages = []

    def factory(srv):
        page = chrome.page()
        pages.append(page)
        page.js("localStorage.clear(); sessionStorage.clear()") if False else None
        return Console(page, srv, seen_states)

    yield factory
    for p in pages:
        p.close()
