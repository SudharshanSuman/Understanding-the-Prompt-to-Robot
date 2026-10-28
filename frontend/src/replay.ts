// Replay of the last run: the recorded events and telemetry frames, in their recorded order and timing.
import { useCallback, useEffect, useRef, useState } from "react";
import type { PipelineEvent } from "./types";

export const MAX_GAP_MS = 2000; // longer pauses are shortened in replay, and the UI says so

export interface RecordedFrame {
  at: number; // ms epoch when the frame was produced (telemetry data.time) or received
  payload: Record<string, unknown>;
}

export type ReplayItem =
  | { kind: "event"; at: number; index: number }
  | { kind: "telemetry"; at: number; frame: RecordedFrame };

export interface Timeline {
  items: ReplayItem[];
  delays: number[]; // ms to wait before each item
  shortened: number; // how many gaps were capped at MAX_GAP_MS
}

/** Events and telemetry merged by time. Items without a usable time keep their order with no delay. */
export function buildTimeline(events: PipelineEvent[], frames: RecordedFrame[]): Timeline {
  // An item without a usable time takes the time of the item before it in its own list.
  const fill = <T extends { at: number }>(list: T[]): T[] => {
    let last = -Infinity;
    return list.map((it) => (Number.isFinite(it.at) ? ((last = it.at), it) : { ...it, at: last }));
  };
  const items: ReplayItem[] = [
    ...fill(events.map((ev, index) => ({ kind: "event" as const, at: Date.parse(ev.timestamp), index }))),
    ...fill(frames.map((frame) => ({ kind: "telemetry" as const, at: frame.at, frame }))),
  ];
  const sorted = items.map((it, i) => ({ it, i })).sort((a, b) => a.it.at - b.it.at || a.i - b.i).map((x) => x.it);
  const delays: number[] = [];
  let shortened = 0;
  let prev: number | null = null;
  for (const it of sorted) {
    let gap = prev === null || !Number.isFinite(it.at - prev) ? 0 : Math.max(0, it.at - prev);
    if (gap > MAX_GAP_MS) { gap = MAX_GAP_MS; shortened++; }
    delays.push(gap);
    if (Number.isFinite(it.at)) prev = it.at;
  }
  return { items: sorted, delays, shortened };
}

export interface ReplayState {
  active: boolean;
  eventCount: number; // events shown so far
  frame: RecordedFrame | null; // telemetry frame shown so far
  progress: number; // 0..1
  step: number; // recorded items shown so far
  total: number; // recorded items in the run
  shortened: number;
}

const IDLE: ReplayState = { active: false, eventCount: 0, frame: null, progress: 0, step: 0, total: 0, shortened: 0 };

/** Plays a timeline with real timers. stop() returns the view to live data. */
export function useReplay(events: PipelineEvent[], frames: () => RecordedFrame[]) {
  const [state, setState] = useState<ReplayState>(IDLE);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const stop = useCallback(() => {
    if (timer.current) clearTimeout(timer.current);
    timer.current = null;
    setState(IDLE);
  }, []);

  const start = useCallback(() => {
    if (timer.current) clearTimeout(timer.current);
    const tl = buildTimeline(events, frames());
    if (tl.items.length === 0) return;
    let i = 0, eventCount = 0, frame: RecordedFrame | null = null;
    setState({ active: true, eventCount: 0, frame: null, progress: 0, step: 0, total: tl.items.length, shortened: tl.shortened });
    const step = () => {
      do { // items recorded at the same moment are shown together, not one timer each
        const it = tl.items[i];
        if (it.kind === "event") eventCount = it.index + 1 > eventCount ? it.index + 1 : eventCount;
        else frame = it.frame;
        i++;
      } while (i < tl.items.length && tl.delays[i] === 0);
      const done = i >= tl.items.length;
      setState({ active: !done, eventCount: done ? events.length : eventCount, frame, progress: i / tl.items.length,
        step: i, total: tl.items.length, shortened: tl.shortened });
      timer.current = done ? null : setTimeout(step, tl.delays[i]);
    };
    timer.current = setTimeout(step, 0);
  }, [events, frames]);

  useEffect(() => () => { if (timer.current) clearTimeout(timer.current); }, []);
  return { state, start, stop };
}

