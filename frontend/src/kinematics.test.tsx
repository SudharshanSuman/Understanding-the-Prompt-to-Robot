import { afterEach, describe, expect, it } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { forwardKinematics, telemetryPose } from "./kinematics";
import { SceneView } from "./components/SceneView";

afterEach(cleanup);

const close = (a: number[], b: number[], tol = 1e-6) => a.every((v, i) => Math.abs(v - b[i]) < tol);

describe("Panda forward kinematics", () => {
  it("zero pose puts the flange at (0.088, 0, 0.926), Franka's published value", () => {
    const arm = forwardKinematics([0, 0, 0, 0, 0, 0, 0]);
    expect(arm.joints).toHaveLength(9);
    expect(close(arm.joints[8], [0.088, 0, 0.926])).toBe(true);
    expect(close(arm.joints[1], [0, 0, 0.333])).toBe(true);
  });

  it("joint 1 rotates the whole arm about the base z axis", () => {
    const f = forwardKinematics([Math.PI / 2, 0, 0, 0, 0, 0, 0]).joints[8];
    expect(close(f, [0, 0.088, 0.926])).toBe(true);
  });

  it("at the ready pose the hand points down, below the flange", () => {
    const arm = forwardKinematics([0, -0.785, 0, -2.356, 0, 1.571, 0.785]);
    const tip = arm.hand.fingers[1];
    expect(tip[2]).toBeLessThan(arm.joints[8][2] - 0.09);
  });
});

const live = (data: Record<string, unknown>) => ({ available: true, source: "ros2_gazebo", data });
const JOINTS = Object.fromEntries([1, 2, 3, 4, 5, 6, 7].map((i) => [`panda_joint${i}`, i / 10]));

describe("telemetry -> pose", () => {
  it("maps joints, gripper and objects", () => {
    const p = telemetryPose(live({ joints: JOINTS, gripper_opening_m: 0.05, perception: "simulation-ground-truth",
      task_id: "task_1", time: 1700000000.5, objects: { red_cube: [0.45, 0.15, 0.02] } }))!;
    expect(p.q).toEqual([0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7]);
    expect(p.gripperOpening).toBe(0.05);
    expect(p.objects.red_cube).toEqual([0.45, 0.15, 0.02]);
    expect(p).toMatchObject({ source: "ros2_gazebo", perception: "simulation-ground-truth", taskId: "task_1" });
  });

  it("no live data -> null; a missing or null joint -> no arm; a bad object entry is dropped", () => {
    expect(telemetryPose({ available: false, reason: "ros unavailable" })).toBeNull();
    expect(telemetryPose(null)).toBeNull();
    const p = telemetryPose(live({ joints: { ...JOINTS, panda_joint4: null }, objects: { red_cube: [0.1, null, 0.2], blue_cube: [1, 2] } }))!;
    expect(p.q).toBeNull();
    expect(p.objects).toEqual({});
    expect(p.orientations).toEqual({});
  });
});

describe("SceneView", () => {
  const base = { env: null, target: null, destination: null, replaying: false };
  it("says ROS is unavailable when there is no telemetry", () => {
    render(<SceneView {...base} pose={null} telemetryReason="ros unavailable" />);
    const text = screen.getByLabelText("Robot and scene view").textContent ?? "";
    expect(text).toContain("No live Gazebo state");
    expect(text).toContain("ros unavailable");
  });

  it("labels live data as simulation telemetry and degrades without WebGL", async () => {
    const pose = telemetryPose(live({ joints: JOINTS, objects: {} }))!;
    render(<SceneView {...base} pose={pose} telemetryReason={null} />);
    expect(screen.getByText("simulation telemetry")).toBeTruthy();
    expect(await screen.findByText(/Not reported: red_cube, blue_cube, green_cylinder/, {}, { timeout: 5000 })).toBeTruthy();
    expect(await screen.findByText(/3D view unavailable/)).toBeTruthy(); // jsdom has no WebGL
  });
  it("reads object_poses: position as a fallback, orientation only when valid", () => {
    const p = telemetryPose(live({ joints: JOINTS, objects: { red_cube: [0.45, 0.15, 0.02] }, object_poses: {
      red_cube: { position: [9, 9, 9], orientation_xyzw: [0, 0, 0.3826834, 0.9238795] },
      blue_cube: { position: [0.5, -0.1, 0.02], orientation_xyzw: [0, 0, 0, 0] },
      green_cylinder: { position: [0.3, 0.2, 0.04], orientation_xyzw: [0, null, 0, 1] } } }))!;
    expect(p.objects.red_cube).toEqual([0.45, 0.15, 0.02]); // 'objects' wins; object_poses only fills gaps
    expect(p.objects.blue_cube).toEqual([0.5, -0.1, 0.02]);
    expect(p.orientations).toEqual({ red_cube: [0, 0, 0.3826834, 0.9238795] }); // zero and null quaternions dropped
  });
});
