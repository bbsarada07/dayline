import { useState } from "react";
import { Link } from "react-router";
import { useQuery } from "@tanstack/react-query";
import { ArrowRight, CalendarClock, CalendarDays, Coffee, MapPin, Mic, Printer, TriangleAlert, UtensilsCrossed } from "lucide-react";
import { LiveBadge } from "@/components/LiveBadge";
import { EmptyState, ErrorState } from "@/components/states";
import { buttonVariants } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { api } from "@/lib/api";
import { useMe } from "@/lib/auth";
import { useClock } from "@/lib/clock";
import { dayDate, duration, greeting, minutesBetween, percent, sameDay, timeOfDay } from "@/lib/format";
import type { AttendanceData, DayItem, Nudge, Order, PrintJob, TodayData } from "@/lib/types";
import { useMediaQuery } from "@/lib/media";
import { cn } from "@/lib/utils";
import { PrintJobSheet, PrintPass, printPassId } from "@/features/print/printShared";
import { OrderPass, OrderSheet, orderPassId } from "@/features/canteen/canteenShared";
import { useAsk } from "@/features/ask/AskContext";
import { AskPanel } from "@/features/ask/AskPanel";
import { DayLine, statusAt, type DayPass } from "./DayLine";

function TodaySkeleton() {
  return (
    <div aria-busy="true" aria-label="Loading your day" className="mt-4 space-y-3">
      {[0, 1, 2, 3].map((i) => (
        <div key={i} className="grid grid-cols-[3.1rem_1.25rem_1fr] gap-x-2">
          <Skeleton className="mt-3 h-4 w-10 justify-self-end" />
          <span />
          <Skeleton className={i === 2 ? "h-11" : "h-24"} />
        </div>
      ))}
    </div>
  );
}

/** What's happening right now, in one sentence-sized card inside the hero. */
function NowCard({ items, now }: { items: DayItem[]; now: Date }) {
  const current = items.find((i) => statusAt(i, now) === "current");
  const next = items.find((i) => i.kind === "class" && statusAt(i, now) === "upcoming");

  let headline: string;
  let detail: string | null = null;
  if (items.length === 0) headline = "No classes today";
  else if (current?.kind === "class") {
    headline = `${current.label} is on now`;
    detail = `${current.room_code} · ${duration(minutesBetween(now, current.end))} left`;
  } else if (current) {
    headline = `${current.label} · until ${timeOfDay(current.end)}`;
  } else if (now < new Date(items[0].start)) headline = `Classes start at ${timeOfDay(items[0].start)}`;
  else headline = "That's all your classes for today";

  return (
    <div className="mt-5 grid gap-2 sm:grid-cols-2">
      <div className="rounded-[16px] border-2 border-hero-text bg-magenta p-3.5 text-white shadow-[4px_4px_0_0_#000]">
        <p className="text-13 font-bold text-white/90">Right now</p>
        <p className="mt-0.5 font-display text-21 leading-tight font-extrabold">{headline}</p>
        {detail ? <p className="mt-1 font-semibold">{detail}</p> : null}
      </div>
      <div className="rounded-[16px] border-2 border-hero-text bg-hero-text p-3.5 text-hero shadow-[4px_4px_0_0_var(--magenta)]">
        <p className="text-13 font-bold text-hero/70">Up next</p>
        {next ? (
          <>
            <p className="mt-0.5 font-display text-21 leading-tight font-extrabold">
              {next.label} · {timeOfDay(next.start)}
            </p>
            <p className="mt-1 flex items-center gap-1 font-semibold">
              <MapPin className="size-4 shrink-0" aria-hidden />
              <span className="truncate">
                {next.room_code} · in {duration(minutesBetween(now, next.start))}
              </span>
            </p>
          </>
        ) : (
          <p className="mt-0.5 font-display text-21 leading-tight font-extrabold">Nothing else today</p>
        )}
      </div>
    </div>
  );
}

