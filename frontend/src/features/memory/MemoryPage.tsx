import { useEffect, useState, type FormEvent } from "react";
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Brain, CalendarClock, CircleAlert, Mic, Printer, Search, Sparkles, Trash, TriangleAlert, User, UtensilsCrossed,
  type LucideIcon,
} from "lucide-react";
import { EmptyState, ErrorState } from "@/components/states";
import { Button } from "@/components/ui/button";
import { Input, Label } from "@/components/ui/input";
import { Sheet } from "@/components/ui/sheet";
import { Skeleton } from "@/components/ui/skeleton";
import { api, errorMessage } from "@/lib/api";
import { useClock } from "@/lib/clock";
import { dayDate, duration, minutesBetween, plural, sameDay, timeOfDay } from "@/lib/format";
import type { MemoryItem, MemoryKind, MemoryList, MemoryWriter } from "@/lib/types";
import { cn } from "@/lib/utils";

/** Who wrote a memory, in that agent's colour (spec 9.1). Words, not just colour. */
const WRITER: Record<MemoryWriter, { label: string; icon: LucideIcon; className: string }> = {
  timetable: { label: "Timetable", icon: CalendarClock, className: "bg-magenta text-white" },
  print: { label: "Print", icon: Printer, className: "bg-cyan text-on-fill" },
  canteen: { label: "Canteen", icon: UtensilsCrossed, className: "bg-yellow text-on-fill" },
  orchestrator: { label: "Dayline", icon: Sparkles, className: "bg-ink text-paper" },
  omi: { label: "Omi", icon: Mic, className: "bg-hero text-hero-text" },
  student: { label: "You", icon: User, className: "bg-paper text-ink" },
};

const KIND: Record<MemoryKind, string> = {
  preference: "Preference",
  action: "Something you did",
  fact: "Fact",
  conversation: "Conversation",
  instruction: "Standing instruction",
};

function when(value: string, now: Date): string {
  return sameDay(value, now) ? `Today, ${timeOfDay(value)}` : `${dayDate(value)}, ${timeOfDay(value)}`;
}

function lastUsed(value: string | null, now: Date): string {
  if (!value) return "Not used yet";
  const minutes = Math.max(0, Math.round(minutesBetween(value, now)));
  return minutes < 1 ? "Used just now" : `Used ${duration(minutes)} ago`;
}

function MemoryCard({ memory, now, onForget, forgetting }: {
  memory: MemoryItem;
  now: Date;
  onForget: (memory: MemoryItem) => void;
  forgetting: boolean;
}) {
  const writer = WRITER[memory.written_by] ?? WRITER.student;
  return (
    <li className="min-w-0 rounded-[16px] border-2 border-edge bg-sheet p-4 shadow-hard">
      <div className="flex items-start justify-between gap-3">
        <p className="min-w-0 text-17 font-extrabold break-words">{memory.text}</p>
        <button
          type="button"
          onClick={() => onForget(memory)}
          disabled={forgetting}
          className="press inline-flex size-11 shrink-0 items-center justify-center rounded-button border-2 border-edge bg-sheet shadow-hard-sm disabled:opacity-50"
        >
          <Trash className="size-5" aria-hidden />
          <span className="sr-only">Forget: {memory.text}</span>
        </button>
      </div>
      <div className="mt-2.5 flex flex-wrap items-center gap-x-3 gap-y-1.5 text-13 font-semibold text-muted">
        <span className={cn("inline-flex items-center gap-1.5 rounded-[8px] border-2 border-edge px-2 py-0.5 font-extrabold", writer.className)}>
          <writer.icon className="size-3.5" aria-hidden />
          <span className="sr-only">Written by </span>
          {writer.label}
        </span>
        <span>{KIND[memory.kind] ?? memory.kind}</span>
        <span>{when(memory.created_at, now)}</span>
        <span>{lastUsed(memory.last_used_at, now)}</span>
      </div>
    </li>
  );
}

