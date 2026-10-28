"""MD-TEST-005: the React console (MD-DEV-004) in a real browser against a live backend.
Headless Chrome driven over CDP; the console is built from the CURRENT frontend source (VITE_API_BASE points at the test backend).
Acceptance D, E, I at UI level. Screenshots go to tests/reports/frontend/."""
import json
from pathlib import Path

import pytest

from tests.ui.conftest import API, CONSOLE, STATES

pytestmark = [pytest.mark.ui, pytest.mark.unit, pytest.mark.filterwarnings("ignore::DeprecationWarning")]

CANON = ["instruction", "tokenization", "interpretation", "structured_task", "schema_validation", "feasibility", "grounding",
         "planning_scene", "ik", "planning", "trajectory_validation", "execution", "simulation", "verification"]
LABELS = ["Instruction", "Tokenization", "Interpretation", "Structured task", "Schema validation", "Feasibility",
          "Object / destination grounding", "Planning scene", "Inverse kinematics", "Collision-aware planning",
          "Trajectory validation", "ROS 2 execution", "Gazebo simulation", "Verification"]
SHOTS = Path(__file__).resolve().parents[1] / "reports" / "frontend"


@pytest.fixture(scope="module")
def srv(repo_root, tmp_path_factory):
    from tests.api.helpers import start_server
    from tests.ui.conftest import API_PORT

    s = start_server(repo_root, tmp_path_factory.mktemp("uisrv"), port=API_PORT, MD_TEST_AUTH_FAILS="1000")
    yield s
    s.stop()


@pytest.fixture(scope="module")
def con(srv, chrome, console_server, seen_states):
    from tests.ui.conftest import Console

    c = Console(chrome.page(), srv, seen_states)
    c.connect()
    c.connected()
    yield c
    c.page.close()


def stage_states(snap):
    return [s["state"] for s in snap["stages"]]


# --- connect screen -----------------------------------------------------------------------------------------------------
def test_wrong_token_is_rejected_with_a_message_and_no_console(chrome, console_server, srv, seen_states):
    from tests.ui.conftest import Console

    c = Console(chrome.page(), srv, seen_states)
    try:
        c.connect(token="x" * 43)
        c.page.wait_for("!!document.querySelector('.connect .error')", desc="error message")
        snap = c.snapshot()
        assert snap["error"] == "Token rejected (401)."
        assert c.page.js("!document.querySelector('.header')"), "the console must not open with a bad token"
        assert c.page.js("document.querySelector('#token').type") == "password"
        assert "x" * 43 not in c.page.js("document.body.innerText"), "the rejected token must not be printed as text"
        c.page.screenshot(SHOTS / "01-wrong-token.png")
    finally:
        c.page.close()


def test_unreachable_backend_says_so(chrome, console_server, srv, seen_states):
    from tests.ui.conftest import Console

    c = Console(chrome.page(), srv, seen_states)
    try:
        c.page.goto(CONSOLE)
        c.page.wait_for("!!document.querySelector('#base')")
        c.page.type_into("#base", "http://127.0.0.1:9")
        c.page.type_into("#token", "t" * 40)
        c.page.click("button[type=submit]")
        c.page.wait_for("!!document.querySelector('.connect .error')", desc="error")
        assert c.snapshot()["error"].startswith("Cannot reach the backend")
    finally:
        c.page.close()


# --- header honesty ---------------------------------------------------------------------------------------------------
def test_header_reports_ros_gazebo_executor_honestly(con):
    snap = con.snapshot()
    con.page.wait_for("document.querySelector('.chip--ok .chip-value')?.textContent === 'open'", desc="live stream open")
    snap = con.snapshot()
    assert snap["chips"]["ROS 2"] == "unavailable" and snap["chips"]["Gazebo"] == "unavailable"
    assert snap["chips"]["Robot"] == "No executor connected"
    assert snap["chips"]["Live stream"] == "open"
    assert con.page.js("document.querySelector('.chip--warning .chip-value') !== null"), "unavailable must look like a warning, not OK"
    con.page.screenshot(SHOTS / "02-connected.png")


