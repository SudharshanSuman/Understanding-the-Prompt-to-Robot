import { useState, type ReactNode } from "react";
import { STAGES, type Environment, type ExecutorStatus, type PipelineEvent, type RosStub, type TaskDetail,
  type TokenizationResult } from "../types";
import { STATE_LABEL, stageViews } from "./StageList";
import { TokenizationPanel } from "./TokenizationPanel";

export const TABS = [
  "Tokenization", "Structured JSON", "Algorithm Explanation", "Spatial Coordinates", "Motion Planning",
  "ROS 2 Topics", "Robot State", "Logs", "Verification",
] as const;
export type Tab = (typeof TABS)[number];

export interface LogEntry {
  at: string;
  level: "info" | "warn" | "error";
  text: string;
}

interface Props {
  task: TaskDetail | null;
  events: PipelineEvent[];
  preview: TokenizationResult | null;
  env: Environment | null;
  telemetry: RosStub | null;
  inspector: RosStub | null;
  executor: ExecutorStatus | null;
  logs: LogEntry[];
}

function Json({ value }: { value: unknown }) {
  return <pre className="json">{JSON.stringify(value, null, 2)}</pre>;
}

/** Shows what a ROS-backed endpoint actually answered; nothing is filled in when ROS is absent. */
function RosBanner({ stub, executor }: { stub: RosStub | null; executor: ExecutorStatus | null }) {
  const parts = [];
  if (!stub) parts.push("not loaded");
  else if (!stub.available) parts.push(`ROS unavailable (${stub.reason ?? "no reason given"})`);
  if (executor && !executor.connected) parts.push("no executor connected");
  if (parts.length === 0) return null;
  return <div className="banner banner--warning" role="status">{parts.join(" · ")}. No live data is shown.</div>;
}

