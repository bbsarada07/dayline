import { useRef, useState, type DragEvent, type ReactNode } from "react";
import { useLocation } from "react-router";
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CircleAlert, CircleCheck, FileText, Minus, Plus, Printer, Scissors, TriangleAlert, Upload } from "lucide-react";
import { Collapsed, PageHeading } from "@/components/PageParts";
import { EmptyState, ErrorState } from "@/components/states";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { api, errorMessage } from "@/lib/api";
import { useClock } from "@/lib/clock";
import { localInputs, money, plural, sameDay } from "@/lib/format";
import type { PrintJob, PrintQuote, PrintUpload } from "@/lib/types";
import { cn } from "@/lib/utils";
import type { PrintPrefill } from "@/features/ask/ProposalCard";
import { markNewPass } from "@/features/today/DayLine";
import { PrintJobSheet, PrintPass, printPassId, when } from "./printShared";

const MAX_COPIES = 20;
const MAX_BYTES = 20 * 1024 * 1024;

function Step({ n, title, children, done = false }: { n: number; title: string; children: ReactNode; done?: boolean }) {
  return (
    <section className="relative">
      <h3 className="flex items-center gap-3">
        <span
          aria-hidden
          className={cn(
            "flex size-9 shrink-0 items-center justify-center rounded-[10px] border-2 border-edge font-display text-17 font-extrabold shadow-hard-sm",
            done ? "bg-ink text-paper" : "bg-cyan text-on-fill",
          )}
        >
          {n}
        </span>
        <span className="font-display text-21 font-extrabold">{title}</span>
      </h3>
      <div className="mt-3">{children}</div>
    </section>
  );
}

function Toggle<T extends string>({ label, value, options, onChange }: {
  label: string;
  value: T;
  options: { value: T; label: string }[];
  onChange: (value: T) => void;
}) {
  return (
    <div>
      <p className="text-15 font-bold" id={`seg-${label}`}>{label}</p>
      <div role="radiogroup" aria-labelledby={`seg-${label}`} className="mt-2 grid grid-cols-2 gap-2">
        {options.map((option) => {
          const on = value === option.value;
          return (
            <button
              key={option.value}
              type="button"
              role="radio"
              aria-checked={on}
              onClick={() => onChange(option.value)}
              className={cn(
                "press min-h-12 rounded-[12px] border-2 border-edge px-2 text-15 font-bold",
                on ? "bg-ink text-paper shadow-hard-sm" : "bg-sheet text-ink",
              )}
            >
              {option.label}
            </button>
          );
        })}
      </div>
    </div>
  );
}

/** Hidden file input, always mounted so any "Choose a PDF" button can open it. */
function HiddenFileInput({ onPicked, busy, inputRef }: {
  onPicked: (file: File) => void;
  busy: boolean;
  inputRef: React.RefObject<HTMLInputElement | null>;
}) {
  return (
    <input
      ref={inputRef}
      type="file"
      accept="application/pdf,.pdf"
      className="sr-only"
      tabIndex={-1}
      aria-hidden
      disabled={busy}
      onChange={(e) => {
        const file = e.target.files?.[0];
        e.target.value = "";
        if (file) onPicked(file);
      }}
    />
  );
}

function DropZone({ onPicked, busy, inputRef }: {
  onPicked: (file: File) => void;
  busy: boolean;
  inputRef: React.RefObject<HTMLInputElement | null>;
}) {
  const [dragging, setDragging] = useState(false);
  const onDrop = (event: DragEvent) => {
    event.preventDefault();
    setDragging(false);
    const file = event.dataTransfer.files[0];
    if (file) onPicked(file);
  };
  return (
    <div
      onDragOver={(e) => {
        e.preventDefault();
        setDragging(true);
      }}
      onDragLeave={() => setDragging(false)}
      onDrop={onDrop}
      className={cn(
        "relative overflow-hidden rounded-[18px] border-[3px] border-dashed border-edge bg-paper p-6 text-center",
        dragging && "bg-cyan/20",
      )}
    >
      <span className="relative mx-auto flex size-16 items-center justify-center rounded-[16px] border-2 border-edge bg-cyan text-on-fill shadow-hard">
        <Upload className="size-8" aria-hidden />
      </span>
      <p className="relative mt-4 font-display text-21 font-extrabold">Drop your PDF here</p>
      <p className="relative text-13 font-semibold text-muted">PDF only, up to 20 MB</p>
      <Button size="lg" className="relative mt-4" onClick={() => inputRef.current?.click()} disabled={busy}>
        {busy ? "Uploading…" : "Choose a PDF"}
      </Button>
    </div>
  );
}

