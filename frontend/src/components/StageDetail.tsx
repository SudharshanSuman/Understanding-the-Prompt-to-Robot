import { STAGES, type PipelineEvent } from "../types";
import { STATE_LABEL } from "./StageList";

/** Every event a stage emitted (waiting → running → result), with its data. */
export function StageDetail({ stage, events }: { stage: string | null; events: PipelineEvent[] }) {
  if (!stage) return <p className="empty small">Select a stage to inspect it.</p>;
  const def = STAGES.find((s) => s.id === stage);
  const mine = events.filter((e) => e.stage === stage);
  return (
    <div className="stage-detail" aria-label={`Details for ${def?.label ?? stage}`}>
      <h3>{def?.label ?? stage}</h3>
      {mine.length === 0 ? <p className="empty small">No events yet.</p> : (
        <ol className="events">
          {mine.map((e) => (
            <li key={e.event_id}>
              <span className={`status status--${e.state}`}>{STATE_LABEL[e.state]}</span>{" "}
              <time className="muted small">{new Date(e.timestamp).toLocaleTimeString()}</time>
              {e.message && <div>{e.message}</div>}
              {Object.keys(e.data).length > 0 && (
                <details><summary>data</summary><pre className="json">{JSON.stringify(e.data, null, 2)}</pre></details>
              )}
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}
