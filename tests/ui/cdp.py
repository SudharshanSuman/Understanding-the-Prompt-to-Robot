"""Minimal Chrome DevTools Protocol driver (no browser-automation package needed): launch headless Chrome, drive one page."""
from __future__ import annotations

import json
import shutil
import subprocess
import time
import urllib.request
from pathlib import Path

from websockets.sync.client import connect


def find_chrome() -> str | None:
    for name in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser"):
        path = shutil.which(name)
        if path:
            return path
    return None


class Chrome:
    def __init__(self, binary: str, profile: Path, port: int, size="1600,1000"):
        self.port = port
        self.proc = subprocess.Popen(
            [binary, "--headless=new", f"--remote-debugging-port={port}", f"--user-data-dir={profile}", "--no-first-run",
             "--no-default-browser-check", "--disable-gpu", "--disable-extensions", f"--window-size={size}", "about:blank"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            try:
                self.targets = json.load(urllib.request.urlopen(f"http://127.0.0.1:{port}/json/list", timeout=1))
                if any(t["type"] == "page" for t in self.targets):
                    return
            except OSError:
                pass
            time.sleep(0.2)
        self.stop()
        raise RuntimeError("Chrome did not start")

    def page(self) -> "Page":
        target = next(t for t in self.targets if t["type"] == "page")
        return Page(target["webSocketDebuggerUrl"])

    def stop(self):
        self.proc.terminate()
        try:
            self.proc.wait(5)
        except subprocess.TimeoutExpired:
            self.proc.kill()


class Page:
    def __init__(self, ws_url: str):
        self.ws = connect(ws_url, max_size=None, open_timeout=10)
        self._id = 0
        self.requests: list[dict] = []
        self.exceptions: list[str] = []
        self.console: list[str] = []
        for domain in ("Page", "Runtime", "Network", "Log"):
            self.call(f"{domain}.enable")

    def _note(self, msg: dict) -> None:
        m, p = msg.get("method"), msg.get("params", {})
        if m == "Network.requestWillBeSent":
            self.requests.append({"url": p["request"]["url"], "method": p["request"]["method"], "headers": p["request"].get("headers", {})})
        elif m == "Runtime.exceptionThrown":
            self.exceptions.append(p["exceptionDetails"].get("exception", {}).get("description") or p["exceptionDetails"]["text"])
        elif m == "Runtime.consoleAPICalled":
            self.console.append(f'{p["type"]}: ' + " ".join(str(a.get("value", a.get("description", ""))) for a in p["args"]))

    def call(self, method: str, **params):
        self._id += 1
        mid = self._id
        self.ws.send(json.dumps({"id": mid, "method": method, "params": params}))
        while True:
            msg = json.loads(self.ws.recv(timeout=30))
            if msg.get("id") == mid:
                if "error" in msg:
                    raise RuntimeError(f"{method}: {msg['error']}")
                return msg.get("result", {})
            self._note(msg)

    def pump(self, seconds: float = 0.05) -> None:
        """Drain pending protocol events (keeps requests/console current)."""
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            try:
                self._note(json.loads(self.ws.recv(timeout=max(0.01, end - time.monotonic()))))
            except TimeoutError:
                return

    def js(self, expression: str):
        r = self.call("Runtime.evaluate", expression=expression, returnByValue=True, awaitPromise=True)
        if "exceptionDetails" in r:
            raise RuntimeError(f"js error: {r['exceptionDetails'].get('exception', {}).get('description', r['exceptionDetails'])}")
        return r["result"].get("value")

    def goto(self, url: str) -> None:
        self.call("Page.navigate", url=url)
        self.wait_for("document.readyState === 'complete'", timeout=15)

    def wait_for(self, expression: str, timeout: float = 10.0, desc: str = ""):
        end = time.monotonic() + timeout
        last = None
        while time.monotonic() < end:
            last = self.js(expression)
            if last:
                return last
            self.pump(0.05)
        raise AssertionError(f"timed out waiting for {desc or expression}; last value {last!r}")

    def click(self, selector: str, text: str | None = None) -> None:
        sel, txt = json.dumps(selector), json.dumps(text)
        ok = self.js(f"""(() => {{
            const els = [...document.querySelectorAll({sel})].filter(e => {txt} === null || e.textContent.trim() === {txt});
            const el = els[0]; if (!el) return false; if (el.disabled) return 'disabled'; el.click(); return true; }})()""")
        assert ok is True, f"click {selector!r} {text!r}: {ok}"

    def type_into(self, selector: str, text: str) -> None:
        sel = json.dumps(selector)
        assert self.js(f"(() => {{ const e = document.querySelector({sel}); if (!e) return false; e.focus(); e.select && e.select(); return true; }})()"), selector
        self.call("Input.insertText", text=text)

    def screenshot(self, path: Path) -> None:
        import base64

        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(base64.b64decode(self.call("Page.captureScreenshot", format="png")["data"]))

    def close(self):
        self.ws.close()
