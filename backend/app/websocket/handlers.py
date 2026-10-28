"""WebSocket streams (INTERFACE_CONTRACTS s7.2) with SEC-006 controls.

Order of checks: Origin allow-list (before accept), connection limit, first-message auth within
a deadline, then schema-checked client messages. Binary frames, oversized frames and idle
connections are closed. Outbound frames go through the same redaction as HTTP responses.
"""

from __future__ import annotations

import asyncio
import threading
from typing import Annotated, Literal, Optional, Union

from fastapi import WebSocket, WebSocketDisconnect
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError

from app.api.security import Guard, safe_dumps
from app.config import Settings
from app.api.routes import telemetry_payload
from app.security import MAX_RAW_CHARS, InputRejected, sanitize_instruction
from app.tasks import TaskManager, TaskNotFound
from app.tokenizer import get_tokenizer

# Close codes: 1003 unsupported data, 1008 policy (bad origin, no auth message within ws_auth_seconds, idle,
# too many failed logins), 1009 too big, 1013 try later (connection cap), 4401 wrong or malformed auth message.
CLOSE_UNSUPPORTED, CLOSE_POLICY, CLOSE_TOO_BIG, CLOSE_BUSY, CLOSE_UNAUTHORIZED = 1003, 1008, 1009, 1013, 4401
OUTBOX_SIZE = 1000
TELEMETRY_PERIOD_S = 0.2  # matches the ROS side (5 Hz) so the 3D arm moves smoothly; frames are never interpolated


