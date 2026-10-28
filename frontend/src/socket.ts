// /ws/pipeline client: first-message auth, subscribe to all tasks, keepalive ping, reconnect.
import type { Api } from "./api";

export interface Frame {
  channel: string;
  task_id?: string;
  payload: Record<string, unknown>;
}

export type SocketState = "connecting" | "open" | "closed" | "unauthorized";

const PING_MS = 60_000; // server closes idle sockets after 5 min
const UNAUTHORIZED = 4401;

export class PipelineSocket {
  private ws: WebSocket | null = null;
  private ping: ReturnType<typeof setInterval> | null = null;
  private retry: ReturnType<typeof setTimeout> | null = null;
  private delay = 1000;
  private stopped = false;

  constructor(
    private api: Api,
    private onFrame: (frame: Frame) => void,
    private onState: (state: SocketState) => void,
  ) {}

  start(): void {
    this.stopped = false;
    this.open();
  }

  stop(): void {
    this.stopped = true;
    if (this.retry) clearTimeout(this.retry);
    if (this.ping) clearInterval(this.ping);
    this.ws?.close(1000);
    this.ws = null;
  }

  private open(): void {
    this.onState("connecting");
    const ws = new WebSocket(this.api.wsUrl("/ws/pipeline"));
    this.ws = ws;
    ws.onopen = () => ws.send(JSON.stringify({ type: "auth", token: this.api.tokenForSocket }));
    ws.onmessage = (msg) => {
      if (typeof msg.data !== "string") return;
      let frame: Frame;
      try {
        frame = JSON.parse(msg.data) as Frame;
      } catch {
        return;
      }
      if (frame.channel === "system" && frame.payload.type === "auth_ok") {
        this.delay = 1000;
        this.onState("open");
        ws.send(JSON.stringify({ type: "subscribe" }));
        this.ping = setInterval(() => ws.send(JSON.stringify({ type: "ping" })), PING_MS);
      }
      this.onFrame(frame);
    };
    ws.onclose = (ev) => {
      if (this.ping) clearInterval(this.ping);
      if (ev.code === UNAUTHORIZED) {
        this.onState("unauthorized");
        return;
      }
      this.onState("closed");
      if (!this.stopped) {
        this.retry = setTimeout(() => this.open(), this.delay);
        this.delay = Math.min(this.delay * 2, 15_000);
      }
    };
  }
}
