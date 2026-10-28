"""MD-DEV-008 live check in real Chrome against a running scripts/demo.sh (console on 5173, API on 8000).

Submits 'Pick up the red cube and place it in the storage box' from the dashboard, screenshots the flow and the scene
while the arm moves, then replays the run. Writes results.json and PNGs to <outdir>. Never prints the token.

    python tests/ui/live_browser_check.py <outdir>
"""
import json
import os
import sys
import time
from pathlib import Path
from types import SimpleNamespace

REPO = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(REPO), str(REPO / "backend")]

from tests.api.helpers import free_port  # noqa: E402
from tests.ui.cdp import Chrome, find_chrome  # noqa: E402
from tests.ui.conftest import CONSOLE, Console  # noqa: E402
from tests.ui.test_ui_viz import _flow, _scene  # noqa: E402

OUT = Path(sys.argv[1])
OUT.mkdir(parents=True, exist_ok=True)
TOKEN_FILE = Path(os.environ.get("XDG_RUNTIME_DIR", Path.home() / ".cache" / "munder_difflin")) / "munder_difflin_demo.token"
srv = SimpleNamespace(token=TOKEN_FILE.read_text().strip(), base="http://127.0.0.1:8000")
R: dict = {}


def save():
    (OUT / "browser_results.json").write_text(json.dumps(R, indent=2, default=str))


chrome = Chrome(find_chrome(), OUT / "chrome-profile", free_port())
try:
    page = chrome.page()
    c = Console(page, srv, set())
    c.connect()
    c.connected(timeout=20)
    page.wait_for("!!document.querySelector('[aria-label=\"Robot and scene view\"]')", timeout=20, desc="scene")
    page.wait_for("!!document.querySelector('[aria-label=\"Robot and scene view\"] .badge')", timeout=60,
                  desc="simulation telemetry badge")
    R["scene_connected"] = _scene(page)
    page.screenshot(OUT / "00_connected_idle.png")

    page.type_into("#cmd", "Pick up the red cube and place it in the storage box")
    page.click("button.btn--primary", "Submit")
    seen_running = False
    mid_shot = False
    t0 = time.monotonic()
    while time.monotonic() - t0 < 240:
        st = page.js("document.querySelector('.panel.right h2 .status')?.textContent.trim() ?? ''")
        running = page.js("[...document.querySelectorAll('.flow-stage[data-state=\"running\"]')].map(s => s.dataset.stage)")
        if running and not mid_shot and "execution" in running:
            R["mid_run_stages_running"] = running
            R["mid_run_scene"] = _scene(page)
            page.screenshot(OUT / "01_mid_run_execution.png")
            mid_shot = True
        seen_running = seen_running or bool(running)
        if st in ("completed", "failed", "cancelled", "needs clarification", "validated no executor"):
            break
        time.sleep(0.3)
    page.pump(1.0)
    R["status_final"] = page.js("document.querySelector('.panel.right h2 .status')?.textContent.trim()")
    R["flow_final"] = _flow(page)
    R["scene_final"] = _scene(page)
    page.screenshot(OUT / "02_final_completed.png")
    save()

    page.click(".flow button", "Replay last run")
    page.wait_for("!!document.querySelector('.flow .banner--info') && /Not live/.test(document.querySelector('.flow .banner--info').textContent)",
                  timeout=15, desc="replay banner")
    page.pump(2.0)
    R["replay_flow"] = _flow(page)
    page.screenshot(OUT / "03_replay_playing.png")
    page.pump(4.0)
    R["replay_flow_later"] = _flow(page)
    page.screenshot(OUT / "04_replay_later.png")
    save()
finally:
    chrome.stop()
save()
print("written", OUT / "browser_results.json")
