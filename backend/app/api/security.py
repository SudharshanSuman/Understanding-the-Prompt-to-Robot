"""Bearer auth, rate limits and redacted responses for the HTTP and WebSocket API (SEC-005/006/010)."""

from __future__ import annotations

import hmac
import json
import threading
import time
from collections import defaultdict, deque
from typing import Any

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse

from app.security import redact, secret_values


class RateLimiter:
    """Sliding window: at most `limit` hits per `window` seconds per key."""

    def __init__(self, limit: int, window: float = 60.0) -> None:
        self.limit, self.window = limit, window
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def hit(self, key: str) -> bool:
        now = time.monotonic()
        with self._lock:
            hits = self._hits[key]
            while hits and now - hits[0] >= self.window:
                hits.popleft()
            if len(hits) >= self.limit:
                return False
            hits.append(now)
            return True


class Guard:
    """Token check shared by HTTP and WebSocket. Constant-time compare: cheap enough for the e-stop path."""

    def __init__(self, token: str, failures_per_min: int) -> None:
        self._token = token.encode()
        self.failures = RateLimiter(failures_per_min)

    def token_ok(self, token: str | None) -> bool:
        return bool(token) and hmac.compare_digest(token.encode(), self._token)

    def secrets(self) -> list[str]:
        return [self._token.decode(), *secret_values()]


def client_key(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def unauthorized(guard: Guard, key: str) -> HTTPException:
    """401 with no detail about why; 429 once a client keeps failing."""
    if not guard.failures.hit(key):
        return HTTPException(status_code=429, detail="too many requests")
    return HTTPException(status_code=401, detail="unauthorized", headers={"WWW-Authenticate": "Bearer"})


def require_token(request: Request) -> None:
    guard: Guard = request.app.state.guard
    scheme, _, token = request.headers.get("authorization", "").partition(" ")
    if scheme.lower() == "bearer" and guard.token_ok(token.strip()):
        return
    raise unauthorized(guard, client_key(request))


def safe_dumps(content: Any, secrets: list[str]) -> str:
    return redact(json.dumps(content, default=str, separators=(",", ":")), secrets)


class RedactedJSONResponse(JSONResponse):
    """Every API response passes through the same redaction as the logs. Subclassed per app with its guard."""

    guard: Guard | None = None

    def render(self, content: Any) -> bytes:
        guard = type(self).guard
        return safe_dumps(content, guard.secrets() if guard else secret_values()).encode()
