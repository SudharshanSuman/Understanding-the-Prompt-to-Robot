"""MD-DEV-007 / D-V3: health, scene reset and scene objects come from the executor, never hard-coded."""

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.executor import ExecutorStatus, SimulatedExecutor
from app.main import create_app
from app.tokenizer import ApproximateTokenizer

TOKEN = "es-" + "Qw8Lp3Zx6Vn1Tb4Hc9Ym2Jr5Kd7Gf0Su"  # random-looking, built at runtime
AUTH = {"Authorization": f"Bearer {TOKEN}"}
ALL_READY = {"move_action": True, "arm_controller": True, "gripper_controller": True, "joint_states": True}


class FakeRos(SimulatedExecutor):
    """Stands in for RosExecutor: reports readiness, telemetry and a reset detail as the test sets them."""

    name = "fake_ros"

    def __init__(self, ready=None, snapshot=None, connected=False, reset_detail="ok"):
        super().__init__()
        self.ready, self.snapshot, self.connected, self.reset_detail = ready, snapshot, connected, reset_detail

    def readiness(self):
        if isinstance(self.ready, Exception):
            raise self.ready
        return self.ready

    def telemetry(self):
        return self.snapshot

    def status(self):
        return super().status().model_copy(update={"name": self.name, "connected": self.connected,
                                                   "detail": "ok" if self.connected else "not ready"})

    def reset(self):
        return ExecutorStatus(name=self.name, connected=self.connected, can_execute=self.connected,
                              e_stop_latched=False, controller_state="IDLE", detail=self.reset_detail)


def client_for(executor):
    return TestClient(create_app(Settings(api_token=TOKEN), providers=[], executor=executor,
                                 tokenizer=ApproximateTokenizer()))


def health(executor):
    with client_for(executor) as c:
        return c.get("/api/v1/health").json()


def test_health_without_ros_is_unavailable_and_keeps_its_public_shape():
    body = health(SimulatedExecutor())
    assert body == {"status": "ok", "ros2": "unavailable", "gazebo": "unavailable", "moveit": "unavailable",
                    "executor_connected": False}


def test_health_reports_each_part_from_the_executors_readiness():
    body = health(FakeRos(ready=ALL_READY, connected=True))
    assert body == {"status": "ok", "ros2": "available", "gazebo": "available", "moveit": "available",
                    "executor_connected": True}


@pytest.mark.parametrize("ready,expected", [
    ({**ALL_READY, "move_action": False}, ("available", "available", "unavailable")),
    ({**ALL_READY, "joint_states": False}, ("available", "unavailable", "available")),  # stale joint states
    ({k: False for k in ALL_READY}, ("unavailable", "unavailable", "unavailable")),
])
def test_health_reports_a_partly_ready_stack_honestly(ready, expected):
    body = health(FakeRos(ready=ready))
    assert (body["ros2"], body["gazebo"], body["moveit"]) == expected and body["executor_connected"] is False


def test_health_without_readiness_uses_connection_then_telemetry():
    assert health(FakeRos(connected=True))["gazebo"] == "available"
    body = health(FakeRos(snapshot={"joints": {}}))  # live data proves ROS 2, nothing more
    assert (body["ros2"], body["gazebo"], body["moveit"]) == ("available", "unknown", "unknown")
    body = health(FakeRos(ready=RuntimeError("graph down")))  # a failing readiness probe claims nothing
    assert (body["ros2"], body["gazebo"], body["moveit"]) == ("unavailable", "unavailable", "unavailable")


@pytest.mark.parametrize("detail,connected,expected", [
    ("ok; scene: objects restored", True, "objects restored"),
    ("ok; scene: not reset: red_cube", True, "not reset: red_cube"),
    ("ok", True, "not reported by the executor: Gazebo scene state unknown"),
    ("reset failed: timeout; latch kept", False, "ros unavailable: Gazebo scene not reset"),
])
def test_scene_reset_is_the_executors_own_result(detail, connected, expected):
    with client_for(FakeRos(connected=connected, reset_detail=detail)) as c:
        body = c.post("/api/v1/simulation/reset", headers=AUTH).json()
    assert body["scene_reset"] == expected


def test_scene_objects_come_from_telemetry_when_live():
    snap = {"time": 1.5, "perception": "simulation-ground-truth",
            "objects": {"red_cube": [0.45, 0.15, 0.02], "bad": [0.1, None, 0.0], "blue_cube": [0.5, -0.1, 0.02]}}
    with client_for(FakeRos(snapshot=snap)) as c:
        body = c.get("/api/v1/environment/objects", headers=AUTH).json()
    assert body["available"] is True and body["source"] == "fake_ros"
    assert body["perception_mode"] == "simulation-ground-truth"
    assert body["objects"] == [{"id": "blue_cube", "position": [0.5, -0.1, 0.02]},
                               {"id": "red_cube", "position": [0.45, 0.15, 0.02]}]  # non-numeric entry dropped
    assert "red_cube" in body["scene_config"]["objects"]


def test_scene_objects_stay_unavailable_without_live_data():
    with client_for(FakeRos(snapshot=None)) as c:
        body = c.get("/api/v1/environment/objects", headers=AUTH).json()
    assert body["available"] is False and body["objects"] == [] and body["perception_mode"] == "unavailable"