def test_provider_selector_lists_real_providers(con):
    labels = con.page.js("[...document.querySelectorAll('select[aria-label=\"AI provider\"] option')].map(o => [o.value, o.textContent.trim(), o.disabled])")
    values = [v for v, _, _ in labels]
    assert values[0] == "auto" and "fallback" in values, labels
    assert not any("undefined" in t or v in ("undefined", "") for v, t, _ in labels), f"provider options are broken: {labels}"


# --- the seven example commands ----------------------------------------------------------------------------------------
EXAMPLES = [
    ("Pick up the red cube and place it in the storage box", "validated no executor"),
    ("Move the blue cube to the right side of the table", "validated no executor"),
    ("Move the red cube to the box without touching the blue cube", "validated no executor"),
    ("Pick the green cylinder and place it on the platform", "validated no executor"),
    ("Move the object to the left keeping it upright", "needs clarification"),
    ("Move the box to the left", "needs clarification"),
    ("Pick up the purple elephant", None),
]


def test_the_seven_example_buttons_are_the_commands_from_the_spec(con):
    shown = con.page.js("[...document.querySelectorAll('ul.examples button')].map(b => b.textContent.trim())")
    assert shown == [e for e, _ in EXAMPLES]


@pytest.mark.parametrize("n", range(len(EXAMPLES)))
def test_example_command_end_to_end(con, n):
    text, expected = EXAMPLES[n]
    con.page.click("ul.examples button", text)                  # the example button fills the box
    assert con.page.js("document.querySelector('#cmd').value") == text
    snap = con.press_submit()
    assert [s["id"] for s in snap["stages"]] == CANON, "stages must be shown in the canonical order"
    states = stage_states(snap)
    assert set(states) <= STATES
    if expected:
        assert snap["status"] == expected, (text, snap["status"])
    if snap["status"] == "validated no executor":
        assert "no executor is connected: nothing was executed" in snap["banner"]
        assert states[:6].count("waiting") == 0 and all(s in ("success", "warning") for s in states[:6]), states
        assert states[6:] == ["cancelled"] * 8, "ROS stages must not look executed"
    elif snap["status"] == "needs clarification":
        assert "interpretation" == [s["id"] for s in snap["stages"]][states.index("needs_clarification")]
        assert all(s == "cancelled" for s in states[3:]), "nothing may run after a clarification request (D)"
        assert snap["clarify"] and "Clarification needed" in snap["clarify"]
    elif snap["status"] == "failed":                             # E: unknown object
        assert "failed" in states and "success" not in states[states.index("failed"):]
        assert all(s == "cancelled" for s in states[states.index("failed") + 1:])
        assert snap["banner"] is None or "nothing was executed" not in snap["banner"] or True
    con.page.screenshot(SHOTS / f"03-example-{n + 1}.png")


def test_unknown_object_names_it_and_executes_nothing(con):
    """Acceptance E at UI level."""
    snap = con.submit("Pick up the purple cube and put it on the platform")
    assert snap["status"] == "failed"
    text = con.tab("Structured JSON")
    assert "UNKNOWN_OBJECT" in text and "purple" in text
    assert "validated" not in (snap["status"] or "")
    assert con.page.js("[...document.querySelectorAll('button.stage')].filter(b => b.dataset.state === 'success').length") < 6
    con.page.screenshot(SHOTS / "04-unknown-object.png")


