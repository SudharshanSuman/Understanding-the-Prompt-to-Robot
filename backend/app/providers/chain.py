"""Try providers in order; the deterministic fallback always runs last."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from app.providers.base import LanguageModelProvider, ProviderError, ProviderStatus
from app.providers.fallback import DeterministicFallbackProvider
from app.schemas import ParsedCommand
from app.security import redact, secret_values
from app.validation.world import WorldModel


@dataclass(frozen=True)
class ProviderAttempt:
    provider: str
    outcome: str  # "success" | "skipped" | "failed"
    detail: str = ""


@dataclass
class ChainResult:
    parsed: ParsedCommand
    provider: str
    used_fallback: bool
    attempts: list[ProviderAttempt] = field(default_factory=list)


class ProviderChain:
    def __init__(
        self,
        providers: Sequence[LanguageModelProvider],
        fallback: LanguageModelProvider | None = None,
    ) -> None:
        self.providers = list(providers)
        self.fallback = fallback or DeterministicFallbackProvider()

    def statuses(self) -> list[ProviderStatus]:
        return [p.status() for p in (*self.providers, self.fallback)]

    def parse(self, command: str, world: WorldModel) -> ChainResult:
        attempts: list[ProviderAttempt] = []
        for provider in self.providers:
            status = provider.status()
            if not (status.configured and status.available):
                attempts.append(ProviderAttempt(provider.name, "skipped", status.detail))
                continue
            try:
                parsed = provider.parse(command, world)
            except ProviderError as exc:
                attempts.append(ProviderAttempt(provider.name, "failed", redact(str(exc), secret_values())))
                continue
            except Exception as exc:  # a provider bug must not take the pipeline down; fall back instead
                attempts.append(ProviderAttempt(provider.name, "failed", f"unexpected {type(exc).__name__}"))
                continue
            attempts.append(ProviderAttempt(provider.name, "success"))
            return ChainResult(parsed, provider.name, used_fallback=False, attempts=attempts)
        parsed = self.fallback.parse(command, world)
        attempts.append(ProviderAttempt(self.fallback.name, "success"))
        return ChainResult(parsed, self.fallback.name, used_fallback=True, attempts=attempts)
