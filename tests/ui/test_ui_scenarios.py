"""MD-TEST-005: browser scenarios that need a different backend: a slow model (running state, Stop button, provider selector),
an e-stop that cannot be confirmed, and the built bundle itself (source maps, secrets, CSP)."""
import re

import pytest

from tests.ui.conftest import API_PORT, CONSOLE, STATES, Console
from tests.ui.test_ui_console import SHOTS

pytestmark = [pytest.mark.ui, pytest.mark.unit, pytest.mark.filterwarnings("ignore::DeprecationWarning")]


@pytest.fixture
def slow_console(backend, chrome, console_server, seen_states):
    srv = backend(MD_TEST_PROVIDERS="slow", MD_TEST_SLOW_SECONDS="3", MD_TEST_AUTH_FAILS="1000")
    c = Console(chrome.page(), srv, seen_states)
    c.connect()
    c.connected()
    yield c
    c.page.close()


def test_running_state_and_stop_button_cancel_a_task_in_flight(slow_console):
    c = slow_console
    c.page.type_into("#cmd", "Move the red cube to the platform")
    assert c.page.js("document.querySelector('button.btn[title=\"Cancel the running task\"]').disabled") is True, "Stop must be off with no task"
    c.page.click("button.btn--primary", "Submit")
    c.page.wait_for("document.querySelector('button.stage[data-stage=interpretation]')?.dataset.state === 'running'", timeout=8,
                    desc="interpretation running (the slow model call)")
    snap = c.snapshot()
    running = [s["id"] for s in snap["stages"] if s["state"] == "running"]
    assert running == ["interpretation"], running
    assert c.page.js("document.querySelector('button.btn[title=\"Cancel the running task\"]').disabled") is False
    c.page.screenshot(SHOTS / "09-running.png")
    c.page.click("button.btn", "Stop")
    c.page.wait_for("document.querySelector('.panel.right h2 .status')?.textContent.trim() === 'cancelled'", timeout=12, desc="cancelled")
    c.page.wait_for("[...document.querySelectorAll('button.stage')].every(b => b.dataset.state !== 'running')", timeout=8)
    final = c.snapshot()
    states = [s["state"] for s in final["stages"]]
    assert final["status"] == "cancelled" and "validated" not in final["status"]
    assert states[-8:] == ["cancelled"] * 8 and "success" not in states[3:], states
    assert c.page.js("document.querySelector('button.btn[title=\"Cancel the running task\"]').disabled") is True
    assert final["banner"] is None, "a cancelled task must not show the 'passed the safety checks' banner"
    c.page.screenshot(SHOTS / "10-cancelled.png")


def test_provider_dropdown_switches_to_the_fallback_and_the_task_uses_it(slow_console):
    c = slow_console
    c.page.js("""(() => { const s = document.querySelector('select[aria-label="AI provider"]'); 
        const set = Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, 'value').set; set.call(s, 'fallback');
        s.dispatchEvent(new Event('change', {bubbles: true})); })()""")
    c.page.wait_for("document.querySelector('select[aria-label=\"AI provider\"]').value === 'fallback'", desc="selected provider shown")
    snap = c.submit("Move the red cube to the platform", timeout=10)    # no 3 s model wait: the slow provider is bypassed
    assert snap["status"] == "validated no executor"
    assert "provider set to fallback" in c.tab("Logs")


def test_estop_that_cannot_be_confirmed_is_shown_as_not_confirmed(backend, chrome, console_server, seen_states):
    srv = backend(MD_TEST_EXECUTOR="stuck", MD_TEST_AUTH_FAILS="1000")
    c = Console(chrome.page(), srv, seen_states)
    try:
        c.connect()
        c.connected()
        c.page.click("button.btn--estop")
        c.page.wait_for("!!document.querySelector('.estop-result')", desc="e-stop result")
        text = c.snapshot()["estop"]
        assert text.startswith("Stop NOT confirmed"), text
        assert "0.5 rad/s" in text and "Stop observed" not in text
        assert c.page.js("document.querySelector('.estop-result').classList.contains('is-bad')")
        c.page.wait_for("document.querySelector('.chip--error .chip-value')?.textContent.startsWith('E-stop latched')", desc="still latched")
        logs = c.tab("Logs")
        assert "e_stop_unverified" in logs and "e_stop_confirmed" not in logs
        c.page.screenshot(SHOTS / "11-estop-not-confirmed.png")
    finally:
        c.page.close()


# --- the built bundle -----------------------------------------------------------------------------------------------------
SECRET_PATTERNS = [r"\bsk-[A-Za-z0-9_-]{24,}", r"\bnvapi-[A-Za-z0-9_-]{20,}", r"\bAKIA[0-9A-Z]{16}\b", r"-----BEGIN [A-Z ]*PRIVATE KEY-----",
                   r"(?i)bearer\s+[A-Za-z0-9_-]{30,}", r"(?i)api[_-]?token\s*[:=]\s*[\"'][A-Za-z0-9_-]{16,}"]


