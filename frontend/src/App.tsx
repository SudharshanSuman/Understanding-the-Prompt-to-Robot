import { useCallback, useEffect, useRef, useState } from "react";
import { Api, ApiError, DEFAULT_API_BASE } from "./api";
import { desktopBridge, type DesktopSession } from "./desktop";
import { PipelineSocket, type Frame, type SocketState } from "./socket";
import { telemetryPose } from "./kinematics";
import { useReplay, type RecordedFrame } from "./replay";
import {
  FINAL_STATUSES, type Environment, type ExecutorStatus, type Health, type PipelineEvent, type ProviderStatus,
  type RosStub, type StopReport, type TaskDetail, type TaskSummary, type TokenizationResult,
} from "./types";
import { Header } from "./components/Header";
import { CommandPanel } from "./components/CommandPanel";
import { SceneView } from "./components/SceneView";
import { FlowView } from "./components/FlowView";
import { StageList } from "./components/StageList";
import { StageDetail } from "./components/StageDetail";
import { Inspector, type LogEntry } from "./components/Inspector";

const MAX_LOGS = 300;
const MAX_FRAMES_PER_TASK = 7500; // 25 min at the 5 Hz telemetry stream
const MAX_RECORDED_TASKS = 5;

interface ConnectProps {
  onConnect: (base: string, token: string) => void;
  error: string;
  desktop: DesktopSession | null;
}

function Connect({ onConnect, error, desktop }: ConnectProps) {
  const [base, setBase] = useState(desktop?.apiBase ?? DEFAULT_API_BASE);
  const [token, setToken] = useState("");
  return (
    <main className="connect">
      <form className="connect-card" onSubmit={(e) => { e.preventDefault(); onConnect(base.trim(), token.trim()); }}>
        <h1>Munder Difflin console</h1>
        <p className="muted">Connect to the backend. The API token is kept in memory for this tab only and is never stored.</p>
        <label className="label" htmlFor="base">Backend URL</label>
        <input id="base" className="input" value={base} onChange={(e) => setBase(e.target.value)} />
        <label className="label" htmlFor="token">API token (set on the backend server)</label>
        <input id="token" className="input" type="password" autoComplete="off" value={token}
               onChange={(e) => setToken(e.target.value)} />
        {error && <p className="error" role="alert">{error}</p>}
        <button className="btn btn--primary" type="submit" disabled={!token.trim()}>Connect</button>
        {desktop?.token && (
          <button className="btn" type="button" onClick={() => onConnect(desktop.apiBase, desktop.token!)}>
            Connect to the desktop backend
          </button>
        )}
      </form>
    </main>
  );
}

