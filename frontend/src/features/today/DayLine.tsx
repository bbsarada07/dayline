import { useEffect, useState, type CSSProperties, type ReactNode } from "react";
import { LazyMotion, domAnimation, m, useReducedMotion } from "framer-motion";
import { Check, Coffee, FlaskConical, MapPin } from "lucide-react";
import type { DayItem } from "@/lib/types";
import { clockTime, duration, minutesBetween, timeOfDay } from "@/lib/format";
import { cn } from "@/lib/utils";

type Status = DayItem["status"];

/** Status from the synced app clock, so the line moves between refetches. */
export function statusAt(item: DayItem, now: Date): Status {
  const t = now.getTime();
  if (t >= new Date(item.end).getTime()) return "past";
  if (t >= new Date(item.start).getTime()) return "current";
  return "upcoming";
}

function NowPill({ now }: { now: Date }) {
  return (
    <span className="inline-block rounded-[8px] border-2 border-edge bg-magenta px-1.5 py-0.5 font-display text-13 leading-none font-extrabold text-white tabular-nums shadow-hard-sm">
      {clockTime(now)}
    </span>
  );
}

type Node = "class" | "past" | "cyan" | "yellow" | "gap" | "none";

const NODE_CLASS: Record<Exclude<Node, "none">, string> = {
  class: "size-3.5 rotate-45 rounded-[3px] border-2 border-edge bg-magenta",
  past: "size-3 rounded-full border-2 border-line bg-paper",
  cyan: "size-3.5 rotate-45 rounded-[3px] border-2 border-edge bg-cyan",
  yellow: "size-3.5 rotate-45 rounded-[3px] border-2 border-edge bg-yellow",
  gap: "size-2.5 rounded-full bg-line",
};

/** One row of the line: time column, rail, content. */
function Row({ time, marker, node, past = false, children }: {
  time: ReactNode;
  marker?: number;
  node: Node;
  past?: boolean;
  children: ReactNode;
}) {
  const markerStyle: CSSProperties | undefined =
    marker === undefined ? undefined : { top: `clamp(12px, ${marker * 100}%, calc(100% - 22px))` };
  return (
    <li className="relative grid grid-cols-[3.1rem_1.25rem_minmax(0,1fr)] gap-x-2 pb-3 sm:grid-cols-[3.75rem_1.25rem_minmax(0,1fr)]">
      <div
        className={cn(
          "relative text-right font-display text-15 font-extrabold tabular-nums",
          past ? "text-muted" : "text-ink",
        )}
      >
        {marker === undefined ? <span className="inline-block pt-3.5">{time}</span> : null}
      </div>
      <div className="relative" aria-hidden>
        <span className={cn("absolute inset-y-0 left-1/2 w-[3px] -translate-x-1/2 rounded-full", past ? "bg-line" : "bg-edge/80")} />
        {node !== "none" && marker === undefined ? (
          <span className={cn("absolute top-[19px] left-1/2 -translate-x-1/2", NODE_CLASS[node])} />
        ) : null}
      </div>
      <div className="min-w-0">{children}</div>
      {marker !== undefined ? (
        <div className="pointer-events-none absolute inset-x-0 z-10" style={markerStyle}>
          <div className="grid -translate-y-1/2 grid-cols-[3.1rem_1.25rem] items-center gap-x-2 sm:grid-cols-[3.75rem_1.25rem]">
            <div className="text-right">{time}</div>
            <span aria-hidden className="pulse-ring mx-auto size-4 rounded-full border-[3px] border-paper bg-magenta" />
          </div>
        </div>
      ) : null}
    </li>
  );
}

function RoomChip({ item, light = false }: { item: DayItem; light?: boolean }) {
  return (
    <span
      className={cn(
        "inline-flex min-w-0 items-center gap-1 rounded-full border-2 px-2 py-0.5 text-13 font-bold",
        light ? "border-white/80" : "border-edge",
      )}
    >
      <MapPin className="size-3.5 shrink-0" aria-hidden />
      <span className="truncate">
        {item.room_code}
        {item.room_name ? <span className="hidden font-semibold sm:inline"> · {item.room_name}</span> : null}
      </span>
    </span>
  );
}

