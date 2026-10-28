"""X4: no API keys or private keys in the repo (spec section 14 / trust boundaries). Runs now."""
import re
from pathlib import Path

import pytest

pytestmark = [pytest.mark.unit]

PATTERNS = {
    "openai/anthropic-style key": re.compile(r"\bsk-[A-Za-z0-9_-]{24,}"),
    "nvidia key": re.compile(r"\bnvapi-[A-Za-z0-9_-]{20,}"),
    "aws access key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "private key block": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
}
# .claude/ holds third-party, reviewed skill docs (git-ignored); they contain AWS-key-shaped EXAMPLE text.
SKIP_DIRS = {".claude", ".venv", "node_modules", ".git", "__pycache__", "build", "install", "log", "reports"}
SKIP_SUFFIX = {".png", ".jpg", ".stl", ".dae", ".pyc", ".so", ".zip"}


def _files(root: Path):
    for p in root.rglob("*"):
        if p.is_file() and not (set(p.relative_to(root).parts) & SKIP_DIRS) and p.suffix not in SKIP_SUFFIX:
            yield p


def test_no_secrets_in_repo(repo_root):
    hits = []
    for p in _files(repo_root):
        if p.stat().st_size > 2_000_000:
            continue
        try:
            text = p.read_text(errors="ignore")
        except OSError:
            continue
        for label, rx in PATTERNS.items():
            real = list(rx.finditer(text))
            if real:
                hits.append(f"{p.relative_to(repo_root)}: {label}")  # never print the match itself
    assert not hits, "possible secrets:\n" + "\n".join(hits)


def test_the_scan_flags_realistic_keys_even_when_labelled_as_examples():
    """No exemption for 'fake'/'example' wording: a real key could be labelled that way (god's decision, MD-TEST-005)."""
    real = "sk-" + "ant-" + "Zq8" * 12
    assert any(rx.search(real) for rx in PATTERNS.values())
    for labelled in (
        "# example: " + real,
        "sk-" + "example-" + "Zq8" * 12,
        "nvapi-" + "EXAMPLE" + "0123456789abcdefghijkl",
        "AKIA" + "IOSFODNN7" + "EXAMPLE",
    ):
        assert any(rx.search(labelled) for rx in PATTERNS.values()), "a key-shaped string with 'example' next to it must still be flagged"


def test_backend_requirements_include_a_websocket_implementation(repo_root):
    """Found by Pam on real uvicorn: without `websockets` (or wsproto) every /ws route answers 404, and the in-process TestClient hides it."""
    text = (repo_root / "backend" / "requirements.txt").read_text().lower()
    assert "websockets" in text or "wsproto" in text or "uvicorn[standard]" in text, text
