import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { Header } from "./Header";

afterEach(cleanup);

const props = (stopping: boolean, onEStop = () => {}) => ({
  health: null, executor: null, providers: [], activeProvider: "auto", socket: "open" as const,
  stopReport: null, stopping, onSelectProvider: () => {}, onEStop, onDisconnect: () => {},
});

describe("Header E-STOP", () => {
  it("is enabled and clickable whenever the e-stop itself is not in flight (UI-2)", () => {
    const onEStop = vi.fn();
    render(<Header {...props(false, onEStop)} />);
    const btn = screen.getByRole("button", { name: "Emergency stop" }) as HTMLButtonElement;
    expect(btn.disabled).toBe(false);
    fireEvent.click(btn);
    expect(onEStop).toHaveBeenCalledOnce();
  });

  it("is disabled only while its own request is pending", () => {
    render(<Header {...props(true)} />);
    expect((screen.getByRole("button", { name: "Emergency stop" }) as HTMLButtonElement).disabled).toBe(true);
  });
});