/** The quote, printed as a shop receipt with a torn edge. */
function Receipt({ q, now, refreshing, error }: { q: PrintQuote; now: Date; refreshing: boolean; error: unknown }) {
  const Row = ({ label, value }: { label: string; value: string }) => (
    <div className="flex items-baseline gap-2">
      <dt className="shrink-0 font-semibold text-muted">{label}</dt>
      <span aria-hidden className="mb-1 flex-1 border-b-2 border-dotted border-line" />
      <dd className="shrink-0 font-extrabold tabular-nums">{value}</dd>
    </div>
  );
  return (
    <div className={cn("rounded-[14px] border-2 border-edge bg-sheet shadow-hard", refreshing && "opacity-70")}>
      <div className="px-4 pt-4 pb-3">
        <p className="text-center font-display text-15 font-extrabold tracking-wide">Print shop receipt</p>
        <div aria-hidden className="my-3 border-t-2 border-dashed border-edge/60" />
        {error ? (
          <p role="alert" className="mb-3 flex items-start gap-2 font-semibold text-alert-text">
            <CircleAlert className="mt-0.5 size-5 shrink-0" aria-hidden />
            {errorMessage(error)}
          </p>
        ) : null}
        <dl className="space-y-2 text-15">
          <Row label={`${plural(q.pages, "page")} × ${plural(q.copies, "copy", "copies")}`} value={`× ${money(q.rate)}`} />
          <Row label="Needed by" value={when(q.deadline, now)} />
          <Row label="Estimated ready" value={when(q.est_ready_at, now)} />
          <Row label="Jobs ahead of you" value={String(q.jobs_ahead)} />
        </dl>
        <div aria-hidden className="my-3 border-t-2 border-dashed border-edge/60" />
        <div className="flex items-baseline justify-between">
          <span className="font-display text-17 font-extrabold">Total</span>
          <span className="font-display text-40 leading-none font-extrabold">{money(q.cost)}</span>
        </div>
        {q.warning ? (
          <p className="mt-3 flex items-start gap-2 rounded-[10px] border-2 border-alert-text p-2.5 font-bold text-alert-text">
            <TriangleAlert className="mt-0.5 size-5 shrink-0" aria-hidden />
            {q.warning}
          </p>
        ) : null}
      </div>
      {/* Perforation: the receipt's tear-off line. */}
      <div aria-hidden className="flex items-center gap-2 px-3 pb-3 text-muted">
        <Scissors className="size-4 shrink-0 -rotate-90" />
        <span className="flex-1 border-t-2 border-dashed border-edge/50" />
      </div>
    </div>
  );
}

