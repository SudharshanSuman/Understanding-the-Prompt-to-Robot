"""Acceptance J: fallback only when it can safely handle the request. L0 with fake providers (no network).
TEST_PLAN.md section 4 J."""
import httpx
import pytest

from tests.support.harness import make_fakes, parts, run

pytestmark = [pytest.mark.unit, pytest.mark.acceptance("J")]

SUPPORTED = "Move the red cube to the platform"


def test_unavailable_provider_falls_back_and_says_so():
    _, _, _, schemas = parts()
    Down, _, _, _ = make_fakes()
    down = Down()
    r = run(SUPPORTED, providers=[down])
    assert down.calls == 0, "an unavailable provider must not be called"
    assert r.provider == "fallback"
    parsing = [e for e in r.events if e.stage == "interpretation"][-1]
    assert parsing.state == schemas.StageState.WARNING
    assert "fallback" in parsing.message.lower()
    assert [a["outcome"] for a in parsing.detail["attempts"]] == ["skipped", "success"]


def test_provider_error_falls_back_and_records_the_failure():
    _, _, _, schemas = parts()
    _, Raises, _, _ = make_fakes()
    r = run(SUPPORTED, providers=[Raises()])
    assert r.provider == "fallback"
    parsing = [e for e in r.events if e.stage == "interpretation"][-1]
    assert parsing.detail["attempts"][0]["outcome"] == "failed"
    assert r.plan is not None and r.report.ok


@pytest.mark.parametrize("command", [
    "Pick the red cube, then the green cylinder, and put both on the platform",
    "Stack the red cube on the blue cube",
    "Do something useful with the boxes",
])
def test_fallback_does_not_guess_when_request_is_beyond_it(command):
    """With the preferred provider down, a request the rule parser cannot represent must not become a
    validated plan that silently drops part of the request."""
    _, Raises, _, _ = make_fakes()
    r = run(command, providers=[Raises()])
    executable = r.plan is not None and r.report is not None and r.report.ok
    assert not executable, f"{command!r} became executable via fallback: {r.plan}"


def test_malformed_model_output_is_retried_a_bounded_number_of_times():
    _, _, _, Garbage = make_fakes()
    g = Garbage(max_retries=2)
    r = run(SUPPORTED, providers=[g])
    assert g.model_calls == 3, f"expected 1 try + 2 retries, got {g.model_calls}"
    assert r.provider == "fallback"
    assert r.plan is not None, "fallback should still handle the supported command after the model fails"


def test_raw_model_text_never_becomes_a_plan():
    """X2: free text such as 'I will move the arm now!' must not produce any plan from that provider."""
    _, _, _, Garbage = make_fakes()
    g = Garbage(text='{"action": "set_joint", "q": [9,9,9]}')
    r = run(SUPPORTED, providers=[g])
    assert r.provider != "cloud"
    assert r.plan is None or r.plan.action.value == "pick_and_place"


def test_available_provider_is_not_replaced_by_fallback():
    _, _, _, schemas = parts()
    _, _, Fixed, _ = make_fakes()
    plan = schemas.TaskPlan(action="pick_and_place", object="red_cube", destination="platform", confidence=0.95)
    f = Fixed(plan)
    r = run(SUPPORTED, providers=[f])
    assert f.calls == 1 and r.provider == "cloud"


def test_missing_api_key_reports_unavailable_without_leaking_anything():
    _, prov, _, _ = parts()
    secret = "sk-" + "ant-TESTSECRET0123456789abcdefghij"  # built at runtime so the repo secret scan stays meaningful
    for cls, var in ((prov.CloudAPIProvider, "ANTHROPIC_API_KEY"), (prov.NVIDIAInferenceProvider, "NVIDIA_API_KEY")):
        absent = cls(env={}, client=httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(500))))
        st = absent.status()
        assert not st.available and not st.configured
        present = cls(env={var: secret}, client=httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(500))))
        assert secret not in repr(present) and secret not in present.status().model_dump_json()


def test_provider_auth_failure_does_not_echo_the_key():
    _, prov, _, _ = parts()
    secret = "sk-" + "ant-TESTSECRET0123456789abcdefghij"  # built at runtime so the repo secret scan stays meaningful
    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(401, json={"error": "bad key"})))
    p = prov.CloudAPIProvider(env={"ANTHROPIC_API_KEY": secret}, client=client)
    with pytest.raises(prov.ProviderError) as exc:
        p.parse(SUPPORTED, parts()[2].default_world())
    assert secret not in str(exc.value)
