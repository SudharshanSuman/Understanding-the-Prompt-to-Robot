"""Shared fixtures and the skip-if-no-ROS/Gazebo scheme (TEST_PLAN.md section 2)."""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = REPO_ROOT / "backend"


def _have_ros() -> tuple[bool, str]:
    if os.environ.get("ROS_DISTRO") != "jazzy":
        return False, "ROS_DISTRO is not 'jazzy' (source /opt/ros/jazzy/setup.bash)"
    try:
        import rclpy  # noqa: F401
    except Exception as exc:  # ImportError or a broken install
        return False, f"rclpy not importable: {exc}"
    return True, ""


def _have_gazebo() -> tuple[bool, str]:
    ok, why = _have_ros()
    if not ok:
        return False, why
    if shutil.which("gz") is None:
        return False, "'gz' not on PATH"
    if os.environ.get("MD_RUN_GAZEBO") != "1":
        return False, "set MD_RUN_GAZEBO=1 to run full-Gazebo tests"
    return True, ""


@pytest.hookimpl(tryfirst=True)
def pytest_collection_modifyitems(config, items):
    ros_ok, ros_why = _have_ros()
    gz_ok, gz_why = _have_gazebo()
    for item in items:
        if "gazebo" in item.keywords:
            if not gz_ok:
                item.add_marker(pytest.mark.skip(reason=f"gazebo layer: {gz_why}"))
        elif "ros" in item.keywords:
            if not ros_ok:
                item.add_marker(pytest.mark.skip(reason=f"ros layer: {ros_why}"))
        elif not any(k in item.keywords for k in ("unit", "slow", "needs_display")):
            item.add_marker(pytest.mark.unit)  # unmarked tests are L0


@pytest.fixture(scope="session")
def repo_root() -> Path:
    return REPO_ROOT


@pytest.fixture(scope="session", autouse=True)
def backend_on_path():
    """Make `import app...` resolve to backend/app (spec section 16 layout)."""
    if BACKEND_DIR.is_dir() and str(BACKEND_DIR) not in sys.path:
        sys.path.insert(0, str(BACKEND_DIR))
    yield


@pytest.fixture(scope="session")
def tolerances():
    from tests.support import tolerances as t
    return t


@pytest.fixture
def no_motion_spy():
    """Counts motion dispatches. L0/L1 tests wire it into the executor dependency (CA-6).
    Assert `spy.calls == []` for every rejected/ambiguous request (D, E, F)."""
    class Spy:
        def __init__(self):
            self.calls = []
        def __call__(self, *a, **k):
            self.calls.append((a, k))
    return Spy()


@pytest.fixture
def ros_node():
    """L1: a throwaway rclpy node. Skipped with the ros marker when ROS is absent."""
    import rclpy
    rclpy.init()
    node = None
    try:
        node = rclpy.create_node("md_test_node")
        yield node
    finally:                      # also when create_node fails, so one broken test cannot poison the next init()
        if node is not None:
            node.destroy_node()
        rclpy.shutdown()
