import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Brain, Check, CircleAlert, Copy, Mic, Send, type LucideIcon } from "lucide-react";
import { Skeleton } from "@/components/ui/skeleton";
import { api } from "@/lib/api";
import { useClock } from "@/lib/clock";
import { dayDate, duration, minutesBetween, sameDay, timeOfDay } from "@/lib/format";
import type { OmiActivityEntry, OmiStatus } from "@/lib/types";
import { cn } from "@/lib/utils";

export function useOmiStatus() {
  return useQuery({ queryKey: ["omi", "status"], queryFn: () => api<OmiStatus>("/omi/status") });
}

export function useOmiActivity() {
  return useQuery({
    queryKey: ["omi", "activity"],
    queryFn: () => api<{ entries: OmiActivityEntry[] }>("/omi/activity"),
  });
}

/** What each logged outcome means, in plain words. */
const OUTCOME: Record<string, { label: string; tone: "ok" | "muted" | "alert" }> = {
  listening: { label: "Heard the wake phrase", tone: "ok" },
  request: { label: "Request heard", tone: "ok" },
  replied: { label: "Replied on your Omi", tone: "ok" },
  reply_in_app: { label: "Replied in Dayline", tone: "ok" },
  accepted: { label: "Conversation received", tone: "ok" },
  stored: { label: "Saved to memory", tone: "ok" },
  no_wake_phrase: { label: "No wake phrase: dropped", tone: "muted" },
  no_request: { label: "Wake phrase, no request", tone: "muted" },
  nothing_kept: { label: "Nothing worth keeping", tone: "muted" },
  empty: { label: "No speech", tone: "muted" },
  skipped: { label: "Skipped", tone: "muted" },
  duplicate: { label: "Duplicate: skipped", tone: "muted" },
  ignored: { label: "Ignored", tone: "alert" },
  rate_limited: { label: "Too many calls", tone: "alert" },
  failed: { label: "Failed", tone: "alert" },
};

const KIND: Record<OmiActivityEntry["kind"], { label: string; icon: LucideIcon }> = {
  transcript: { label: "Live speech", icon: Mic },
  memory: { label: "Conversation", icon: Brain },
  reply: { label: "Reply", icon: Send },
};

function when(value: string, now: Date | null): string {
  if (!now) return timeOfDay(value);
  const minutes = Math.round(minutesBetween(value, now));
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${duration(minutes)} ago`;
  return sameDay(value, now) ? timeOfDay(value) : `${dayDate(value)}, ${timeOfDay(value)}`;
}

/** The server's log of Omi calls: what happened, never what was said. */
export function OmiActivity({ limit = 12, className }: { limit?: number; className?: string }) {
  const activity = useOmiActivity();
  const { now } = useClock();
  if (activity.isPending) return <Skeleton className={cn("h-24", className)} />;
  if (activity.isError) {
    return <p className={cn("font-semibold text-alert-text", className)}>The activity log didn't load.</p>;
  }
  const entries = activity.data.entries.slice(0, limit);
  if (!entries.length) {
    return <p className={cn("font-semibold text-muted", className)}>Nothing from Omi yet.</p>;
  }
  return (
    <ol className={cn("space-y-1.5", className)} aria-label="Recent Omi activity">
      {entries.map((entry) => {
        const outcome = OUTCOME[entry.outcome] ?? { label: entry.outcome, tone: "muted" as const };
        const kind = KIND[entry.kind];
        return (
          <li key={entry.id} className="flex items-start gap-2.5 rounded-[10px] border-2 border-line bg-sheet px-2.5 py-2">
            <kind.icon className="mt-0.5 size-4 shrink-0 text-muted" aria-hidden />
            <div className="min-w-0 flex-1">
              <p className="flex flex-wrap items-baseline gap-x-2 text-13">
                <span
                  className={cn(
                    "font-extrabold",
                    outcome.tone === "alert" ? "text-alert-text" : outcome.tone === "ok" ? "text-stamp-text" : "text-ink",
                  )}
                >
                  {outcome.label}
                </span>
                <span className="font-semibold text-muted">
                  {kind.label}
                  {entry.source === "simulator" ? " · simulator" : " · Omi"} · {when(entry.created_at, now)}
                </span>
              </p>
              {entry.detail ? <p className="text-13 font-semibold break-words text-muted">{entry.detail}</p> : null}
            </div>
          </li>
        );
      })}
    </ol>
  );
}

/** A long value (a webhook URL) with a Copy button. */
export function CopyField({ label, value, hint }: { label: string; value: string; hint?: string }) {
  const [state, setState] = useState<"idle" | "copied" | "failed">("idle");
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(value);
      setState("copied");
    } catch {
      setState("failed");
    }
    setTimeout(() => setState("idle"), 2000);
  };
  return (
    <div className="min-w-0">
      <p className="text-13 font-extrabold">{label}</p>
      {hint ? <p className="text-13 font-semibold text-muted">{hint}</p> : null}
      <div className="mt-1 flex items-stretch gap-2">
        <code className="min-w-0 flex-1 overflow-x-auto rounded-[10px] border-2 border-edge bg-paper px-2.5 py-2 font-mono text-13 whitespace-nowrap select-all">
          {value}
        </code>
        <button
          type="button"
          onClick={copy}
          className="press inline-flex min-h-11 shrink-0 items-center gap-1.5 rounded-button border-2 border-edge bg-sheet px-3 text-13 font-bold shadow-hard-sm"
        >
          {state === "copied" ? <Check className="size-4" aria-hidden /> : state === "failed" ? <CircleAlert className="size-4" aria-hidden /> : <Copy className="size-4" aria-hidden />}
          {state === "copied" ? "Copied" : state === "failed" ? "Select it" : "Copy"}
          <span className="sr-only"> {label}</span>
        </button>
      </div>
    </div>
  );
}
