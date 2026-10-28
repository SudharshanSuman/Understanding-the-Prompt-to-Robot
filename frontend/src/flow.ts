// Prompt-to-arm flow: derives what the Flow view shows from the real pipeline events only.
import { STAGES, type PipelineEvent, type StageState, type TokenizationResult, type TokenUnit } from "./types";

const TERMINAL: ReadonlySet<StageState> = new Set(["success", "warning", "failed", "cancelled", "needs_clarification"]);

export interface FlowStep {
  id: string;
  label: string;
  group: string;
  state: StageState;
  seen: boolean; // at least one event arrived for this stage
  message: string;
  data: Record<string, unknown>;
  startedAt: number | null; // ms epoch of the first 'running' event
  endedAt: number | null; // ms epoch of the terminal event
  durationMs: number | null; // only when both ends were observed
}

/** Cancelled before it ever started: the pipeline stopped earlier, so this stage simply did not run. */
export const notRun = (s: FlowStep): boolean => s.state === "cancelled" && s.startedAt === null;

/** One step per canonical stage; later events win. Durations come from event timestamps, never estimated. */
export function flowSteps(events: PipelineEvent[]): FlowStep[] {
  const steps = new Map<string, FlowStep>();
  for (const s of STAGES) {
    steps.set(s.id, { id: s.id, label: s.label, group: s.group, state: "waiting", seen: false, message: "", data: {},
      startedAt: null, endedAt: null, durationMs: null });
  }
  for (const ev of events) {
    const step = steps.get(ev.stage);
    if (!step) continue;
    const at = Date.parse(ev.timestamp);
    step.state = ev.state;
    step.seen = true;
    step.message = ev.message;
    step.data = ev.data;
    if (ev.state === "running" && step.startedAt === null && Number.isFinite(at)) step.startedAt = at;
    if (TERMINAL.has(ev.state) && Number.isFinite(at)) step.endedAt = at;
  }
  for (const step of steps.values()) {
    step.durationMs = step.startedAt !== null && step.endedAt !== null && step.endedAt >= step.startedAt
      ? step.endedAt - step.startedAt : null;
  }
  return [...steps.values()];
}

export type FlowPhase =
  | "idle" | "running" | "completed" | "rejected" | "needs_clarification" | "failed" | "cancelled" | "no_executor";

export interface FlowOutcome {
  phase: FlowPhase;
  stage: string | null; // the stage that decided the outcome
  message: string;
}

const SAFETY_STAGES = new Set(["instruction", "interpretation", "schema_validation", "feasibility"]);

/** The honest headline for a run: who stopped it and why, or that it completed. */
export function flowOutcome(steps: FlowStep[]): FlowOutcome {
  if (!steps.some((s) => s.seen)) return { phase: "idle", stage: null, message: "" };
  const clar = steps.find((s) => s.state === "needs_clarification");
  if (clar) return { phase: "needs_clarification", stage: clar.id, message: clar.message };
  const failed = steps.find((s) => s.state === "failed");
  if (failed) {
    return { phase: SAFETY_STAGES.has(failed.id) ? "rejected" : "failed", stage: failed.id, message: failed.message };
  }
  const firstCancel = steps.find((s) => s.state === "cancelled");
  if (firstCancel) {
    const noExec = firstCancel.data.reason === "headless_run_complete" || /no executor connected/.test(firstCancel.message);
    return { phase: noExec ? "no_executor" : "cancelled", stage: firstCancel.id, message: firstCancel.message };
  }
  if (steps.some((s) => s.state === "running" || s.state === "waiting")) {
    const cur = steps.find((s) => s.state === "running") ?? null;
    return { phase: "running", stage: cur?.id ?? null, message: cur?.message ?? "" };
  }
  return { phase: "completed", stage: "verification", message: steps[steps.length - 1].message };
}

export function tokensFrom(events: PipelineEvent[]): TokenizationResult | null {
  for (let i = events.length - 1; i >= 0; i--) {
    const t = events[i].stage === "tokenization" ? events[i].data.tokenization : undefined;
    if (t && typeof t === "object" && Array.isArray((t as TokenizationResult).tokens)) return t as TokenizationResult;
  }
  return null;
}

export interface PlanCard {
  action: string;
  object: string;
  destination: string;
  confidence: number | null;
}

/** The interpreted TaskPlan, as the structured_task event carries it. */
export function planFrom(events: PipelineEvent[]): PlanCard | null {
  for (let i = events.length - 1; i >= 0; i--) {
    const p = events[i].stage === "structured_task" ? events[i].data.plan : undefined;
    if (p && typeof p === "object") {
      const plan = p as Record<string, unknown>;
      if (typeof plan.action === "string" && typeof plan.object === "string" && typeof plan.destination === "string") {
        return { action: plan.action, object: plan.object, destination: plan.destination,
          confidence: typeof plan.confidence === "number" ? plan.confidence : null };
      }
    }
  }
  return null;
}

export type PlanField = "action" | "object" | "destination";

const ACTION_WORDS: Record<string, string[]> = {
  pick_and_place: ["pick", "place", "put", "move", "grab", "take", "drop", "set", "bring"],
};
const ALIAS_WORDS: Record<string, string[]> = { cube: ["block"] };

function fieldWords(field: PlanField, value: string): Set<string> {
  if (field === "action") return new Set(ACTION_WORDS[value] ?? value.split("_"));
  const words = value.toLowerCase().split("_").filter(Boolean);
  return new Set(words.flatMap((w) => [w, ...(ALIAS_WORDS[w] ?? [])]));
}

/**
 * Tokens whose text matches a word of each plan field. This is a text match done here for display;
 * the model does not report which tokens it used, and the UI says so.
 */
export function fieldTokens(plan: PlanCard, tokens: TokenUnit[]): Record<PlanField, number[]> {
  const out: Record<PlanField, number[]> = { action: [], object: [], destination: [] };
  for (const field of ["action", "object", "destination"] as PlanField[]) {
    const words = fieldWords(field, plan[field]);
    for (const t of tokens) {
      const w = t.text.trim().toLowerCase().replace(/[^a-z0-9]/g, "");
      if (w && words.has(w)) out[field].push(t.index);
    }
  }
  return out;
}
