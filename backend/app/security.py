"""Input sanitization (SEC-001) and secret redaction for logs (SEC-010)."""

from __future__ import annotations

import logging
import os
import re
import unicodedata
from collections.abc import Callable, Iterable, Mapping

MAX_INSTRUCTION_CHARS = 2048
MAX_WORD_CHARS = 64
MAX_RAW_CHARS = 64 * 1024

_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f​-‏‪-‮⁦-⁩﻿]")
_SECRET_ENV_RE = re.compile(r"(KEY|TOKEN|SECRET|PASSWORD|PASSWD|CREDENTIAL)", re.IGNORECASE)
_SECRET_PATTERNS = (
    re.compile(r"(?i)\b(bearer|x-api-key:?|authorization:?)\s+[A-Za-z0-9._~+/=-]{8,}"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{12,}"),
    re.compile(r"\bnvapi-[A-Za-z0-9_-]{12,}"),
    re.compile(r"\bgsk_[A-Za-z0-9]{20,}"),  # Groq
    re.compile(r"\bxai-[A-Za-z0-9]{20,}"),  # xAI
    re.compile(r"\bAIza[0-9A-Za-z_-]{30,}"),  # Google
)
REDACTED = "[REDACTED]"


class InputRejected(ValueError):
    """The instruction cannot be accepted; the message is safe to show to the user."""


def sanitize_instruction(text: str) -> str:
    """Normalize and bound a user instruction, or raise InputRejected."""
    if not isinstance(text, str):
        raise InputRejected("instruction must be text")
    if "\x00" in text:
        raise InputRejected("instruction contains a null byte")
    if len(text) > MAX_RAW_CHARS:  # hard cap before any processing; the real limit applies after normalisation
        raise InputRejected(f"instruction is longer than {MAX_INSTRUCTION_CHARS} characters")
    text = unicodedata.normalize("NFKC", text)
    text = _CONTROL_RE.sub("", text.replace("\r", " ").replace("\n", " ").replace("\t", " "))
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        raise InputRejected("instruction is empty")
    if len(text) > MAX_INSTRUCTION_CHARS:
        raise InputRejected(f"instruction is longer than {MAX_INSTRUCTION_CHARS} characters")
    if any(len(word) > MAX_WORD_CHARS for word in text.split()):
        raise InputRejected(f"instruction contains a word longer than {MAX_WORD_CHARS} characters")
    return text


def secret_values(env: Mapping[str, str] | None = None) -> list[str]:
    env = os.environ if env is None else env
    return [v for k, v in env.items() if _SECRET_ENV_RE.search(k) and v and len(v) >= 6]


def redact(text: str, secrets: Iterable[str] = ()) -> str:
    for value in sorted(set(secrets), key=len, reverse=True):
        text = text.replace(value, REDACTED)
    for pattern in _SECRET_PATTERNS:
        text = pattern.sub(lambda m: (m.group(1) + " " if m.groups() else "") + REDACTED, text)
    return text


class RedactingFilter(logging.Filter):
    """Rewrites every record so secret env values and key-like strings never reach a handler."""

    def __init__(self, env: Mapping[str, str] | None = None,
                 extra: Callable[[], Iterable[str]] | None = None) -> None:
        super().__init__()
        self._env = env
        self._extra = extra

    def filter(self, record: logging.LogRecord) -> bool:
        secrets = [*secret_values(self._env), *(self._extra() if self._extra else ())]
        if record.name == "uvicorn.access" and isinstance(record.args, tuple):
            # uvicorn's AccessFormatter unpacks args (client, method, path, version, status): keep the tuple.
            record.args = tuple(redact(a, secrets) if isinstance(a, str) else a for a in record.args)
            record.msg = redact(str(record.msg), secrets)
            return True
        message = record.getMessage()
        if record.exc_info and not record.exc_text:
            record.exc_text = logging.Formatter().formatException(record.exc_info)
        record.msg, record.args = redact(message, secrets), None
        if record.exc_text:
            record.exc_text = redact(record.exc_text, secrets)
        return True


def install_log_redaction(logger: logging.Logger | None = None,
                          extra: Callable[[], Iterable[str]] | None = None) -> RedactingFilter:
    """Attach the filter to the logger and every handler it has now (root by default)."""
    logger = logger or logging.getLogger()
    flt = RedactingFilter(extra=extra)
    for old in [f for f in logger.filters if isinstance(f, RedactingFilter)]:
        logger.removeFilter(old)  # one per logger, even when create_app runs many times
    for handler in logger.handlers:
        for old in [f for f in handler.filters if isinstance(f, RedactingFilter)]:
            handler.removeFilter(old)
        handler.addFilter(flt)
    logger.addFilter(flt)
    return flt
