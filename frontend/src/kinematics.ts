// Franka Panda forward kinematics (Craig / modified DH, Franka "Robot and interface specifications")
// and the mapping from /ws/telemetry payloads to a pose. World frame = panda_link0 base (ros2_interfaces s8).

export type Vec3 = [number, number, number];
type Mat4 = number[]; // row-major 4x4

const PI2 = Math.PI / 2;
// [a, d, alpha] per joint 1..7, then the flange (link8, theta = 0).
const DH: [number, number, number][] = [
  [0, 0.333, 0], [0, 0, -PI2], [0, 0.316, PI2], [0.0825, 0, PI2],
  [-0.0825, 0.384, -PI2], [0, 0, PI2], [0.088, 0, PI2],
];
const FLANGE: [number, number, number] = [0, 0.107, 0];
export const PANDA_JOINTS = ["panda_joint1", "panda_joint2", "panda_joint3", "panda_joint4",
  "panda_joint5", "panda_joint6", "panda_joint7"] as const;
const HAND_YAW = -Math.PI / 4; // panda_hand is the flange rotated -45 deg about z
export const FINGER_BASE = 0.0584; // hand z offset where the fingers start
export const FINGER_TIP = 0.1034; // hand z offset of the fingertip centre

function mul(A: Mat4, B: Mat4): Mat4 {
  const C = new Array(16).fill(0);
  for (let r = 0; r < 4; r++) for (let c = 0; c < 4; c++) {
    let s = 0;
    for (let k = 0; k < 4; k++) s += A[r * 4 + k] * B[k * 4 + c];
    C[r * 4 + c] = s;
  }
  return C;
}

// T = RotX(alpha) * TransX(a) * RotZ(theta) * TransZ(d)
function dh(a: number, d: number, alpha: number, theta: number): Mat4 {
  const ca = Math.cos(alpha), sa = Math.sin(alpha), ct = Math.cos(theta), st = Math.sin(theta);
  return [
    ct, -st, 0, a,
    st * ca, ct * ca, -sa, -d * sa,
    st * sa, ct * sa, ca, d * ca,
    0, 0, 0, 1,
  ];
}

const rotZ = (t: number): Mat4 => [Math.cos(t), -Math.sin(t), 0, 0, Math.sin(t), Math.cos(t), 0, 0, 0, 0, 1, 0, 0, 0, 0, 1];
const origin = (T: Mat4): Vec3 => [T[3], T[7], T[11]];
const apply = (T: Mat4, p: Vec3): Vec3 => [
  T[0] * p[0] + T[1] * p[1] + T[2] * p[2] + T[3],
  T[4] * p[0] + T[5] * p[1] + T[6] * p[2] + T[7],
  T[8] * p[0] + T[9] * p[1] + T[10] * p[2] + T[11],
];

export interface ArmPose {
  joints: Vec3[]; // base, frames 1..7, flange: 9 points to draw links between
  hand: { origin: Vec3; fingers: [Vec3, Vec3, Vec3, Vec3] }; // left base, left tip, right base, right tip
}

/** Joint positions for 7 arm angles (rad) and a gripper opening (m, distance between fingers). */
export function forwardKinematics(q: number[], gripperOpening = 0.08): ArmPose {
  if (q.length !== 7) throw new Error("need 7 joint angles");
  let T: Mat4 = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1];
  const joints: Vec3[] = [origin(T)];
  for (let i = 0; i < 7; i++) {
    T = mul(T, dh(DH[i][0], DH[i][1], DH[i][2], q[i]));
    joints.push(origin(T));
  }
  T = mul(T, dh(FLANGE[0], FLANGE[1], FLANGE[2], 0));
  joints.push(origin(T));
  const H = mul(T, rotZ(HAND_YAW));
  const half = Math.max(0, Math.min(gripperOpening, 0.08)) / 2;
  return {
    joints,
    hand: {
      origin: origin(H),
      fingers: [apply(H, [0, half, FINGER_BASE]), apply(H, [0, half, FINGER_TIP]),
        apply(H, [0, -half, FINGER_BASE]), apply(H, [0, -half, FINGER_TIP])],
    },
  };
}

export interface TelemetryPose {
  source: string;
  perception: string | null;
  time: number | null; // s epoch (ROS host clock)
  taskId: string | null;
  stage: string | null;
  heldObject: string | null;
  eStopLatched: boolean;
  q: number[] | null; // null when any arm joint is missing or not finite: then no arm is drawn
  gripperOpening: number | null;
  objects: Record<string, Vec3>; // only entries with 3 finite numbers
  orientations: Record<string, Quat>; // object_poses orientation_xyzw, only 4 finite numbers of non-zero length
}

export type Quat = [number, number, number, number]; // x, y, z, w

const num = (v: unknown): number | null => (typeof v === "number" && Number.isFinite(v) ? v : null);

/** A /ws/telemetry or GET /telemetry payload -> pose, or null when it is not live data. */
export function telemetryPose(payload: unknown): TelemetryPose | null {
  if (!payload || typeof payload !== "object") return null;
  const p = payload as Record<string, unknown>;
  if (p.available !== true || !p.data || typeof p.data !== "object") return null;
  const d = p.data as Record<string, unknown>;
  const joints = (d.joints && typeof d.joints === "object" ? d.joints : {}) as Record<string, unknown>;
  const q = PANDA_JOINTS.map((j) => num(joints[j]));
  const objects: Record<string, Vec3> = {};
  if (d.objects && typeof d.objects === "object") {
    for (const [id, v] of Object.entries(d.objects as Record<string, unknown>)) {
      if (Array.isArray(v) && v.length === 3) {
        const xyz = v.map(num);
        if (xyz.every((n) => n !== null)) objects[id] = xyz as Vec3;
      }
    }
  }
  const orientations: Record<string, Quat> = {};
  if (d.object_poses && typeof d.object_poses === "object") {
    for (const [id, v] of Object.entries(d.object_poses as Record<string, unknown>)) {
      const pose = (v && typeof v === "object" ? v : {}) as Record<string, unknown>;
      const pos = Array.isArray(pose.position) && pose.position.length === 3 ? pose.position.map(num) : null;
      if (!objects[id] && pos?.every((n) => n !== null)) objects[id] = pos as Vec3;
      const q = Array.isArray(pose.orientation_xyzw) && pose.orientation_xyzw.length === 4 ? pose.orientation_xyzw.map(num) : null;
      if (q?.every((n) => n !== null) && Math.hypot(...(q as number[])) > 1e-6) orientations[id] = q as Quat;
    }
  }
  const str = (v: unknown) => (typeof v === "string" && v ? v : null);
  return {
    source: String(p.source ?? d.source ?? "unknown"),
    perception: str(d.perception),
    time: num(d.time),
    taskId: str(d.task_id),
    stage: str(d.stage),
    heldObject: str(d.held_object),
    eStopLatched: d.e_stop_latched === true,
    q: q.every((v) => v !== null) ? (q as number[]) : null,
    gripperOpening: num(d.gripper_opening_m),
    objects,
    orientations,
  };
}
