import { fieldTokens, flowOutcome, flowSteps, notRun, planFrom, tokensFrom, type FlowOutcome, type PlanField } from "../flow";
import type { PipelineEvent } from "../types";
import { STATE_LABEL } from "./StageList";

interface Props {
  events: PipelineEvent[];
  instruction: string | null;
  replay: { active: boolean; progress: number; shortened: number; step?: number; total?: number };
  canReplay: boolean;
  onReplay: () => void;
  onStopReplay: () => void;
}

const OUTCOME_TEXT: Record<FlowOutcome["phase"], string> = {
  idle: "",
  running: "Running",
  completed: "Completed: verified in simulation",
  rejected: "Rejected by the safety checks: nothing was sent to the robot",
  needs_clarification: "Needs clarification: nothing was sent to the robot",
  failed: "Failed",
  cancelled: "Cancelled",
  no_executor: "Passed the safety checks, but no executor is connected: nothing was executed",
};

const FIELD_LABEL: Record<PlanField, string> = { action: "Action", object: "Object", destination: "Destination" };

function duration(ms: number | null): string {
  if (ms === null) return "";
  return ms < 1000 ? `${ms} ms` : `${(ms / 1000).toFixed(1)} s`;
}

/** Prompt -> tokens -> TaskPlan -> checks -> motion, drawn only from the pipeline events it is given. */
export function FlowView({ events, instruction, replay, canReplay, onReplay, onStopReplay }: Props) {
  const steps = flowSteps(events);
  const outcome = flowOutcome(steps);
  const tokens = tokensFrom(events);
  const plan = planFrom(events);
  const fields = plan && tokens ? fieldTokens(plan, tokens.tokens) : null;
  const fieldOf = (index: number): PlanField | null =>
    fields ? ((["object", "destination", "action"] as PlanField[]).find((f) => fields[f].includes(index)) ?? null) : null;
  const approximate = tokens ? !tokens.is_live_model_tokenization || tokens.tokens.some((t) => t.is_approximate) : false;
  const text = (steps.find((s) => s.id === "instruction")?.data.instruction as string | undefined) ?? instruction ?? "";
  let group = "";

  return (
    <section className="panel flow" aria-label="Prompt to arm flow">
      <h2 className="panel-title">
        Prompt → arm
        <span className="flow-actions">
          {replay.active ? (
            <button type="button" className="btn btn--small" onClick={onStopReplay}>Stop replay</button>
          ) : (
            <button type="button" className="btn btn--small" onClick={onReplay} disabled={!canReplay}>Replay last run</button>
          )}
        </span>
      </h2>
      {replay.active && (
        <div className="banner banner--info" role="status">
          Replay of the recorded run ({Math.round(replay.progress * 100)}%{replay.total
            ? `, recorded update ${replay.step ?? 0} of ${replay.total}` : ""}){replay.shortened > 0
            ? `; ${replay.shortened} pause(s) longer than 2 s shortened` : ""}. Not live.
        </div>
      )}
      {outcome.phase === "idle" ? (
        <p className="empty">Submit a command to see it become tokens, a task, checks and arm motion.</p>
      ) : (
        <>
          <div className="flow-row">
            <span className="flow-label">Instruction</span>
            <q className="flow-instruction">{text}</q>
          </div>

          <div className="flow-row">
            <span className="flow-label">Tokens</span>
            {tokens ? (
              <div className="flow-tokens" aria-label={`${tokens.tokens.length} tokens`}>
                {tokens.tokens.map((t) => {
                  const f = fieldOf(t.index);
                  return (
                    <span key={t.index} className={`flow-token${f ? ` flow-token--${f}` : ""}`} data-token-index={t.index}
                          style={{ animationDelay: `${Math.min(t.index, 60) * 40}ms` }} title={f ? FIELD_LABEL[f] : undefined}>
                      {t.text}
                    </span>
                  );
                })}
                {approximate && <span className="badge badge--warning">approximate: not the model's tokenizer</span>}
              </div>
            ) : <span className="muted">{steps[1].state === "waiting" ? "waiting" : steps[1].message || "no tokens"}</span>}
          </div>

          <div className="flow-row">
            <span className="flow-label">Task</span>
            {plan ? (
              <div className="flow-plan" aria-label="Interpreted task">
                {(["action", "object", "destination"] as PlanField[]).map((f) => (
                  <span key={f} className={`flow-field flow-field--${f}`}>
                    <b>{FIELD_LABEL[f]}</b> <code>{plan[f]}</code>
                    {fields && fields[f].length === 0 && <span className="muted"> (no matching word)</span>}
                  </span>
                ))}
                <span className="flow-field"><b>Confidence</b> {plan.confidence === null ? "n/a" : plan.confidence.toFixed(2)}</span>
                <span className="note small">Colours mark words in your text that match each field (a text match done here; the
                  model does not report which tokens it used).</span>
              </div>
            ) : <span className="muted">{steps[2].message || "not interpreted yet"}</span>}
          </div>

          <ol className="flow-stages" aria-label="Stages">
            {steps.map((s) => {
              const header = s.group !== group ? (group = s.group) : null;
              const skipped = notRun(s);
              return (
                <li key={s.id} className={`flow-stage flow-stage--${skipped ? "not_run" : s.state}`} data-stage={s.id}
                    data-state={s.state} data-ran={skipped ? "false" : undefined}
                    title={s.message || undefined}>
                  {header && <span className="flow-group">{header}</span>}
                  <span className="flow-stage-name">{s.label}</span>
                  <span className="flow-stage-state">{skipped ? "Not run" : STATE_LABEL[s.state]}{s.durationMs !== null ? ` · ${duration(s.durationMs)}` : ""}</span>
                </li>
              );
            })}
          </ol>

          {outcome.phase !== "running" && (
            <div className={`flow-outcome flow-outcome--${outcome.phase}`} role="status" data-phase={outcome.phase}>
              <b>{OUTCOME_TEXT[outcome.phase]}</b>
              {outcome.stage && outcome.message && <span> · {steps.find((s) => s.id === outcome.stage)?.label}: {outcome.message}</span>}
            </div>
          )}
        </>
      )}
    </section>
  );
}