function Hero({ name, fullName, now, items }: { name: string; fullName: string; now: Date; items: DayItem[] | null }) {
  const initials = fullName.split(" ").filter(Boolean).slice(0, 2).map((p) => p[0]?.toUpperCase()).join("");
  return (
    <section className="relative -mx-4 -mt-4 overflow-hidden rounded-b-[28px] border-b-2 border-edge bg-hero px-5 pt-5 pb-6 text-hero-text sm:mx-0 sm:mt-0 sm:rounded-[24px] sm:border-2 sm:p-7 sm:shadow-hard-lg">
      <div aria-hidden className="halftone pointer-events-none absolute -top-16 -right-16 size-64 rounded-full text-magenta" />
      <div aria-hidden className="halftone pointer-events-none absolute -bottom-20 left-1/3 size-56 rounded-full text-cyan opacity-60" />
      <div className="relative flex flex-wrap items-center justify-between gap-2">
        <span className="rounded-full border-2 border-hero-muted/50 px-2.5 py-0.5 text-13 font-bold">{dayDate(now)}</span>
        <span className="flex items-center gap-2">
          <LiveBadge onDark />
          {/* Phones reach Profile from here; the dock holds the four main screens. */}
          <Link
            to="/profile"
            aria-label="Your profile"
            className="press flex size-11 rotate-3 items-center justify-center rounded-[12px] border-2 border-hero-text bg-magenta font-display text-15 font-extrabold text-white lg:hidden"
          >
            {initials}
          </Link>
        </span>
      </div>
      <h1 className="relative mt-5">
        <span className="block text-17 font-bold text-hero-muted sm:text-21">{greeting(now)},</span>
        <span className="misprint block truncate font-display text-[52px] leading-[0.95] font-extrabold tracking-tight sm:text-64">
          {name}
        </span>
      </h1>
      <div className="relative">{items ? <NowCard items={items} now={now} /> : <Skeleton className="mt-5 h-24 border-hero-muted/40 bg-transparent" />}</div>
    </section>
  );
}

function StatTile({ value, label, to, tone, alert = false }: { value: string; label: string; to?: string; tone: string; alert?: boolean }) {
  const body = (
    <>
      <span aria-hidden className={cn("absolute top-0 left-0 h-2 w-full", tone)} />
      <span className={cn("block font-display text-40 leading-none font-extrabold tabular-nums", alert && "text-alert-text")}>{value}</span>
      <span className="mt-1 block text-13 leading-tight font-bold text-muted">{label}</span>
    </>
  );
  const cls = "relative block overflow-hidden rounded-[16px] border-2 border-edge bg-sheet px-3 pt-4 pb-3 shadow-hard";
  return to ? (
    <Link to={to} className={cn(cls, "press")}>
      {body}
    </Link>
  ) : (
    <div className={cls}>{body}</div>
  );
}

function OrderButton({ order, now, onOpen }: { order: Order; now: Date; onOpen: (id: number) => void }) {
  return (
    <button
      type="button"
      className="block w-full rounded-surface text-left"
      onClick={() => onOpen(order.id)}
      aria-label={`Canteen token ${order.token_no}. Show details`}
    >
      <OrderPass order={order} now={now} />
    </button>
  );
}

function PassButton({ job, now, onOpen }: { job: PrintJob; now: Date; onOpen: (id: number) => void }) {
  return (
    <button
      type="button"
      className="block w-full rounded-surface text-left"
      onClick={() => onOpen(job.id)}
      aria-label={`Print job ${job.code}, ${job.original_filename}. Show details`}
    >
      <PrintPass job={job} now={now} />
    </button>
  );
}