class _Msg(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AuthMsg(_Msg):
    type: Literal["auth"]
    token: str = Field(max_length=512)


class PingMsg(_Msg):
    type: Literal["ping"]


class SubscribeMsg(_Msg):
    type: Literal["subscribe"]
    task_id: Optional[str] = Field(default=None, max_length=64)  # None: every task


class UnsubscribeMsg(_Msg):
    type: Literal["unsubscribe"]


class TokenizeMsg(_Msg):
    type: Literal["tokenize"]
    text: str = Field(min_length=1, max_length=MAX_RAW_CHARS)


ClientMsg = TypeAdapter(Annotated[Union[PingMsg, SubscribeMsg, UnsubscribeMsg, TokenizeMsg],
                                  Field(discriminator="type")])
_AUTH = TypeAdapter(AuthMsg)


class ConnectionSlots:
    def __init__(self, limit: int) -> None:
        self.limit, self.used = limit, 0
        self._lock = threading.Lock()

    def acquire(self) -> bool:
        with self._lock:
            if self.used >= self.limit:
                return False
            self.used += 1
            return True

    def release(self) -> None:
        with self._lock:
            self.used = max(0, self.used - 1)


def origin_allowed(origin: str | None, settings: Settings) -> bool:
    """Browsers always send Origin, so it must be on the list. By design, a request with no Origin
    (a non-browser client: CLI, ROS bridge) is let through to the token check, because cross-site
    attacks come from browsers, which cannot omit it. MD_REQUIRE_ORIGIN=true closes that path."""
    if origin is None:
        return not settings.require_origin
    return "*" in settings.allowed_origins or origin in settings.allowed_origins


class _Closed(Exception):
    def __init__(self, code: int, reason: str = "") -> None:
        self.code, self.reason = code, reason


class Session:
    def __init__(self, ws: WebSocket) -> None:
        self.ws = ws
        app = ws.app
        self.settings: Settings = app.state.settings
        self.guard: Guard = app.state.guard
        self.manager: TaskManager = app.state.manager
        self.outbox: asyncio.Queue = asyncio.Queue(maxsize=OUTBOX_SIZE)
        self.subscription = None
        self.background: list[asyncio.Task] = []

    async def send(self, frame: dict) -> None:
        await self.ws.send_text(safe_dumps(frame, self.guard.secrets()))

    def queue(self, channel: str, payload: dict, task_id: str | None = None) -> None:
        frame = {"channel": channel, "payload": payload, **({"task_id": task_id} if task_id else {})}
        try:
            self.outbox.put_nowait(frame)
        except asyncio.QueueFull:
            pass

    async def receive_text(self, timeout: float, timeout_reason: str = "idle timeout") -> str:
        try:
            message = await asyncio.wait_for(self.ws.receive(), timeout)
        except asyncio.TimeoutError:
            raise _Closed(CLOSE_POLICY, timeout_reason) from None
        if message["type"] == "websocket.disconnect":
            raise WebSocketDisconnect(message.get("code", 1000))
        if message.get("bytes") is not None:
            raise _Closed(CLOSE_UNSUPPORTED, "binary frames are not accepted")
        text = message.get("text") or ""
        if len(text.encode()) > self.settings.ws_max_frame_bytes:
            raise _Closed(CLOSE_TOO_BIG, "frame too large")
        return text

    async def authenticate(self) -> None:
        text = await self.receive_text(self.settings.ws_auth_seconds, "auth timeout")
        try:
            token = _AUTH.validate_json(text).token
        except ValidationError:
            token = None
        if not self.guard.token_ok(token):
            client = self.ws.client.host if self.ws.client else "unknown"
            if not self.guard.failures.hit(client):  # same budget as HTTP; the valid token still works
                raise _Closed(CLOSE_POLICY, "too many failed logins")
            raise _Closed(CLOSE_UNAUTHORIZED, "unauthorized")

    async def pump(self) -> None:
        while True:
            await self.send(await self.outbox.get())


async def _serve(ws: WebSocket, on_ready, on_message) -> None:
    settings: Settings = ws.app.state.settings
    slots: ConnectionSlots = ws.app.state.ws_slots
    if not origin_allowed(ws.headers.get("origin"), settings):
        await ws.close(code=CLOSE_POLICY)  # before accept: the handshake is refused (HTTP 403)
        return
    if not slots.acquire():
        await ws.close(code=CLOSE_BUSY)
        return
    session, pump = Session(ws), None
    try:
        await ws.accept()
        await session.authenticate()
        await session.send({"channel": "system", "payload": {"type": "auth_ok"}})
        pump = asyncio.create_task(session.pump())
        await on_ready(session)
        while True:
            text = await session.receive_text(settings.ws_idle_seconds)
            try:
                msg = ClientMsg.validate_json(text)
            except ValidationError as exc:
                session.queue("error", {"type": "invalid_message",
                                        "errors": [e["msg"] for e in exc.errors(include_input=False)][:5]})
                continue
            await on_message(session, msg)
    except _Closed as closed:
        await _close(ws, closed.code, closed.reason)
    except WebSocketDisconnect:
        pass
    finally:
        if pump:
            pump.cancel()
        for task in session.background:
            task.cancel()
        session.manager.unsubscribe(session.subscription)
        slots.release()


async def _close(ws: WebSocket, code: int, reason: str) -> None:
    try:
        await ws.close(code=code, reason=reason)
    except RuntimeError:  # already closed by the client
        pass


async def _common(session: Session, msg) -> bool:
    if isinstance(msg, PingMsg):
        session.queue("system", {"type": "pong"})
        return True
    if isinstance(msg, TokenizeMsg):
        try:
            result = (session.manager.tokenizer or get_tokenizer()).tokenize(
                sanitize_instruction(session.manager.scrub(msg.text)))
            session.queue("tokenization", result.model_dump(mode="json"))
        except InputRejected as exc:
            session.queue("error", {"type": "input_rejected", "message": str(exc)})
        return True
    return False


async def pipeline_ws(ws: WebSocket) -> None:
    async def ready(session: Session) -> None:
        return None

    async def message(session: Session, msg) -> None:
        if await _common(session, msg):
            return
        session.manager.unsubscribe(session.subscription)
        session.subscription = None
        if isinstance(msg, SubscribeMsg):
            try:
                session.subscription = session.manager.subscribe(session.outbox, msg.task_id)
            except TaskNotFound:
                session.queue("error", {"type": "unknown_task", "task_id": msg.task_id})
                return
            session.queue("system", {"type": "subscribed", "task_id": msg.task_id})

    await _serve(ws, ready, message)


async def telemetry_ws(ws: WebSocket) -> None:
    def snapshot(session: Session) -> dict:
        payload = telemetry_payload(session.manager.executor)
        session.queue("telemetry", payload)
        return payload

    async def stream(session: Session, available: bool) -> None:
        # Live data streams; 'unavailable' is sent once per change, not repeated every tick.
        while True:
            await asyncio.sleep(TELEMETRY_PERIOD_S)
            payload = telemetry_payload(session.manager.executor)
            if payload["available"] or available:
                session.queue("telemetry", payload)
            available = payload["available"]

    async def ready(session: Session) -> None:
        first = snapshot(session)
        session.background.append(asyncio.create_task(stream(session, first["available"])))

    async def message(session: Session, msg) -> None:
        if not await _common(session, msg):
            snapshot(session)

    await _serve(ws, ready, message)