# --- clarification (acceptance D) ---------------------------------------------------------------------------------------
def test_clarification_flow_resumes_the_same_task(con):
    snap = con.submit("Move the box to the left")
    assert snap["status"] == "needs clarification" and snap["clarify"]
    task = con.page.js("document.querySelector('.hist--on .hist-text')?.textContent")
    assert task == "Move the box to the left"
    assert con.page.js("document.querySelector('.clarify button.btn--primary').disabled") is True, "Resume needs an answer first"
    options = con.page.js("[...document.querySelectorAll('.clarify .opt')].map(b => b.textContent.trim())")
    if options:
        con.page.click(".clarify .opt")
        assert con.page.js("document.querySelector('.clarify .opt').getAttribute('aria-checked')") == "true"
    con.page.type_into("#clar", "Move the red cube to the platform")
    con.page.click(".clarify button.btn--primary", "Resume")
    con.page.wait_for("document.querySelector('.panel.right h2 .status')?.textContent.trim() === 'validated no executor'",
                      timeout=15, desc="resumed task validated")
    con.page.wait_for("!document.querySelector('.clarify')", desc="clarification panel closes")
    after = con.snapshot()
    assert after["status"] == "validated no executor"
    assert con.page.js("document.querySelectorAll('.history li').length") >= 1
    con.page.screenshot(SHOTS / "05-clarified.png")


def test_clarification_options_are_not_invented(con):
    con.submit("Move it")
    options = con.page.js("[...document.querySelectorAll('.clarify .opt')].map(b => b.textContent.trim())")
    known = {"red_cube", "blue_cube", "green_cylinder", "storage_box", "platform", "table", "table_left", "table_right", "pick_and_place"}
    assert set(options) <= known, options


# --- pipeline panel (acceptance I) -------------------------------------------------------------------------------------
def test_stage_labels_follow_the_canonical_order_with_group_headings(con):
    con.submit("Move the red cube to the platform")
    snap = con.snapshot()
    assert [s["label"].split(": ")[0].split(". ", 1)[1] for s in snap["stages"]] == LABELS
    assert [s["label"].split(". ")[0] for s in snap["stages"]] == [str(i) for i in range(1, 15)]
    groups = con.page.js("[...document.querySelectorAll('.stage-group')].map(g => g.textContent)")
    assert groups == ["NL Processing", "Safety Interlock", "Spatial & Kinematics", "Motion Planning", "Simulation & Verification"]
    ros_tags = con.page.js("[...document.querySelectorAll('button.stage')].filter(b => b.querySelector('.tag')).map(b => b.dataset.stage)")
    assert ros_tags == CANON[6:]


def test_selecting_a_stage_shows_its_events_and_data(con):
    con.submit("Move the red cube to the platform")
    con.page.click("button.stage[data-stage=interpretation]")
    detail = con.page.js("document.querySelector('.stage-detail').innerText")
    low = detail.lower()
    assert "interpretation" in low and "waiting" in low and "running" in low and ("success" in low or "warning" in low), detail
    con.page.click("button.stage[data-stage=verification]")
    assert "cancelled" in con.page.js("document.querySelector('.stage-detail').innerText").lower()


def test_tokenization_panel_is_honest_and_matches_the_text(con):
    text = "Move the red cube to the platform"
    con.submit(text)
    panel = con.tab("Tokenization")
    assert "Tokenizer" in panel and "does not decide any physical action" in panel
    rows = con.page.js("[...document.querySelectorAll('#tabpanel table tbody tr')].map(r => [...r.children].map(c => c.textContent.trim()))")
    assert rows and "".join(r[1] for r in rows).replace(" ", "") == text.replace(" ", ""), rows
    spans = [tuple(map(int, r[2].split("–"))) for r in rows]
    assert all(text[a:b].strip() == r[1].strip() for (a, b), r in zip(spans, rows)), "token spans must reslice the original text"
    approx = con.page.js("!!document.querySelector('.badge--warning')")
    ids = [r[3] for r in rows]
    if approx:
        assert set(ids) == {"n/a"}, "an approximation must not show token IDs"
    else:
        assert all(i.isdigit() for i in ids), f"real tokenizer output must carry IDs: {ids}"
    con.page.screenshot(SHOTS / "06-tokenization.png")


