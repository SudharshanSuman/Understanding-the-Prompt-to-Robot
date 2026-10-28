"""Spec test J: provider fallback is reported and used only when the fallback can safely handle the request.

All HTTP is mocked with httpx.MockTransport. No real model is called and no key is used.
"""

import json

import httpx
import pytest

from app.providers import (
    CloudAPIProvider, LLMProvider, LocalInferenceProvider, MalformedOutputError, NVIDIAInferenceProvider,
    ProviderChain, ProviderStatus, extract_json_object,
)
from app.schemas import ClarificationRequest, TaskPlan

PLAN = {"kind": "task", "action": "pick_and_place", "object": "red_cube", "destination": "platform",
        "constraints": {"avoid_objects": [], "keep_upright": False}, "confidence": 0.8}
FAKE_KEY = "test-key-not-real"


def client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


class Scripted(LLMProvider):
    name, kind = "scripted", "cloud"

    def __init__(self, replies, max_retries=2):
        super().__init__(max_retries=max_retries)
        self.replies, self.calls = list(replies), []

    def status(self):
        return ProviderStatus(name=self.name, kind=self.kind, configured=True, available=True)

    def _complete(self, system, messages):
        self.calls.append(messages)
        return self.replies.pop(0)


def test_extract_json_tolerates_fences_and_chatter():
    assert extract_json_object('Sure!\n```json\n{"a": "}"}\n```') == {"a": "}"}
    assert extract_json_object('{bad} then {"b": 1}') == {"b": 1}
    with pytest.raises(ValueError):
        extract_json_object("no json here")


def test_retry_recovers_from_malformed_json(world):
    p = Scripted(["not json", '{"kind": "task", "object": "red_cube"}', json.dumps(PLAN)])
    assert isinstance(p.parse("pick the red cube onto the platform", world), TaskPlan)
    assert len(p.calls) == 3
    assert "rejected" in p.calls[1][-1]["content"]  # error fed back to the model


def test_retry_gives_up_after_limit(world):
    p = Scripted(["nope", "still nope"], max_retries=1)
    with pytest.raises(MalformedOutputError) as err:
        p.parse("x", world)
    assert len(err.value.errors) == 2


def test_chain_falls_back_to_deterministic_on_malformed(world):
    result = ProviderChain([Scripted(["bad"] * 3)]).parse("Put the green cylinder in the storage box", world)
    assert result.used_fallback and result.provider == "fallback"
    assert [a.outcome for a in result.attempts] == ["failed", "success"]
    assert result.parsed.object == "green_cylinder"


def test_chain_skips_unconfigured_providers(world):
    chain = ProviderChain([CloudAPIProvider(env={}), NVIDIAInferenceProvider(env={})])
    result = chain.parse("Put the green cylinder in the storage box", world)
    assert result.used_fallback
    assert [a.outcome for a in result.attempts] == ["skipped", "skipped", "success"]
    assert all(s.name for s in chain.statuses())


def test_keys_only_from_env_and_never_in_status_or_repr():
    unset = CloudAPIProvider(env={}).status()
    assert not unset.configured and "ANTHROPIC_API_KEY" in unset.detail
    p = CloudAPIProvider(env={"ANTHROPIC_API_KEY": FAKE_KEY})
    assert p.status().configured
    assert FAKE_KEY not in p.status().model_dump_json() and FAKE_KEY not in repr(p)


def test_cloud_provider_request_shape(world):
    seen = {}

    def handler(req):
        seen["url"], seen["headers"], seen["body"] = str(req.url), req.headers, json.loads(req.content)
        return httpx.Response(200, json={"content": [{"type": "text", "text": json.dumps(PLAN)}]})

    p = CloudAPIProvider(env={"ANTHROPIC_API_KEY": FAKE_KEY}, client=client(handler))
    assert isinstance(p.parse("cmd", world), TaskPlan)
    assert seen["url"] == "https://api.anthropic.com/v1/messages"
    assert seen["headers"]["x-api-key"] == FAKE_KEY and "anthropic-version" in seen["headers"]
    assert seen["body"]["messages"][0] == {"role": "user", "content": '{"instruction": "cmd"}'}
    assert "untrusted data" in seen["body"]["system"]


def test_nvidia_provider_openai_compatible(world):
    def handler(req):
        assert str(req.url) == "https://integrate.api.nvidia.com/v1/chat/completions"
        assert req.headers["authorization"] == f"Bearer {FAKE_KEY}"
        clar = {"kind": "clarification", "question": "Which box?", "reason": "two boxes"}
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(clar)}}]})

    p = NVIDIAInferenceProvider(env={"NVIDIA_API_KEY": FAKE_KEY}, client=client(handler))
    assert isinstance(p.parse("move the box", world), ClarificationRequest)


def test_auth_failure_falls_back(world):
    p = NVIDIAInferenceProvider(env={"NVIDIA_API_KEY": FAKE_KEY},
                                client=client(lambda req: httpx.Response(401, json={})))
    result = ProviderChain([p]).parse("Put the green cylinder in the storage box", world)
    assert result.used_fallback and "authentication" in result.attempts[0].detail


