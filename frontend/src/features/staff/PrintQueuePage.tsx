import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CircleAlert, ExternalLink, Printer } from "lucide-react";
import { EmptyState, ErrorState } from "@/components/states";
import { Button, buttonVariants } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { api, errorMessage } from "@/lib/api";
import { useClock } from "@/lib/clock";
import { minutesBetween, money, plural, timeLeft } from "@/lib/format";
import type { PrintJob, PrintQueue } from "@/lib/types";
import { cn } from "@/lib/utils";
import { STATUS_LABEL, optionsLabel, when } from "@/features/print/printShared";
import { CollectDesk } from "./CollectDesk";

type NextStep = { status: "printing" | "ready" | "collected"; label: string };

const NEXT: Record<string, NextStep | undefined> = {
  queued: { status: "printing", label: "Start printing" },
  printing: { status: "ready", label: "Mark ready" },
  ready: { status: "collected", label: "Mark collected" },
};

function isUrgent(job: PrintJob, now: Date, urgentMinutes: number) {
  return (job.status === "queued" || job.status === "printing") && minutesBetween(now, job.deadline) <= urgentMinutes;
}

function CodeTag({ code }: { code: string }) {
  return (
    <span className="inline-block rounded-[8px] border-2 border-edge bg-cyan px-2 py-0.5 font-display text-17 font-extrabold text-on-fill tabular-nums">
      {code}
    </span>
  );
}

function UrgentStamp() {
  return (
    <span className="inline-block rounded-[6px] border-[3px] border-magenta-text px-1.5 font-display text-13 font-extrabold text-magenta-text">
      Urgent
    </span>
  );
}

function OpenFile({ job }: { job: PrintJob }) {
  if (!job.has_file) return <span className="text-13 font-semibold text-muted">File deleted</span>;
  return (
    <a
      href={`/api/print/jobs/${job.id}/file`}
      target="_blank"
      rel="noopener"
      className={buttonVariants({ variant: "secondary", className: "min-h-12" })}
    >
      <ExternalLink aria-hidden /> Open file
    </a>
  );
}

function Deadline({ job, now, urgent }: { job: PrintJob; now: Date; urgent: boolean }) {
  return (
    <div>
      <p className="font-display text-17 font-extrabold tabular-nums">{when(job.deadline, now)}</p>
      <p className={cn("text-13 font-bold", urgent ? "text-magenta-text" : "text-muted")}>{timeLeft(now, job.deadline)}</p>
      {urgent ? <UrgentStamp /> : null}
    </div>
  );
}

function StepButton({ job, busy, onStep }: { job: PrintJob; busy: boolean; onStep: (job: PrintJob, step: NextStep) => void }) {
  const step = NEXT[job.status];
  if (!step) return null;
  return (
    <Button
      variant={step.status === "collected" ? "secondary" : "primary"}
      className="min-h-14 w-full px-5 text-17 sm:w-auto"
      disabled={busy}
      onClick={() => onStep(job, step)}
    >
      {busy ? "Saving…" : step.label}
      <span className="sr-only"> {job.code}</span>
    </Button>
  );
}

type SectionProps = {
  title: string;
  jobs: PrintJob[];
  now: Date;
  urgentMinutes: number;
  busyId: number | null;
  onStep: (job: PrintJob, step: NextStep) => void;
  empty: string;
};

