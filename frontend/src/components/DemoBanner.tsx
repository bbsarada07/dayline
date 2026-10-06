import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { CircleAlert, Clock, RotateCcw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Sheet } from "@/components/ui/sheet";
import { api, errorMessage } from "@/lib/api";
import { useClock } from "@/lib/clock";
import { weekdayTime } from "@/lib/format";

/** Shown on every screen while demo time is on, with "Reset demo" on demo deployments. */
export function DemoBanner() {
  const client = useQueryClient();
  const { now, demo, demoMode } = useClock();
  const [confirming, setConfirming] = useState(false);
  const reset = useMutation({
    mutationFn: () => api<{ now: string }>("/demo/reset", { method: "POST", timeoutMs: 60_000 }),
    onSuccess: () => {
      setConfirming(false);
      client.invalidateQueries();
    },
  });

  if (!demo || !now) return null;
  return (
    <>
      <div
        className="sticky top-0 z-30 flex min-h-8 flex-wrap items-center justify-center gap-x-3 gap-y-1 border-b-2 border-edge bg-magenta px-4 py-1 text-13 font-bold text-white"
      >
        <span role="status" className="inline-flex items-center gap-2">
          <Clock className="size-4" aria-hidden />
          Demo time: {weekdayTime(now)}
        </span>
        {demoMode ? (
          <button
            type="button"
            onClick={() => {
              reset.reset();
              setConfirming(true);
            }}
            className="press inline-flex min-h-11 items-center gap-1.5 rounded-[8px] border-2 border-white px-2.5 font-bold sm:min-h-8"
          >
            <RotateCcw className="size-4" aria-hidden /> Reset demo
          </button>
        ) : null}
      </div>
      {demoMode ? (
        <Sheet
          open={confirming}
          onOpenChange={setConfirming}
          title="Reset the demo?"
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
      ) : null}
    </>
  );
}
