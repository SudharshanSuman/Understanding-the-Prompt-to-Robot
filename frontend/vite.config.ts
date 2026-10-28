/// <reference types="vitest/config" />
import { defineConfig, loadEnv, type Plugin } from "vite";
import react from "@vitejs/plugin-react";

// Strict CSP, production build only: Vite's dev server needs inline scripts/styles for HMR.
function csp(apiBase: string): Plugin {
  const http = new URL(apiBase);
  const ws = `${http.protocol === "https:" ? "wss:" : "ws:"}//${http.host}`;
  const policy = [
    "default-src 'self'",
    "script-src 'self'",
    "style-src 'self'",
    "img-src 'self' data:",
    `connect-src 'self' ${http.origin} ${ws}`,
    "object-src 'none'",
    "base-uri 'none'",
    "form-action 'none'",
  ].join("; ");
  return {
    name: "md-csp",
    apply: "build",
    transformIndexHtml: (html) =>
      html.replace("<head>", `<head>\n    <meta http-equiv="Content-Security-Policy" content="${policy}" />`),
  };
}

// SEC-014-D1: a meta CSP cannot carry frame-ancestors, so the dev and preview servers send it as a header.
const FRAME_HEADERS = { "Content-Security-Policy": "frame-ancestors 'none'", "X-Frame-Options": "DENY" };

export default defineConfig(({ mode }) => {
  // Only VITE_API_BASE is read: a non-secret URL. Never put a token or key in a VITE_ variable.
  const apiBase = loadEnv(mode, ".", "VITE_").VITE_API_BASE || "http://127.0.0.1:8000";
  return {
    plugins: [react(), csp(apiBase)],
    define: { __API_BASE__: JSON.stringify(apiBase) },
    build: { sourcemap: false, target: "es2022" },
    server: { headers: FRAME_HEADERS },
    preview: { headers: FRAME_HEADERS },
    test: { environment: "jsdom", include: ["src/**/*.test.tsx"] },
  };
});