function NewJob({ now, onCreated, inputRef, prefill }: {
  now: Date;
  onCreated: (job: PrintJob) => void;
  inputRef: React.RefObject<HTMLInputElement | null>;
  /** From "Edit" on an agent's proposal: the file and settings it chose. */
  prefill?: PrintPrefill;
}) {
  const client = useQueryClient();
  const [file, setFile] = useState<PrintUpload | null>(prefill?.upload ?? null);
  const [copies, setCopies] = useState(prefill?.copies ?? 1);
  const [color, setColor] = useState(prefill?.color ?? false);
  const [doubleSided, setDoubleSided] = useState(prefill?.double_sided ?? false);
  const [deadline, setDeadline] = useState<string | null>(prefill?.deadline ?? null); // "YYYY-MM-DDTHH:mm" college time; null = suggested
  const [pickError, setPickError] = useState<string | null>(null);
  const [pickedName, setPickedName] = useState<string | null>(null); // shown while the PDF uploads

  const upload = useMutation({
    mutationFn: (picked: File) => {
      const form = new FormData();
      form.append("file", picked);
      return api<PrintUpload>("/print/uploads", { method: "POST", body: form, timeoutMs: 120_000 });
    },
    onSuccess: (data) => {
      setFile(data);
      setPickedName(null);
    },
    onError: () => setPickedName(null),
  });

  const onPicked = (picked: File) => {
    setPickError(null);
    upload.reset();
    if (picked.size > MAX_BYTES) {
      setPickError("That PDF is bigger than 20 MB. Compress it or split it, then try again.");
      return;
    }
    setFile(null);
    setPickedName(picked.name);
    upload.mutate(picked);
  };

  const options = { upload_id: file?.upload_id, copies, color, double_sided: doubleSided, deadline: deadline ?? undefined };
  const quote = useQuery({
    queryKey: ["print", "quote", options],
    queryFn: () => api<PrintQuote>("/print/quote", { method: "POST", body: options }),
    enabled: file !== null,
    placeholderData: keepPreviousData,
    staleTime: 0,
    refetchInterval: 30_000,
  });

  const pay = useMutation({
    mutationFn: () => api<PrintJob>("/print/jobs", { method: "POST", body: options }),
    onSuccess: (job) => {
      setFile(null);
      markNewPass(printPassId(job));
      client.removeQueries({ queryKey: ["print", "quote"] });
      client.invalidateQueries({ queryKey: ["print", "mine"] });
      client.invalidateQueries({ queryKey: ["today"] });
      onCreated(job);
    },
  });

  const pickFailed = pickError ?? (upload.isError ? errorMessage(upload.error) : null);
  const fileInput = <HiddenFileInput onPicked={onPicked} busy={upload.isPending || pay.isPending} inputRef={inputRef} />;
  const pickErrorLine = pickFailed ? (
    <p role="alert" className="mt-3 flex items-start gap-2 font-semibold text-alert-text">
      <CircleAlert className="mt-0.5 size-5 shrink-0" aria-hidden />
      {pickFailed}
    </p>
  ) : null;

  if (!file && !upload.isPending) {
    return (
      <Step n={1} title="Pick a PDF">
        {fileInput}
        <DropZone onPicked={onPicked} busy={upload.isPending} inputRef={inputRef} />
        {pickErrorLine}
      </Step>
    );
  }

  const q = quote.data;
  const minDeadline = localInputs(now);
  const deadlineValue = deadline ?? (q ? `${localInputs(q.deadline).date}T${localInputs(q.deadline).time}` : "");

  return (
    <div className="space-y-7">
      {fileInput}
      <Step n={1} title="Pick a PDF" done>
        <div className="flex items-center gap-3 rounded-[14px] border-2 border-edge bg-paper p-3">
          <span className="flex size-11 shrink-0 items-center justify-center rounded-[10px] border-2 border-edge bg-cyan text-on-fill">
            <FileText className="size-5" aria-hidden />
          </span>
          <div className="min-w-0 flex-1">
            <p className="truncate font-extrabold" title={file?.original_filename ?? pickedName ?? ""}>
              {file?.original_filename ?? pickedName}
            </p>
            <p className="text-13 font-semibold text-muted">{file ? plural(file.pages, "page") : "Uploading and counting pages…"}</p>
          </div>
          <Button variant="secondary" onClick={() => inputRef.current?.click()} disabled={pay.isPending || upload.isPending}>
            {upload.isPending ? "Uploading…" : "Change file"}
          </Button>
        </div>
        {pickErrorLine}
      </Step>

      <Step n={2} title="Choose how">
        <div className="space-y-4">
          <div>
            <p className="text-15 font-bold" id="copies-label">Copies</p>
            <div className="mt-2 inline-flex items-center gap-2" role="group" aria-labelledby="copies-label">
              <Button variant="secondary" size="icon" aria-label="One copy fewer" disabled={copies <= 1} onClick={() => setCopies((c) => c - 1)}>
                <Minus aria-hidden />
              </Button>
              <output aria-live="polite" className="w-14 text-center font-display text-40 leading-none font-extrabold tabular-nums">
                {copies}
              </output>
              <Button variant="secondary" size="icon" aria-label="One copy more" disabled={copies >= MAX_COPIES} onClick={() => setCopies((c) => c + 1)}>
                <Plus aria-hidden />
              </Button>
            </div>
          </div>
          <div className="grid gap-4 sm:grid-cols-2">
            <Toggle
              label="Colour"
              value={color ? "colour" : "bw"}
              options={[{ value: "bw", label: "Black and white" }, { value: "colour", label: "Colour" }]}
              onChange={(v) => setColor(v === "colour")}
            />
            <Toggle
              label="Sides"
              value={doubleSided ? "double" : "single"}
              options={[{ value: "single", label: "Single sided" }, { value: "double", label: "Double sided" }]}
              onChange={(v) => setDoubleSided(v === "double")}
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="deadline">Needed by</Label>
            <div className="flex flex-wrap items-center gap-2">
              <input
                id="deadline"
                type="datetime-local"
                value={deadlineValue}
                min={`${minDeadline.date}T${minDeadline.time}`}
                onChange={(e) => setDeadline(e.target.value || null)}
                className="min-h-12 rounded-button border-2 border-edge bg-sheet px-3 text-17 font-semibold text-ink"
              />
              {deadline !== null ? (
                <Button variant="ghost" onClick={() => setDeadline(null)}>
                  Use suggested time
                </Button>
              ) : null}
            </div>
            {q?.deadline_reason && deadline === null ? <p className="text-13 font-semibold text-muted">{q.deadline_reason}</p> : null}
          </div>
        </div>
      </Step>

      <Step n={3} title="Check and pay">
        <section aria-label="Price and timing" aria-live="polite">
          {quote.isError && !q ? (
            <ErrorState error={quote.error} onRetry={() => quote.refetch()} title="Couldn't price this job" />
          ) : !q ? (
            <Skeleton className="h-56" />
          ) : (
            <Receipt q={q} now={now} refreshing={quote.isFetching} error={quote.isError ? quote.error : null} />
          )}
        </section>

        <div className="mt-5">
          <p className="inline-block rounded-[6px] border-2 border-dashed border-edge bg-paper px-2.5 py-1 text-13 font-extrabold">
            Demo payment — no money moves
          </p>
          <Button size="lg" className="mt-3 w-full text-21" disabled={!q || quote.isFetching || pay.isPending} onClick={() => pay.mutate()}>
            {pay.isPending ? "Paying…" : q ? `Confirm and pay ${money(q.cost)}` : "Confirm and pay"}
          </Button>
          <p className="mt-2 text-center text-13 font-semibold text-muted">The job joins the shop's queue as soon as you confirm.</p>
          {pay.isError ? (
            <p role="alert" className="mt-3 flex items-start gap-2 font-semibold text-alert-text">
              <CircleAlert className="mt-0.5 size-5 shrink-0" aria-hidden />
              {errorMessage(pay.error)}
            </p>
          ) : null}
        </div>
      </Step>
    </div>
  );
}

