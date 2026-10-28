import { afterEach, describe, expect, it } from "vitest";
import { desktopBridge } from "./desktop";

describe("desktopBridge", () => {
  afterEach(() => { delete (window as { mdDesktop?: unknown }).mdDesktop; });

  it("is absent in a normal browser", () => {
    expect(desktopBridge()).toBeNull();
  });

  it("ignores a bridge without a session function", () => {
    (window as { mdDesktop?: unknown }).mdDesktop = { session: "nope" };
    expect(desktopBridge()).toBeNull();
  });

  it("returns the preload bridge when present", async () => {
    const session = { apiBase: "http://127.0.0.1:41234", token: null };
    (window as { mdDesktop?: unknown }).mdDesktop = { session: async () => session };
    await expect(desktopBridge()!.session()).resolves.toEqual(session);
  });
});
