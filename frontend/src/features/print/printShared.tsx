import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Check, CircleAlert, ExternalLink, Printer } from "lucide-react";
import { Pass } from "@/components/Pass";
import { Stamp, useBecameWhileShown } from "@/components/Stamp";
import { Button, buttonVariants } from "@/components/ui/button";
import { Sheet } from "@/components/ui/sheet";
import { api, errorMessage } from "@/lib/api";
import { dayDate, money, plural, sameDay, timeOfDay } from "@/lib/format";
import type { PrintJob, PrintStatus } from "@/lib/types";
import { cn } from "@/lib/utils";
import { CollectBarcode } from "@/features/canteen/canteenShared";

export const STATUS_LABEL: Record<PrintStatus, string> = {
  queued: "In the queue",
  printing: "Printing now",
  ready: "Ready to collect",
  collected: "Collected",
  cancelled: "Cancelled",
  expired: "Expired: not collected within 24 hours",
};

/** Id of a print job's pass on the day line. */
export const printPassId = (job: Pick<PrintJob, "id">) => `print-${job.id}`;

const STEPS: PrintStatus[] = ["queued", "printing", "ready", "collected"];

export function optionsLabel(job: Pick<PrintJob, "color" | "double_sided">): string {
  return `${job.color ? "Colour" : "Black and white"} · ${job.double_sided ? "Double sided" : "Single sided"}`;
}

export function pagesLabel(job: Pick<PrintJob, "pages" | "copies">): string {
  return `${plural(job.pages, "page")} × ${plural(job.copies, "copy", "copies")}`;
}

/** "1:50 pm" today, "Tue 6 Oct, 1:50 pm" on another day. */
export function when(value: string, now: Date): string {
  return sameDay(value, now) ? timeOfDay(value) : `${dayDate(value)}, ${timeOfDay(value)}`;
}

/** One line saying where the job is, in words. */
export function statusLine(job: PrintJob, now: Date): string {
  if (job.status === "queued" || job.status === "printing") {
    return `${STATUS_LABEL[job.status]} · ready about ${when(job.est_ready_at, now)}`;
  }
  if (job.status === "ready") return "Ready to collect at the print shop";
  return STATUS_LABEL[job.status];
}

/** Rubber-stamp status for finished and ready jobs. */
function StatusStamp({ status, press = false }: { status: PrintStatus; press?: boolean }) {
  if (status !== "ready" && status !== "collected" && status !== "cancelled" && status !== "expired") return null;
  const tone = status === "collected" ? "success" : status === "ready" ? "neutral" : "alert";
  const text = status === "expired" ? "Expired" : status === "ready" ? "Ready" : STATUS_LABEL[status];
  return <Stamp text={text} tone={tone} press={press} />;
}

/** The cyan pass for a print job (day line, job list). */
export function PrintPass({ job, now }: { job: PrintJob; now: Date }) {
  const active = job.status === "queued" || job.status === "printing";
  // Collected while on screen (a scan at the print desk): the stamp presses on.
  const justCollected = useBecameWhileShown(job.status, "collected");
  return (
    <Pass
      tone="cyan"
      header={
        <>
          <span className="inline-flex min-w-0 items-center gap-2">
            <Printer className="size-[18px] shrink-0" aria-hidden />
            <span className="truncate">Printout</span>
          </span>
          <span className="shrink-0 tabular-nums">{job.code}</span>
        </>
      }
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="truncate text-17 font-extrabold">{job.original_filename}</p>
          <p className="mt-0.5 text-13 font-semibold text-muted">
            {pagesLabel(job)} · {optionsLabel(job)}
          </p>
        </div>
        <StatusStamp status={job.status} press={justCollected} />
      </div>
      <div className="mt-2.5 flex items-end justify-between gap-3">
        <div className="min-w-0 text-13">
          {active ? <p className="font-bold">{statusLine(job, now)}</p> : null}
          {active || job.status === "ready" ? <p className="font-semibold text-muted">Needed by {when(job.deadline, now)}</p> : null}
          {job.status === "ready" ? <p className="font-bold">Collect it at the print shop</p> : null}
        </div>
        <p className="shrink-0 font-display text-21 font-extrabold">{money(job.cost)}</p>
      </div>
    </Pass>
  );
}