const ACTIVE: PrintJob["status"][] = ["queued", "printing", "ready"];

/** Jobs on the way first, then finished ones folded away ("Earlier today", "Past jobs"). */
function JobGroups({ jobs, now, onOpen }: { jobs: PrintJob[]; now: Date; onOpen: (id: number) => void }) {
  const active = jobs.filter((j) => ACTIVE.includes(j.status));
  const finished = jobs.filter((j) => !ACTIVE.includes(j.status));
  const finishedOn = (j: PrintJob) => j.collected_at ?? j.deadline;
  const earlierToday = finished.filter((j) => sameDay(finishedOn(j), now));
  const past = finished.filter((j) => !sameDay(finishedOn(j), now));
  const ticket = (job: PrintJob) => (
    <button
      key={job.id}
      type="button"
      className="block w-full rounded-surface text-left"
      onClick={() => onOpen(job.id)}
      aria-label={`${job.code}, ${job.original_filename}. Show details`}
    >
      <PrintPass job={job} now={now} />
    </button>
  );
  return (
    <div className="space-y-4">
      {active.length ? (
        <ul className="space-y-5">
          {active.map((job) => (
            <li key={job.id}>{ticket(job)}</li>
          ))}
        </ul>
      ) : (
        <p className="font-semibold text-muted">Nothing printing right now.</p>
      )}
      <Collapsed title="Earlier today" count={earlierToday.length}>{earlierToday.map(ticket)}</Collapsed>
      <Collapsed title="Past jobs" count={past.length}>{past.map(ticket)}</Collapsed>
    </div>
  );
}

