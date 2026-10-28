import { useEffect, useRef, useState } from "react";
import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import { forwardKinematics, type TelemetryPose, type Vec3 } from "../kinematics";

// Static bodies, copied from ros2_ws/src/munder_difflin_control/munder_difflin_control/scene.py (world = panda_link0).
const TABLE = { size: [1.1, 1.0] as const, centre: [0.3, 0.0] as const };
const STORAGE_BOX = { xy: [0.45, -0.4] as const, inner: 0.24, wall: 0.01, height: 0.08 };
const DESTINATION_MARKS: Record<string, [number, number]> = {
  platform: [0.3, 0.35], table_left: [0.55, 0.28], table_right: [0.65, -0.15], storage_box: [0.45, -0.4],
};
const OBJECT_SHAPES: Record<string, { kind: "box" | "cylinder"; size: number[]; color: number }> = {
  red_cube: { kind: "box", size: [0.04, 0.04, 0.04], color: 0xd9534f },
  blue_cube: { kind: "box", size: [0.04, 0.04, 0.04], color: 0x4a90e2 },
  green_cylinder: { kind: "cylinder", size: [0.025, 0.08], color: 0x3fb950 },
};

const UPRIGHT_CYLINDER = new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(1, 0, 0), Math.PI / 2);

interface Props {
  pose: TelemetryPose;
  target: string | null;
  destination: string | null;
}

function link(a: Vec3, b: Vec3, radius: number, material: THREE.Material): THREE.Mesh | null {
  const va = new THREE.Vector3(...a), vb = new THREE.Vector3(...b);
  const len = va.distanceTo(vb);
  if (len < 1e-6) return null;
  const mesh = new THREE.Mesh(new THREE.CylinderGeometry(radius, radius, len, 12), material);
  mesh.position.copy(va.clone().add(vb).multiplyScalar(0.5));
  mesh.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), vb.clone().sub(va).normalize());
  return mesh;
}

function staticScene(scene: THREE.Scene) {
  const table = new THREE.Mesh(new THREE.BoxGeometry(TABLE.size[0], TABLE.size[1], 0.02),
    new THREE.MeshStandardMaterial({ color: 0x2a3442 }));
  table.position.set(TABLE.centre[0], TABLE.centre[1], -0.01);
  scene.add(table);
  const wallMat = new THREE.MeshStandardMaterial({ color: 0x8b6b3f });
  const { xy, inner, wall, height } = STORAGE_BOX;
  const outer = inner + 2 * wall;
  const parts: [number, number, number, number, number, number][] = [
    [outer, outer, wall, 0, 0, wall / 2],
    [wall, outer, height, (inner + wall) / 2, 0, height / 2], [wall, outer, height, -(inner + wall) / 2, 0, height / 2],
    [inner, wall, height, 0, (inner + wall) / 2, height / 2], [inner, wall, height, 0, -(inner + wall) / 2, height / 2],
  ];
  for (const [sx, sy, sz, px, py, pz] of parts) {
    const m = new THREE.Mesh(new THREE.BoxGeometry(sx, sy, sz), wallMat);
    m.position.set(xy[0] + px, xy[1] + py, pz);
    scene.add(m);
  }
  const platform = new THREE.Mesh(new THREE.BoxGeometry(0.14, 0.14, 0.005), new THREE.MeshStandardMaterial({ color: 0xe3b341 }));
  platform.position.set(0.3, 0.35, 0.0025);
  scene.add(platform);
  scene.add(new THREE.AmbientLight(0xffffff, 0.6));
  const sun = new THREE.DirectionalLight(0xffffff, 1.2);
  sun.position.set(1, 1, 2);
  scene.add(sun);
}

