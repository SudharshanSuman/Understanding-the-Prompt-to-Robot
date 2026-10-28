"""Scene constants. Frame: world == base of panda_link0, table top at z=0 (see munder_difflin_gazebo world SDF).

Ids equal config/scene.json ids exactly. Static bodies and destinations come from here; graspable bodies
are read live from Gazebo ground truth (/model/<id>/pose, bridged PosePublisher) and fall back to these initial poses.
"""
HAND_LINK = 'panda_hand'
ARM_JOINTS = [f'panda_joint{i}' for i in range(1, 8)]
READY = [0.0, -0.785, 0.0, -2.356, 0.0, 1.571, 0.785]
GRIP_CENTER_BELOW_HAND = 0.095  # object centre is this far below the panda_hand origin when grasped
FINGER_OPEN = 0.04  # panda_finger_joint1 travel per finger (m)

# id -> dict(shape, size/radius+height, init xyz, grip half-width = finger position when closed on it)
OBJECTS = {
    'red_cube': dict(shape='box', dims=(0.04, 0.04, 0.04), init=(0.45, 0.15, 0.02), half_width=0.02),
    'blue_cube': dict(shape='box', dims=(0.04, 0.04, 0.04), init=(0.35, -0.12, 0.02), half_width=0.02),
    'green_cylinder': dict(shape='cylinder', dims=(0.025, 0.08), init=(0.55, -0.05, 0.04), half_width=0.025),
}
# static collision bodies for the MoveIt planning scene: id -> list of (box dims, centre xyz)
_W, _H, _T = 0.24, 0.08, 0.01
STATIC = {
    # table top lowered 1 cm in the planning scene so panda_link0 (which sits on it) is not in start collision
    'table': [((1.1, 1.0, 0.4), (0.3, 0.0, -0.21))],
    'platform': [((0.14, 0.14, 0.005), (0.30, 0.35, 0.0025))],
    'storage_box': [
        ((_W + 2 * _T, _W + 2 * _T, _T), (0.45, -0.40, _T / 2)),
        ((_T, _W + 2 * _T, _H), (0.45 + (_W + _T) / 2, -0.40, _H / 2)),
        ((_T, _W + 2 * _T, _H), (0.45 - (_W + _T) / 2, -0.40, _H / 2)),
        ((_W, _T, _H), (0.45, -0.40 + (_W + _T) / 2, _H / 2)),
        ((_W, _T, _H), (0.45, -0.40 - (_W + _T) / 2, _H / 2)),
    ],
}
# destination id -> dict(xy centre, support_top z (where the object bottom rests), tol = allowed xy error for 'placed')
DESTINATIONS = {
    'storage_box': dict(xy=(0.45, -0.40), top=0.01, tol=0.09),
    'platform': dict(xy=(0.30, 0.35), top=0.005, tol=0.05),
    'table_left': dict(xy=(0.55, 0.28), top=0.0, tol=0.05),
    'table_right': dict(xy=(0.65, -0.15), top=0.0, tol=0.05),
}


def half_height(obj_id: str) -> float:
    o = OBJECTS[obj_id]
    return o['dims'][2] / 2 if o['shape'] == 'box' else o['dims'][1] / 2
