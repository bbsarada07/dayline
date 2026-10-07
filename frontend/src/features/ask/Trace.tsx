import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { LazyMotion, domAnimation, m, useReducedMotion } from "framer-motion";
import {
  Brain, BrainCircuit, CalendarClock, ChevronDown, CircleAlert, Info, Mic, Printer, Sparkles, UtensilsCrossed, Wrench,
  type LucideIcon,
} from "lucide-react";
import { api } from "@/lib/api";
import type { AgentName, MemoryList, MemoryStatus, TraceEvent } from "@/lib/types";
import { cn } from "@/lib/utils";

export const AGENT: Record<AgentName, { label: string; icon: LucideIcon; fill: string; text: string; dot: string }> = {
  orchestrator: { label: "Dayline", icon: Sparkles, fill: "bg-ink", text: "text-paper", dot: "bg-ink" },
  timetable: { label: "Timetable", icon: CalendarClock, fill: "bg-magenta", text: "text-white", dot: "bg-magenta" },
  print: { label: "Print", icon: Printer, fill: "bg-cyan", text: "text-on-fill", dot: "bg-cyan" },
  canteen: { label: "Canteen", icon: UtensilsCrossed, fill: "bg-yellow", text: "text-on-fill", dot: "bg-yellow" },
};

type Phase = "working" | "done";

/** Which agents joined the run, in order, and whether each has finished. */
function agentPhases(events: TraceEvent[], finished: boolean): [AgentName, Phase][] {
  const phases = new Map<AgentName, Phase>();
  for (const event of events) {
    if (event.type === "agent_started" || event.type === "tool_called" || event.type === "memory_read" || event.type === "memory_write") {
      if (!phases.has(event.agent)) phases.set(event.agent, "working");
      if (event.type === "agent_started") phases.set(event.agent, "working");
    }
    if (event.type === "agent_finished") phases.set(event.agent, "done");
  }
  // A consulted agent (Timetable asked by Print) has no "finished" of its own.
  return [...phases].map(([agent, phase]) => [agent, finished ? "done" : phase]);
}

/**
 * An agent joins the run as an outlined chip and fills with its colour when it has
 * done its part (spec 9.1 motion 1). Instant with reduced motion.
 */
function AgentChip({ agent, phase }: { agent: AgentName; phase: Phase }) {
  const reduce = useReducedMotion();
  const a = AGENT[agent];
  const done = phase === "done";
  return (
    <span className="relative inline-flex min-h-8 items-center gap-1.5 overflow-hidden rounded-[9px] border-2 border-edge bg-sheet px-2 text-13 font-extrabold">
      <m.span
        aria-hidden
        className={cn("absolute inset-0 origin-left", a.fill)}
        initial={reduce ? false : { scaleX: 0 }}
        animate={{ scaleX: done ? 1 : 0.18 }}
        transition={reduce ? { duration: 0 } : { type: "spring", duration: 0.45, bounce: 0.15 }}
      />
      <span className={cn("relative inline-flex items-center gap-1.5 transition-colors duration-300", done && a.text)}>
        <a.icon className="size-3.5" aria-hidden />
        {a.label}
        {done ? <span className="sr-only">, done</span> : <span className="pulse-dot size-1.5 rounded-full bg-current" aria-label=", working" />}
      </span>
    </span>
  );
}

type Step = { icon: LucideIcon; system: string | null; text: string; agent?: AgentName; tone?: "alert" | "muted" };

/** What the step's labels can rely on: all of it comes from the run or the server, nothing is guessed. */
type Systems = {
  mode?: "lyzr" | "mock"; // from the run itself; unknown for older history
  fellBack: (agent: AgentName) => boolean; // the trace has a note that the offline router answered for it
  store?: MemoryStatus["backend"];
  fromOmi: Set<string>; // memory texts written by Omi
};

function agentSystem(agent: AgentName, sys: Systems): string {
  const name = agent === "orchestrator" ? "Orchestrator" : AGENT[agent].label;
  if (sys.mode === "mock" || (sys.mode === "lyzr" && sys.fellBack(agent))) return `Offline router · ${name}`;
  if (sys.mode === "lyzr") return `Lyzr · ${name} agent`;
  return `${name} agent`;
}

function memorySystem(action: "read" | "write", count: number, items: string[] | undefined, sys: Systems): string {
  const store = sys.store === "temporary" ? "Temporary memory" : sys.store === "qdrant" ? "Qdrant" : "Memory";
  const omi = (items ?? []).filter((text) => sys.fromOmi.has(text)).length;
  return `${store} ${action} · ${count}${omi ? ` (${omi} from Omi)` : ""}`;
}

