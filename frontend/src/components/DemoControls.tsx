import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { CircleAlert, Clock, RotateCcw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Sheet } from "@/components/ui/sheet";
import { api, errorMessage } from "@/lib/api";
import { useClock } from "@/lib/clock";
import { clockTime, dayDate, weekdayTime } from "@/lib/format";
import { cn } from "@/lib/utils";

/** Demo time is running on a demo deployment: the only time these controls show. */
export function useDemoOn() {
  const { now, demo, demoMode } = useClock();
  return { on: Boolean(now && demo && demoMode), now };
}

/** "Reset demo" with a confirmation first. Renders the trigger via `children(open)`. */
export function ResetDemo({ children }: { children: (open: () => void) => React.ReactNode }) {
  const client = useQueryClient();
  const [confirming, setConfirming] = useState(false);
  const reset = useMutation({
    mutationFn: () => api<{ now: string }>("/demo/reset", { method: "POST", timeoutMs: 60_000 }),
    onSuccess: (data) => {
      setConfirming(false);
      // Show the new demo time at once, then refetch everything else.
      client.setQueryData(["clock"], { now: data.now, demo: true, demo_mode: true });
      client.invalidateQueries({ predicate: (q) => q.queryKey[0] !== "clock" });
    },
  });
  const open = () => {
    reset.reset();
    setConfirming(true);
  };
  return (
    <>
      {children(open)}
      <Sheet
        open={confirming}
        onOpenChange={setConfirming}
        title="Reset all demo data?"
        description="Everyone using this demo goes back to Monday 12:20 with fresh data. Orders, print jobs and scans made so far are cleared."
      >
        {reset.isError ? (
          <p role="alert" className="mb-3 flex items-start gap-2 font-semibold text-alert-text">
            <CircleAlert className="mt-0.5 size-5 shrink-0" aria-hidden />
            {errorMessage(reset.error)}
          </p>
        ) : null}
        <div className="flex flex-wrap gap-2">
          <Button onClick={() => reset.mutate()} disabled={reset.isPending}>
            <RotateCcw aria-hidden /> {reset.isPending ? "Resetting…" : "Reset demo"}
          </Button>
          <Button variant="secondary" onClick={() => setConfirming(false)} disabled={reset.isPending}>
            Keep going
          </Button>
        </div>
      </Sheet>
    </>
  );
}

/** Laptop sidebar and staff header: "Demo time Mon 12:36 · Reset demo". */
export function DemoChip({ onDark = false, stacked = false, className }: {
  onDark?: boolean;
  /** Narrow places (the sidebar): time on one line, "Reset demo" under it. */
  stacked?: boolean;
  className?: string;
}) {
  const { on, now } = useDemoOn();
  if (!on || !now) return null;
  return (
    <ResetDemo>
      {(open) => (
        <div
          className={cn(
            "flex flex-wrap items-center gap-x-1.5 gap-y-1 rounded-[12px] border-2 px-2.5 py-1.5 text-13 font-bold",
            onDark ? "border-hero-muted/40 text-hero-muted" : "border-line bg-sheet text-muted",
            className,
          )}
        >
          <Clock className="size-4 shrink-0" aria-hidden />
          <span role="status">Demo time {weekdayTime(now)}</span>
          {stacked ? <span className="basis-full" aria-hidden /> : <span aria-hidden>·</span>}
          <button
            type="button"
            onClick={open}
            className={cn("min-h-8 rounded-[6px] px-1 font-extrabold underline underline-offset-2", onDark ? "text-hero-text" : "text-ink")}
          >
            Reset demo
          </button>
        </div>
      )}
    </ResetDemo>
  );
}

/** Phones and tablets, under the greeting on Today: "Mon 5 Oct · demo time 12:36". */
export function DemoTimeLine({ className }: { className?: string }) {
  const { on, now } = useDemoOn();
  if (!on || !now) return null;
  return (
    <p role="status" className={cn("flex items-center gap-1.5 text-13 font-bold", className)}>
      <Clock className="size-4 shrink-0" aria-hidden />
      {dayDate(now)} · demo time {clockTime(now)}
    </p>
  );
}

/** Phones and tablets, on Profile: the "Reset demo" button (laptops use the sidebar chip). */
export function ResetDemoButton({ className }: { className?: string }) {
  const { on } = useDemoOn();
  if (!on) return null;
  return (
    <ResetDemo>
      {(open) => (
        <Button variant="secondary" size="lg" className={cn("w-full", className)} onClick={open}>
          <RotateCcw aria-hidden /> Reset demo
        </Button>
      )}
    </ResetDemo>
  );
}
