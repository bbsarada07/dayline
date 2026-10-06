import { useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CircleAlert, TriangleAlert } from "lucide-react";
import { ErrorState } from "@/components/states";
import { Button } from "@/components/ui/button";
import { Input, Label } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { api, errorMessage } from "@/lib/api";
import { useClock } from "@/lib/clock";
import { dayDate, localInputs, timeOfDay } from "@/lib/format";
import type { AdminSettings, ClockInfo } from "@/lib/types";

function DemoTimeCard() {
  const client = useQueryClient();
  const { now, demo, query } = useClock();
  const [date, setDate] = useState("");
  const [time, setTime] = useState("");
  const [saved, setSaved] = useState<string | null>(null);

  // Prefill the form once with the current app time.
  if (now && !date && !time) {
    const inputs = localInputs(now);
    setDate(inputs.date);
    setTime(inputs.time);
  }

  const onDone = (data: ClockInfo, message: string) => {
    client.setQueryData(["clock"], data);
    client.invalidateQueries();
    setSaved(message);
  };

  const setDemo = useMutation({
    mutationFn: () => api<ClockInfo>("/admin/demo-time", { method: "PUT", body: { local: `${date}T${time}` } }),
    onSuccess: (data) => onDone(data, `Demo time set to ${dayDate(data.now)}, ${timeOfDay(data.now)}.`),
  });
  const clearDemo = useMutation({
    mutationFn: () => api<ClockInfo>("/admin/demo-time", { method: "DELETE" }),
    onSuccess: (data) => onDone(data, "Back to real time."),
  });

  const onSubmit = (event: FormEvent) => {
    event.preventDefault();
    setSaved(null);
    setDemo.mutate();
  };

  const error = setDemo.error ?? clearDemo.error;
  const busy = setDemo.isPending || clearDemo.isPending;

  return (
    <section className="rounded-[20px] border-2 border-edge bg-sheet p-5 shadow-hard">
      <h2 className="font-display text-28 font-extrabold">Demo time</h2>
      <p className="mt-1 text-muted">
        Moves the app's clock for everyone: next class, deadlines and pickup times. It keeps ticking from the time
        you set.
      </p>

      {query.isError ? (
        <div className="mt-4">
          <ErrorState error={query.error} onRetry={() => query.refetch()} title="The clock didn't load" />
        </div>
      ) : !now ? (
        <Skeleton className="mt-4 h-12" />
      ) : (
        <p className="mt-4">
          <span className="text-muted">App time now: </span>
          <span className="font-semibold">
            {dayDate(now)}, {timeOfDay(now)}
          </span>{" "}
          <span className="text-muted">({demo ? "demo time" : "real time"})</span>
        </p>
      )}

      <form onSubmit={onSubmit} className="mt-4 flex flex-wrap items-end gap-3">
        <div className="space-y-2">
          <Label htmlFor="demo-date">Date</Label>
          <Input id="demo-date" type="date" value={date} onChange={(e) => setDate(e.target.value)} required className="w-44" />
        </div>
        <div className="space-y-2">
          <Label htmlFor="demo-time">Time</Label>
          <Input id="demo-time" type="time" value={time} onChange={(e) => setTime(e.target.value)} required className="w-36" />
        </div>
        <Button type="submit" disabled={busy || !date || !time}>
          Set demo time
        </Button>
        {demo ? (
          <Button
            variant="secondary"
            disabled={busy}
            onClick={() => {
              setSaved(null);
              clearDemo.mutate();
            }}
          >
            Back to real time
          </Button>
        ) : null}
      </form>

      <div aria-live="polite" className="mt-3 min-h-6">
        {error ? (
          <p className="flex items-start gap-2 text-alert-text">
            <CircleAlert className="mt-0.5 size-5 shrink-0" aria-hidden />
            {errorMessage(error)}
          </p>
        ) : saved ? (
          <p className="text-stamp-text font-semibold">{saved}</p>
        ) : null}
      </div>
    </section>
  );
}

type RateKey = keyof AdminSettings["print_rates"];

const RATE_FIELDS: { key: RateKey; label: string }[] = [
  { key: "bw_single", label: "Black and white, single sided" },
  { key: "bw_double", label: "Black and white, double sided" },
  { key: "colour_single", label: "Colour, single sided" },
  { key: "colour_double", label: "Colour, double sided" },
];

const toRupees = (paise: number) => (paise / 100).toFixed(2);
const toPaise = (rupees: string) => Math.round(Number.parseFloat(rupees) * 100);

