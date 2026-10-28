import { useState } from "react";
import type { TaskDetail, TaskSummary } from "../types";

export const EXAMPLES = [
  "Pick up the red cube and place it in the storage box",
  "Move the blue cube to the right side of the table",
  "Move the red cube to the box without touching the blue cube",
  "Pick the green cylinder and place it on the platform",
  "Move the object to the left keeping it upright",
  "Move the box to the left",
  "Pick up the purple elephant",
];

interface Props {
  current: TaskDetail | null;
  history: TaskSummary[];
  busy: boolean;
  onSubmit: (text: string) => void;
  onStop: () => void;
  onReset: () => void;
  onPreview: (text: string) => void;
  onOpen: (taskId: string) => void;
  onClarify: (option: string | null, freeText: string) => void;
}

const ACTIVE = new Set(["accepted", "running", "executing"]);

export function CommandPanel(p: Props) {
  const [text, setText] = useState("");
  const [answer, setAnswer] = useState("");
  const [option, setOption] = useState<string | null>(null);
  const active = p.current !== null && ACTIVE.has(p.current.status);
  const clar = p.current?.status === "needs_clarification" ? p.current.clarification : null;

  return (
    <aside className="panel left" aria-label="Command">
      <h2 className="panel-title">Command</h2>
      <label htmlFor="cmd" className="label">Natural-language instruction</label>
      <textarea id="cmd" className="input" rows={4} value={text} maxLength={2048}
                onChange={(e) => setText(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && (e.ctrlKey || e.metaKey) && text.trim()) p.onSubmit(text);
                }}
                placeholder="e.g. Pick up the red cube and place it in the storage box" />
      <div className="row">
        <button type="button" className="btn btn--primary" disabled={!text.trim() || p.busy}
                onClick={() => p.onSubmit(text)}>Submit</button>
        <button type="button" className="btn" disabled={!active} onClick={p.onStop}
                title="Cancel the running task">Stop</button>
        <button type="button" className="btn" onClick={p.onReset} title="Clear the e-stop latch">Reset</button>
        <button type="button" className="btn btn--ghost" disabled={!text.trim()} onClick={() => p.onPreview(text)}>
          Preview tokens
        </button>
      </div>
      <p className="hint">Ctrl+Enter submits.</p>

      {clar && (
        <div className="clarify" role="alert">
          <h3>Clarification needed</h3>
          <p>{clar.question}</p>
          {clar.reason && <p className="muted small">{clar.reason}</p>}
          {clar.options.length > 0 && (
            <div className="options" role="radiogroup" aria-label="Options">
              {clar.options.map((o) => (
                <button key={o} type="button" role="radio" aria-checked={option === o}
                        className={`opt${option === o ? " opt--on" : ""}`} onClick={() => setOption(o)}>{o}</button>
              ))}
            </div>
          )}
          <label htmlFor="clar" className="label">Restate the full command</label>
          <input id="clar" className="input" value={answer} onChange={(e) => setAnswer(e.target.value)}
                 placeholder="e.g. Put the red cube on the platform" />
          <button type="button" className="btn btn--primary" disabled={!answer.trim() || p.busy}
                  onClick={() => p.onClarify(option, answer)}>Resume</button>
        </div>
      )}

      <h3 className="sub">Examples</h3>
      <ul className="examples">
        {EXAMPLES.map((ex) => (
          <li key={ex}><button type="button" className="link" onClick={() => setText(ex)}>{ex}</button></li>
        ))}
      </ul>

      <h3 className="sub">History</h3>
      {p.history.length === 0 ? <p className="empty">No tasks yet.</p> : (
        <ul className="history">
          {p.history.map((h) => (
            <li key={h.task_id}>
              <button type="button" className={`hist${p.current?.task_id === h.task_id ? " hist--on" : ""}`}
                      onClick={() => p.onOpen(h.task_id)}>
                <span className={`status status--${h.status}`}>{h.status.replace(/_/g, " ")}</span>
                <span className="hist-text">{h.instruction}</span>
                <span className="muted small">{new Date(h.created_at).toLocaleTimeString()}</span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </aside>
  );
}
