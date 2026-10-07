import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ChefHat, CircleAlert, Soup, UtensilsCrossed } from "lucide-react";
import { EmptyState, ErrorState } from "@/components/states";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { api, errorMessage } from "@/lib/api";
import { useClock } from "@/lib/clock";
import { timeLeft, timeOfDay } from "@/lib/format";
import { useBoardTheme } from "@/lib/theme";
import type { KitchenBoard, MenuItem, Order, OrderStatus, PrepList, SuggestedPrep } from "@/lib/types";
import { cn } from "@/lib/utils";
import { VegMark } from "@/features/canteen/canteenShared";
import { CollectDesk } from "./CollectDesk";

type NextStep = { status: "preparing" | "ready" | "collected"; label: string };

const NEXT: Partial<Record<OrderStatus, NextStep>> = {
  placed: { status: "preparing", label: "Start preparing" },
  preparing: { status: "ready", label: "Mark ready" },
  ready: { status: "collected", label: "Mark collected" },
};

const COLUMNS: { key: keyof KitchenBoard; title: string; tone: string }[] = [
  { key: "placed", title: "Placed", tone: "bg-yellow" },
  { key: "preparing", title: "Preparing", tone: "bg-ink" },
  { key: "ready", title: "Ready", tone: "bg-stamp" },
];

function Ticket({ order, now, busy, onStep }: { order: Order; now: Date; busy: boolean; onStep: (order: Order, step: NextStep) => void }) {
  const step = NEXT[order.status];
  return (
    <li className="min-w-0 rounded-[16px] border-2 border-edge bg-sheet p-3 shadow-hard">
      <div className="flex items-start justify-between gap-2">
        <span className="rounded-[10px] border-2 border-edge bg-yellow px-2.5 font-display text-40 leading-tight font-extrabold text-on-fill tabular-nums">
          {order.token_no}
          <span className="sr-only"> token</span>
        </span>
        <div className="min-w-0 text-right">
          <p className="font-display text-17 font-extrabold tabular-nums">{timeOfDay(order.pickup_time)}</p>
          <p className="text-13 font-bold text-muted">{timeLeft(now, order.pickup_time)}</p>
        </div>
      </div>
      <ul className="mt-2 space-y-0.5">
        {order.items.map((line) => (
          <li key={line.menu_item_id} className="flex items-center gap-2 text-17 font-extrabold">
            <VegMark veg={line.is_veg} />
            <span className="min-w-0 break-words">
              {line.name} <span className="text-muted">× {line.qty}</span>
            </span>
          </li>
        ))}
      </ul>
      <p className="mt-1 truncate text-13 font-semibold text-muted">{order.student_name}</p>
      {step ? (
        <Button
          variant={step.status === "collected" ? "secondary" : "primary"}
          className="mt-3 min-h-14 w-full text-17"
          disabled={busy}
          onClick={() => onStep(order, step)}
        >
          {busy ? "Saving…" : step.label}
          <span className="sr-only"> token {order.token_no}</span>
        </Button>
      ) : null}
    </li>
  );
}

/** Last 5-minute pickup slot inside a window (a 12:30 window holds 12:30, 12:35, 12:40). */
function lastPickup(window: PrepList["windows"][number]): Date {
  return new Date(new Date(window.end).getTime() - 5 * 60_000);
}