def _dist_files(root):
    return [p for p in root.rglob("*") if p.is_file()]


@pytest.mark.parametrize("where", ["fresh-build", "committed-dist"])
def test_dist_has_no_source_maps_secrets_or_stray_files(dist, repo_root, where):
    root = dist if where == "fresh-build" else repo_root / "frontend" / "dist"
    if not root.exists():
        pytest.skip("no committed dist/ in this checkout")
    files = _dist_files(root)
    assert files, root
    assert not [p for p in files if p.suffix == ".map"], "source maps shipped"
    assert {p.suffix for p in files} <= {".html", ".js", ".css", ".svg", ".png", ".ico"}, {p.suffix for p in files}
    for p in files:
        text = p.read_text(errors="ignore")
        assert "sourceMappingURL" not in text, p.name
        for rx in SECRET_PATTERNS:
            assert not re.search(rx, text), f"{p.name} matches a secret pattern ({rx[:20]})"
        assert "/home/" not in text and "sudharshan" not in text, f"{p.name} leaks a local path"


def test_bundle_never_touches_browser_storage(dist):
    js = "\n".join(p.read_text(errors="ignore") for p in dist.rglob("*.js"))
    for api in ("localStorage", "sessionStorage", "indexedDB", "document.cookie"):
        assert api not in js, f"bundle references {api}: the token must stay in memory"


def test_csp_is_strict_and_only_allows_the_backend(dist):
    html = (dist / "index.html").read_text()
    m = re.search(r'http-equiv="Content-Security-Policy" content="([^"]+)"', html)
    assert m, "no CSP meta in the production build"
    policy = dict(part.strip().split(" ", 1) for part in m.group(1).split(";") if part.strip())
    assert policy["default-src"] == "'self'" and policy["script-src"] == "'self'" and policy["object-src"] == "'none'"
    assert "unsafe-inline" not in m.group(1) and "unsafe-eval" not in m.group(1) and "*" not in m.group(1)
    assert policy["connect-src"].split() == ["'self'", f"http://127.0.0.1:{API_PORT}", f"ws://127.0.0.1:{API_PORT}"]
    assert policy["form-action"] == "'none'" and policy["base-uri"] == "'none'"
    assert 'name="referrer" content="no-referrer"' in html


def test_the_page_really_runs_under_that_csp_without_violations(chrome, console_server, backend, seen_states):
    srv = backend(MD_TEST_AUTH_FAILS="1000")
    c = Console(chrome.page(), srv, seen_states)
    try:
        c.page.call("Page.addScriptToEvaluateOnNewDocument", source="window.__csp = []; "
                    "document.addEventListener('securitypolicyviolation', e => window.__csp.push(e.violatedDirective + ' ' + e.blockedURI))")
        c.connect()
        c.connected()
        c.submit("Move the red cube to the platform")
        assert c.page.js("window.__csp") == []
        assert not c.page.exceptions, c.page.exceptions
    finally:
        c.page.close()


# --- keep last: acceptance I wants all 7 states visible --------------------------------------------------------------------
def test_zz_every_one_of_the_seven_states_was_rendered_in_the_browser(seen_states):
    missing = STATES - seen_states
    assert not missing, f"states never rendered: {sorted(missing)} (seen {sorted(seen_states)})"


# --- E-STOP must stay usable (safety control; defect UI-2, fixed, kept as a permanent regression test) --------------------------
def test_estop_works_while_a_task_submit_is_in_flight(backend, chrome, console_server, seen_states):
    srv = backend(MD_TEST_AUTH_FAILS="1000")
    c = Console(chrome.page(), srv, seen_states)
    try:
        c.connect()
        c.connected()
        # make POST /tasks hang for 4 s on the page side (a slow network or a busy backend)
        c.page.js("""(() => { const real = window.fetch; window.fetch = (u, o) => (o && o.method === 'POST' && String(u).endsWith('/api/v1/tasks'))
            ? new Promise(r => setTimeout(() => r(real(u, o)), 4000)) : real(u, o); })()""")
        c.page.type_into("#cmd", "Move the red cube to the platform")
        c.page.click("button.btn--primary", "Submit")
        c.page.pump(0.5)
        assert c.page.js("document.querySelector('button.btn--primary').disabled") is True, "test premise: the submit must still be pending"
        assert c.page.js("document.querySelector('button.btn--estop').disabled") is False, "E-STOP is disabled while a submit is pending"
        c.page.click("button.btn--estop")
        c.page.wait_for("!!document.querySelector('.estop-result')", desc="e-stop result while the submit is still pending", timeout=3)
        assert c.page.js("document.querySelector('button.btn--primary').disabled") is True, "the e-stop result must arrive before the slow submit finishes"
        text = c.snapshot()["estop"]
        assert text.startswith("Stop observed"), text
        c.page.wait_for("document.querySelector('.chip--error .chip-value')?.textContent.startsWith('E-stop latched')", desc="latched")
        c.page.screenshot(SHOTS / "22-estop-during-pending-submit.png")
    finally:
        c.page.close()