def test_ollama_status_and_parse(world):
    def handler(req):
        if req.url.path == "/api/tags":
            return httpx.Response(200, json={"models": [{"name": "llama3.2:latest"}]})
        body = json.loads(req.content)
        assert body["format"] == "json" and body["messages"][0]["role"] == "system"
        return httpx.Response(200, json={"message": {"content": json.dumps(PLAN)}})

    p = LocalInferenceProvider(env={}, client=client(handler))
    assert p.status().available
    assert isinstance(p.parse("cmd", world), TaskPlan)


def test_ollama_down_or_model_missing_reports_unavailable():
    def down(req):
        raise httpx.ConnectError("refused")

    assert not LocalInferenceProvider(env={}, client=client(down)).status().available
    missing = LocalInferenceProvider(
        env={}, client=client(lambda r: httpx.Response(200, json={"models": [{"name": "other"}]}))).status()
    assert not missing.available and "not pulled" in missing.detail


def test_contract_methods_parse_instruction_tokenize_health_check(world):
    import asyncio

    from app.providers import DeterministicFallbackProvider

    p = DeterministicFallbackProvider()
    out = asyncio.run(p.parse_instruction("Put the green cylinder in the storage box", world.model_dump()))
    assert out["kind"] == "task" and out["object"] == "green_cylinder"
    status = asyncio.run(p.health_check())
    dumped = status.model_dump()
    assert dumped["provider_id"] == "fallback" and dumped["error_message"] is None
    assert status.latency_ms is not None
    assert p.tokenize("hi").tokens


def test_unavailable_status_carries_contract_error_message():
    dumped = NVIDIAInferenceProvider(env={}).status().model_dump()
    assert dumped["available"] is False and "NVIDIA_API_KEY" in dumped["error_message"]


def test_no_key_in_logs_or_errors_on_failure(world, caplog):
    import logging

    caplog.set_level(logging.DEBUG)
    p = CloudAPIProvider(env={"ANTHROPIC_API_KEY": FAKE_KEY},
                         client=client(lambda req: httpx.Response(500, text=FAKE_KEY)))
    result = ProviderChain([p]).parse("Put the green cylinder in the storage box", world)
    assert result.used_fallback
    blob = caplog.text + " ".join(a.detail for a in result.attempts) + result.parsed.model_dump_json()
    assert FAKE_KEY not in blob


@pytest.mark.parametrize("cmd", [
    "Sort every object on the table by colour",
    "Pick up the red cube and place it on the platform, then put the green cylinder in the storage box",
    "Move the box to the left",
])
def test_unavailable_provider_and_unsafe_request_gives_no_task(cmd, validator):
    """J case 2: the fallback must refuse or ask, never best-guess an unsupported request."""
    from app.pipeline import run_pipeline
    from app.schemas import StageState
    from app.tokenizer import ApproximateTokenizer

    r = run_pipeline(cmd, ProviderChain([CloudAPIProvider(env={})]), validator, ApproximateTokenizer())
    assert r.plan is None and r.state == StageState.NEEDS_CLARIFICATION


def test_fallback_use_is_visible_in_events(validator):
    """J case 1: the UI can see that the fallback handled the request and why."""
    from app.pipeline import run_pipeline
    from app.schemas import StageState
    from app.tokenizer import ApproximateTokenizer

    r = run_pipeline("Put the green cylinder in the storage box", ProviderChain([CloudAPIProvider(env={})]),
                     validator, ApproximateTokenizer())
    parsing = [e for e in r.events if e.stage == "interpretation"][-1]
    assert parsing.state == StageState.WARNING and "fallback" in parsing.message
    assert parsing.detail["attempts"][0] == {"provider": "cloud", "outcome": "skipped",
                                             "detail": "ANTHROPIC_API_KEY not set"}


@pytest.mark.parametrize("hostile", ["{" * 20000, '{"a":' * 3000, "}" * 50000 + "{" * 50000])
def test_json_extraction_is_linear_on_hostile_output(hostile):
    """BE-5: unbalanced output used to cost O(n^2) (~12 s for 20k braces)."""
    import time

    t = time.perf_counter()
    with pytest.raises(ValueError):
        extract_json_object(hostile)
    assert time.perf_counter() - t < 0.5


def test_json_extraction_caps_output_size_and_survives_deep_nesting():
    with pytest.raises(ValueError, match="longer than"):
        extract_json_object("x" * 100_001)
    deep = '{"a":' * 100_000 + "1" + "}" * 100_000
    with pytest.raises(ValueError):  # over the size cap; a RecursionError inside json is also contained
        extract_json_object(deep)
    assert extract_json_object('{"a":' * 500 + "1" + "}" * 500)["a"]  # moderate nesting still parses


def test_missing_ollama_model_is_named_with_what_is_installed():
    tags = {"models": [{"name": "qwen:14b"}, {"name": "deepseek-r1:7b"}]}
    st = LocalInferenceProvider(env={}, client=client(lambda r: httpx.Response(200, json=tags))).status()
    assert not st.available and st.model == "llama3.2"
    assert "'llama3.2' is not pulled" in st.detail and "deepseek-r1:7b, qwen:14b" in st.detail
    assert "ollama pull llama3.2" in st.detail and "MD_LOCAL_MODEL" in st.detail