function Steps({ status }: { status: PrintStatus }) {
  const reached = STEPS.indexOf(status);
  if (reached < 0) return <StatusStamp status={status} />;
  return (
    <ol className="grid grid-cols-4 gap-1.5" aria-label="Progress">
      {STEPS.map((step, index) => {
        const done = index <= reached;
        return (
          <li key={step} className="min-w-0">
            <span
              className={cn("block h-3 rounded-full border-2 border-edge", done ? "bg-cyan" : "bg-sheet")}
              aria-hidden
            />
            <span className={cn("mt-1.5 flex items-start gap-1 text-13", done ? "font-extrabold" : "font-semibold text-muted")}>
              {index === reached ? <Check className="mt-0.5 size-3.5 shrink-0" aria-hidden /> : null}
              <span>{STATUS_LABEL[step]}</span>
              {index === reached ? <span className="sr-only">(current step)</span> : null}
            </span>
          </li>
        );
      })}
    </ol>
  );
}

function Detail({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex justify-between gap-4 py-2">
      <dt className="font-semibold text-muted">{label}</dt>
      <dd className="min-w-0 text-right font-bold break-words">{children}</dd>
    </div>
  );
}

/** Full details of one job, with cancel while it's still queued. */
export function PrintJobSheet({ job, now, onClose }: { job: PrintJob | null; now: Date; onClose: () => void }) {
  const client = useQueryClient();
  const [confirming, setConfirming] = useState(false);
  const cancel = useMutation({
    mutationFn: (id: number) => api<PrintJob>(`/print/jobs/${id}/cancel`, { method: "POST" }),
    onSuccess: () => {
      setConfirming(false);
      client.invalidateQueries({ queryKey: ["print"] });
      client.invalidateQueries({ queryKey: ["today"] });
    },
  });

  const close = () => {
    setConfirming(false);
    cancel.reset();
    onClose();
  };

  return (
    <Sheet open={job !== null} onOpenChange={(open) => !open && close()} title={job ? `Print job ${job.code}` : ""}>
      {job ? (
        <div>
          <Steps status={job.status} />
          {job.status === "ready" ? <CollectBarcode /> : null}
          <dl className="mt-4 divide-y-2 divide-dashed divide-line">
            <Detail label="File">{job.original_filename}</Detail>
            <Detail label="Pages">{pagesLabel(job)}</Detail>
            <Detail label="Options">{optionsLabel(job)}</Detail>
            <Detail label="Needed by">{when(job.deadline, now)}</Detail>
            {job.status === "queued" || job.status === "printing" ? (
              <Detail label="Estimated ready">{when(job.est_ready_at, now)}</Detail>
            ) : null}
            {job.ready_at ? <Detail label="Ready at">{when(job.ready_at, now)}</Detail> : null}
            {job.collected_at ? <Detail label="Collected at">{when(job.collected_at, now)}</Detail> : null}
            <Detail label="Cost">
              {money(job.cost)} <span className="font-semibold text-muted">(demo payment)</span>
            </Detail>
          </dl>

          <div className="mt-4 flex flex-wrap gap-2">
            {job.has_file ? (
              <a
                href={`/api/print/jobs/${job.id}/file`}
                target="_blank"
                rel="noopener"
                className={buttonVariants({ variant: "secondary" })}
              >
                <ExternalLink aria-hidden /> Open file
              </a>
            ) : null}
            {job.status === "queued" && !confirming ? (
              <Button variant="secondary" onClick={() => setConfirming(true)}>
                Cancel job
              </Button>
            ) : null}
          </div>

          {job.status === "queued" && confirming ? (
            <div className="mt-4 rounded-[14px] border-2 border-edge bg-tint p-4">
              <p className="font-extrabold">Cancel {job.code}?</p>
              <p className="mt-1 text-muted">The file is deleted from the shop. This was a demo payment, so no money moves.</p>
              <div className="mt-3 flex flex-wrap gap-2">
                <Button onClick={() => cancel.mutate(job.id)} disabled={cancel.isPending}>
                  {cancel.isPending ? "Cancelling…" : "Cancel job"}
                </Button>
                <Button variant="ghost" onClick={() => setConfirming(false)} disabled={cancel.isPending}>
                  Keep job
                </Button>
              </div>
            </div>
          ) : null}

          {cancel.isError ? (
            <p role="alert" className="mt-3 flex items-start gap-2 font-semibold text-alert-text">
              <CircleAlert className="mt-0.5 size-5 shrink-0" aria-hidden />
              {errorMessage(cancel.error)}
            </p>
          ) : null}
        </div>
      ) : null}
    </Sheet>
  );
}
