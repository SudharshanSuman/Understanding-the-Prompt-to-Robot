"""L1 skeleton. Each test is a SKIP with the missing prerequisite, never a pass.
Replace the skip with the body described in TEST_PLAN.md once the prerequisite exists."""
import pytest

pytestmark = [pytest.mark.ros]

NEEDS_WS = "NOT IMPLEMENTED: ros2_ws not built yet (no munder_difflin_* packages, no controller names)"


@pytest.mark.acceptance("D")
@pytest.mark.acceptance("E")
@pytest.mark.acceptance("F")
def test_rejected_requests_leak_no_execute_goal(ros_node):
    """Submit D/E/F inputs; assert zero FollowJointTrajectory/MoveGroup execute goals and unchanged joint_states."""
    pytest.skip(NEEDS_WS)


@pytest.mark.acceptance("C")
def test_C_blue_cube_in_planning_scene_and_path_clears_it(ros_node):
    """Query planning scene: blue_cube present at the scene pose; sampled path clearance >= CLEARANCE_MIN;
    negative control: forced straight path is flagged as colliding."""
    pytest.skip(NEEDS_WS)


@pytest.mark.acceptance("G")
def test_G_cancel_stops_motion_and_status_follows_observation(ros_node):
    """Cancel mid-trajectory; action result CANCELED/ABORTED; joint velocities < STOP_VEL within STOP_TIMEOUT;
    'cancelled' status timestamp is after the observed stop."""
    pytest.skip(NEEDS_WS)


@pytest.mark.acceptance("H")
def test_H_stopped_joint_states_detected_and_new_motion_blocked(ros_node):
    """Stop the joint_states source; header shows disconnected within DISCONNECT_TIMEOUT; submit is refused, no goal sent."""
    pytest.skip(NEEDS_WS)
