/**
 * Desktop mode: the Electron preload exposes `window.mdDesktop` (see ../desktop/preload.cjs).
 * It hands over the per-launch backend URL and token in memory. In a normal browser it is absent.
 */
export interface DesktopSession {
  apiBase: string;
  token: string | null; // null: the app connected to an existing backend, so the user enters the token
}

interface Bridge {
  session(): Promise<DesktopSession>;
}

export function desktopBridge(): Bridge | null {
  const b = (window as { mdDesktop?: Bridge }).mdDesktop;
  return b && typeof b.session === "function" ? b : null;
}
