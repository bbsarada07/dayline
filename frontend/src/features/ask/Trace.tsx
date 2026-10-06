import { useState } from "react";
import { LazyMotion, domAnimation, m, useReducedMotion } from "framer-motion";
import {
  Brain, BrainCircuit, CalendarClock, ChevronDown, CircleAlert, Info, Printer, Sparkles, UtensilsCrossed, Wrench,
  type LucideIcon,
} from "lucide-react";
import type { AgentName, TraceEvent } from "@/lib/types";
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

function stepView(event: TraceEvent): { icon: LucideIcon; text: string; agent?: AgentName; tone?: "alert" | "muted" } | null {
  switch (event.type) {
    case "agent_started":
      return event.agent === "orchestrator" ? null : { icon: AGENT[event.agent].icon, text: event.label, agent: event.agent };
    case "tool_called":
      return {
        icon: event.ok ? Wrench : CircleAlert,
        text: event.for ? `${event.label} (for ${AGENT[event.for].label})` : event.label,
        agent: event.agent,
        tone: event.ok ? undefined : "alert",
      };
    case "memory_read":
      return { icon: Brain, text: event.label, agent: event.agent };
    case "memory_write":
      return { icon: BrainCircuit, text: event.label, agent: event.agent };
    case "note":
      return { icon: Info, text: event.text, tone: "muted" };
    default:
      return null;
  }
}

/** The run, live: agent chips and each step. Folds to one line when the answer arrives. */
export function Trace({ events, finished }: { events: TraceEvent[]; finished: boolean }) {
  const [open, setOpen] = useState(false);
  const phases = agentPhases(events, finished);
  const steps = events.map(stepView).filter((s) => s !== null);
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
                <span className="min-w-0 break-words">{step.text}</span>
              </li>
            ))}
          </ol>
        ) : null}
      </div>
    </LazyMotion>
  );
}
