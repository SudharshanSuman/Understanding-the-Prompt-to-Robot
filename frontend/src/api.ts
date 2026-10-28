// REST client for /api/v1. The token lives only in memory, entered by the user at runtime.
import type {
  Environment, ExecutorStatus, Health, ProviderStatus, RosStub, StopReport, TaskDetail, TaskSummary,
  TokenizationResult,
} from "./types";

declare const __API_BASE__: string;
export const DEFAULT_API_BASE: string = typeof __API_BASE__ === "string" ? __API_BASE__ : "http://127.0.0.1:8000";

export class ApiError extends Error {
  constructor(public status: number, message: string, public body?: unknown) {
    super(message);
  }
}

function describe(body: unknown, status: number): string {
  if (body && typeof body === "object" && "detail" in body) {
    const detail = (body as { detail: unknown }).detail;
    if (typeof detail === "string") return detail;
    if (detail && typeof detail === "object" && "status" in detail) return String((detail as { status: unknown }).status);
  }
  return `HTTP ${status}`;
}

export class Api {
  constructor(public base: string, private token: string) {}

  wsUrl(path: string): string {
    const url = new URL(path, this.base);
    url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
    return url.toString();
  }

  get tokenForSocket(): string {
    return this.token;
  }

  private async call<T>(method: string, path: string, body?: unknown, auth = true): Promise<T> {
    const headers: Record<string, string> = {};
    if (body !== undefined) headers["Content-Type"] = "application/json";
    if (auth) headers.Authorization = `Bearer ${this.token}`;
    const res = await fetch(new URL(`/api/v1${path}`, this.base), {
      method, headers, body: body === undefined ? undefined : JSON.stringify(body),
      credentials: "omit", cache: "no-store",
    });
    const text = await res.text();
    const data = text ? JSON.parse(text) : null;
    if (!res.ok) throw new ApiError(res.status, describe(data, res.status), data);
    return data as T;
  }

  health = () => this.call<Health>("GET", "/health", undefined, false);
  providers = () => this.call<ProviderStatus[]>("GET", "/providers");
  activeProvider = () => this.call<ProviderStatus>("GET", "/providers/active");
  selectProvider = (provider_id: string) => this.call<ProviderStatus>("POST", "/providers/select", { provider_id });
  executor = () => this.call<ExecutorStatus>("GET", "/executor");
  submit = (instruction: string) => this.call<{ task_id: string; status: string }>("POST", "/tasks", { instruction });
  tasks = () => this.call<TaskSummary[]>("GET", "/tasks");
  task = (id: string) => this.call<TaskDetail>("GET", `/tasks/${encodeURIComponent(id)}`);
  cancel = (id: string) => this.call<{ status: string }>("POST", `/tasks/${encodeURIComponent(id)}/cancel`);
  clarify = (id: string, selected_option: string | null, free_text: string) =>
    this.call<{ status: string }>("POST", `/tasks/${encodeURIComponent(id)}/clarify`, { selected_option, free_text });
  tokenize = (text: string) => this.call<TokenizationResult>("POST", "/tokenize", { text });
  environment = () => this.call<Environment>("GET", "/environment/objects");
  telemetry = () => this.call<RosStub>("GET", "/telemetry");
  inspector = () => this.call<RosStub>("GET", "/ros/inspector");
  reset = () => this.call<{ status: string; e_stop_latched: boolean; scene_reset: string }>("POST", "/simulation/reset");

  // 503 carries the observed (unverified) report in detail: return it, never pretend it stopped.
  async eStop(): Promise<StopReport> {
    try {
      return await this.call<StopReport>("POST", "/simulation/e-stop");
    } catch (err) {
      if (err instanceof ApiError && err.status === 503 && err.body && typeof err.body === "object") {
        return (err.body as { detail: StopReport }).detail;
      }
      throw err;
    }
  }
}
