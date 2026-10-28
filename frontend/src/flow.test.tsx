import { afterEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, render, screen } from "@testing-library/react";
import { fieldTokens, flowOutcome, flowSteps, planFrom, tokensFrom } from "./flow";
import { buildTimeline, MAX_GAP_MS, useReplay } from "./replay";
import { FlowView } from "./components/FlowView";
import { STAGES, type PipelineEvent, type StageState } from "./types";

afterEach(cleanup);

let seq = 0;
const T0 = Date.parse("2026-10-28T10:00:00Z");
const ev = (stage: string, state: StageState, ms: number, message = "", data: Record<string, unknown> = {}): PipelineEvent => ({
  event_id: `t:${seq++}`, stage, state, message, data, timestamp: new Date(T0 + ms).toISOString(),
});
const TEXT = "Put the red cube in the storage box";
const words = TEXT.split(" ");
let pos = 0;
const TOKENS = {
  raw_text: TEXT, tokenizer_name: "approximate", is_live_model_tokenization: false,
  tokens: words.map((w, index) => { const start = TEXT.indexOf(w, pos); pos = start + w.length;
    return { index, text: w, start, end: start + w.length, token_id: null, is_approximate: true, role: null }; }),
};
const PLAN = { action: "pick_and_place", object: "red_cube", destination: "storage_box", confidence: 0.92 };

function headless(): PipelineEvent[] {
  return [
    ev("instruction", "running", 0), ev("instruction", "success", 2, "instruction accepted", { instruction: TEXT }),
    ev("tokenization", "running", 3), ev("tokenization", "warning", 5, "approximate", { tokenization: TOKENS }),
    ev("interpretation", "running", 6), ev("interpretation", "success", 406, "interpreted by local"),
    ev("structured_task", "running", 407), ev("structured_task", "success", 408, "task proposal built", { plan: PLAN }),
    ev("schema_validation", "running", 409), ev("schema_validation", "success", 410, "ok"),
    ev("feasibility", "running", 411), ev("feasibility", "success", 412, "task is feasible"),
  ];
}

describe("flow state machine", () => {
  it("measures durations from event timestamps and reports no_executor honestly", () => {
    const events = [...headless(), ...["grounding", "planning_scene", "ik", "planning", "trajectory_validation",
      "execution", "simulation", "verification"].map((s) => ev(s, "cancelled", 413, "no executor connected",
      { reason: "headless_run_complete" }))];
    const steps = flowSteps(events);
    expect(steps.find((s) => s.id === "interpretation")?.durationMs).toBe(400);
    expect(steps.find((s) => s.id === "grounding")?.durationMs).toBeNull(); // never started: no invented duration
    expect(flowOutcome(steps)).toMatchObject({ phase: "no_executor", stage: "grounding" });
  });

  it("is running while a stage runs, completed only when verification succeeded", () => {
    const run = [...headless(), ev("grounding", "running", 500)];
    expect(flowOutcome(flowSteps(run))).toMatchObject({ phase: "running", stage: "grounding" });
    const done = [...headless(), ...["grounding", "planning_scene", "ik", "planning", "trajectory_validation",
      "execution", "simulation", "verification"].flatMap((s, i) => [ev(s, "running", 500 + i * 10), ev(s, "success", 505 + i * 10, `${s} ok`)])];
    expect(flowOutcome(flowSteps(done)).phase).toBe("completed");
  });

  it("a failed safety stage is a rejection; a failed ROS stage is a failure", () => {
    const rejected = [...headless().slice(0, 10), ev("feasibility", "running", 411), ev("feasibility", "failed", 412, "out of reach")];
    expect(flowOutcome(flowSteps(rejected))).toEqual({ phase: "rejected", stage: "feasibility", message: "out of reach" });
    const failed = [...headless(), ev("ik", "running", 500), ev("ik", "failed", 520, "no IK")];
    expect(flowOutcome(flowSteps(failed))).toMatchObject({ phase: "failed", stage: "ik" });
  });

  it("clarification wins over the cancelled stages after it", () => {
    const events = [...headless().slice(0, 5), ev("interpretation", "needs_clarification", 50, "Which cube?"),
      ev("structured_task", "cancelled", 51, "skipped: interpretation ended needs_clarification")];
    expect(flowOutcome(flowSteps(events))).toMatchObject({ phase: "needs_clarification", message: "Which cube?" });
  });

  it("extracts tokens and plan, and maps plan fields to matching words", () => {
    const events = headless();
    const tokens = tokensFrom(events)!;
    const plan = planFrom(events)!;
    expect(plan).toEqual(PLAN);
    const map = fieldTokens(plan, tokens.tokens);
    const text = (ids: number[]) => ids.map((i) => tokens.tokens[i].text);
    expect(text(map.action)).toEqual(["Put"]);
    expect(text(map.object)).toEqual(["red", "cube"]);
    expect(text(map.destination)).toEqual(["storage", "box"]);
  });
});

