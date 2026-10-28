"""L2 skeleton (opt-in: MD_RUN_GAZEBO=1). Physical outcomes are read from Gazebo, not from the code under test.
Each test skips with the missing prerequisite; none can pass vacuously. See TEST_PLAN.md sections 3 and 4."""
import pytest

pytestmark = [pytest.mark.gazebo, pytest.mark.slow]

NEEDS_SCENE = "NOT IMPLEMENTED: arm/world/model names undecided (TEST_PLAN gap 4)"


@pytest.mark.acceptance("A")
def test_A_joints_really_moved():
    """joint_states before/after differ by > MOTION_EPS; final within JOINT_TOL of trajectory end; action result SUCCESSFUL."""
    pytest.skip(NEEDS_SCENE)


@pytest.mark.acceptance("B")
def test_B_red_cube_grasped_transported_released_inside_box():
    """Cube tracks EE while gripper closed (GRASP_TRACK_TOL); settles inside box AABB with PLACE_MARGIN; gripper open;
    pipeline 'success' only after verification and agrees with measured pose."""
    pytest.skip(NEEDS_SCENE)


@pytest.mark.acceptance("C")
def test_C_blue_cube_untouched():
    """Blue cube displacement < UNTOUCHED_TOL_* at >= SAMPLE_HZ for the whole run; B placement criteria also hold."""
    pytest.skip(NEEDS_SCENE)


@pytest.mark.acceptance("G")
def test_G_cancel_physical_stop():
    pytest.skip(NEEDS_SCENE)


@pytest.mark.acceptance("H")
def test_H_gz_killed_mid_motion_reports_failed_not_success():
    pytest.skip(NEEDS_SCENE)