export function PrintPage() {
  const { now } = useClock();
  const location = useLocation();
  const prefill = (location.state as { prefill?: PrintPrefill } | null)?.prefill;
  const fileInput = useRef<HTMLInputElement>(null);
  const [selected, setSelected] = useState<number | null>(null);
  const [created, setCreated] = useState<PrintJob | null>(null);
  const jobs = useQuery({ queryKey: ["print", "mine"], queryFn: () => api<{ jobs: PrintJob[] }>("/print/jobs/mine") });
  const list = jobs.data?.jobs ?? [];
  const selectedJob = list.find((j) => j.id === selected) ?? null;

  return (
    <div>
      <PageHeading
        title="Print"
        subtitle="Printed before your class."
        icon={Printer}
        className="bg-cyan text-on-fill"
      />

      <div className="mt-6 grid items-start gap-8 lg:grid-cols-[minmax(0,1.1fr)_minmax(0,1fr)]">
        <section aria-labelledby="new-job" className="rounded-[20px] border-2 border-edge bg-sheet p-4 shadow-hard sm:p-6">
          <h2 id="new-job" className="sr-only">Print a file</h2>
          {created ? (
            <div role="status" className="mb-5 flex items-start gap-3 rounded-[14px] border-2 border-edge bg-paper p-3">
              <span className="flex size-10 shrink-0 items-center justify-center rounded-[10px] border-2 border-edge bg-cyan text-on-fill">
                <CircleCheck className="size-5" aria-hidden />
              </span>
              <div className="min-w-0">
                <p className="font-extrabold">{created.code} is in the queue</p>
                <p className="text-13 font-semibold text-muted">You'll get a notice here when it's ready.</p>
              </div>
            </div>
          ) : null}
          {now ? <NewJob key={location.key} now={now} inputRef={fileInput} prefill={prefill} onCreated={(job) => setCreated(job)} /> : <Skeleton className="h-56" />}
        </section>

        <section aria-labelledby="my-jobs" className="min-w-0">
          <h2 id="my-jobs" className="font-display text-28 font-extrabold">Your print jobs</h2>
          <div className="mt-4">
            {jobs.isPending || !now ? (
              <div className="space-y-4" aria-busy="true" aria-label="Loading print jobs">
                <Skeleton className="h-40" />
                <Skeleton className="h-40" />
              </div>
            ) : jobs.isError ? (
              <ErrorState error={jobs.error} onRetry={() => jobs.refetch()} title="Your print jobs didn't load" />
            ) : list.length === 0 ? (
              <EmptyState
                icon={Printer}
                title="No print jobs yet"
                action={<Button variant="secondary" onClick={() => fileInput.current?.click()}>Choose a PDF</Button>}
              >
                Upload a PDF and the print shop will have it ready before your class.
              </EmptyState>
            ) : (
              <JobGroups jobs={list} now={now} onOpen={setSelected} />
            )}
          </div>
        </section>
      </div>

      {now ? <PrintJobSheet job={selectedJob} now={now} onClose={() => setSelected(null)} /> : null}
    </div>
  );
}