function ClassBlock({ item, status, isNext, now }: { item: DayItem; status: Status; isNext: boolean; now: Date }) {
  const isLab = item.subject_kind === "lab";
  const current = status === "current";
  const times = `${timeOfDay(item.start)} – ${timeOfDay(item.end)}`;

  if (status === "past") {
    return (
      <div className="rounded-[14px] border-2 border-dashed border-line px-3 py-2.5 text-muted">
        <div className="flex items-center justify-between gap-3">
          <p className="min-w-0 truncate font-display text-17 font-extrabold">
            {item.label}
            {isLab ? <span className="sr-only"> (lab)</span> : null}
          </p>
          <span className="inline-flex shrink-0 items-center gap-1 text-13 font-bold">
            <Check className="size-4" aria-hidden /> Done
          </span>
        </div>
        <p className="mt-0.5 truncate text-13">
          {item.room_code} · {times}
        </p>
      </div>
    );
  }

  return (
    <div
      className={cn(
        "relative overflow-hidden rounded-[14px] border-2 border-edge px-3.5 py-3 shadow-hard",
        current ? "bg-magenta text-white" : "border-l-[10px] border-l-magenta bg-sheet",
      )}
    >
      {current ? <div aria-hidden className="halftone pointer-events-none absolute -top-8 -right-8 size-32 rounded-full text-white" /> : null}
      <div className="relative flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="truncate font-display text-21 leading-tight font-extrabold">
            {item.label}
            {isLab ? <span className="sr-only"> (lab)</span> : null}
          </p>
          {item.subject_name && item.subject_name !== item.label ? (
            <p className={cn("truncate text-13 font-semibold", current ? "text-white/90" : "text-muted")}>{item.subject_name}</p>
          ) : null}
        </div>
        {isLab ? <FlaskConical aria-hidden className="mt-1 size-5 shrink-0" /> : null}
      </div>
      <div className="relative mt-2 flex flex-wrap items-center gap-x-3 gap-y-1.5">
        <RoomChip item={item} light={current} />
        <span className="text-13 font-semibold tabular-nums">{times}</span>
      </div>
      {current ? (
        <p className="relative mt-2.5 inline-block rounded-[8px] border-2 border-edge bg-sheet px-2 py-0.5 text-13 font-extrabold text-ink">
          On now · {duration(minutesBetween(now, item.end))} left
        </p>
      ) : isNext ? (
        <p className="relative mt-2.5 inline-block rounded-[8px] bg-ink px-2 py-0.5 text-13 font-extrabold text-paper">
          Next · in {duration(minutesBetween(now, item.start))}
        </p>
      ) : null}
    </div>
  );
}

function GapBlock({ item, status }: { item: DayItem; status: Status }) {
  const length = duration(minutesBetween(item.start, item.end));
  const isBreak = item.kind === "break";
  return (
    <div
      className={cn(
        "flex min-h-11 flex-wrap items-center justify-between gap-x-3 gap-y-0.5 rounded-[14px] border-2 px-3 py-2 text-15",
        isBreak ? "hatch border-line" : "border-dashed border-line",
        status === "past" && "text-muted",
        status === "current" && "border-edge",
      )}
    >
      <span className="inline-flex min-w-0 items-center gap-2">
        {isBreak ? <Coffee className="size-4 shrink-0" aria-hidden /> : null}
        <span className="font-extrabold">{item.label}</span>
        <span className="font-semibold text-muted">· {length}</span>
      </span>
      <span className="text-13 font-semibold text-muted tabular-nums">Until {timeOfDay(item.end)}</span>
    </div>
  );
}

/** Something an agent pinned onto the day at the time it matters (a printout, a lunch pickup). */
export type DayPass = { id: string; at: string; tone: "cyan" | "yellow"; content: ReactNode };

// Passes the student just created (e.g. by paying for a print job). Each one
// drops onto the line the first time it is shown, then never again.
const pendingDrops = new Set<string>();