describe("FlowView", () => {
  const props = { replay: { active: false, progress: 0, shortened: 0 }, canReplay: true, onReplay: () => {}, onStopReplay: () => {} };

  it("shows tokens, the approximate label and the plan card", () => {
    render(<FlowView events={headless()} instruction={TEXT} {...props} />);
    expect(screen.getByLabelText(`${words.length} tokens`)).toBeTruthy();
    expect(screen.getByText(/approximate: not the model's tokenizer/)).toBeTruthy();
    expect(screen.getByLabelText("Interpreted task").textContent).toContain("red_cube");
    expect(document.querySelector('[data-token-index="2"]')?.className).toContain("flow-token--object");
  });

  it("renders a rejection honestly", () => {
    const events = [...headless().slice(0, 10), ev("feasibility", "running", 411), ev("feasibility", "failed", 412, "out of reach")];
    render(<FlowView events={events} instruction={TEXT} {...props} />);
    const out = screen.getByRole("status");
    expect(out.dataset.phase).toBe("rejected");
    expect(out.textContent).toContain("nothing was sent to the robot");
    expect(out.textContent).toContain("out of reach");
  });

  it("renders a clarification request honestly, with no plan card", () => {
    const events = [...headless().slice(0, 5), ev("interpretation", "needs_clarification", 50, "Which cube?")];
    render(<FlowView events={events} instruction={TEXT} {...props} />);
    expect(screen.getByRole("status").dataset.phase).toBe("needs_clarification");
    expect(screen.queryByLabelText("Interpreted task")).toBeNull();
    expect(document.querySelector('[data-stage="interpretation"]')?.getAttribute("data-state")).toBe("needs_clarification");
  });

  it("says when it is a replay", () => {
    render(<FlowView events={headless()} instruction={TEXT} {...props} replay={{ active: true, progress: 0.5, shortened: 1 }} />);
    expect(screen.getByText(/Replay of the recorded run \(50%\); 1 pause/)).toBeTruthy();
    expect(screen.getByRole("button", { name: "Stop replay" })).toBeTruthy();
  });
});

describe("replay timeline", () => {
  it("merges events and telemetry by time and caps long pauses", () => {
    const events = [ev("instruction", "running", 0), ev("execution", "running", 10_000)];
    const frames = [{ at: T0 + 500, payload: { n: 1 } }, { at: T0 + 10_200, payload: { n: 2 } }];
    const tl = buildTimeline(events, frames);
    expect(tl.items.map((i) => i.kind)).toEqual(["event", "telemetry", "event", "telemetry"]);
    expect(tl.delays).toEqual([0, 500, MAX_GAP_MS, 200]);
    expect(tl.shortened).toBe(1);
  });
});

// The backend first announces every stage as waiting, then runs them; stages after the stop are cancelled.
function backendRun(): PipelineEvent[] {
  return [
    ...STAGES.map((st) => ev(st.id, "waiting", 0)),
    ...headless(),
    ...STAGES.slice(6).map((st) => ev(st.id, "cancelled", 413, "no executor connected", { reason: "headless_run_complete" })),
  ];
}

function ReplayHarness({ events }: { events: PipelineEvent[] }) {
  const replay = useReplay(events, () => []);
  const shown = replay.state.active ? events.slice(0, replay.state.eventCount) : events;
  return <FlowView events={shown} instruction={TEXT} replay={replay.state} canReplay onReplay={replay.start}
                   onStopReplay={replay.stop} />;
}

describe("replay drives the flow (D-V1)", () => {
  afterEach(() => { vi.useRealTimers(); });

  it("shows the stage tiles from the first recorded update, advances them and ends on the outcome", () => {
    vi.useFakeTimers();
    const events = backendRun();
    render(<ReplayHarness events={events} />);
    act(() => { screen.getByRole("button", { name: "Replay last run" }).click(); });
    act(() => { vi.advanceTimersByTime(0); });
    // only "waiting" announcements so far: the tiles are drawn, not the empty placeholder
    expect(document.querySelectorAll(".flow-stage").length).toBe(STAGES.length);
    expect(screen.getByText(/recorded update \d+ of 34/)).toBeTruthy();
    act(() => { vi.advanceTimersByTime(6); }); // past instruction (2 ms), tokenization (5 ms), interpretation starts (6 ms)
    expect(document.querySelector('[data-stage="instruction"]')?.getAttribute("data-state")).toBe("success");
    expect(document.querySelectorAll(".flow-token").length).toBe(words.length);
    expect(document.querySelector('[data-stage="interpretation"]')?.getAttribute("data-state")).toBe("running");
    act(() => { vi.advanceTimersByTime(1000); });
    expect(screen.queryByText(/Replay of the recorded run/)).toBeNull();
    expect(document.querySelector(".flow-outcome")?.getAttribute("data-phase")).toBe("no_executor");
  });
});

describe("stages that never ran (D-V2)", () => {
  const props = { replay: { active: false, progress: 0, shortened: 0 }, canReplay: true, onReplay: () => {}, onStopReplay: () => {} };

  it("labels stages cancelled before they started as 'Not run'", () => {
    render(<FlowView events={backendRun()} instruction={TEXT} {...props} />);
    const tile = document.querySelector('[data-stage="verification"]');
    expect(tile?.textContent).toContain("Not run");
    expect(tile?.getAttribute("data-state")).toBe("cancelled"); // the backend's state is kept as data
    expect(tile?.getAttribute("data-ran")).toBe("false");
  });

  it("keeps 'Cancelled' for a stage that was running when it was cancelled", () => {
    const events = [...headless(), ev("grounding", "running", 420), ev("grounding", "cancelled", 430, "cancelled by user")];
    render(<FlowView events={events} instruction={TEXT} {...props} />);
    const tile = document.querySelector('[data-stage="grounding"]');
    expect(tile?.textContent).toContain("Cancelled");
    expect(tile?.hasAttribute("data-ran")).toBe(false);
  });
});