function stepView(event: TraceEvent, sys: Systems): Step | null {
  switch (event.type) {
    case "agent_started":
      return event.agent === "orchestrator"
        ? null
        : { icon: AGENT[event.agent].icon, system: agentSystem(event.agent, sys), text: event.label, agent: event.agent };
    case "tool_called":
      return {
        icon: event.ok ? Wrench : CircleAlert,
        // The agent that asked for the tool decided to call it; the label names whose data it read.
        system: agentSystem(event.for ?? event.agent, sys),
        text: event.for ? `${event.label} (${AGENT[event.agent].label} data)` : event.label,
        agent: event.agent,
        tone: event.ok ? undefined : "alert",
      };
    case "memory_read":
      return { icon: Brain, system: memorySystem("read", event.count, event.items, sys), text: event.label, agent: event.agent };
    case "memory_write":
      return { icon: BrainCircuit, system: memorySystem("write", 1, [event.text], sys), text: event.label, agent: event.agent };
    case "note":
      return { icon: Info, system: null, text: event.text, tone: "muted" };
    default:
      return null;
  }
}

function useSystems(events: TraceEvent[], mode: Systems["mode"]): Systems {
  const reads = events.some((e) => e.type === "memory_read" && e.items?.length);
  const status = useQuery({ queryKey: ["memory", "status"], queryFn: () => api<MemoryStatus>("/memory/status"), staleTime: 60_000 });
  const list = useQuery({ queryKey: ["memory", "list"], queryFn: () => api<MemoryList>("/memory"), enabled: reads });
  const notes = events.flatMap((e) => (e.type === "note" ? [e.text] : []));
  const budget = notes.some((t) => /budget/i.test(t));
  return {
    mode,
    fellBack: (agent) => budget || notes.some((t) => /offline router/i.test(t) && t.includes(`The ${AGENT[agent].label} agent`)),
    store: status.data?.backend,
    fromOmi: new Set((list.data?.memories ?? []).filter((m) => m.written_by === "omi").map((m) => m.text)),
  };
}

/** The run, live: agent chips and each step. Folds to one line when the answer arrives. */
export function Trace({ events, finished, mode, via }: {
  events: TraceEvent[];
  finished: boolean;
  /** How the run was answered (from its "run" event). */
  mode?: "lyzr" | "mock";
  /** The request was spoken to Omi. */
  via?: "omi";
}) {
  const [open, setOpen] = useState(true); // the steps stay open when the answer arrives; the student can fold them
  const phases = agentPhases(events, finished);
  const sys = useSystems(events, mode);
  const steps: Step[] = [
    ...(via === "omi" ? [{ icon: Mic, system: "Omi", text: "Heard on your wearable" }] : []),
    ...events.map((e) => stepView(e, sys)).filter((s) => s !== null),
  ];
  const showSteps = !finished || open;
  if (phases.length === 0 && steps.length === 0) {
    return finished ? null : <p className="pulse-dot text-13 font-bold text-muted">Thinking…</p>;
  }
  return (
    <LazyMotion features={domAnimation} strict>
      <div className="space-y-2">
        <div className="flex flex-wrap items-center gap-1.5">
          {phases.map(([agent, phase]) => (
            <AgentChip key={agent} agent={agent} phase={phase} />
          ))}
          {finished && steps.length ? (
            <button
              type="button"
              onClick={() => setOpen((v) => !v)}
              aria-expanded={open}
              className="inline-flex min-h-8 items-center gap-1 rounded-[8px] px-1.5 text-13 font-bold text-muted hover:text-ink"
            >
              {open ? "Hide" : "Show"} {steps.length} {steps.length === 1 ? "step" : "steps"}
              <ChevronDown className={cn("size-4 transition-transform", open && "rotate-180")} aria-hidden />
            </button>
          ) : null}
        </div>
        {showSteps ? (
          <ol className="space-y-1 border-l-2 border-dashed border-line pl-3" aria-live={finished ? undefined : "polite"}>
            {steps.map((step, i) => (
              <li key={i} className={cn("flex items-start gap-2 text-13 font-semibold", step.tone === "alert" ? "text-alert-text" : "text-muted")}>
                <span aria-hidden className={cn("mt-1.5 size-2 shrink-0 rounded-full border border-edge", step.agent ? AGENT[step.agent].dot : "bg-line")} />
                <step.icon className="mt-0.5 size-3.5 shrink-0" aria-hidden />
                <span className="min-w-0 break-words">
                  {step.system ? <span className="font-extrabold text-ink">{step.system}</span> : null}
                  {step.system ? " · " : null}
                  {step.text}
                </span>
              </li>
            ))}
          </ol>
        ) : null}
      </div>
    </LazyMotion>
  );
}
