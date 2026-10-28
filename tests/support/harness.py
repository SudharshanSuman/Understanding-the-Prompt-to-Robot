"""Builders and fakes for L0 tests against backend/app (real validator, real pipeline, fake providers)."""
from __future__ import annotations

from tests.support.adapter import backend


def parts():
    """Return (pipeline, providers, validation, schemas) modules or skip."""
    return (backend("app.pipeline"), backend("app.providers"), backend("app.validation"), backend("app.schemas"))


def run(command: str, providers=(), tokenizer=None, is_cancelled=None, world=None, reachability=None):
    pipeline, prov, valid, _ = parts()
    vkwargs = {} if reachability is None else {"reachability": reachability}
    validator = valid.SafetyValidator(world or valid.default_world(), **vkwargs)
    chain = prov.ProviderChain(list(providers))
    kwargs = {}
    if tokenizer is not None:
        kwargs["tokenizer"] = tokenizer
    if is_cancelled is not None:
        kwargs["is_cancelled"] = is_cancelled
    return pipeline.run_pipeline(command, chain, validator, **kwargs)


def make_fakes():
    """Fake providers: no network, fully deterministic. Created lazily so imports can skip."""
    _, prov, valid, schemas = parts()

    class Down(prov.LanguageModelProvider):
        name, kind = "cloud", "cloud"
        def __init__(self): self.calls = 0
        def status(self):
            return prov.ProviderStatus(name=self.name, kind=self.kind, configured=False, available=False,
                                       detail="down (test)")
        def parse(self, command, world):
            self.calls += 1
            raise prov.ProviderUnavailable("down")

    class Raises(Down):
        def status(self):
            return prov.ProviderStatus(name=self.name, kind=self.kind, configured=True, available=True)
        def parse(self, command, world):
            self.calls += 1
            raise prov.ProviderError("boom (test)")

    class Fixed(prov.LanguageModelProvider):
        """Available provider that returns a fixed (possibly hostile) parse result."""
        name, kind = "cloud", "cloud"
        def __init__(self, result): self.result, self.calls = result, 0
        def status(self):
            return prov.ProviderStatus(name=self.name, kind=self.kind, configured=True, available=True)
        def parse(self, command, world):
            self.calls += 1
            return self.result

    class Garbage(prov.LLMProvider):
        """LLMProvider whose model never returns valid JSON; counts model calls."""
        name, kind = "cloud", "cloud"
        def __init__(self, text="I will move the arm now!", max_retries=2):
            super().__init__(max_retries=max_retries)
            self.text, self.model_calls = text, 0
        def status(self):
            return prov.ProviderStatus(name=self.name, kind=self.kind, configured=True, available=True)
        def _complete(self, system, messages):
            self.model_calls += 1
            return self.text

    return Down, Raises, Fixed, Garbage