const NUDGE_TONE: Record<Nudge["agent"], { icon: typeof Printer; className: string }> = {
  timetable: { icon: CalendarClock, className: "bg-magenta text-white" },
  print: { icon: Printer, className: "bg-cyan text-on-fill" },
  canteen: { icon: UtensilsCrossed, className: "bg-yellow text-on-fill" },
  omi: { icon: Mic, className: "bg-hero text-hero-text" }, // kept for backend nudge compatibility
};

/** At most two nudges from simple rules (lunch soon and nothing ordered...), each with one action. */
function Nudges({ nudges }: { nudges: Nudge[] }) {
  const ask = useAsk();
  const desktop = useMediaQuery("(min-width: 1024px)");
  if (!nudges.length) return null;
  const run = (nudge: Nudge) => {
    if (!nudge.ask) return;
    // "... of this ..." needs a file first: put the words in the ask box and let the student attach.
    const needsFile = /\bthis\b/i.test(nudge.ask);
    if (needsFile) ask.setDraft(nudge.ask);
    else ask.send(nudge.ask);
    if (!desktop) ask.openSheet(); // laptops show the panel beside the day line
  };
  return (
    <ul className="mt-5 grid gap-2.5 sm:grid-cols-2 lg:grid-cols-1 2xl:grid-cols-2" aria-label="Suggestions">
      {nudges.map((nudge) => {
        const tone = NUDGE_TONE[nudge.agent];
        return (
          <li key={nudge.id} className="flex items-center gap-3 rounded-[16px] border-2 border-edge bg-sheet p-3 shadow-hard">
            <span className={cn("inline-flex size-10 shrink-0 -rotate-3 items-center justify-center rounded-[10px] border-2 border-edge", tone.className)}>
              <tone.icon className="size-5" aria-hidden />
            </span>
            <p className="min-w-0 flex-1 font-bold">{nudge.text}</p>
            {nudge.to ? (
              <Link to={nudge.to} className={buttonVariants({ variant: "secondary", className: "shrink-0" })}>
                {nudge.action}
              </Link>
            ) : (
              <button type="button" onClick={() => run(nudge)} disabled={ask.busy} className={buttonVariants({ className: "shrink-0" })}>
                {nudge.action}
              </button>
            )}
          </li>
        );
      })}
    </ul>
  );
}

function PanelCard({ title, children, className }: { title: string; children: React.ReactNode; className?: string }) {
  return (
    <section className={cn("rounded-[18px] border-2 border-edge bg-sheet p-4 shadow-hard", className)}>
      <h2 className="font-display text-21 font-extrabold">{title}</h2>
      <div className="mt-2">{children}</div>
    </section>
  );
}

