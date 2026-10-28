import { afterEach, describe, expect, it } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { Inspector } from "./Inspector";
import type { PipelineEvent, TokenizationResult } from "../types";

afterEach(cleanup);

const tok = (text: string): TokenizationResult => ({
  raw_text: text,
  tokenizer_name: "regex_word_level",
  is_live_model_tokenization: false,
  tokens: text.split(" ").map((t, i) => ({ index: i, text: t, start: 0, end: 0, token_id: null, is_approximate: true, role: null })),
});

const taskEvent: PipelineEvent = {
  event_id: "e1", stage: "tokenization", state: "success", timestamp: "2026-10-28T00:00:00Z", message: "",
  data: { tokenization: tok("Put the red cube") },
};

const base = { task: null, env: null, telemetry: null, inspector: null, executor: null, logs: [] };

describe("Inspector tokenization tab (UI-1)", () => {
  it("shows a requested preview even while a task is selected", () => {
    render(<Inspector {...base} events={[taskEvent]} preview={tok("Pick up the green cylinder")} />);
    expect(screen.getByText("cylinder")).toBeTruthy();
    expect(screen.queryByText("cube")).toBeNull();
    expect(screen.getByText(/preview/)).toBeTruthy();
  });

  it("shows the task's tokenization when there is no preview", () => {
    render(<Inspector {...base} events={[taskEvent]} preview={null} />);
    expect(screen.getByText("cube")).toBeTruthy();
  });
});
