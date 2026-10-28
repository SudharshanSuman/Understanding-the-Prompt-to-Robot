"""Bearer auth, rate limits and redacted responses for the HTTP and WebSocket API (SEC-005/006/010)."""

from __future__ import annotations

import hmac
import json
import threading
import time
from collections import defaultdict, deque
from collections.abc import Callable
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


def bearer_ok(guard: Guard, authorization: str) -> bool:
    scheme, _, token = authorization.partition(" ")
    return scheme.lower() == "bearer" and guard.token_ok(token.strip())


def require_token(request: Request) -> None:
    guard: Guard = request.app.state.guard
    if bearer_ok(guard, request.headers.get("authorization", "")):
        return
    raise unauthorized(guard, client_key(request))


class RequestGate:
    """Pure ASGI middleware run before routing (MD-TEST-004 API-1).

    1. Protected paths are authenticated before a single body byte is read, so a client without the
       token gets 401/429, never a validation error, and costs no memory.
    2. The body cap is enforced while the body streams, so chunked uploads (no Content-Length) are cut
       off at `max_body_bytes` too. Exceeding it answers 413 in place of whatever the app would send.
    """

    def __init__(self, app, guard: Guard, max_body_bytes: int, response_class: type[JSONResponse],
                 is_public: Callable[[str], bool]) -> None:
        self.app, self.guard, self.max, self.response_class, self.is_public = (
            app, guard, max_body_bytes, response_class, is_public)

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope["headers"]}
        path = scope["path"]
        if path.startswith("/api/") and scope["method"] != "OPTIONS" and not self.is_public(path) \
                and not bearer_ok(self.guard, headers.get("authorization", "")):
            client = scope.get("client")
            exc = unauthorized(self.guard, client[0] if client else "unknown")
            return await self._reply(scope, receive, send, exc.status_code, exc.detail, exc.headers)
        length = headers.get("content-length")
        if length is not None and (not length.isdigit() or int(length) > self.max):
            return await self._reply(scope, receive, send, 413, "request body too large")

        received, exceeded, replied = 0, False, False

        async def limited_receive():
            nonlocal received, exceeded
            if exceeded:
                return {"type": "http.disconnect"}
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max:
                    exceeded = True
                    return {"type": "http.disconnect"}  # the app stops reading; the rest is never buffered
            return message

        async def guarded_send(message):
            nonlocal replied
            if not exceeded:
                return await send(message)
            if not replied:
                replied = True
                await self._reply(scope, receive, send, 413, "request body too large")

        try:
            await self.app(scope, limited_receive, guarded_send)
        except Exception:
            if not exceeded:
                raise
        if exceeded and not replied:
            await self._reply(scope, receive, send, 413, "request body too large")

    async def _reply(self, scope, receive, send, status: int, detail: str, headers=None) -> None:
        await self.response_class({"detail": detail}, status_code=status, headers=headers)(scope, receive, send)


def safe_dumps(content: Any, secrets: list[str]) -> str:
    return redact(json.dumps(content, default=str, separators=(",", ":")), secrets)


class RedactedJSONResponse(JSONResponse):
    """Every API response passes through the same redaction as the logs. Subclassed per app with its guard."""

    guard: Guard | None = None

    def render(self, content: Any) -> bytes:
        guard = type(self).guard
        return safe_dumps(content, guard.secrets() if guard else secret_values()).encode()