/** Call when the student creates something that will appear as a pass. */
export function markNewPass(id: string) {
  pendingDrops.add(id);
}

/** A new pass drops onto the line and settles, once (~350 ms). Instant with reduced motion. */
function PassDrop({ id, children }: { id: string; children: ReactNode }) {
  const reduce = useReducedMotion();
  const [isNew] = useState(() => pendingDrops.has(id));
  useEffect(() => {
    pendingDrops.delete(id);
  }, [id]);
  if (!isNew || reduce) return <>{children}</>;
  return (
    <LazyMotion features={domAnimation} strict>
      <m.div
        initial={{ y: -40, rotate: -6, opacity: 0 }}
        animate={{ y: 0, rotate: 0, opacity: 1 }}
        transition={{ type: "spring", duration: 0.35, bounce: 0.3 }}
      >
        {children}
      </m.div>
    </LazyMotion>
  );
}

function PassRow({ pass, index }: { pass: DayPass; index: number }) {
  return (
    <Row time={clockTime(pass.at)} node={pass.tone}>
      <PassDrop id={pass.id}>
        <div className={cn("transition-transform hover:rotate-0", index % 2 ? "rotate-1" : "-rotate-1")}>{pass.content}</div>
      </PassDrop>
    </Row>
  );
}

/** Passes whose time falls in [from, to). */
function between(passes: DayPass[], from: number, to: number): DayPass[] {
  return passes.filter((p) => {
    const t = new Date(p.at).getTime();
    return t >= from && t < to;
  });
}

/** The student's day drawn as a line of periods, with a moving "now" marker and pinned passes. */
export function DayLine({ items, now, passes = [] }: { items: DayItem[]; now: Date; passes?: DayPass[] }) {
  const sorted = [...passes].sort((a, b) => new Date(a.at).getTime() - new Date(b.at).getTime());
  const row = (pass: DayPass) => <PassRow key={pass.id} pass={pass} index={sorted.indexOf(pass)} />;

  if (items.length === 0) {
    return (
      <ol aria-label="Today's timeline" className="mt-3">
        {sorted.map(row)}
      </ol>
    );
  }

  const first = items[0];
  const last = items[items.length - 1];
  const beforeDay = now < new Date(first.start);
  const afterDay = now >= new Date(last.end);
  const nextClassId = items.find((i) => i.kind === "class" && statusAt(i, now) === "upcoming")?.id;

  return (
    <ol aria-label="Today's timeline" className="mt-3">
      {beforeDay ? (
        <Row time={<NowPill now={now} />} marker={0.5} node="none">
          <p className="py-3 font-semibold text-muted">Now · classes start at {timeOfDay(first.start)}</p>
        </Row>
      ) : null}
      {between(sorted, -Infinity, new Date(first.start).getTime()).map(row)}
      {items.map((item, index) => {
        const status = statusAt(item, now);
        const nextStart = index + 1 < items.length ? new Date(items[index + 1].start).getTime() : Infinity;
        const pinned = between(sorted, new Date(item.start).getTime(), nextStart);
        const progress =
          status === "current"
            ? minutesBetween(item.start, now) / Math.max(1, minutesBetween(item.start, item.end))
            : undefined;
        const node: Node = item.kind !== "class" ? "gap" : status === "past" ? "past" : "class";
        return [
          <Row
            key={item.id}
            time={status === "current" ? <NowPill now={now} /> : clockTime(item.start)}
            marker={progress}
            node={node}
            past={status === "past"}
          >
            {status === "current" ? <span className="sr-only">Now, {timeOfDay(now)}. </span> : null}
            {item.kind === "class" ? (
              <ClassBlock item={item} status={status} isNext={item.id === nextClassId} now={now} />
            ) : (
              <GapBlock item={item} status={status} />
            )}
          </Row>,
          ...pinned.map(row),
        ];
      })}
      {afterDay ? (
        <Row time={<NowPill now={now} />} marker={0.5} node="none">
          <p className="py-3 font-semibold text-muted">Now · that's all your classes for today</p>
        </Row>
      ) : null}
    </ol>
  );
}
