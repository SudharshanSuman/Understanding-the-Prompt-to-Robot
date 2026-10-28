"""Single place for pass/fail thresholds. PROPOSED defaults (TEST_PLAN.md section 3);
Jim/Pam must confirm them against the chosen arm, gripper and scene."""

MOTION_EPS = 0.05          # rad: minimum joint change that counts as "moved"
JOINT_TOL = 0.02           # rad: final joints vs trajectory end point
PLACE_MARGIN = 0.01        # m: cube must be this far inside the box AABB
SETTLE_VEL = 0.01          # m/s: cube counts as settled below this
UNTOUCHED_TOL_POS = 0.005  # m: obstacle displacement allowed
UNTOUCHED_TOL_DEG = 2.0    # deg
CLEARANCE_MIN = 0.01       # m: min arm-to-obstacle distance along the path
GRASP_TRACK_TOL = 0.01     # m: EE-to-object relative pose drift while carried
STOP_VEL = 0.01            # rad/s
STOP_TIMEOUT = 3.0         # s after cancel
DISCONNECT_TIMEOUT = 5.0   # s until the UI reports sim disconnected
SAMPLE_HZ = 10             # minimum pose/joint sampling rate during a run