function PrepPanel({ prep, error, onRetry }: { prep: PrepList | undefined; error: unknown; onRetry: () => void }) {
  return (
    <section aria-labelledby="prep-heading" className="rounded-[20px] border-2 border-edge bg-sheet p-4 shadow-hard">
      <h2 id="prep-heading" className="flex items-center gap-2 font-display text-28 font-extrabold">
        <Soup className="size-7" aria-hidden /> Prep list
      </h2>
      <p className="text-13 font-semibold text-muted">What to cook for each 15-minute pickup window. Orders not ready yet.</p>
      {error && !prep ? (
        <div className="mt-4">
          <ErrorState error={error} onRetry={onRetry} title="The prep list didn't load" />
        </div>
      ) : !prep ? (
        <Skeleton className="mt-4 h-40" />
      ) : prep.windows.length === 0 ? (
        <p className="mt-4 rounded-[12px] border-2 border-dashed border-line p-4 font-semibold text-muted">Nothing to cook right now.</p>
      ) : (
        <ol className="mt-4 space-y-4">
          {prep.windows.map((window) => (
            <li key={window.start}>
              <p className="inline-block rounded-[8px] bg-ink px-2 py-0.5 font-display text-15 font-extrabold text-paper tabular-nums">
                Ready by {timeOfDay(window.start)}{" "}
                <span className="font-semibold opacity-80">
                  · pickups {timeOfDay(window.start)} – {timeOfDay(lastPickup(window))}
                </span>
              </p>
              <ul className="mt-2 divide-y-2 divide-dashed divide-line">
                {window.items.map((item) => (
                  <li key={item.name} className="flex items-baseline justify-between gap-3 py-1.5">
                    <span className="min-w-0 font-display text-21 font-extrabold break-words">{item.name}</span>
                    <span className="shrink-0 font-display text-28 font-extrabold tabular-nums">× {item.qty}</span>
                  </li>
                ))}
              </ul>
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}

function OrdersTab({ now }: { now: Date }) {
  const client = useQueryClient();
  const board = useQuery({ queryKey: ["canteen", "board"], queryFn: () => api<KitchenBoard>("/canteen/board"), refetchInterval: 60_000 });
  const prep = useQuery({ queryKey: ["canteen", "prep"], queryFn: () => api<PrepList>("/canteen/prep-list"), refetchInterval: 60_000 });
  const step = useMutation({
    mutationFn: ({ order, next }: { order: Order; next: NextStep }) =>
      api<Order>(`/canteen/orders/${order.id}/status`, { method: "POST", body: { status: next.status } }),
    onSettled: () => client.invalidateQueries({ queryKey: ["canteen"], predicate: (q) => q.queryKey[1] !== "quote" }),
  });
  const busyId = step.isPending ? (step.variables?.order.id ?? null) : null;

  if (board.isError) return <ErrorState error={board.error} onRetry={() => board.refetch()} title="The kitchen board didn't load" />;

  return (
    <div className="grid items-start gap-6 lg:grid-cols-[320px_minmax(0,1fr)] xl:grid-cols-[360px_minmax(0,1fr)]">
      <PrepPanel prep={prep.data} error={prep.isError ? prep.error : null} onRetry={() => prep.refetch()} />
      <div className="min-w-0">
        {step.isError ? (
          <p role="alert" className="mb-4 flex items-start gap-2 rounded-[14px] border-2 border-edge bg-sheet p-3 font-semibold text-alert-text">
            <CircleAlert className="mt-0.5 size-5 shrink-0" aria-hidden />
            {errorMessage(step.error)}
          </p>
        ) : null}
        <div className="grid items-start gap-4 md:grid-cols-3">
          {COLUMNS.map(({ key, title, tone }) => {
            const tickets = board.data?.[key] ?? [];
            return (
              <section key={key} aria-label={`${title} orders`} className="min-w-0">
                <h2 className="flex items-center gap-2 font-display text-21 font-extrabold">
                  <span aria-hidden className={cn("size-3.5 rotate-45 rounded-[3px] border-2 border-edge", tone)} />
                  {title} <span className="text-muted">({board.data ? tickets.length : "…"})</span>
                </h2>
                {!board.data ? (
                  <Skeleton className="mt-3 h-40" />
                ) : tickets.length === 0 ? (
                  <p className="mt-3 rounded-[14px] border-2 border-dashed border-line p-4 text-15 font-semibold text-muted">No tickets.</p>
                ) : (
                  <ul className="mt-3 space-y-3">
                    {tickets.map((order) => (
                      <Ticket key={order.id} order={order} now={now} busy={busyId === order.id} onStep={(o, n) => step.mutate({ order: o, next: n })} />
                    ))}
                  </ul>
                )}
              </section>
            );
          })}
        </div>
      </div>
    </div>
  );
}

function MenuRow({ item }: { item: SuggestedPrep["items"][number] }) {
  const client = useQueryClient();
  // Drafts are null until staff type, so live stock changes from orders keep showing
  // and never overwrite what someone is in the middle of typing.
  const [stockDraft, setStockDraft] = useState<string | null>(null);
  const [priceDraft, setPriceDraft] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const stock = stockDraft ?? String(item.stock_today);
  const price = priceDraft ?? (item.price / 100).toFixed(2);
  const save = useMutation({
    mutationFn: (body: Partial<Pick<MenuItem, "is_available" | "stock_today" | "price">>) =>
      api<MenuItem>(`/canteen/menu/${item.id}`, { method: "PATCH", body }),
    onSuccess: () => {
      setStockDraft(null);
      setPriceDraft(null);
      setSaved(true);
      client.invalidateQueries({ queryKey: ["canteen"] });
    },
  });
  const stockValid = /^\d{1,4}$/.test(stock) && Number(stock) <= 1000;
  const priceValid = /^\d+(\.\d{1,2})?$/.test(price) && Number(price) >= 1 && Number(price) <= 1000;
  const stockChanged = stockDraft !== null && stockDraft !== String(item.stock_today);
  const priceChanged = priceDraft !== null && priceDraft !== (item.price / 100).toFixed(2);
  const dirty = stockChanged || priceChanged;

  return (
    <li className="min-w-0 rounded-[16px] border-2 border-edge bg-sheet p-4 shadow-hard">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="flex items-center gap-2 text-17 font-extrabold">
            <VegMark veg={item.is_veg} /> <span className="break-words">{item.name}</span>
          </p>
          <p className="text-13 font-semibold text-muted capitalize">{item.category}</p>
        </div>
        <button
          type="button"
          role="switch"
          aria-checked={item.is_available}
          aria-label={`${item.name} available`}
          disabled={save.isPending}
          onClick={() => save.mutate({ is_available: !item.is_available })}
          className={cn(
            "press inline-flex min-h-11 items-center gap-2 rounded-full border-2 border-edge px-3 text-15 font-bold shadow-hard-sm",
            item.is_available ? "bg-stamp text-white" : "bg-sheet text-muted",
          )}
        >
          <span aria-hidden className={cn("size-3 rounded-full border-2", item.is_available ? "border-white bg-white" : "border-muted")} />
          {item.is_available ? "Available" : "Not available"}
        </button>
      </div>

      <dl className="mt-3 grid grid-cols-2 gap-2">
        <div className="rounded-[12px] border-2 border-edge p-2 text-center">
          <dt className="text-13 font-bold text-muted">Pre-ordered today</dt>
          <dd className="font-display text-28 font-extrabold tabular-nums">{item.preordered_today}</dd>
        </div>
        <div className="rounded-[12px] border-2 border-dashed border-edge p-2 text-center">
          <dt className="text-13 font-bold text-muted">Suggested prep</dt>
          <dd className="font-display text-28 font-extrabold tabular-nums">{item.suggested}</dd>
        </div>
      </dl>

      <form
        className="mt-3 flex flex-wrap items-end gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          // Only what changed: a price edit must not write back a stock value orders have since used.
          save.mutate({
            ...(stockChanged ? { stock_today: Number(stock) } : {}),
            ...(priceChanged ? { price: Math.round(Number(price) * 100) } : {}),
          });
        }}
      >
        <label className="min-w-0 flex-1 text-13 font-bold">
          Stock today
          <Input inputMode="numeric" value={stock} onChange={(e) => {
              setSaved(false);
              setStockDraft(e.target.value);
            }} aria-invalid={!stockValid} className="mt-1" />
        </label>
        <label className="min-w-0 flex-1 text-13 font-bold">
          Price (₹)
          <Input inputMode="decimal" value={price} onChange={(e) => {
              setSaved(false);
              setPriceDraft(e.target.value);
            }} aria-invalid={!priceValid} className="mt-1" />
        </label>
        <Button type="submit" className="min-h-12" disabled={!dirty || !stockValid || !priceValid || save.isPending}>
          {save.isPending ? "Saving…" : "Save"}
        </Button>
      </form>
      <div aria-live="polite" className="mt-1 min-h-5 text-13 font-semibold">
        {save.isError ? <span className="text-alert-text">{errorMessage(save.error)}</span> : null}
        {!stockValid ? <span className="text-alert-text">Stock must be a whole number from 0 to 1000.</span> : null}
        {stockValid && !priceValid ? <span className="text-alert-text">Price must be between ₹1 and ₹1000.</span> : null}
        {saved && !dirty ? <span className="text-stamp-text">Saved. Students see it straight away.</span> : null}
      </div>
    </li>
  );
}

function MenuTab() {
  const data = useQuery({ queryKey: ["canteen", "suggested"], queryFn: () => api<SuggestedPrep>("/canteen/suggested-prep") });
  if (data.isPending) return <Skeleton className="h-64" />;
  if (data.isError) return <ErrorState error={data.error} onRetry={() => data.refetch()} title="The menu didn't load" />;
  if (data.data.items.length === 0) {
    return (
      <EmptyState icon={UtensilsCrossed} title="No menu items">
        Menu items appear here once they're added.
      </EmptyState>
    );
  }
  return (
    <div>
      <p className="font-semibold text-muted">
        Suggested prep: {data.data.label.charAt(0).toLowerCase() + data.data.label.slice(1)}, a simple average of what was ordered.
      </p>
      <ul className="mt-4 grid grid-cols-[minmax(0,1fr)] gap-4 md:grid-cols-2 xl:grid-cols-3">
        {data.data.items.map((item) => (
          <MenuRow key={item.id} item={item} />
        ))}
      </ul>
    </div>
  );
}

function Counter({ value, label, tone }: { value: number | string; label: string; tone: string }) {
  return (
    <div className="relative overflow-hidden rounded-[16px] border-2 border-edge bg-sheet px-4 pt-4 pb-3 shadow-hard">
      <span aria-hidden className={cn("absolute top-0 left-0 h-2 w-full", tone)} />
      <p className="font-display text-40 leading-none font-extrabold tabular-nums">{value}</p>
      <p className="mt-1 text-13 font-bold text-muted">{label}</p>
    </div>
  );
}

/** Kitchen board for canteen staff. Dark by default; updates live as students order. */
export function KitchenPage() {
  useBoardTheme();
  const { now } = useClock();
  const [tab, setTab] = useState<"orders" | "menu">("orders");
  const board = useQuery({ queryKey: ["canteen", "board"], queryFn: () => api<KitchenBoard>("/canteen/board"), refetchInterval: 60_000 });

  return (
    <div>
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="flex items-center gap-3 font-display text-40 leading-none font-extrabold sm:text-64">
            <ChefHat className="size-10 sm:size-14" aria-hidden />
            <span className="[text-shadow:3px_3px_0_var(--yellow)]">Kitchen</span>
          </h1>
          <p className="mt-2 font-semibold text-muted">Today's pre-orders. New ones appear on their own.</p>
        </div>
        <div role="tablist" aria-label="Kitchen views" className="flex gap-2">
          {(
            [
              ["orders", "Orders"],
              ["menu", "Menu and stock"],
            ] as const
          ).map(([value, label]) => (
            <button
              key={value}
              type="button"
              role="tab"
              aria-selected={tab === value}
              onClick={() => setTab(value)}
              className={cn(
                "press min-h-12 rounded-[12px] border-2 border-edge px-4 font-bold shadow-hard-sm",
                tab === value ? "bg-ink text-paper" : "bg-sheet",
              )}
            >
              {label}
            </button>
          ))}
        </div>
      </div>

      {board.data ? (
        <div className="mt-6 grid grid-cols-3 gap-3 sm:max-w-xl">
          <Counter value={board.data.placed.length} label="placed" tone="bg-yellow" />
          <Counter value={board.data.preparing.length} label="preparing" tone="bg-ink" />
          <Counter value={board.data.ready.length} label="ready" tone="bg-stamp" />
        </div>
      ) : null}

      <div className="mt-6">
        <CollectDesk station="canteen" />
      </div>

      <div className="mt-8" role="tabpanel" aria-label={tab === "orders" ? "Orders" : "Menu and stock"}>
        {tab === "orders" ? now ? <OrdersTab now={now} /> : <Skeleton className="h-64" /> : <MenuTab />}
      </div>
    </div>
  );
}
