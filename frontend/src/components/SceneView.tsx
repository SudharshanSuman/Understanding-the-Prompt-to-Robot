import type { TelemetryPose } from "../kinematics";
import type { Environment } from "../types";
import { lazy, Suspense } from "react";

// three.js is loaded only once there is telemetry to draw.
const ArmView3D = lazy(() => import("./ArmView3D").then((m) => ({ default: m.ArmView3D })));

interface Props {
  env: Environment | null;
  target: string | null;
  destination: string | null;
  pose: TelemetryPose | null; // live (or replayed) simulation telemetry; null = none
  telemetryReason: string | null; // why there is no telemetry, from the backend
  replaying: boolean;
}

/**
 * Live telemetry draws the 3D view. Without it, the scene from GET /environment/objects is drawn as a
 * schematic: items are laid out in a row, not at their real positions, and it says so.
 */
export function SceneView({ env, target, destination, pose, telemetryReason, replaying }: Props) {
  if (pose) {
    return (
      <section className="panel" aria-label="Robot and scene view">
        <h2 className="panel-title">
          Scene <span className={`badge ${replaying ? "badge--info" : "badge--ok"}`}>
            {replaying ? "replay of recorded simulation telemetry" : "simulation telemetry"}</span>
        </h2>
        <div className="kv-row small">
          <span className="kv"><b>Source</b> {pose.source}</span>
          {pose.perception && <span className="kv"><b>Object positions</b> {pose.perception}</span>}
          {pose.stage && <span className="kv"><b>Stage</b> {pose.stage}</span>}
          {pose.heldObject && <span className="kv"><b>Holding</b> {pose.heldObject}</span>}
          {pose.eStopLatched && <span className="badge badge--warning">E-stop latched</span>}
        </div>
        <Suspense fallback={<p className="muted small">Loading 3D view…</p>}>
          <ArmView3D pose={pose} target={target} destination={destination} />
        </Suspense>
      </section>
    );
  }
  const objects = env?.scene_config.objects ?? [];
  const destinations = env?.scene_config.destinations ?? [];
  const live = env?.available === true;
  const W = 640, H = 300;
  const slot = (i: number, n: number, y: number) => ({ x: ((i + 1) * W) / (n + 1), y });
  const boxW = (name: string, n: number) => Math.min(Math.max(68, name.length * 7.4 + 16), (W - 40) / n - 8);

  return (
    <section className="panel" aria-label="Robot and scene view">
      <h2 className="panel-title">Scene</h2>
      {!live && (
        <div className="banner banner--warning" role="status">
          No live Gazebo state — {replaying ? "no telemetry was recorded for this run" : telemetryReason ?? env?.reason ?? "ros unavailable"}. Schematic from the scene configuration;
          positions are illustrative, not measured.
        </div>
      )}
      <svg viewBox={`0 0 ${W} ${H}`} className="scene" role="img"
           aria-label={`Schematic of ${objects.length} configured objects and ${destinations.length} destinations`}>
        <rect x="20" y="40" width={W - 40} height={H - 70} rx="6" className="scene-table" />
        <text x="32" y="60" className="scene-caption">table (schematic, not to scale)</text>
        <g aria-hidden="true">
          <circle cx={W / 2} cy={H - 18} r="12" className="scene-robot" />
          <text x={W / 2 + 18} y={H - 13} className="scene-caption">arm base (pose unknown)</text>
        </g>
        {objects.map((o, i) => {
          const { x, y } = slot(i, objects.length, 115);
          const cls = o === target ? "scene-obj scene-obj--target" : o === destination ? "scene-obj scene-obj--dest" : "scene-obj";
          return (
            <g key={o}>
              <rect x={x - boxW(o, objects.length) / 2} y={y - 20} width={boxW(o, objects.length)} height="40" rx="4" className={cls} />
              <text x={x} y={y + 4} textAnchor="middle" className="scene-label">{o}</text>
            </g>
          );
        })}
        {destinations.map((d, i) => {
          const { x, y } = slot(i, destinations.length, 200);
          return (
            <g key={d}>
              <rect x={x - boxW(d, destinations.length) / 2} y={y - 16} width={boxW(d, destinations.length)} height="32" rx="4"
                    className={d === destination ? "scene-dest scene-dest--on" : "scene-dest"} />
              <text x={x} y={y + 4} textAnchor="middle" className="scene-label">{d}</text>
            </g>
          );
        })}
      </svg>
      <div className="legend">
        <span><i className="sw sw--target" /> target</span>
        <span><i className="sw sw--dest" /> destination</span>
        <span className="muted">Objects: {objects.length} · Destinations: {destinations.length} · Perception: {env?.perception_mode ?? "unknown"}</span>
      </div>
    </section>
  );
}