function PrintSettingsForm({ settings }: { settings: AdminSettings }) {
  const client = useQueryClient();
  const [rates, setRates] = useState<Record<RateKey, string>>(() => ({
    bw_single: toRupees(settings.print_rates.bw_single),
    bw_double: toRupees(settings.print_rates.bw_double),
    colour_single: toRupees(settings.print_rates.colour_single),
    colour_double: toRupees(settings.print_rates.colour_double),
  }));
  const [speed, setSpeed] = useState(String(settings.print_seconds_per_page));
  const [saved, setSaved] = useState(false);

  const valid =
    RATE_FIELDS.every(({ key }) => /^\d+(\.\d{1,2})?$/.test(rates[key].trim())) && /^\d+$/.test(speed) && Number(speed) >= 1;

  const save = useMutation({
    mutationFn: () =>
      api<AdminSettings>("/admin/settings", {
        method: "PUT",
        body: {
          print_rates: Object.fromEntries(RATE_FIELDS.map(({ key }) => [key, toPaise(rates[key])])),
          print_seconds_per_page: Number(speed),
        },
      }),
    onSuccess: (data) => {
      client.setQueryData(["admin", "settings"], data);
      setSaved(true);
    },
  });

  const onSubmit = (event: FormEvent) => {
    event.preventDefault();
    setSaved(false);
    save.mutate();
  };

  return (
    <form onSubmit={onSubmit} className="mt-4 space-y-4">
      {!settings.print_rates_confirmed ? (
        <p className="flex items-start gap-2 rounded-[12px] border-2 border-alert-text p-3 font-bold">
          <TriangleAlert className="mt-0.5 size-5 shrink-0 text-alert-text" aria-hidden />
          These are placeholder rates. Replace them with the real shop rates, then save.
        </p>
      ) : null}
      <div className="grid gap-4 sm:grid-cols-2">
        {RATE_FIELDS.map(({ key, label }) => (
          <div key={key} className="space-y-2">
            <Label htmlFor={`rate-${key}`}>{label} (₹ per page)</Label>
            <Input
              id={`rate-${key}`}
              inputMode="decimal"
              value={rates[key]}
              onChange={(e) => setRates((r) => ({ ...r, [key]: e.target.value }))}
              required
            />
          </div>
        ))}
        <div className="space-y-2">
          <Label htmlFor="print-speed">Seconds per page (for ready-time estimates)</Label>
          <Input id="print-speed" inputMode="numeric" value={speed} onChange={(e) => setSpeed(e.target.value)} required />
        </div>
      </div>
      <Button type="submit" disabled={!valid || save.isPending}>
        {save.isPending ? "Saving…" : "Save print settings"}
      </Button>
      <div aria-live="polite" className="min-h-6">
        {!valid ? (
          <p className="text-alert-text">Rates must be amounts like 2 or 1.50, and seconds per page a whole number.</p>
        ) : save.isError ? (
          <p className="flex items-start gap-2 text-alert-text">
            <CircleAlert className="mt-0.5 size-5 shrink-0" aria-hidden />
            {errorMessage(save.error)}
          </p>
        ) : saved ? (
          <p className="font-semibold text-stamp-text">Print settings saved. New quotes use them straight away.</p>
        ) : null}
      </div>
    </form>
  );
}

function PrintSettingsCard() {
  const settings = useQuery({ queryKey: ["admin", "settings"], queryFn: () => api<AdminSettings>("/admin/settings") });
  return (
    <section className="rounded-[20px] border-2 border-edge bg-sheet p-5 shadow-hard">
      <h2 className="font-display text-28 font-extrabold">Print rates</h2>
      <p className="mt-1 text-muted">Cost = pages × copies × rate. Students see the cost before they pay.</p>
      {settings.isPending ? (
        <Skeleton className="mt-4 h-40" />
      ) : settings.isError ? (
        <div className="mt-4">
          <ErrorState error={settings.error} onRetry={() => settings.refetch()} title="Print settings didn't load" />
        </div>
      ) : (
        <PrintSettingsForm settings={settings.data} />
      )}
    </section>
  );
}

/** Admin home. Demo time and print rates so far; the full settings editor, imports and impact come in Phase 6. */
export function AdminPage() {
  return (
    <div className="mx-auto max-w-3xl space-y-6">
      <h1 className="misprint font-display text-40 leading-none font-extrabold sm:text-64">Admin</h1>
      <DemoTimeCard />
      <PrintSettingsCard />
    </div>
  );
}