function QueueSection({ title, jobs, now, urgentMinutes, busyId, onStep, empty }: SectionProps) {
  return (
    <section aria-label={title} className="mt-8">
      <h2 className="font-display text-28 font-extrabold">
        {title} <span className="text-muted">({jobs.length})</span>
      </h2>
      {jobs.length === 0 ? (
        <p className="mt-3 rounded-[14px] border-2 border-dashed border-edge bg-sheet p-4 font-semibold text-muted">{empty}</p>
      ) : (
        <>
          {/* Shop PC: dense table. */}
          <div className="mt-3 hidden overflow-hidden rounded-[16px] border-2 border-edge bg-sheet shadow-hard lg:block">
            <table className="w-full border-collapse text-left">
              <thead className="bg-hero text-13 text-hero-text">
                <tr>
                  {["Job", "Student", "File", "Pages", "Options", "Needed by", "Status", ""].map((h) => (
                    <th key={h} scope="col" className="px-3 py-2.5 font-bold">
                      {h || <span className="sr-only">Actions</span>}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {jobs.map((job) => {
                  const urgent = isUrgent(job, now, urgentMinutes);
                  return (
                    <tr key={job.id} className={cn("border-t-2 border-line align-top", urgent && "bg-magenta/8")}>
                      <td className={cn("py-3 pr-3 pl-3", urgent && "border-l-[8px] border-l-magenta")}>
                        <CodeTag code={job.code} />
                      </td>
                      <td className="max-w-40 px-3 py-3">
                        <p className="truncate font-bold">{job.student_name}</p>
                        <p className="text-13 font-semibold text-muted">{job.roll_no}</p>
                      </td>
                      <td className="max-w-56 px-3 py-3">
                        <p className="truncate font-semibold" title={job.original_filename}>{job.original_filename}</p>
                        <p className="text-13 font-semibold text-muted">{money(job.cost)} paid (demo)</p>
                      </td>
                      <td className="px-3 py-3 font-display text-17 font-extrabold whitespace-nowrap tabular-nums">
                        {job.pages} × {job.copies}
                      </td>
                      <td className="px-3 py-3 text-13 font-semibold">{optionsLabel(job)}</td>
                      <td className="px-3 py-3 whitespace-nowrap">
                        <Deadline job={job} now={now} urgent={urgent} />
                      </td>
                      <td className="px-3 py-3 text-13 font-bold">{STATUS_LABEL[job.status]}</td>
                      <td className="px-3 py-3">
                        <div className="flex justify-end gap-2">
                          <OpenFile job={job} />
                          <StepButton job={job} busy={busyId === job.id} onStep={onStep} />
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>

          {/* Smaller screens: one card per job. */}
          <ul className="mt-3 space-y-4 lg:hidden">
            {jobs.map((job) => {
              const urgent = isUrgent(job, now, urgentMinutes);
              return (
                <li
                  key={job.id}
                  className={cn(
                    "min-w-0 rounded-[16px] border-2 border-edge bg-sheet p-4 shadow-hard",
                    urgent && "border-l-[8px] border-l-magenta",
                  )}
                >
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <CodeTag code={job.code} />
                      <p className="mt-2 truncate font-bold">
                        {job.student_name} <span className="font-semibold text-muted">· {job.roll_no}</span>
                      </p>
                    </div>
                    <div className="shrink-0 text-right">
                      <Deadline job={job} now={now} urgent={urgent} />
                    </div>
                  </div>
                  <p className="mt-2 truncate font-semibold" title={job.original_filename}>{job.original_filename}</p>
                  <p className="text-13 font-semibold text-muted">
                    {plural(job.pages, "page")} × {plural(job.copies, "copy", "copies")} · {optionsLabel(job)}
                  </p>
                  <p className="mt-1 text-13 font-bold">{STATUS_LABEL[job.status]}</p>
                  <div className="mt-3 flex flex-wrap gap-2">
                    <OpenFile job={job} />
                    <StepButton job={job} busy={busyId === job.id} onStep={onStep} />
                  </div>
                </li>
              );
            })}
          </ul>
        </>
      )}
    </section>
  );
}

function Counter({ value, label, tone }: { value: number; label: string; tone: string }) {
  return (
    <div className="relative overflow-hidden rounded-[16px] border-2 border-edge bg-sheet px-4 pt-4 pb-3 shadow-hard">
      <span aria-hidden className={cn("absolute top-0 left-0 h-2 w-full", tone)} />
      <p className="font-display text-40 leading-none font-extrabold tabular-nums">{value}</p>
      <p className="mt-1 text-13 font-bold text-muted">{label}</p>
    </div>
  );
}

/** Print shop dashboard. Updates live as students pay for jobs. */
export function PrintQueuePage() {
  const client = useQueryClient();
  const { now } = useClock();
  const queue = useQuery({
    queryKey: ["print", "queue"],
    queryFn: () => api<PrintQueue>("/print/queue"),
    refetchInterval: 60_000,
  });
  const step = useMutation({
    mutationFn: ({ job, next }: { job: PrintJob; next: NextStep }) =>
      api<PrintJob>(`/print/jobs/${job.id}/status`, { method: "POST", body: { status: next.status } }),
    onSettled: () => client.invalidateQueries({ queryKey: ["print"] }),
  });
  const busyId = step.isPending ? (step.variables?.job.id ?? null) : null;
  const onStep = (job: PrintJob, next: NextStep) => step.mutate({ job, next });
  const data = queue.data;
  const urgentCount = data && now ? data.to_print.filter((j) => isUrgent(j, now, data.urgent_minutes)).length : 0;

  return (
    <div>
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="misprint-cyan font-display text-40 leading-none font-extrabold sm:text-64">Print queue</h1>
          <p className="mt-2 font-semibold text-muted">Sorted by when students need them. New jobs appear on their own.</p>
        </div>
      </div>

      {data ? (
        <div className="mt-6 grid grid-cols-3 gap-3 sm:max-w-xl">
          <Counter value={data.to_print.length} label="to print" tone="bg-cyan" />
          <Counter value={urgentCount} label="urgent" tone="bg-magenta" />
          <Counter value={data.ready.length} label="waiting for pickup" tone="bg-stamp" />
        </div>
      ) : null}

      <div className="mt-6">
        <CollectDesk station="print" />
      </div>

      {step.isError ? (
        <p role="alert" className="mt-5 flex items-start gap-2 rounded-[14px] border-2 border-edge bg-sheet p-3 font-semibold text-alert-text">
          <CircleAlert className="mt-0.5 size-5 shrink-0" aria-hidden />
          {errorMessage(step.error)}
        </p>
      ) : null}

      {queue.isPending || !now ? (
        <div className="mt-6 space-y-3" aria-busy="true" aria-label="Loading the queue">
          <Skeleton className="h-24 sm:max-w-xl" />
          <Skeleton className="h-20" />
          <Skeleton className="h-20" />
        </div>
      ) : queue.isError ? (
        <div className="mt-6">
          <ErrorState error={queue.error} onRetry={() => queue.refetch()} title="The queue didn't load" />
        </div>
      ) : queue.data.to_print.length === 0 && queue.data.ready.length === 0 ? (
        <div className="mt-8">
          <EmptyState icon={Printer} title="No print jobs right now">
            When a student pays for a printout it shows up here, sorted by when they need it.
          </EmptyState>
        </div>
      ) : (
        <>
          <QueueSection
            title="To print"
            jobs={queue.data.to_print}
            now={now}
            urgentMinutes={queue.data.urgent_minutes}
            busyId={busyId}
            onStep={onStep}
            empty="Nothing to print. Ready jobs are below."
          />
          <QueueSection
            title="Waiting for pickup"
            jobs={queue.data.ready}
            now={now}
            urgentMinutes={queue.data.urgent_minutes}
            busyId={busyId}
            onStep={onStep}
            empty="No printouts waiting for pickup."
          />
        </>
      )}
    </div>
  );
}
