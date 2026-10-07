import { useState } from "react";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { ChartNoAxesColumn, ChevronDown, CircleCheck, FlaskConical, Minus, Plus, TriangleAlert } from "lucide-react";
import { EmptyState, ErrorState } from "@/components/states";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { api, errorMessage } from "@/lib/api";
import { percent, plural } from "@/lib/format";
import type { AttendanceData, Standing, SubjectAttendance, WhatIfResult } from "@/lib/types";
import { cn } from "@/lib/utils";

const MAX_MISS = 20;

function StandingIcon({ standing }: { standing: Standing }) {
  if (standing.status === "below") return <TriangleAlert className="mt-0.5 size-[18px] shrink-0 text-alert-text" aria-hidden />;
  if (standing.status === "ok") return <CircleCheck className="mt-0.5 size-[18px] shrink-0 text-stamp-text" aria-hidden />;
  return null;
}

/** Chunky bar with a notch at the threshold. The statement says the same thing in words. */
function ProgressBar({ standing }: { standing: Standing }) {
  const value = standing.percentage ?? 0;
  return (
    <div className="relative mt-4 h-4 rounded-full border-2 border-edge bg-paper" aria-hidden>
      <div
        className={cn("h-full rounded-full", standing.status === "below" ? "bg-alert" : "bg-magenta")}
        style={{ width: `${Math.min(100, value)}%` }}
      />
      <span className="absolute -top-2 -bottom-2 w-1 -translate-x-1/2 rounded-full bg-ink" style={{ left: `${standing.threshold}%` }} />
    </div>
  );
}

function WhatIf({ subject }: { subject: SubjectAttendance }) {
  const [miss, setMiss] = useState(1);
  const result = useQuery({
    queryKey: ["what-if", subject.subject_id, miss],
    queryFn: () =>
      api<WhatIfResult>("/attendance/what-if", { method: "POST", body: { subject_id: subject.subject_id, miss } }),
    placeholderData: keepPreviousData,
    staleTime: 0,
  });
  const after = result.data?.after;
  const name = subject.short_name ?? subject.name;

  return (
    <div className="relative mt-3 overflow-hidden rounded-[14px] border-2 border-edge bg-hero p-4 text-hero-text">
      <div className="relative flex flex-wrap items-center gap-x-3 gap-y-2">
        <span id={`miss-label-${subject.subject_id}`} className="font-bold">If I miss the next</span>
        <div className="inline-flex items-center gap-2" role="group" aria-labelledby={`miss-label-${subject.subject_id}`}>
          <Button variant="hero" size="icon" onClick={() => setMiss((m) => Math.max(1, m - 1))} disabled={miss <= 1} aria-label="One class fewer">
            <Minus aria-hidden />
          </Button>
          <output className="w-12 text-center font-display text-40 leading-none font-extrabold tabular-nums" aria-live="polite">
            {miss}
          </output>
          <Button variant="hero" size="icon" onClick={() => setMiss((m) => Math.min(MAX_MISS, m + 1))} disabled={miss >= MAX_MISS} aria-label="One class more">
            <Plus aria-hidden />
          </Button>
        </div>
        <span className="font-bold">{miss === 1 ? "class" : "classes"} of {name}</span>
      </div>

      <div className="relative mt-4 min-h-14" aria-live="polite">
        {result.isError && !result.data ? (
          <p className="font-semibold">
            {errorMessage(result.error)}{" "}
            <button type="button" className="font-bold underline" onClick={() => result.refetch()}>
              Try again
            </button>
          </p>
        ) : after ? (
          <div className={cn(result.isFetching && "opacity-70")}>
            <p className="flex flex-wrap items-baseline gap-x-2">
              <span className="text-hero-muted">You'd be at</span>
              <span className="misprint font-display text-40 leading-none font-extrabold">
                {after.percentage === null ? "—" : percent(after.percentage)}
              </span>
              <span className="text-hero-muted">
                ({after.attended} of {after.held})
              </span>
            </p>
            <p className="mt-2 flex items-start gap-1.5 font-bold">
              {after.status === "below" ? (
                <TriangleAlert className="mt-0.5 size-[18px] shrink-0" aria-hidden />
              ) : (
                <CircleCheck className="mt-0.5 size-[18px] shrink-0" aria-hidden />
              )}
              <span>{after.statement}.</span>
            </p>
          </div>
        ) : (
          <Skeleton className="h-14 border-hero-muted/40 bg-transparent" />
        )}
      </div>
    </div>
  );
}

