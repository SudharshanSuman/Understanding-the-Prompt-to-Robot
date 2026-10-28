import { afterEach, describe, expect, it } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { TokenizationPanel } from "./TokenizationPanel";
import type { TokenizationResult } from "../types";

afterEach(cleanup);

// Shape copied from a real backend response (regex_word_level approximation).
const approx: TokenizationResult = {
  raw_text: "Put the red cube",
  tokenizer_name: "regex_word_level",
  is_live_model_tokenization: false,
  note: "Approximation: words and punctuation split by a regex, not the model's tokenizer.",
  tokens: [
    { index: 0, text: "Put", start: 0, end: 3, token_id: null, is_approximate: true, role: null },
    { index: 1, text: "the", start: 4, end: 7, token_id: null, is_approximate: true, role: null },
    { index: 2, text: "red", start: 8, end: 11, token_id: null, is_approximate: true, role: null },
    { index: 3, text: "cube", start: 12, end: 16, token_id: null, is_approximate: true, role: null },
  ],
};

const real: TokenizationResult = {
  raw_text: "Put it",
  tokenizer_name: "cl100k_base",
  is_live_model_tokenization: true,
  tokens: [
    { index: 0, text: "Put", start: 0, end: 3, token_id: 10267, is_approximate: false, role: null },
    { index: 1, text: " it", start: 3, end: 6, token_id: 433, is_approximate: false, role: null },
  ],
};

describe("TokenizationPanel", () => {
  it("labels an approximation and never shows token IDs it does not have", () => {
    render(<TokenizationPanel result={approx} />);
    expect(screen.getByText("regex_word_level")).toBeTruthy();
    expect(screen.getByRole("status").textContent).toMatch(/Approximation/);
    expect(screen.getAllByText("n/a")).toHaveLength(4);
    expect(screen.getByText(/does not decide any physical action/)).toBeTruthy();
  });

  it("shows token boundaries over the original text", () => {
    render(<TokenizationPanel result={approx} />);
    const box = screen.getByLabelText("Original text with token boundaries");
    expect(box.textContent).toBe("Put the red cube");
    const spans = box.querySelectorAll("[data-token-index]");
    expect([...spans].map((s) => s.textContent)).toEqual(["Put", "the", "red", "cube"]);
  });

  it("shows real token IDs and no approximation badge for a real tokenizer", () => {
    render(<TokenizationPanel result={real} />);
    expect(screen.getByText("cl100k_base")).toBeTruthy();
    expect(screen.getByText("10267")).toBeTruthy();
    expect(screen.queryByText(/Approximation/)).toBeNull();
    expect(screen.getByText("Real tokenizer output")).toBeTruthy();
  });

  it("says when there is nothing to show", () => {
    render(<TokenizationPanel result={null} />);
    expect(screen.getByText(/No tokenization yet/)).toBeTruthy();
  });
});
