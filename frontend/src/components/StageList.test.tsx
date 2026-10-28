import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { StageList, stageViews } from "./StageList";
import { STAGES, STAGE_STATES, type PipelineEvent, type StageState } from "../types";

afterEach(cleanup);

let seq = 0;
const ev = (stage: string, state: StageState, message = ""): PipelineEvent => ({
  event_id: `t:${seq++}`, stage, state, message, data: {}, timestamp: "2026-10-28T00:00:00Z",
});

describe("StageList", () => {
  it("lists the 14 canonical stages in order, all waiting with no events", () => {
    render(<StageList events={[]} selected={null} onSelect={() => {}} />);
    const items = screen.getAllByRole("button");
    expect(items.map((b) => b.dataset.stage)).toEqual(STAGES.map((s) => s.id));
    expect(items).toHaveLength(14);
    expect(items.every((b) => b.dataset.state === "waiting")).toBe(true);
  });

  it("shows the latest state of each stage, as text and not colour alone", () => {
    const events = [
      ...STAGES.map((s) => ev(s.id, "waiting")),
      ev("instruction", "running"), ev("instruction", "success", "instruction accepted"),
      ev("interpretation", "running"), ev("interpretation", "needs_clarification", "Which box do you mean?"),
      ...STAGES.slice(3).map((s) => ev(s.id, "cancelled", "skipped")),
    ];
    render(<StageList events={events} selected={null} onSelect={() => {}} />);
    const instruction = screen.getByRole("button", { name: /Instruction: Success/ });
    expect(instruction.textContent).toContain("instruction accepted");
    expect(screen.getByRole("button", { name: /Interpretation: Needs clarification/ }).textContent)
      .toContain("Which box do you mean?");
    expect(screen.getByRole("button", { name: /Verification: Cancelled/ })).toBeTruthy();
  });

  it("renders every one of the 7 states", () => {
    const events = STAGE_STATES.map((state, i) => ev(STAGES[i].id, state));
    render(<StageList events={events} selected={null} onSelect={() => {}} />);
    for (const [i, state] of STAGE_STATES.entries()) {
      const btn = document.querySelector(`[data-stage="${STAGES[i].id}"]`) as HTMLElement;
      expect(btn.dataset.state).toBe(state);
      expect(btn.className).toContain(`stage--${state}`);
    }
  });

  it("selects a stage for inspection", () => {
    const onSelect = vi.fn();
    render(<StageList events={[]} selected="ik" onSelect={onSelect} />);
    fireEvent.click(screen.getByRole("button", { name: /Feasibility/ }));
    expect(onSelect).toHaveBeenCalledWith("feasibility");
    expect(screen.getByRole("button", { name: /Inverse kinematics/ }).getAttribute("aria-pressed")).toBe("true");
  });

  it("marks ROS 2 stages and groups them", () => {
    render(<StageList events={[]} selected={null} onSelect={() => {}} />);
    expect(screen.getAllByText("ROS 2")).toHaveLength(8);
    expect(screen.getByText("Safety Interlock")).toBeTruthy();
  });

  it("ignores events for unknown stages", () => {
    const views = stageViews([ev("motion_planning", "success")]);
    expect(Object.keys(views)).toHaveLength(14);
    expect(views.planning.state).toBe("waiting");
  });
});