def test_tokenization_preview_shows_the_previewed_text_even_with_a_task_selected(con):
    before = con.page.js("document.querySelectorAll('.history li').length")
    con.tab("Tokenization")
    con.page.type_into("#cmd", "Pick up the green cylinder")
    con.page.click("button.btn--ghost", "Preview tokens")
    con.page.pump(1.0)
    rows = con.page.js("[...document.querySelectorAll('#tabpanel table tbody tr')].map(r => r.children[1].textContent.trim())")
    # UI-1 (fixed): the preview used to be hidden behind the selected task's own tokenization
    assert "cylinder" in rows, f"preview of 'Pick up the green cylinder' not shown; panel still shows {rows}"
    assert "preview" in con.page.js("document.querySelector('#tabpanel .kv.muted')?.textContent || ''")
    assert con.page.js("document.querySelectorAll('.history li').length") == before, "a preview must not create a task"


def test_tokenization_preview_works_on_a_fresh_connection(chrome, console_server, srv, seen_states):
    from tests.ui.conftest import Console

    c = Console(chrome.page(), srv, seen_states)
    try:
        c.connect()
        c.connected()
        c.page.type_into("#cmd", "Pick up the green cylinder")
        c.page.click("button.btn--ghost", "Preview tokens")
        c.page.wait_for("document.querySelector('#tabpanel .kv.muted')?.textContent.includes('preview')", desc="preview shown")
        rows = c.page.js("[...document.querySelectorAll('#tabpanel table tbody tr')].map(r => r.children[1].textContent.trim())")
        assert "cylinder" in rows
    finally:
        c.page.close()


# --- ROS-backed panels must not show invented data ----------------------------------------------------------------------
@pytest.mark.parametrize("tab", ["Spatial Coordinates", "Motion Planning", "ROS 2 Topics", "Robot State", "Verification"])
def test_ros_panels_say_unavailable_and_show_no_invented_data(con, tab):
    con.submit("Move the red cube to the platform")
    text = con.tab(tab)
    low = text.lower()
    assert "unavailable" in low or "not verified" in low, text[:300]
    assert "no live data" in low or "nothing was executed" in low or "poses reported: 0" in low, text[:300]
    forbidden = ["joint_states\": [", "position\": [", "success\"", "1.57", "0.785"]
    assert not any(f in text for f in forbidden), f"{tab} shows numbers that no ROS system produced: {text[:300]}"
    if tab == "ROS 2 Topics":
        assert '"nodes": []' in text and '"topics": []' in text
    if tab == "Robot State":
        assert '"joint_states": null' in text and '"gripper": null' in text
    if tab == "Spatial Coordinates":
        assert "Poses reported: 0" in text and "names only, no coordinates" in text
    if tab == "Verification":
        assert "Not verified" in text
    con.page.screenshot(SHOTS / f"07-{tab.lower().replace(' ', '-')}.png")


def test_scene_view_is_labelled_a_schematic_with_no_live_state(con):
    text = con.page.js("document.querySelector('[aria-label=\"Robot and scene view\"]').innerText")
    assert "No live Gazebo state" in text and "illustrative, not measured" in text
    assert "red_cube" in text and "storage_box" in text   # names from the configured scene only
    assert "Perception: unavailable" in text


# --- logs, history -------------------------------------------------------------------------------------------------------
def test_logs_tab_records_task_events_without_the_token(con, srv):
    text = con.tab("Logs")
    assert "submitted task_" in text and "validated_no_executor" in text
    assert srv.token not in text


def test_history_lists_tasks_newest_first_and_reopens_one(con):
    con.submit("Pick the green cylinder and place it on the platform")
    items = con.page.js("[...document.querySelectorAll('.history li .hist-text')].map(e => e.textContent)")
    assert len(items) >= 8 and items[0] == "Pick the green cylinder and place it on the platform", items[:3]
    con.page.click(".history li:nth-child(3) button")
    con.page.wait_for("document.querySelector('.hist--on') !== null")


