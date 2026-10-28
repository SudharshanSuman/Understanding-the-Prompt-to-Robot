"""Spec test I: tokenization and processing are inspectable; token IDs are never fabricated."""

import pytest
from pydantic import ValidationError

from app.schemas import TokenizationResult, TokenUnit
from app.tokenizer import ApproximateTokenizer, get_tokenizer

TEXT = "Pick up the red cube, then stop."


def test_approximation_is_labelled_and_has_no_ids():
    r = ApproximateTokenizer().tokenize(TEXT)
    assert r.is_approximate and not r.is_live_model_tokenization
    assert r.tokenizer_name == "regex_word_level" and r.raw_text == TEXT
    assert [t.text for t in r.tokens] == ["Pick", "up", "the", "red", "cube", ",", "then", "stop", "."]
    assert all(t.token_id is None and t.is_approximate for t in r.tokens)
    assert "Approximation" in r.note and "does not decide any physical action" in r.note


def test_offsets_reslice_the_original_text():
    r = ApproximateTokenizer().tokenize("  Héllo  wörld 42! ")
    assert all(r.raw_text[t.start:t.end] == t.text for t in r.tokens)


def test_schema_refuses_fake_ids_on_approximation():
    with pytest.raises(ValidationError):
        TokenUnit(index=0, text="a", start=0, end=1, token_id=7, is_approximate=True)


def test_schema_requires_ids_for_real_tokens():
    with pytest.raises(ValidationError):
        TokenUnit(index=0, text="a", start=0, end=1, is_approximate=False)


def test_schema_rejects_offsets_that_do_not_reslice():
    bad = TokenUnit(index=0, text="b", start=0, end=1, is_approximate=True)
    with pytest.raises(ValidationError):
        TokenizationResult(raw_text="a", tokens=[bad], tokenizer_name="x", is_live_model_tokenization=False)


def test_schema_rejects_mixed_real_and_approximate_tokens():
    tok = TokenUnit(index=0, text="a", start=0, end=1, token_id=1)
    with pytest.raises(ValidationError):
        TokenizationResult(raw_text="a", tokens=[tok], tokenizer_name="x", is_live_model_tokenization=False)


def test_get_tokenizer_without_real_tokenizer_is_approximate():
    assert get_tokenizer(prefer_real=False).tokenize("hi").is_approximate


def test_real_tokenizer_if_installed():
    pytest.importorskip("tiktoken")
    r = get_tokenizer().tokenize(TEXT)
    if r.is_live_model_tokenization:
        assert all(t.token_id is not None for t in r.tokens)


def test_pipeline_exposes_instruction_tokens_task_and_validation(chain, validator):
    from app.pipeline import run_pipeline
    from app.schemas import TaskPlan

    cmd = "Put the green cylinder in the storage box"
    r = run_pipeline(cmd, chain, validator, ApproximateTokenizer())
    tok_event = [e for e in r.events if e.stage == "tokenization"][-1]
    exposed = TokenizationResult.model_validate(tok_event.detail["tokenization"])
    assert exposed.raw_text == cmd and exposed.is_approximate
    assert TaskPlan.model_validate(r.plan.model_dump()) == r.plan
    assert r.report.ok
    from app.schemas import HEADLESS_STAGES

    ran = [e.stage for e in r.events if e.state.value != "waiting" and e.stage in HEADLESS_STAGES]
    assert ran == [s for s in HEADLESS_STAGES for _ in (0, 1)]  # running + result, in canonical order
    task_event = [e for e in r.events if e.stage == "structured_task"][-1]
    assert task_event.detail["task"]["target_object"] == "green_cylinder"
