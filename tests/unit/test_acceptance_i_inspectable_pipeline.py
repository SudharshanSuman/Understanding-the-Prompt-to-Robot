"""Acceptance I: tokenization and processing inspectable end to end (L0 on the real pipeline).
TEST_PLAN.md section 4 I. Stage names: INTERFACE_CONTRACTS s3 / ADR-009 (14 canonical stages). Headless, the backend runs
instruction..feasibility; grounding..verification are announced, then closed out 'cancelled' (headless) or after a stop."""
import pytest

from tests.support.adapter import PIPELINE_STAGES
from tests.support.harness import parts, run

pytestmark = [pytest.mark.unit, pytest.mark.acceptance("I")]

COMMAND = "Pick the red cube and place it on the platform"
HEADLESS = PIPELINE_STAGES[:6]   # instruction .. feasibility
ROS_ONLY = PIPELINE_STAGES[6:]   # grounding .. verification


def _by_stage(events):
    out = {}
    for e in events:
        out.setdefault(e.stage, []).append(e)
    return out


def test_all_14_stages_are_announced_waiting_first_in_canonical_order():
    r = run(COMMAND)
    first = r.events[:len(PIPELINE_STAGES)]
    assert [e.stage for e in first] == list(PIPELINE_STAGES)
    assert all(e.state.value == "waiting" for e in first)


def test_headless_stages_end_in_a_terminal_ui_state_on_success():
    _, _, _, schemas = parts()
    r = run(COMMAND)
    by = _by_stage(r.events)
    for stage in HEADLESS:
        assert by[stage][-1].state in schemas.TERMINAL_STATES, f"{stage} ended {by[stage][-1].state}"
    assert r.state in schemas.TERMINAL_STATES


def test_ros_stages_are_closed_out_cancelled_never_faked_after_a_headless_success():
    """No executor connected: grounding..verification must never report running/success. Pam closes them out as
    cancelled with reason headless_run_complete (Jim's answer to the open 'terminal headless?' question)."""
    r = run(COMMAND)
    by = _by_stage(r.events)
    for stage in ROS_ONLY:
        states = [e.state.value for e in by[stage]]
        assert states == ["waiting", "cancelled"], f"{stage}: {states}"
        assert by[stage][-1].detail.get("reason") == "headless_run_complete"
    assert r.state.value in {"success", "warning"}, "a cancelled ROS stage must not turn the headless run into a failure"


def test_after_a_failure_every_later_stage_is_cancelled():
    _, _, _, schemas = parts()
    r = run("Pick up the purple cube and put it on the platform")
    by = _by_stage(r.events)
    assert r.state == schemas.StageState.FAILED
    failed_at = [s for s in PIPELINE_STAGES if by[s][-1].state == schemas.StageState.FAILED]
    assert len(failed_at) == 1
    for stage in PIPELINE_STAGES[PIPELINE_STAGES.index(failed_at[0]) + 1:]:
        assert by[stage][-1].state == schemas.StageState.CANCELLED, stage


def test_run_id_and_timestamps_are_consistent():
    r = run(COMMAND)
    assert {e.run_id for e in r.events} == {r.run_id}
    stamps = [e.timestamp for e in r.events]
    assert stamps == sorted(stamps), "event timestamps go backwards"


def test_tokenization_result_is_exposed_and_honest():
    r = run(COMMAND)
    t = r.tokens
    assert t is not None and t.tokenizer_name and t.tokens and t.count == len(t.tokens)
    assert t.raw_text == COMMAND
    for tok in t.tokens:
        if t.is_approximate:
            assert tok.token_id is None and tok.is_approximate, "approximate token carries an ID (fabricated)"
        else:
            assert isinstance(tok.token_id, int) and not tok.is_approximate
    if t.is_approximate:
        assert "approximat" in t.note.lower()


def test_token_boundaries_reslice_the_original_text_exactly():
    """Spec section 7: boundaries. Offsets are checked here independently of the model's own validator."""
    r = run(COMMAND)
    last_end = 0
    for tok in r.tokens.tokens:
        assert COMMAND[tok.start:tok.end] == tok.text, tok
        assert tok.start >= last_end, "token offsets overlap or go backwards"
        last_end = tok.end


def test_tokenization_event_carries_the_full_tokenization():
    r = run(COMMAND)
    ev = _by_stage(r.events)["tokenization"][-1]
    dumped = ev.detail.get("tokenization")
    assert dumped and dumped["tokenizer_name"] == r.tokens.tokenizer_name
    assert len(dumped["tokens"]) == r.tokens.count


def test_approximate_tokenization_is_flagged_as_warning_not_success():
    _, _, _, schemas = parts()
    from app.tokenizer import ApproximateTokenizer
    r = run(COMMAND, tokenizer=ApproximateTokenizer())
    last = _by_stage(r.events)["tokenization"][-1]
    assert last.state == schemas.StageState.WARNING


def test_structured_task_is_inspectable_after_the_run():
    r = run(COMMAND)
    assert r.plan is not None and r.plan.model_dump()["object"] == "red_cube"
    assert r.report is not None and r.report.ok


def test_note_states_tokenization_does_not_decide_physical_action():
    note = run(COMMAND).tokens.note.lower()
    assert "does not decide" in note and "physical action" in note


def test_pipeline_events_use_only_canonical_stage_names():
    r = run(COMMAND)
    assert {e.stage for e in r.events} == set(PIPELINE_STAGES)


def test_structured_task_and_feasibility_events_carry_their_data():
    r = run(COMMAND)
    by = _by_stage(r.events)
    st = by["structured_task"][-1]
    assert st.detail["plan"]["object"] == "red_cube" and st.detail["task"]["task_id"] == r.run_id
    assert by["interpretation"][-1].detail["provider"] == r.provider
