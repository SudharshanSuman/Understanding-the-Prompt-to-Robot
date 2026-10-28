import { STAGES, type PipelineEvent, type StageState } from "../types";

export const STATE_LABEL: Record<StageState, string> = {
  waiting: "Waiting",
  running: "Running",
  success: "Success",
  warning: "Warning",
  failed: "Failed",
  cancelled: "Cancelled",
  needs_clarification: "Needs clarification",
};

const STATE_GLYPH: Record<StageState, string> = {
  waiting: "○", running: "◐", success: "✓", warning: "!", failed: "✕", cancelled: "–", needs_clarification: "?",
};

export interface StageView {
  state: StageState;
  message: string;
  data: Record<string, unknown>;
}

/** Latest state of each canonical stage, from the event stream (later events win). */
export function stageViews(events: PipelineEvent[]): Record<string, StageView> {
  const views: Record<string, StageView> = {};
  for (const s of STAGES) views[s.id] = { state: "waiting", message: "", data: {} };
  for (const ev of events) {
    if (views[ev.stage]) views[ev.stage] = { state: ev.state, message: ev.message, data: ev.data };
  }
  return views;
}

interface Props {
  events: PipelineEvent[];
  selected: string | null;
  onSelect: (stage: string) => void;
}

export function StageList({ events, selected, onSelect }: Props) {
  const views = stageViews(events);
  let group = "";
  return (
    <ol className="stages" aria-label="Pipeline stages">
      {STAGES.map((s, i) => {
        const v = views[s.id];
        const header = s.group !== group ? (group = s.group) : null;
        return (
          <li key={s.id} className="stage-item">
            {header && <div className="stage-group">{header}</div>}
            <button
              type="button"
              className={`stage stage--${v.state}${selected === s.id ? " stage--selected" : ""}`}
              aria-pressed={selected === s.id}
              aria-label={`${i + 1}. ${s.label}: ${STATE_LABEL[v.state]}`}
              data-stage={s.id}
              data-state={v.state}
              onClick={() => onSelect(s.id)}
            >
              <span className="stage-glyph" aria-hidden="true">{STATE_GLYPH[v.state]}</span>
              <span className="stage-body">
                <span className="stage-name">
                  <span className="stage-num">{String(i + 1).padStart(2, "0")}</span> {s.label}
                  {s.ros && <span className="tag" title="Runs in ROS 2 only">ROS 2</span>}
                </span>
                <span className="stage-msg">{v.message || STATE_LABEL[v.state]}</span>
              </span>
              <span className="stage-state">{STATE_LABEL[v.state]}</span>
            </button>
          </li>
        );
      })}
    </ol>
  );
}