export default function App() {
  const [api, setApi] = useState<Api | null>(null);
  const [connectError, setConnectError] = useState("");
  const [desktop, setDesktop] = useState<DesktopSession | null>(null);
  const [health, setHealth] = useState<Health | null>(null);
  const [executor, setExecutor] = useState<ExecutorStatus | null>(null);
  const [providers, setProviders] = useState<ProviderStatus[]>([]);
  const [active, setActive] = useState("auto");
  const [socket, setSocket] = useState<SocketState>("closed");
  const [history, setHistory] = useState<TaskSummary[]>([]);
  const [current, setCurrent] = useState<TaskDetail | null>(null);
  const [events, setEvents] = useState<Record<string, PipelineEvent[]>>({});
  const [selectedStage, setSelectedStage] = useState<string | null>(null);
  const [preview, setPreview] = useState<TokenizationResult | null>(null);
  const [env, setEnv] = useState<Environment | null>(null);
  const [telemetry, setTelemetry] = useState<RosStub | null>(null);
  const [inspector, setInspector] = useState<RosStub | null>(null);
  const [stopReport, setStopReport] = useState<StopReport | null>(null);
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const [busy, setBusy] = useState(false);
  const [stopping, setStopping] = useState(false); // e-stop has its own flag: unrelated work must never block it
  const currentId = useRef<string | null>(null);
  // Telemetry frames recorded per task id (as the executor reports it), for replay of the last run.
  const recorded = useRef<Map<string, RecordedFrame[]>>(new Map());

  const log = useCallback((level: LogEntry["level"], text: string) => {
    setLogs((l) => [...l.slice(-MAX_LOGS + 1), { at: new Date().toLocaleTimeString(), level, text }]);
  }, []);

  const fail = useCallback((what: string, err: unknown) => {
    const msg = err instanceof ApiError ? `${err.status} ${err.message}` : String(err);
    log("error", `${what}: ${msg}`);
    if (err instanceof ApiError && err.status === 401) setApi(null);
  }, [log]);

  const refreshStatus = useCallback(async (a: Api) => {
    try {
      const [h, ex, pr, ac] = await Promise.all([a.health(), a.executor(), a.providers(), a.activeProvider()]);
      setHealth(h); setExecutor(ex); setProviders(pr); setActive(ac.provider_id);
    } catch (err) { fail("status", err); }
  }, [fail]);

  const openTask = useCallback(async (a: Api, id: string) => {
    try {
      const detail = await a.task(id);
      currentId.current = id;
      setCurrent(detail);
      setEvents((m) => ({ ...m, [id]: detail.events }));
    } catch (err) { fail("load task", err); }
  }, [fail]);

  const connect = useCallback(async (base: string, token: string) => {
    const a = new Api(base, token);
    try {
      await a.health();
      await a.executor(); // proves the token works
    } catch (err) {
      setConnectError(err instanceof ApiError && err.status === 401 ? "Token rejected (401)." :
        `Cannot reach the backend at ${base}: ${err instanceof Error ? err.message : String(err)}`);
      return;
    }
    setConnectError("");
    setApi(a);
  }, []);

  // Desktop mode: the backend the app launched is connected to automatically with its per-launch token.
  useEffect(() => {
    const bridge = desktopBridge();
    if (!bridge) return;
    let live = true;
    bridge.session().then((s) => {
      if (!live) return;
      setDesktop(s);
      if (s.token) void connect(s.apiBase, s.token);
    }, (err) => setConnectError(`Desktop bridge failed: ${String(err)}`));
    return () => { live = false; };
  }, [connect]);

  // Live stream + periodic status while connected.
  useEffect(() => {
    if (!api) return;
    const onFrame = (f: Frame) => {
      const id = f.task_id;
      if (f.channel === "pipeline_event" && id) {
        const ev = f.payload as unknown as PipelineEvent;
        setEvents((m) => {
          const list = m[id] ?? [];
          return list.some((e) => e.event_id === ev.event_id) ? m : { ...m, [id]: [...list, ev] };
        });
      } else if (f.channel === "task_status" && id) {
        const status = String(f.payload.status);
        log("info", `task ${id}: ${status}`);
        setCurrent((c) => (c && c.task_id === id ? { ...c, status } : c));
        if (FINAL_STATUSES.has(status)) {
          void api.tasks().then(setHistory).catch((e) => fail("history", e));
          if (currentId.current === id) void openTask(api, id);
        }
      } else if (f.channel === "error") {
        log("warn", `stream error: ${JSON.stringify(f.payload)}`);
      }
    };
    const s = new PipelineSocket(api, onFrame, (st) => { setSocket(st); log(st === "open" ? "info" : "warn", `live stream ${st}`); });
    s.start();
    const onTelemetry = (f: Frame) => {
      if (f.channel !== "telemetry") return;
      setTelemetry(f.payload as RosStub);
      const pose = telemetryPose(f.payload);
      if (!pose?.taskId) return;
      const map = recorded.current;
      const list = map.get(pose.taskId) ?? [];
      if (!map.has(pose.taskId)) {
        map.set(pose.taskId, list);
        while (map.size > MAX_RECORDED_TASKS) map.delete(map.keys().next().value as string);
      }
      list.push({ at: pose.time !== null ? pose.time * 1000 : Date.now(), payload: f.payload });
      if (list.length > MAX_FRAMES_PER_TASK) list.shift();
    };
    const ts = new PipelineSocket(api, onTelemetry, (st) => { if (st !== "open") log("warn", `telemetry stream ${st}`); },
      "/ws/telemetry", false);
    ts.start();
    void refreshStatus(api);
    void api.tasks().then(setHistory).catch((e) => fail("history", e));
    void api.environment().then(setEnv).catch((e) => fail("environment", e));
    void api.telemetry().then(setTelemetry).catch((e) => fail("telemetry", e));
    void api.inspector().then(setInspector).catch((e) => fail("inspector", e));
    const timer = setInterval(() => void refreshStatus(api), 10_000);
    return () => { s.stop(); ts.stop(); clearInterval(timer); };
  }, [api, fail, log, openTask, refreshStatus]);

  const taskEvents = current ? events[current.task_id] ?? current.events : [];
  const replayId = current && FINAL_STATUSES.has(current.status) ? current.task_id : null;
  const replay = useReplay(taskEvents, () => (replayId ? recorded.current.get(replayId) ?? [] : []));
  const stopReplay = replay.stop;
  useEffect(() => stopReplay(), [current?.task_id, stopReplay]); // a different task ends any replay

  if (!api) return <Connect key={desktop?.apiBase ?? ""} onConnect={connect} error={connectError} desktop={desktop} />;

  const run = async (what: string, fn: () => Promise<void>) => {
    setBusy(true);
    try { await fn(); } catch (err) { fail(what, err); } finally { setBusy(false); }
  };

  const submit = (text: string) => run("submit", async () => {
    const r = await api.submit(text);
    log("info", `submitted ${r.task_id}`);
    setSelectedStage(null);
    setPreview(null); // a new task replaces an older preview in the Tokenization tab
    await openTask(api, r.task_id);
    setHistory(await api.tasks());
  });

  const shownEvents = replay.state.active ? taskEvents.slice(0, replay.state.eventCount) : taskEvents;
  const livePose = telemetryPose(telemetry);
  const pose = replay.state.active ? telemetryPose(replay.state.frame?.payload) : livePose;
  const task = current?.task as { target_object?: string; destination?: string } | null | undefined;

  return (
    <div className="app">
      <Header
        health={health} executor={executor} providers={providers} activeProvider={active} socket={socket}
        stopReport={stopReport} stopping={stopping}
        onSelectProvider={(id) => run("select provider", async () => {
          const st = await api.selectProvider(id);
          setActive(st.provider_id);
          log("info", `provider set to ${st.provider_id}`);
        })}
        onEStop={async () => {
          setStopping(true);
          try {
            const report = await api.eStop();
            setStopReport(report);
            log(report.status === "e_stop_confirmed" ? "warn" : "error",
              `E-STOP ${report.status}: max |q̇| ${report.max_joint_velocity ?? "n/a"} (${report.source})`);
            await refreshStatus(api);
          } catch (err) { fail("e-stop", err); } finally { setStopping(false); }
        }}
        onDisconnect={() => { setApi(null); setCurrent(null); setEvents({}); }}
      />
      <CommandPanel
        current={current} history={history} busy={busy}
        onSubmit={submit}
        onStop={() => current && run("cancel", async () => { await api.cancel(current.task_id); log("warn", `cancel ${current.task_id}`); })}
        onReset={() => run("reset", async () => {
          const r = await api.reset();
          setStopReport(null);
          log("info", `reset: e-stop latched=${r.e_stop_latched}; ${r.scene_reset}`);
          await refreshStatus(api);
        })}
        onPreview={(text) => run("tokenize", async () => setPreview(await api.tokenize(text)))}
        onOpen={(id) => { setPreview(null); void openTask(api, id); }}
        onClarify={(option, freeText) => current && run("clarify", async () => {
          const id = current.task_id;
          setEvents((m) => ({ ...m, [id]: [] }));
          setPreview(null);
          await api.clarify(id, option, freeText);
          await openTask(api, id);
        })}
      />
      <div className="center center-stack">
        <FlowView events={shownEvents} instruction={current?.instruction ?? null}
                  replay={replay.state} canReplay={replayId !== null && taskEvents.length > 0}
                  onReplay={replay.start} onStopReplay={replay.stop} />
        <SceneView env={env} target={task?.target_object ?? null} destination={task?.destination ?? null}
                   pose={pose} replaying={replay.state.active}
                   telemetryReason={telemetry && telemetry.available === false ? String(telemetry.reason ?? "ros unavailable") : null} />
      </div>
      <aside className="panel right" aria-label="Pipeline">
        <h2 className="panel-title">
          Pipeline {current && <span className={`status status--${current.status}`}>{current.status.replace(/_/g, " ")}</span>}
        </h2>
        {current?.status === "validated_no_executor" && (
          <div className="banner banner--warning" role="status">
            Passed the safety checks, but no executor is connected: nothing was executed.
          </div>
        )}
        <StageList events={taskEvents} selected={selectedStage} onSelect={setSelectedStage} />
        <StageDetail stage={selectedStage} events={taskEvents} />
      </aside>
      <Inspector task={current} events={taskEvents} preview={preview} env={env} telemetry={telemetry}
                 inspector={inspector} executor={executor} logs={logs} />
    </div>
  );
}