function StageEvents({ events, ids }: { events: PipelineEvent[]; ids: string[] }) {
  const views = stageViews(events);
  return (
    <table className="table">
      <thead><tr><th>Stage</th><th>State</th><th>Message</th></tr></thead>
      <tbody>
        {ids.map((id) => (
          <tr key={id}>
            <td>{STAGES.find((s) => s.id === id)?.label ?? id}</td>
            <td><span className={`status status--${views[id].state}`}>{STATE_LABEL[views[id].state]}</span></td>
            <td>{views[id].message || <span className="muted">—</span>}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

const EXPLAIN: Record<string, string> = {
  instruction: "The text is normalised (Unicode NFKC), control characters are removed and length is capped.",
  tokenization: "The text is split into tokens for display. A real tokenizer gives IDs; otherwise a labelled approximation without IDs.",
  interpretation: "Deterministic checks for unknown names and ambiguity run first; then an AI provider (or the rule-based fallback) proposes a task.",
  structured_task: "The proposal becomes a strict task object (Pydantic, unknown fields rejected).",
  schema_validation: "The task is checked against the scene: real, graspable objects, known destinations, and matching what the user asked.",
  feasibility: "Reachability and parser confidence. Reachability stays unconfirmed until MoveIt IK checks it.",
  grounding: "Object and destination names are resolved to poses from perception (ROS 2).",
  planning_scene: "MoveIt's collision scene is built from the perceived objects.",
  ik: "Inverse kinematics finds joint angles that reach the grasp and place poses.",
  planning: "A collision-free path is planned (e.g. OMPL RRTConnect).",
  trajectory_validation: "The path is checked for limits and collisions before execution.",
  execution: "ros2_control executes the trajectory; feedback is monitored.",
  simulation: "Gazebo simulates the motion and the grasp.",
  verification: "The object's observed position is checked against the destination.",
};

export function Inspector(p: Props) {
  const [tab, setTab] = useState<Tab>("Tokenization");
  const live = p.events.find((e) => e.stage === "tokenization" && e.data && "tokenization" in e.data);
  const tokens = (live?.data.tokenization as TokenizationResult | undefined) ?? p.preview;
  const views = stageViews(p.events);

  const panels: Record<Tab, ReactNode> = {
    "Tokenization": (
      <TokenizationPanel result={tokens} source={live ? `from task ${p.task?.task_id ?? ""}` : p.preview ? "preview" : undefined} />
    ),
    "Structured JSON": p.task ? (
      <div className="grid2">
        <div><h4>Task (RoboticTask)</h4><Json value={p.task.task} /></div>
        <div><h4>Validation report</h4><Json value={p.task.report} /></div>
        <div><h4>Plan</h4><Json value={p.task.plan} /></div>
        <div><h4>Clarification</h4><Json value={p.task.clarification} /></div>
      </div>
    ) : <p className="empty">No task selected.</p>,
    "Algorithm Explanation": (
      <div>
        <div className="banner banner--info">Educational explanation — describes what each stage does. The right-hand column is the live message from the selected task.</div>
        <table className="table">
          <thead><tr><th>Stage</th><th>What it does (educational)</th><th>Live</th></tr></thead>
          <tbody>
            {STAGES.map((s) => (
              <tr key={s.id}>
                <td>{s.label}</td>
                <td>{EXPLAIN[s.id]}</td>
                <td><span className={`status status--${views[s.id].state}`}>{STATE_LABEL[views[s.id].state]}</span> {views[s.id].message}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    ),
    "Spatial Coordinates": (
      <div>
        <RosBanner stub={p.env} executor={null} />
        <p>Perception mode: <code>{p.env?.perception_mode ?? "unknown"}</code>. Poses reported: {p.env?.objects.length ?? 0}.</p>
        <h4>Configured scene (names only, no coordinates)</h4>
        <Json value={p.env?.scene_config ?? null} />
      </div>
    ),
    "Motion Planning": (
      <div>
        <RosBanner stub={p.telemetry} executor={p.executor} />
        <StageEvents events={p.events} ids={["grounding", "planning_scene", "ik", "planning", "trajectory_validation"]} />
      </div>
    ),
    "ROS 2 Topics": (
      <div>
        <RosBanner stub={p.inspector} executor={null} />
        <h4>Inspector response</h4>
        <Json value={p.inspector} />
      </div>
    ),
    "Robot State": (
      <div>
        <RosBanner stub={p.telemetry} executor={p.executor} />
        <div className="grid2">
          <div><h4>Executor</h4><Json value={p.executor} /></div>
          <div><h4>Telemetry response</h4><Json value={p.telemetry} /></div>
        </div>
      </div>
    ),
    "Logs": p.logs.length === 0 ? <p className="empty">No log entries.</p> : (
      <ol className="logs" aria-live="polite">
        {p.logs.map((l, i) => (
          <li key={i} className={`log log--${l.level}`}><time>{l.at}</time> {l.text}</li>
        ))}
      </ol>
    ),
    "Verification": (
      <div>
        {views.verification.state !== "success" && (
          <div className="banner banner--warning" role="status">
            Not verified — {p.executor?.connected ? "verification has not succeeded" : "no executor connected; nothing was executed"}.
            Success is reported only from observed execution and verification.
          </div>
        )}
        <StageEvents events={p.events} ids={["execution", "simulation", "verification"]} />
      </div>
    ),
  };

  return (
    <section className="panel bottom" aria-label="Inspector">
      <div className="tabs" role="tablist">
        {TABS.map((t) => (
          <button key={t} type="button" role="tab" id={`tab-${t}`} aria-selected={tab === t}
                  aria-controls="tabpanel" className={`tab${tab === t ? " tab--on" : ""}`} onClick={() => setTab(t)}>
            {t}
          </button>
        ))}
      </div>
      <div id="tabpanel" role="tabpanel" aria-labelledby={`tab-${tab}`} className="tabpanel">{panels[tab]}</div>
    </section>
  );
}