/** Live 3D view: arm drawn from telemetry joint angles by forward kinematics, objects at their telemetry positions. */
export function ArmView3D({ pose, target, destination }: Props) {
  const host = useRef<HTMLDivElement | null>(null);
  const view = useRef<{ renderer: THREE.WebGLRenderer; scene: THREE.Scene; camera: THREE.PerspectiveCamera;
    dynamic: THREE.Group; render: () => void } | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const el = host.current;
    if (!el) return;
    let renderer: THREE.WebGLRenderer;
    try {
      renderer = new THREE.WebGLRenderer({ antialias: true });
    } catch (err) {
      setError(`3D view unavailable: WebGL could not start (${err instanceof Error ? err.message : String(err)})`);
      return;
    }
    const scene = new THREE.Scene();
    scene.background = new THREE.Color(0x0b0f14);
    const camera = new THREE.PerspectiveCamera(45, 1, 0.01, 20);
    camera.up.set(0, 0, 1); // ROS frame: z up
    camera.position.set(1.6, -1.1, 1.0);
    staticScene(scene);
    const dynamic = new THREE.Group();
    scene.add(dynamic);
    el.appendChild(renderer.domElement);
    const controls = new OrbitControls(camera, renderer.domElement);
    controls.target.set(0.35, 0, 0.25);
    const render = () => renderer.render(scene, camera);
    const resize = () => {
      const w = el.clientWidth || 640, h = el.clientHeight || 360;
      renderer.setSize(w, h, false);
      camera.aspect = w / h;
      camera.updateProjectionMatrix();
      render();
    };
    controls.addEventListener("change", render); // render on demand: no animation loop
    controls.update();
    const ro = typeof ResizeObserver === "function" ? new ResizeObserver(resize) : null;
    ro?.observe(el);
    resize();
    view.current = { renderer, scene, camera, dynamic, render };
    return () => {
      ro?.disconnect();
      controls.dispose();
      renderer.dispose();
      renderer.domElement.remove();
      view.current = null;
    };
  }, []);

  useEffect(() => {
    const v = view.current;
    if (!v) return;
    for (const child of [...v.dynamic.children]) {
      v.dynamic.remove(child);
      const mesh = child as THREE.Mesh;
      mesh.geometry?.dispose();
      (Array.isArray(mesh.material) ? mesh.material : [mesh.material]).forEach((m) => m?.dispose());
    }
    const linkMat = new THREE.MeshStandardMaterial({ color: 0xe6edf3 });
    const jointMat = new THREE.MeshStandardMaterial({ color: 0x4cc2ff });
    if (pose.q) {
      const arm = forwardKinematics(pose.q, pose.gripperOpening ?? 0.08);
      arm.joints.forEach((p, i) => {
        if (i > 0) { const m = link(arm.joints[i - 1], p, 0.035, linkMat); if (m) v.dynamic.add(m); }
        const s = new THREE.Mesh(new THREE.SphereGeometry(0.045, 16, 12), jointMat);
        s.position.set(...p);
        v.dynamic.add(s);
      });
      const [lb, lt, rb, rt] = arm.hand.fingers;
      for (const m of [link(lb, rb, 0.012, linkMat), link(lb, lt, 0.008, jointMat), link(rb, rt, 0.008, jointMat)]) if (m) v.dynamic.add(m);
    }
    for (const [id, xyz] of Object.entries(pose.objects)) {
      const shape = OBJECT_SHAPES[id];
      if (!shape) continue;
      const mat = new THREE.MeshStandardMaterial({ color: shape.color, emissive: id === target ? 0x1d4f6b : 0x000000 });
      const geo = shape.kind === "box" ? new THREE.BoxGeometry(shape.size[0], shape.size[1], shape.size[2])
        : new THREE.CylinderGeometry(shape.size[0], shape.size[0], shape.size[1], 24);
      const m = new THREE.Mesh(geo, mat);
      const q = pose.orientations[id];
      if (q) m.quaternion.set(q[0], q[1], q[2], q[3]).normalize(); // the reported orientation, not assumed upright
      if (shape.kind === "cylinder") m.quaternion.multiply(UPRIGHT_CYLINDER); // three's cylinder axis is y; the world's is z
      m.position.set(...xyz);
      v.dynamic.add(m);
    }
    if (destination && DESTINATION_MARKS[destination]) {
      const [x, y] = DESTINATION_MARKS[destination];
      const ring = new THREE.Mesh(new THREE.RingGeometry(0.07, 0.08, 40), new THREE.MeshBasicMaterial({ color: 0xe3b341, side: THREE.DoubleSide }));
      ring.position.set(x, y, 0.002);
      v.dynamic.add(ring);
    }
    v.render();
  }, [pose, target, destination]);

  const missing = Object.keys(OBJECT_SHAPES).filter((id) => !pose.objects[id]);
  const unoriented = Object.keys(OBJECT_SHAPES).filter((id) => pose.objects[id] && !pose.orientations[id]);
  return (
    <div className="arm3d">
      {error ? <p className="banner banner--warning" role="status">{error}</p> : <div ref={host} className="arm3d-canvas" aria-hidden="true" />}
      <p className="small muted">
        Arm: links drawn between joint positions computed from the reported angles (forward kinematics), not the robot mesh.
        {!pose.q && " No complete joint reading: arm not drawn."}
        {missing.length > 0 && ` Not reported: ${missing.join(", ")}.`}
        {unoriented.length > 0 && ` No orientation reported, drawn upright: ${unoriented.join(", ")}.`}
        {" "}Drag to rotate, scroll to zoom.
      </p>
    </div>
  );
}
