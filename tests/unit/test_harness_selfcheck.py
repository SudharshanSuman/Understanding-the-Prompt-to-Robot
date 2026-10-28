"""Proves the skeleton itself works (runs now, needs no backend)."""
import pytest

from tests.support import adapter, tolerances


def test_pipeline_order_matches_spec_section_5():
    assert adapter.PIPELINE_STAGES[0] == "instruction"
    assert adapter.PIPELINE_STAGES[-1] == "verification"
    assert len(adapter.PIPELINE_STAGES) == 14
    assert len(adapter.PIPELINE_STAGES) == len(set(adapter.PIPELINE_STAGES))


def test_ui_states_match_spec_section_5():
    assert adapter.UI_STATES == {
        "waiting", "running", "success", "warning", "failed", "cancelled", "needs_clarification"}


def test_tolerances_are_positive():
    for name in dir(tolerances):
        if name.isupper():
            assert getattr(tolerances, name) > 0, name


def test_repo_root_fixture(repo_root):
    assert (repo_root / "tests" / "conftest.py").is_file()


def test_missing_backend_module_skips_not_passes():
    with pytest.raises(pytest.skip.Exception):
        adapter.backend("app.definitely_not_a_module")


@pytest.mark.ros
def test_ros_marker_is_skipped_without_ros(request):
    """If this runs, ROS is really present; if not, conftest skipped it."""
    import rclpy  # noqa: F401
