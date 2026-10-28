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
# A match that spells out that it is a placeholder is a deliberate fixture/doc example (e.g. nvapi-SECRET..., AKIA...EXAMPLE),
# not a credential. Real keys are random, so these words do not occur in them in practice. Everything else still fails.
PLACEHOLDER_WORDS = ("fake", "example", "secret", "dummy", "placeholder", "notreal", "leakcheck", "apileak")
SKIP_DIRS = {".venv", "node_modules", ".git", "__pycache__", "build", "install", "log", "reports"}
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
            real = [m for m in rx.finditer(text) if not any(w in m.group(0).lower() for w in PLACEHOLDER_WORDS)]
            if real:
                hits.append(f"{p.relative_to(repo_root)}: {label}")  # never print the match itself
    assert not hits, "possible secrets:\n" + "\n".join(hits)


def test_the_scan_still_catches_a_realistic_key_and_ignores_labelled_placeholders():
    real = "sk-" + "ant-" + "Zq8" * 12
    assert any(rx.search(real) for rx in PATTERNS.values())
    flagged = [m for rx in PATTERNS.values() for m in rx.finditer(real) if not any(w in m.group(0).lower() for w in PLACEHOLDER_WORDS)]
    assert flagged, "a realistic key must not be waved through by the placeholder rule"
    fake = "nvapi-" + "SECRET" + "0123456789abcdefghijkl"
    assert not [m for rx in PATTERNS.values() for m in rx.finditer(fake) if not any(w in m.group(0).lower() for w in PLACEHOLDER_WORDS)]
