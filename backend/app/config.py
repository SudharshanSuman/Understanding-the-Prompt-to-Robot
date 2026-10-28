"""Service settings, read once from the environment and checked at startup (SEC S5).

Only names are documented (.env.example); values are never logged or returned by the API.
"""

from __future__ import annotations

import ipaddress
import os
from collections.abc import Mapping
from dataclasses import dataclass

MIN_TOKEN_CHARS = 32
MIN_DISTINCT_CHARS = 8  # a random 32-char token has ~25; "aaaa..." or "abab..." has 1-2
DEFAULT_ORIGINS = ("http://localhost:5173", "http://127.0.0.1:5173")


def _trivial_token(token: str) -> bool:
    """True for tokens with almost no entropy: few distinct characters, or a short pattern repeated."""
    if len(set(token)) < MIN_DISTINCT_CHARS:
        return True
    return any(token == (token[:p] * (len(token) // p + 1))[: len(token)] for p in range(1, len(token) // 2 + 1))


class ConfigError(RuntimeError):
    """The service must not start with this configuration; the message names the variable, never its value."""


def _truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


def _is_loopback(host: str) -> bool:
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


@dataclass(frozen=True)
class Settings:
    api_token: str
    host: str = "127.0.0.1"
    port: int = 8000
    allowed_origins: tuple[str, ...] = DEFAULT_ORIGINS
    debug: bool = False
    allow_remote: bool = False
    require_origin: bool = False  # True: WebSocket clients without an Origin header are refused too
    task_rate_per_min: int = 10
    auth_failures_per_min: int = 20
    ws_max_connections: int = 10
    ws_idle_seconds: float = 300.0
    ws_auth_seconds: float = 5.0
    ws_max_frame_bytes: int = 8192
    max_tasks_kept: int = 100

    def __repr__(self) -> str:  # never include the token
        return f"Settings(host={self.host!r}, port={self.port}, origins={self.allowed_origins}, debug={self.debug})"

    def validate(self) -> Settings:
        if len(self.api_token) < MIN_TOKEN_CHARS:
            raise ConfigError(f"MD_API_TOKEN must be set to at least {MIN_TOKEN_CHARS} characters")
        if not _is_loopback(self.host) and not self.allow_remote:
            raise ConfigError("MD_BIND_HOST is not a loopback address; set MD_ALLOW_REMOTE=true to bind it on purpose")
        if "*" in self.allowed_origins and not self.debug:
            raise ConfigError("MD_ALLOWED_ORIGINS may only contain '*' when DEBUG=true")
        if not 0 < self.port < 65536:
            raise ConfigError("APP_PORT must be between 1 and 65535")
        if self.task_rate_per_min < 1:
            raise ConfigError("MD_TASK_RATE_PER_MIN must be at least 1")
        if self.auth_failures_per_min < 1 or self.ws_max_connections < 1 or self.max_tasks_kept < 1:
            raise ConfigError("auth failure budget, WebSocket connection limit and task history must be at least 1")
        if _trivial_token(self.api_token):  # checked last so other errors still name their own variable
            raise ConfigError("MD_API_TOKEN is too predictable (repeated characters or a short repeated pattern); "
                              "generate one, e.g. python3 -c 'import secrets; print(secrets.token_urlsafe(32))'")
        return self

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> Settings:
        env = os.environ if env is None else env
        debug = _truthy(env.get("DEBUG"))
        origins = tuple(o.strip() for o in env.get("MD_ALLOWED_ORIGINS", "").split(",") if o.strip())
        try:
            port = int(env.get("APP_PORT", "8000"))
            rate = int(env.get("MD_TASK_RATE_PER_MIN", "10"))
        except ValueError as exc:
            raise ConfigError("APP_PORT and MD_TASK_RATE_PER_MIN must be integers") from exc
        return cls(
            api_token=env.get("MD_API_TOKEN", ""),
            host=env.get("MD_BIND_HOST", "127.0.0.1"),
            port=port,
            allowed_origins=origins or (("*",) if debug else DEFAULT_ORIGINS),
            debug=debug,
            allow_remote=_truthy(env.get("MD_ALLOW_REMOTE")),
            require_origin=_truthy(env.get("MD_REQUIRE_ORIGIN")),
            task_rate_per_min=rate,
        ).validate()
