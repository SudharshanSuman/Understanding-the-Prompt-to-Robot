"""Model-backed providers. API keys are read only from environment variables."""

from __future__ import annotations

import os
from collections.abc import Mapping

import httpx

from app.providers.base import LLMProvider, ProviderError, ProviderStatus, ProviderUnavailable

DEFAULT_TIMEOUT = 30.0


class _HTTPProvider(LLMProvider):
    def __init__(
        self,
        env: Mapping[str, str] | None = None,
        client: httpx.Client | None = None,
        max_retries: int = 2,
    ) -> None:
        super().__init__(max_retries=max_retries)
        self._env = os.environ if env is None else env
        self._client = client or httpx.Client(timeout=DEFAULT_TIMEOUT)

    def _post(self, url: str, payload: dict, headers: dict[str, str]) -> dict:
        try:
            response = self._client.post(url, json=payload, headers=headers)
        except httpx.HTTPError as exc:
            raise ProviderUnavailable(f"{self.name}: request failed: {type(exc).__name__}") from exc
        if response.status_code in (401, 403):
            raise ProviderUnavailable(f"{self.name}: authentication rejected (HTTP {response.status_code})")
        if response.status_code >= 400:
            raise ProviderError(f"{self.name}: HTTP {response.status_code}")
        try:
            return response.json()
        except ValueError as exc:
            raise ProviderError(f"{self.name}: response body is not JSON") from exc

    def __repr__(self) -> str:  # never include keys
        return f"<{type(self).__name__} name={self.name!r}>"


class CloudAPIProvider(_HTTPProvider):
    """Anthropic Messages API. Env: ANTHROPIC_API_KEY, MD_CLOUD_MODEL, MD_CLOUD_BASE_URL."""

    name = "cloud"
    kind = "cloud"

    @property
    def model(self) -> str:
        return self._env.get("MD_CLOUD_MODEL", "claude-sonnet-5-5")

    def _key(self) -> str | None:
        return self._env.get("ANTHROPIC_API_KEY") or None

    def status(self) -> ProviderStatus:
        configured = self._key() is not None
        return ProviderStatus(
            name=self.name, kind=self.kind, configured=configured, available=configured, model=self.model,
            detail="API key present (not verified until first call)" if configured else "ANTHROPIC_API_KEY not set",
        )

    def _complete(self, system: str, messages: list[dict[str, str]]) -> str:
        key = self._key()
        if key is None:
            raise ProviderUnavailable("cloud: ANTHROPIC_API_KEY not set")
        base = self._env.get("MD_CLOUD_BASE_URL", "https://api.anthropic.com").rstrip("/")
        body = self._post(
            f"{base}/v1/messages",
            {"model": self.model, "max_tokens": 1024, "system": system, "messages": messages},
            {"x-api-key": key, "anthropic-version": "2023-06-01"},
        )
        try:
            return "".join(block["text"] for block in body["content"] if block.get("type") == "text")
        except (KeyError, TypeError) as exc:
            raise ProviderError("cloud: unexpected response shape") from exc


class LocalInferenceProvider(_HTTPProvider):
    """Ollama chat API. Env: OLLAMA_HOST, MD_LOCAL_MODEL. No key needed."""

    name = "local"
    kind = "local"

    @property
    def model(self) -> str:
        return self._env.get("MD_LOCAL_MODEL", "llama3.2")

    @property
    def host(self) -> str:
        return self._env.get("OLLAMA_HOST", "http://localhost:11434").rstrip("/")

    def status(self) -> ProviderStatus:
        try:
            response = self._client.get(f"{self.host}/api/tags")
            response.raise_for_status()
            names = {m.get("name", "") for m in response.json().get("models", [])}
        except (httpx.HTTPError, ValueError) as exc:
            return ProviderStatus(name=self.name, kind=self.kind, configured=True, available=False,
                                  model=self.model, detail=f"Ollama not reachable at {self.host}: {type(exc).__name__}")
        has_model = self.model in names or f"{self.model}:latest" in names
        return ProviderStatus(
            name=self.name, kind=self.kind, configured=True, available=has_model, model=self.model,
            detail="model installed" if has_model else f"model '{self.model}' not pulled in Ollama",
        )

    def _complete(self, system: str, messages: list[dict[str, str]]) -> str:
        body = self._post(
            f"{self.host}/api/chat",
            {"model": self.model, "stream": False, "format": "json",
             "messages": [{"role": "system", "content": system}, *messages]},
            {},
        )
        try:
            return body["message"]["content"]
        except (KeyError, TypeError) as exc:
            raise ProviderError("local: unexpected response shape") from exc


class NVIDIAInferenceProvider(_HTTPProvider):
    """OpenAI-compatible chat completions. Env: NVIDIA_API_KEY, NVIDIA_BASE_URL, NVIDIA_MODEL."""

    name = "nvidia"
    kind = "nvidia"

    @property
    def model(self) -> str:
        return self._env.get("NVIDIA_MODEL", "meta/llama-3.1-8b-instruct")

    def _key(self) -> str | None:
        return self._env.get("NVIDIA_API_KEY") or None

    def status(self) -> ProviderStatus:
        configured = self._key() is not None
        return ProviderStatus(
            name=self.name, kind=self.kind, configured=configured, available=configured, model=self.model,
            detail="API key present (not verified until first call)" if configured else "NVIDIA_API_KEY not set",
        )

    def _complete(self, system: str, messages: list[dict[str, str]]) -> str:
        key = self._key()
        if key is None:
            raise ProviderUnavailable("nvidia: NVIDIA_API_KEY not set")
        base = self._env.get("NVIDIA_BASE_URL", "https://integrate.api.nvidia.com/v1").rstrip("/")
        body = self._post(
            f"{base}/chat/completions",
            {"model": self.model, "temperature": 0, "max_tokens": 1024,
             "messages": [{"role": "system", "content": system}, *messages]},
            {"Authorization": f"Bearer {key}"},
        )
        try:
            return body["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError) as exc:
            raise ProviderError("nvidia: unexpected response shape") from exc
