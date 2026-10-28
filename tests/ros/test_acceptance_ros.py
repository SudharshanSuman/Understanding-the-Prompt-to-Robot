"""L1 acceptance tests that still cannot run. Each is a SKIP with the exact missing prerequisite, never a pass.

What CAN run on ROS milestone 1 (sim + controllers + trajectory/gripper actions, no MoveIt, no executor) lives in
test_sim_m1.py: controllers, joint_states, trajectory goal, G cancel at action level, joint limits, invalid goals,
gripper, clean shutdown. Replace a skip below with a real body when its prerequisite exists.
"""
import pytest

pytestmark = [pytest.mark.ros]

NEEDS_EXECUTOR = ("NOT IMPLEMENTED: the ROS executor (backend -> ROS bridge that turns a validated task into goals and reports "
                  "observed results) does not exist yet; milestone 1 has only the simulation and controllers")
NEEDS_MOVEIT = ("NOT IMPLEMENTED: no MoveIt planning scene / move_group in a milestone-1 launch "
                "(munder_difflin_bringup moveit.launch.py is not part of the verified milestone)")


@pytest.mark.acceptance("D")
@pytest.mark.acceptance("E")
@pytest.mark.acceptance("F")
def test_rejected_requests_leak_no_execute_goal():
    """Submit D/E/F inputs; assert zero FollowJointTrajectory/MoveGroup execute goals and unchanged joint_states."""
    pytest.skip(NEEDS_EXECUTOR)


@pytest.mark.acceptance("C")
def test_C_blue_cube_in_planning_scene_and_path_clears_it():
    """Query planning scene: blue_cube present at the scene pose; sampled path clearance >= CLEARANCE_MIN;
    negative control: forced straight path is flagged as colliding."""
    pytest.skip(NEEDS_MOVEIT)


@pytest.mark.acceptance("G")
def test_G_backend_status_follows_the_observed_stop():
    """The 'cancelled' task status timestamp must be after the observed stop (joint velocities < STOP_VEL).
    The action-level half of G (cancel mid-trajectory -> CANCELED, velocities < STOP_VEL within STOP_TIMEOUT, no drift)
    runs in test_sim_m1.py::test_G_cancel_mid_trajectory_stops_the_arm_and_holds."""
    pytest.skip(NEEDS_EXECUTOR)


@pytest.mark.acceptance("H")
def test_H_stopped_joint_states_detected_and_new_motion_blocked():
    """Stop the joint_states source; header shows disconnected within DISCONNECT_TIMEOUT; submit is refused, no goal sent."""
    pytest.skip(NEEDS_EXECUTOR)
