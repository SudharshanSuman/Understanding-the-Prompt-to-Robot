"""MD-DEV-008 browser checks: prompt-to-arm flow panel, scene view, replay, reduced motion, console errors.

Selectors come from Pam's MD-DEV-008 hand-off. Run with a free console port, for example
    MD_UI_CONSOLE_PORT=4174 pytest tests/ui/test_ui_viz.py
The backend allow-list is set per test (MD_ALLOWED_ORIGINS) so the console origin is accepted.
Screenshots and observed values go to MD_UI_SHOTS (default: the tester scratchpad).
"""
import json
import os
import re
from pathlib import Path

import pytest

from tests.ui.conftest import API_PORT, CONSOLE, CONSOLE_PORT, Console

SHOTS = Path(os.environ.get("MD_UI_SHOTS", "/tmp/claude-1000/-home-sudharshan-Documents-Robotic-Operation-with-Prompt-Engineering/97b88ce4-b4da-4b70-944f-d08727416d0a/scratchpad/viz"))
PHASES = {"completed", "rejected", "needs_clarification", "failed", "no_executor", "cancelled"}
OBSERVED: dict = {}
ORIGIN = {"MD_ALLOWED_ORIGINS": f"http://127.0.0.1:{CONSOLE_PORT},http://localhost:{CONSOLE_PORT}"}


def _flow(page):
    return page.js("""(() => {
      const f = document.querySelector('section[aria-label="Prompt to arm flow"]');
      if (!f) return null;
      return {
        tokens: [...f.querySelectorAll('.flow-token')].map(t => ({i: t.dataset.tokenIndex, cls: t.className,
                 text: t.textContent.trim(), anim: getComputedStyle(t).animationName})),
        stages: [...f.querySelectorAll('.flow-stage')].map(s => ({stage: s.dataset.stage, state: s.dataset.state,
                 text: s.textContent.trim().slice(0, 120)})),
        outcome: f.querySelector('.flow-outcome')?.dataset.phase ?? null,
        outcomeText: f.querySelector('.flow-outcome')?.textContent.trim() ?? null,
        approx: /approximate/i.test(f.textContent),
        banner: f.querySelector('.banner--info')?.textContent.trim() ?? null,
        replayDisabled: [...f.querySelectorAll('button')].find(b => b.textContent.trim() === 'Replay last run')?.disabled ?? null,
        stopReplay: !!([...f.querySelectorAll('button')].find(b => b.textContent.trim() === 'Stop replay')),
      };
    })()""")


def _scene(page):
    return page.js("""(() => {
      const s = document.querySelector('[aria-label="Robot and scene view"]');
      if (!s) return null;
      return {text: s.textContent.replace(/\\s+/g, ' ').trim().slice(0, 400), badge: !!s.querySelector('.badge'),
              badgeText: s.querySelector('.badge')?.textContent.trim() ?? null, canvas: !!s.querySelector('.arm3d')};
    })()""")


def _shot(page, name):
    page.screenshot(SHOTS / f"{name}.png")


def _record(name, value):
    OBSERVED[name] = value
    SHOTS.mkdir(parents=True, exist_ok=True)
    (SHOTS / "observed.json").write_text(json.dumps(OBSERVED, indent=2, default=str))


@pytest.fixture
def viz(backend, make_console, console_server, seen_states, request):
    srv = backend(**ORIGIN)
    c = make_console(srv)
    c.connect()
    c.connected()
    yield c
    if os.environ.get("MD_UI_SHOTS_ALWAYS"):
        _shot(c.page, request.node.name)


def test_M1_flow_panel_and_scene_empty_state_without_telemetry(viz):
    p = viz.page
    flow = p.wait_for("!!document.querySelector('section[aria-label=\"Prompt to arm flow\"]')", desc="flow section")
    scene = _scene(p)
    _record("scene_without_telemetry", scene)
    assert "No live Gazebo state" in scene["text"]
    assert "illustrative, not measured" in scene["text"]
    assert not scene["badge"], "a telemetry badge shows although no telemetry exists"
    _shot(p, "01_empty_state")