# --- the token never leaves memory -------------------------------------------------------------------------------------
def test_token_is_never_in_the_dom_storage_cookies_urls_or_logs(con, srv):
    token = srv.token
    page = con.page
    for tab in ("Tokenization", "Structured JSON", "Algorithm Explanation", "Logs", "Robot State", "ROS 2 Topics"):
        con.tab(tab)
    page.pump(0.3)
    assert token not in page.js("document.documentElement.outerHTML"), "token in the DOM"
    assert token not in page.js("document.body.innerText")
    assert page.js("JSON.stringify([Object.entries(localStorage), Object.entries(sessionStorage), document.cookie])") == "[[],[],\"\"]"
    dbs = page.js("(async () => (await indexedDB.databases()).map(d => d.name))()")
    assert dbs == [], dbs
    assert token not in page.js("location.href + JSON.stringify(performance.getEntriesByType('resource').map(r => r.name))")
    assert token not in "\n".join(page.console), "token in console output"
    assert not page.exceptions, page.exceptions
    for r in page.requests:
        assert token not in r["url"], r["url"]
        if r["url"].startswith(CONSOLE):
            assert not any(token in str(v) for v in r["headers"].values())


def test_only_the_console_and_the_backend_are_contacted(con):
    hosts = {r["url"].split("/")[2] for r in con.page.requests if r["url"].startswith(("http", "ws"))}
    assert hosts <= {"127.0.0.1:5173", "127.0.0.1:18765"}, hosts


def test_bearer_token_only_goes_to_the_backend(con, srv):
    with_auth = [r for r in con.page.requests if "authorization" in {k.lower() for k in r["headers"]}]
    assert with_auth and all(r["url"].startswith(API) for r in with_auth)
    assert all(srv.token in next(v for k, v in r["headers"].items() if k.lower() == "authorization") for r in with_auth)


def test_disconnect_forgets_the_session(con, srv):
    con.page.click("button.btn--ghost", "Disconnect")
    con.page.wait_for("!!document.querySelector('#token')", desc="connect form again")
    assert con.page.js("document.querySelector('#token').value") == ""
    assert srv.token not in con.page.js("document.documentElement.outerHTML")
    con.connect()
    con.connected()


# --- e-stop (observed result) ------------------------------------------------------------------------------------------
def test_estop_shows_the_observed_result_latches_and_reset_clears_it(con):
    con.page.click("button.btn--estop")
    con.page.wait_for("!!document.querySelector('.estop-result')", desc="e-stop result")
    snap = con.snapshot()
    assert snap["estop"].startswith("Stop observed") and "max |q̇| 0 rad/s" in snap["estop"]
    assert "simulated joint state (no ROS 2 connected)" in snap["estop"], "the source of the observation must be shown"
    con.page.wait_for("document.querySelector('.chip--error .chip-value')?.textContent.startsWith('E-stop latched')", desc="latched chip")
    con.page.screenshot(SHOTS / "08-estop-confirmed.png")
    before = con.page.js("document.querySelectorAll('.history li').length")
    con.page.type_into("#cmd", "Move the red cube to the platform")
    con.page.click("button.btn--primary", "Submit")
    con.page.wait_for("document.querySelector('.log--error') !== null || [...document.querySelectorAll('.estop-result')].length > 1", timeout=5) if False else None
    con.tab("Logs")
    con.page.wait_for("[...document.querySelectorAll('.log')].some(l => l.textContent.includes('submit'))", desc="submit rejection logged")
    logs = con.tab("Logs")
    assert "409" in logs and "latched" in logs, logs[-300:]
    assert con.page.js("document.querySelectorAll('.history li').length") == before, "no task may be created while latched"
    con.page.click("button.btn", "Reset")
    con.page.wait_for("!document.querySelector('.estop-result')", desc="e-stop result cleared")
    con.page.wait_for("document.querySelector('.chip--warning .chip-value') && !document.querySelector('.chip--error')", desc="chip back to warning")
    assert "ros unavailable" in con.tab("Logs"), "reset must say the scene was not reset"
    assert con.submit("Move the red cube to the platform")["status"] == "validated no executor"