/** Laptop-only side column. */
function SidePanel({ items, now, attendance }: { items: DayItem[]; now: Date; attendance: AttendanceData | undefined }) {
  const gaps = items.filter((i) => i.kind !== "class" && statusAt(i, now) !== "past");
  const below = attendance?.subjects.filter((s) => s.standing.status === "below") ?? [];
  return (
    <div className="space-y-5">
      <section className="relative overflow-hidden rounded-[18px] border-2 border-edge bg-yellow p-4 text-on-fill shadow-hard">
        <div aria-hidden className="halftone pointer-events-none absolute -right-6 -bottom-6 size-28 rounded-full text-on-fill" />
        <UtensilsCrossed className="relative size-7 rotate-6" aria-hidden />
        <p className="relative mt-2 font-display text-21 font-extrabold">Hungry later?</p>
        <p className="relative font-semibold">Order now, pick it up in your break.</p>
        <Link to="/canteen" className={buttonVariants({ className: "relative mt-3" })}>
          Order food <ArrowRight aria-hidden />
        </Link>
      </section>

      <section className="relative overflow-hidden rounded-[18px] border-2 border-edge bg-cyan p-4 text-on-fill shadow-hard">
        <div aria-hidden className="halftone pointer-events-none absolute -right-6 -bottom-6 size-28 rounded-full text-on-fill" />
        <Printer className="relative size-7 -rotate-6" aria-hidden />
        <p className="relative mt-2 font-display text-21 font-extrabold">Need a printout?</p>
        <p className="relative font-semibold">Skip the queue: it's ready before your class.</p>
        <Link to="/print" className={buttonVariants({ className: "relative mt-3" })}>
          Print a file <ArrowRight aria-hidden />
        </Link>
      </section>

      <PanelCard title="Breaks left today">
        {gaps.length ? (
          <ul className="space-y-1.5">
            {gaps.map((gap) => (
              <li key={gap.id} className="flex items-center justify-between gap-3">
                <span className="inline-flex min-w-0 items-center gap-2 font-semibold">
                  {gap.kind === "break" ? <Coffee className="size-4 shrink-0 text-muted" aria-hidden /> : null}
                  <span className="truncate">{gap.label}</span>
                </span>
                <span className="shrink-0 text-13 font-semibold text-muted tabular-nums">
                  {timeOfDay(gap.start)} – {timeOfDay(gap.end)}
                </span>
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-muted">No breaks or free time left today.</p>
        )}
      </PanelCard>

      <PanelCard title="Attendance to watch">
        {!attendance ? (
          <Skeleton className="h-12" />
        ) : below.length ? (
          <ul className="space-y-2">
            {below.map((s) => (
              <li key={s.subject_id} className="flex items-start gap-2">
                <TriangleAlert className="mt-0.5 size-4 shrink-0 text-alert-text" aria-hidden />
                <span className="min-w-0">
                  <span className="font-bold">
                    {s.short_name ?? s.name} is at {percent(s.standing.percentage ?? 0)}.
                  </span>{" "}
                  <span className="text-muted">{s.standing.statement}.</span>
                </span>
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-muted">Every subject is at {attendance.threshold}% or above.</p>
        )}
        <Link to="/attendance" className={buttonVariants({ variant: "secondary", className: "mt-3" })}>
          See all attendance <ArrowRight aria-hidden />
        </Link>
      </PanelCard>
    </div>
  );
}

export function TodayPage() {
  const me = useMe().data;
  const { now } = useClock();
  const [openJob, setOpenJob] = useState<number | null>(null);
  const [openOrder, setOpenOrder] = useState<number | null>(null);
  const today = useQuery({
    queryKey: ["today"],
    queryFn: () => api<TodayData>("/today"),
    refetchInterval: 5 * 60_000,
  });
  const attendance = useQuery({ queryKey: ["attendance"], queryFn: () => api<AttendanceData>("/attendance") });

  const firstName = me?.name.split(" ")[0] ?? "";
  const shownNow = now ?? (today.data ? new Date(today.data.now) : null);
  const items = today.data?.items ?? null;
  const jobs = today.data?.print_jobs ?? [];
  // Pinned at the deadline, the moment the printout matters. Jobs due another day are listed above the line.
  const pinned = shownNow ? jobs.filter((j) => sameDay(j.deadline, shownNow)) : [];
  const otherDays = shownNow ? jobs.filter((j) => !sameDay(j.deadline, shownNow)) : [];
  const orders = today.data?.orders ?? [];
  // Canteen tokens are pinned at their pickup time.
  const pinnedOrders = shownNow ? orders.filter((o) => sameDay(o.pickup_time, shownNow)) : [];
  const passes: DayPass[] = shownNow
    ? [
        ...pinned.map((job): DayPass => ({
          id: printPassId(job),
          at: job.deadline,
          tone: "cyan",
          content: <PassButton job={job} now={shownNow} onOpen={setOpenJob} />,
        })),
        ...pinnedOrders.map((order): DayPass => ({
          id: orderPassId(order),
          at: order.pickup_time,
          tone: "yellow",
          content: <OrderButton order={order} now={shownNow} onOpen={setOpenOrder} />,
        })),
      ]
    : [];

  const classesLeft = items && shownNow ? items.filter((i) => i.kind === "class" && statusAt(i, shownNow) !== "past").length : null;
  const activePrints = jobs.filter((j) => j.status === "queued" || j.status === "printing" || j.status === "ready").length;
  const activeOrders = orders.filter((o) => o.status === "placed" || o.status === "preparing" || o.status === "ready").length;
  const belowCount = attendance.data?.subjects.filter((s) => s.standing.status === "below").length;

  return (
    <div className="lg:grid lg:grid-cols-[minmax(0,1fr)_380px] lg:gap-8 xl:gap-10">
      <div className="min-w-0">
        {shownNow ? <Hero name={firstName} fullName={me?.name ?? ""} now={shownNow} items={items} /> : <Skeleton className="h-64" />}

        <div className="mt-5 grid grid-cols-2 gap-2.5 sm:grid-cols-4 sm:gap-4">
          <StatTile value={classesLeft === null ? "–" : String(classesLeft)} label={classesLeft === 1 ? "class left today" : "classes left today"} tone="bg-magenta" />
          <StatTile value={String(activeOrders)} label={activeOrders === 1 ? "food order on the way" : "food orders on the way"} to="/canteen" tone="bg-yellow" />
          <StatTile value={String(activePrints)} label={activePrints === 1 ? "printout on the way" : "printouts on the way"} to="/print" tone="bg-cyan" />
          <StatTile
            value={belowCount === undefined ? "–" : String(belowCount)}
            label={`below ${attendance.data?.threshold ?? 75}%`}
            to="/attendance"
            tone="bg-alert"
            alert={!!belowCount}
          />
        </div>

        <Nudges nudges={today.data?.nudges ?? []} />

        <h2 className="mt-8 font-display text-28 font-extrabold">Your day</h2>
        {today.isPending || !shownNow ? (
          <TodaySkeleton />
        ) : today.isError ? (
          <div className="mt-4">
            <ErrorState error={today.error} onRetry={() => today.refetch()} title="Your day didn't load" />
          </div>
        ) : today.data.items.length === 0 && passes.length === 0 && otherDays.length === 0 ? (
          <div className="mt-4">
            <EmptyState
              icon={CalendarDays}
              title="No classes today"
              action={
                <Link to="/attendance" className={buttonVariants({ variant: "secondary" })}>
                  Check attendance
                </Link>
              }
            >
              Your classes, breaks and free time show up here on college days.
            </EmptyState>
          </div>
        ) : (
          <>
            {otherDays.length ? (
              <section aria-labelledby="other-days" className="mt-4">
                <h3 id="other-days" className="text-17 font-extrabold">Also waiting for you</h3>
                <ul className="mt-2 space-y-3">
                  {otherDays.map((job) => (
                    <li key={job.id}>
                      <PassButton job={job} now={shownNow} onOpen={setOpenJob} />
                    </li>
                  ))}
                </ul>
              </section>
            ) : null}
            {today.data.items.length === 0 ? <p className="mt-4 font-semibold text-muted">No classes today.</p> : null}
            <DayLine items={today.data.items} now={shownNow} passes={passes} />
          </>
        )}
        {shownNow ? (
          <>
            <PrintJobSheet job={jobs.find((j) => j.id === openJob) ?? null} now={shownNow} onClose={() => setOpenJob(null)} />
            <OrderSheet order={orders.find((o) => o.id === openOrder) ?? null} now={shownNow} onClose={() => setOpenOrder(null)} />
          </>
        ) : null}
      </div>

      {items && shownNow ? (
        <aside className="hidden space-y-5 lg:block" aria-label="At a glance">
          <section className="h-[min(680px,calc(100dvh-4rem))] rounded-[20px] border-2 border-edge bg-sheet p-4 shadow-hard-magenta">
            <AskPanel className="h-full" />
          </section>
          <SidePanel items={items} now={shownNow} attendance={attendance.data} />
        </aside>
      ) : null}
    </div>
  );
}