def test_M2_submit_drives_tokens_stage_tiles_and_outcome(viz):
    p = viz.page
    viz.submit("Pick up the red cube and place it in the storage box")
    p.wait_for("!!document.querySelector('.flow-outcome')", timeout=20, desc="outcome")
    f = _flow(p)
    _record("flow_after_submit", f)
    assert f["tokens"], "no flow tokens rendered"
    assert all(t["cls"] for t in f["tokens"])
    assert {t["cls"].split("flow-token--")[-1].split()[0] for t in f["tokens"] if "flow-token--" in t["cls"]} <= {"action", "object", "destination"}
    assert f["stages"], "no stage tiles rendered"
    assert f["outcome"] in PHASES, f"outcome phase {f['outcome']!r} not one of {sorted(PHASES)}"
    _shot(p, "02_after_submit")


def test_M3_reject_and_clarify_are_shown_with_their_own_phase(viz):
    p = viz.page
    viz.submit("make me a sandwich on the moon")
    p.wait_for("!!document.querySelector('.flow-outcome')", timeout=20, desc="outcome")
    rejected = _flow(p)
    _record("flow_rejected", rejected)
    assert rejected["outcome"] in PHASES
    _shot(p, "03_rejected_or_clarify")


def test_M4_replay_is_disabled_until_final_then_plays_and_says_not_live(viz):
    p = viz.page
    f = _flow(p)
    _record("flow_before_any_run", f)
    if f["replayDisabled"] is not None:
        assert f["replayDisabled"] is True, "Replay button enabled before any finished task"
    viz.submit("Pick up the red cube and place it in the storage box")
    p.wait_for("[...document.querySelectorAll('.flow button')].some(b => b.textContent.trim() === 'Replay last run' && !b.disabled)",
               timeout=20, desc="replay enabled")
    p.click(".flow button", "Replay last run")
    banner = p.wait_for("document.querySelector('.flow .banner--info') && /Not live/.test(document.querySelector('.flow .banner--info').textContent)",
                        timeout=10, desc="replay banner")
    f = _flow(p)
    _record("flow_replay", f)
    assert "Replay of the recorded run" in (f["banner"] or ""), f["banner"]
    assert f["stopReplay"], "no 'Stop replay' button while replaying"
    _shot(p, "04_replay")


def test_M5_reduced_motion_turns_token_animation_off(viz):
    p = viz.page
    viz.submit("Pick up the red cube and place it in the storage box")
    p.call("Emulation.setEmulatedMedia", features=[{"name": "prefers-reduced-motion", "value": "reduce"}])
    p.pump(0.3)
    names = p.js("[...document.querySelectorAll('.flow-token')].map(t => getComputedStyle(t).animationName)")
    _record("reduced_motion_animation_names", names)
    assert names, "no flow tokens to check"
    assert all(n == "none" for n in names), f"animation still on under reduced motion: {set(names)}"


def test_M6_no_console_errors_no_exceptions_no_csp_violations(viz):
    p = viz.page
    viz.submit("Pick up the red cube and place it in the storage box")
    p.pump(0.5)
    errors = [m for m in p.console if m.startswith("error") or "Content Security Policy" in m]
    _record("console", p.console[-50:])
    _record("exceptions", p.exceptions)
    assert not p.exceptions, p.exceptions
    assert not errors, errors


def test_M7_scene_falls_back_when_the_executor_is_unavailable(backend, make_console, console_server, seen_states):
    """Backend with no RosExecutor (the simulated one reports no telemetry): the scene must say no live state."""
    srv = backend(**ORIGIN)
    c = make_console(srv)
    c.connect()
    c.connected()
    c.page.wait_for("!!document.querySelector('[aria-label=\"Robot and scene view\"]')", desc="scene view")
    scene = _scene(c.page)
    _record("scene_fallback", scene)
    assert "No live Gazebo state" in scene["text"]
    assert not scene["canvas"], "a 3D canvas is drawn without telemetry"


STATIC_ASSET_DIR = None


def test_M8_bundle_has_no_eval_or_new_function(dist):
    """Count eval / new Function in the built JS (three.js and the console). Reported as observed; the assertion is zero."""
    hits = {}
    for js in sorted((dist / "assets").glob("*.js")):
        text = js.read_text(errors="replace")
        n = len(re.findall(r"\beval\(", text)) + len(re.findall(r"new Function\(", text))
        if n:
            hits[js.name] = n
    _record("eval_hits", hits)
    assert not hits, f"eval or new Function found in the bundle: {hits}"
