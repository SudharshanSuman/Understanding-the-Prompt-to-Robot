import type { ExecutorStatus, Health, ProviderStatus, StopReport } from "../types";
import type { SocketState } from "../socket";

type Tone = "ok" | "warning" | "error" | "neutral";

function Chip({ label, value, tone, title }: { label: string; value: string; tone: Tone; title?: string }) {
  return (
    <div className={`chip chip--${tone}`} title={title}>
      <span className="chip-label">{label}</span>
      <span className="chip-value">{value}</span>
    </div>
  );
}

interface Props {
  health: Health | null;
  executor: ExecutorStatus | null;
  providers: ProviderStatus[];
  activeProvider: string;
  socket: SocketState;
  stopReport: StopReport | null;
  /** True only while the e-stop request itself is in flight; other work never disables E-STOP. */
  stopping: boolean;
  onSelectProvider: (id: string) => void;
  onEStop: () => void;
  onDisconnect: () => void;
}

export function Header(p: Props) {
  const ros = p.health?.ros2 ?? "unknown";
  const gazebo = p.health?.gazebo ?? "unknown";
  // An executor that is not connected is a warning, never success.
  const robot = !p.executor
    ? { value: "unknown", tone: "neutral" as Tone }
    : p.executor.e_stop_latched
      ? { value: `E-stop latched (${p.executor.controller_state})`, tone: "error" as Tone }
      : p.executor.connected
        ? { value: p.executor.controller_state, tone: "ok" as Tone }
        : { value: "No executor connected", tone: "warning" as Tone };

  return (
    <header className="header">
      <div className="brand">
        <span className="brand-mark" aria-hidden="true">▣</span>
        <span>Munder Difflin <span className="muted">robot console</span></span>
      </div>
      <div className="chips">
        <Chip label="ROS 2" value={ros} tone={ros === "available" ? "ok" : "warning"} />
        <Chip label="Gazebo" value={gazebo} tone={gazebo === "available" ? "ok" : "warning"} />
        <label className="chip chip--neutral provider">
          <span className="chip-label">AI provider</span>
          <select value={p.activeProvider} onChange={(e) => p.onSelectProvider(e.target.value)} aria-label="AI provider">
            <option value="auto">auto (chain)</option>
            {p.providers.map((pr) => (
              <option key={pr.provider_id} value={pr.provider_id} disabled={!pr.configured}>
                {pr.provider_id}{pr.model_name ? ` · ${pr.model_name}` : ""}
                {!pr.configured ? " (not configured)" : !pr.available ? " (unavailable)" : ""}
              </option>
            ))}
          </select>
        </label>
        <Chip label="Robot" value={robot.value} tone={robot.tone} title={p.executor?.detail} />
        <Chip label="Live stream" value={p.socket} tone={p.socket === "open" ? "ok" : p.socket === "unauthorized" ? "error" : "warning"} />
      </div>
      <div className="estop-wrap">
        {p.stopReport && (
          <span className={`estop-result ${p.stopReport.status === "e_stop_confirmed" ? "is-ok" : "is-bad"}`} role="status">
            {p.stopReport.status === "e_stop_confirmed" ? "Stop observed" : "Stop NOT confirmed"}
            {" · max |q̇| "}{p.stopReport.max_joint_velocity ?? "n/a"} rad/s · {p.stopReport.source}
          </span>
        )}
        <button type="button" className="btn btn--estop" onClick={p.onEStop} disabled={p.stopping}
                aria-label="Emergency stop">E-STOP</button>
        <button type="button" className="btn btn--ghost" onClick={p.onDisconnect}>Disconnect</button>
      </div>
    </header>
  );
}