/** What Dayline remembers about the student. Every agent reads and writes here. */
export function MemoryPage() {
  const client = useQueryClient();
  const { now } = useClock();
  const [note, setNote] = useState("");
  const [search, setSearch] = useState("");
  const [query, setQuery] = useState("");
  const [confirmAll, setConfirmAll] = useState(false);

  // Search as you type, a moment after typing stops.
  useEffect(() => {
    const id = setTimeout(() => setQuery(search.trim()), 350);
    return () => clearTimeout(id);
  }, [search]);

  const list = useQuery({ queryKey: ["memory", "list"], queryFn: () => api<MemoryList>("/memory") });
  const found = useQuery({
    queryKey: ["memory", "search", query],
    queryFn: () => api<MemoryList>(`/memory?q=${encodeURIComponent(query)}`),
    enabled: query.length > 0,
    placeholderData: keepPreviousData,
    staleTime: 60_000,
  });

  const refresh = () => client.invalidateQueries({ queryKey: ["memory"] });
  const add = useMutation({
    mutationFn: (text: string) => api<MemoryItem>("/memory/notes", { method: "POST", body: { text } }),
    onSuccess: () => {
      setNote("");
      refresh();
    },
  });
  const forget = useMutation({
    mutationFn: (memory: MemoryItem) => api(`/memory/${memory.id}`, { method: "DELETE" }),
    onSuccess: refresh,
  });
  const forgetAll = useMutation({
    mutationFn: () => api<{ deleted: number }>("/memory", { method: "DELETE" }),
    onSuccess: () => {
      setConfirmAll(false);
      refresh();
    },
  });

  const onAdd = (event: FormEvent) => {
    event.preventDefault();
    if (note.trim()) add.mutate(note.trim());
  };

  const searching = query.length > 0;
  const active = searching ? found : list;
  const memories = active.data?.memories ?? [];
  const status = list.data?.status ?? found.data?.status;
  const total = list.data?.memories.length ?? 0;

  return (
    <div className="mx-auto max-w-4xl">
      <header className="relative overflow-hidden rounded-[24px] border-2 border-edge bg-hero px-5 py-6 text-hero-text shadow-hard-lg sm:px-7">
        <div aria-hidden className="halftone pointer-events-none absolute -top-12 -right-12 size-56 rounded-full text-cyan" />
        <Brain aria-hidden className="absolute right-5 bottom-4 size-20 rotate-6 opacity-20 sm:size-28" />
        <h1 className="relative font-display text-40 leading-none font-extrabold sm:text-64">Memory</h1>
        <p className="relative mt-2 max-w-lg text-17 font-semibold text-hero-muted">
          What Dayline remembers about you. The canteen, print and timetable agents all read and write here, so what one
          learns helps the others.
        </p>
      </header>

      {status?.notice ? (
        <p role="status" className="mt-5 flex items-start gap-2 rounded-[14px] border-2 border-alert-text bg-sheet p-3 font-bold text-alert-text">
          <TriangleAlert className="mt-0.5 size-5 shrink-0" aria-hidden />
          {status.notice}
        </p>
      ) : null}

      <div className="mt-6 grid gap-5 md:grid-cols-2">
        <form onSubmit={onAdd} className="rounded-[18px] border-2 border-edge bg-sheet p-4 shadow-hard">
          <Label htmlFor="memory-note">Tell Dayline to remember</Label>
          <div className="mt-2 flex gap-2">
            <Input
              id="memory-note"
              value={note}
              onChange={(e) => {
                setNote(e.target.value);
                if (add.isError) add.reset();
              }}
              placeholder="Remember that my lab record is due Thursday"
              maxLength={600}
            />
            <Button type="submit" className="min-h-12" disabled={!note.trim() || add.isPending}>
              {add.isPending ? "Saving…" : "Remember"}
            </Button>
          </div>
          {add.isError ? (
            <p role="alert" className="mt-2 flex items-start gap-2 text-13 font-semibold text-alert-text">
              <CircleAlert className="mt-0.5 size-4 shrink-0" aria-hidden />
              {errorMessage(add.error)}
            </p>
          ) : (
            <p className="mt-2 text-13 font-semibold text-muted">Start with "Remember that…".</p>
          )}
        </form>

        <div className="rounded-[18px] border-2 border-edge bg-sheet p-4 shadow-hard">
          <Label htmlFor="memory-search">Search your memories</Label>
          <div className="relative mt-2">
            <Search className="pointer-events-none absolute top-1/2 left-3 size-5 -translate-y-1/2 text-muted" aria-hidden />
            <Input
              id="memory-search"
              type="search"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="When is my lab work due?"
              className="pl-10"
            />
          </div>
          <p className="mt-2 text-13 font-semibold text-muted">Finds memories by meaning, not just exact words.</p>
        </div>
      </div>

      <section aria-labelledby="memory-list" className="mt-8">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h2 id="memory-list" className="font-display text-28 font-extrabold">
            {searching ? "Best matches" : "Newest first"}{" "}
            {!searching && list.data ? <span className="text-muted">({total})</span> : null}
          </h2>
          {!searching && total > 0 ? (
            <Button variant="secondary" onClick={() => setConfirmAll(true)}>
              <Trash aria-hidden /> Forget everything
            </Button>
          ) : null}
        </div>

        {forget.isError ? (
          <p role="alert" className="mt-3 font-semibold text-alert-text">{errorMessage(forget.error)}</p>
        ) : null}

        <div className="mt-4" aria-live="polite">
          {active.isPending || !now ? (
            <div className="space-y-3" aria-busy="true" aria-label="Loading memories">
              <Skeleton className="h-24" />
              <Skeleton className="h-24" />
            </div>
          ) : active.isError ? (
            <ErrorState error={active.error} onRetry={() => active.refetch()} title="Memories didn't load" />
          ) : memories.length === 0 ? (
            searching ? (
              <p className="rounded-[14px] border-2 border-dashed border-edge bg-sheet p-4 font-semibold text-muted">
                Nothing matches "{query}".
              </p>
            ) : (
              <EmptyState icon={Brain} title="Nothing remembered yet">
                Order food, print something, or tell Dayline to remember a fact. It shows up here, with who wrote it.
              </EmptyState>
            )
          ) : (
            <ul className={cn("space-y-3", active.isFetching && "opacity-70")}>
              {memories.map((memory) => (
                <MemoryCard
                  key={memory.id}
                  memory={memory}
                  now={now}
                  onForget={(m) => forget.mutate(m)}
                  forgetting={forget.isPending && forget.variables?.id === memory.id}
                />
              ))}
            </ul>
          )}
        </div>
      </section>

      <Sheet
        open={confirmAll}
        onOpenChange={setConfirmAll}
        title="Forget everything?"
        description={`Deletes all ${plural(total, "memory", "memories")} Dayline has about you. The agents start from scratch. This can't be undone.`}
      >
        {forgetAll.isError ? (
          <p role="alert" className="mb-3 font-semibold text-alert-text">{errorMessage(forgetAll.error)}</p>
        ) : null}
        <div className="flex flex-wrap gap-2">
          <Button onClick={() => forgetAll.mutate()} disabled={forgetAll.isPending}>
            <Trash aria-hidden /> {forgetAll.isPending ? "Forgetting…" : "Forget everything"}
          </Button>
          <Button variant="secondary" onClick={() => setConfirmAll(false)} disabled={forgetAll.isPending}>
            Keep my memories
          </Button>
        </div>
      </Sheet>
    </div>
  );
}