function SubjectCard({ subject }: { subject: SubjectAttendance }) {
  const [open, setOpen] = useState(false);
  const s = subject.standing;
  const below = s.status === "below";
  const panelId = `what-if-${subject.subject_id}`;

  return (
    <li className={cn("relative min-w-0 rounded-[18px] border-2 border-edge bg-sheet p-4", below ? "shadow-[4px_4px_0_0_var(--alert)]" : "shadow-hard")}>
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0">
          <h2 className="flex items-center gap-2 font-display text-28 leading-tight font-extrabold">
            <span className="truncate">{subject.short_name ?? subject.name}</span>
            {subject.kind === "lab" ? <FlaskConical className="size-5 shrink-0" aria-label="Lab" /> : null}
          </h2>
          <p className="truncate text-13 font-semibold text-muted">
            {subject.name} · {subject.code}
          </p>
        </div>
        <div className="shrink-0 text-right">
          <p className={cn("font-display text-40 leading-none font-extrabold tabular-nums", below && "text-alert-text")}>
            {s.percentage === null ? "—" : percent(s.percentage)}
          </p>
          {below ? (
            <p className="mt-1.5 inline-block rotate-[-5deg] rounded-[6px] border-[3px] border-alert-text px-1.5 font-display text-13 font-extrabold text-alert-text">
              Below {s.threshold}%
            </p>
          ) : null}
        </div>
      </div>
      <ProgressBar standing={s} />
      <p className="mt-2 text-13 font-semibold text-muted">
        {s.attended} of {plural(s.held, "class", "classes")} attended
      </p>
      <p className={cn("mt-2 flex items-start gap-1.5 text-17 font-extrabold", below && "text-alert-text")}>
        <StandingIcon standing={s} />
        <span>{s.statement}.</span>
      </p>

      <Button variant="secondary" className="mt-3" aria-expanded={open} aria-controls={panelId} onClick={() => setOpen((v) => !v)}>
        What if I miss classes?
        <ChevronDown aria-hidden className={cn(open && "rotate-180")} />
      </Button>
      {open ? (
        <div id={panelId}>
          <WhatIf subject={subject} />
        </div>
      ) : null}
    </li>
  );
}

export function AttendancePage() {
  const query = useQuery({ queryKey: ["attendance"], queryFn: () => api<AttendanceData>("/attendance") });
  const data = query.data;
  const belowCount = data?.subjects.filter((s) => s.standing.status === "below").length ?? 0;
  const threshold = data?.threshold ?? 75;

  return (
    <div className="mx-auto max-w-5xl">
      <header
        className={cn(
          "relative overflow-hidden rounded-[24px] border-2 border-edge px-5 py-6 shadow-hard-lg sm:px-7",
          data && belowCount ? "bg-alert text-white" : "bg-hero text-hero-text",
        )}
      >
        <h1 className="relative font-display text-40 leading-none font-extrabold sm:text-64">Attendance</h1>
        <p className="relative mt-3 flex items-center gap-2 text-17 font-bold sm:text-21">
          {!data ? (
            `Stay at ${threshold}% or above in every subject.`
          ) : belowCount ? (
            <>
              <TriangleAlert className="size-6 shrink-0" aria-hidden />
              {plural(belowCount, "subject")} below {threshold}%
            </>
          ) : (
            <>
              <CircleCheck className="size-6 shrink-0" aria-hidden />
              Every subject is at {threshold}% or above
            </>
          )}
        </p>
      </header>

      {query.isPending ? (
        <div className="mt-6 grid gap-5 md:grid-cols-2" aria-busy="true" aria-label="Loading attendance">
          {[0, 1, 2, 3].map((i) => (
            <Skeleton key={i} className="h-56" />
          ))}
        </div>
      ) : query.isError ? (
        <div className="mt-6">
          <ErrorState error={query.error} onRetry={() => query.refetch()} title="Attendance didn't load" />
        </div>
      ) : query.data.subjects.length === 0 ? (
        <div className="mt-6">
          <EmptyState icon={ChartNoAxesColumn} title="No attendance yet">
            Your subjects and attendance appear here once the college uploads them.
          </EmptyState>
        </div>
      ) : (
        <ul className="mt-6 grid grid-cols-[minmax(0,1fr)] items-start gap-5 md:grid-cols-2">
          {query.data.subjects.map((subject) => (
            <SubjectCard key={subject.subject_id} subject={subject} />
          ))}
        </ul>
      )}
    </div>
  );
}
