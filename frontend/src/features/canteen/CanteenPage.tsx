import { useEffect, useState } from "react";
import { useLocation } from "react-router";
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CircleAlert, Clock, Minus, Plus, ShoppingBag, UtensilsCrossed } from "lucide-react";
import { Collapsed, PageHeading } from "@/components/PageParts";
import { EmptyState, ErrorState } from "@/components/states";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/input";
import { Sheet } from "@/components/ui/sheet";
import { Skeleton } from "@/components/ui/skeleton";
import { api, errorMessage } from "@/lib/api";
import { useClock } from "@/lib/clock";
import { money, plural, sameDay, timeOfDay } from "@/lib/format";
import { useMediaQuery } from "@/lib/media";
import type { CanteenQuote, MenuData, MenuItem, Order } from "@/lib/types";
import { cn } from "@/lib/utils";
import type { CanteenPrefill } from "@/features/ask/ProposalCard";
import { markNewPass } from "@/features/today/DayLine";
import { OrderPass, OrderSheet, VegMark, orderPassId } from "./canteenShared";

const MAX_QTY = 10;
const LOW_STOCK = 5;
const CATEGORY_LABEL: Record<string, string> = { breakfast: "Breakfast", meals: "Meals", snacks: "Snacks", drinks: "Drinks" };

type Cart = Record<number, number>;

function categoryName(category: string) {
  return CATEGORY_LABEL[category] ?? category.charAt(0).toUpperCase() + category.slice(1);
}

function Stepper({ name, qty, max, onChange }: { name: string; qty: number; max: number; onChange: (qty: number) => void }) {
  return (
    <div className="inline-flex items-center gap-1.5" role="group" aria-label={`${name} quantity`}>
      <Button variant="secondary" size="icon" aria-label={`One ${name} fewer`} onClick={() => onChange(qty - 1)}>
        <Minus aria-hidden />
      </Button>
      <output aria-live="polite" className="w-7 text-center font-display text-21 font-extrabold tabular-nums">
        {qty}
      </output>
      <Button variant="secondary" size="icon" aria-label={`One ${name} more`} disabled={qty >= max} onClick={() => onChange(qty + 1)}>
        <Plus aria-hidden />
      </Button>
    </div>
  );
}

function MenuCard({ item, qty, onChange }: { item: MenuItem; qty: number; onChange: (qty: number) => void }) {
  const max = Math.min(MAX_QTY, item.stock_today);
  const unavailableText = !item.is_available ? "Not available today" : item.stock_today === 0 ? "Sold out" : null;
  return (
    <li
      className={cn(
        "flex min-w-0 items-center justify-between gap-3 rounded-[16px] border-2 border-edge bg-sheet p-3 shadow-hard",
        unavailableText && "border-dashed shadow-none",
        qty > 0 && "shadow-[4px_4px_0_0_var(--yellow)]",
      )}
    >
      <div className="min-w-0">
        <p className="flex items-center gap-2">
          <VegMark veg={item.is_veg} />
          <span className={cn("truncate text-17 font-extrabold", unavailableText && "text-muted")}>{item.name}</span>
        </p>
        <p className="mt-0.5 flex flex-wrap items-center gap-x-2 text-13 font-semibold text-muted">
          <span className="font-display text-17 font-extrabold text-ink">{money(item.price)}</span>
          <span className="inline-flex items-center gap-1">
            <Clock className="size-3.5" aria-hidden /> {item.prep_minutes} min
          </span>
          {!unavailableText && item.stock_today <= LOW_STOCK ? <span className="font-bold text-alert-text">Only {item.stock_today} left</span> : null}
        </p>
      </div>
      {unavailableText ? (
        <span className="shrink-0 rounded-[8px] border-2 border-dashed border-line px-2 py-1 text-13 font-bold text-muted">{unavailableText}</span>
      ) : qty > 0 ? (
        <Stepper name={item.name} qty={qty} max={max} onChange={onChange} />
      ) : (
        <Button variant="secondary" className="shrink-0" onClick={() => onChange(1)}>
          <Plus aria-hidden /> Add
        </Button>
      )}
    </li>
  );
}

/** Cart, pickup time, receipt and demo payment. One copy is mounted: side panel on laptops, sheet on phones. */
function CartPanel({ cart, menuById, setQty, pickup, setPickup, onPaid }: {
  cart: Cart;
  menuById: Map<number, MenuItem>;
  setQty: (id: number, qty: number) => void;
  /** A slot from the quote, or null for the suggested time. Lives in the page so closing the sheet keeps it. */
  pickup: string | null;
  setPickup: (pickup: string | null) => void;
  onPaid: (order: Order) => void;
}) {
  const client = useQueryClient();
  const lines = Object.entries(cart).map(([id, qty]) => ({ menu_item_id: Number(id), qty }));
  const body = { items: lines, pickup_time: pickup ?? undefined };
  const quote = useQuery({
    queryKey: ["canteen", "quote", body],
    queryFn: () => api<CanteenQuote>("/canteen/quote", { method: "POST", body }),
    enabled: lines.length > 0,
    placeholderData: keepPreviousData,
    staleTime: 0,
    refetchInterval: 30_000,
  });
  const pay = useMutation({
    // Pay for exactly what the receipt shows: its pickup time and total. If either is
    // out of date the server says so and nothing is charged.
    mutationFn: (q: CanteenQuote) =>
      api<Order>("/canteen/orders", {
        method: "POST",
        body: { items: lines, pickup_time: pickup ?? q.pickup_time, expected_total: q.total },
      }),
    onError: () => client.invalidateQueries({ queryKey: ["canteen", "quote"] }),
    onSuccess: (order) => {
      markNewPass(orderPassId(order));
      client.removeQueries({ queryKey: ["canteen", "quote"] });
      client.invalidateQueries({ queryKey: ["canteen"] });
      client.invalidateQueries({ queryKey: ["today"] });
      onPaid(order);
    },
  });

  if (lines.length === 0) {
    return (
      <div className="rounded-[18px] border-2 border-dashed border-edge bg-sheet p-5 text-center">
        <ShoppingBag className="mx-auto size-8" aria-hidden />
        <p className="mt-2 font-display text-21 font-extrabold">Your cart is empty</p>
        <p className="text-muted">Add food from the menu. You pick it up when you're free.</p>
      </div>
    );
  }

  const q = quote.data;
  const chosen = pickup ?? q?.pickup_time ?? "";

  return (
    <div className="space-y-5">
      <ul className="space-y-2">
        {lines.map(({ menu_item_id, qty }) => {
          const item = menuById.get(menu_item_id);
          if (!item) return null;
          return (
            <li key={menu_item_id} className="flex items-center justify-between gap-3">
              <span className="flex min-w-0 items-center gap-2 font-bold">
                <VegMark veg={item.is_veg} />
                <span className="truncate">{item.name}</span>
              </span>
              <Stepper name={item.name} qty={qty} max={Math.min(MAX_QTY, item.stock_today)} onChange={(n) => setQty(menu_item_id, n)} />
            </li>
          );
        })}
      </ul>

      <div className="space-y-2">
        <Label htmlFor="pickup">Pickup time</Label>
        <select
          id="pickup"
          value={chosen}
          disabled={!q}
          onChange={(e) => setPickup(e.target.value === q?.pickup_time && pickup === null ? null : e.target.value)}
          className="min-h-12 w-full rounded-button border-2 border-edge bg-sheet px-3 text-17 font-bold text-ink"
        >
          {q?.pickup_slots.map((slot) => (
            <option key={slot} value={slot}>
              {timeOfDay(slot)}
              {q.pickup_is_default && slot === q.pickup_time ? " (suggested)" : ""}
            </option>
          ))}
        </select>
        {q?.pickup_reason ? <p className="text-13 font-semibold text-muted">{q.pickup_reason}</p> : null}
        {pickup !== null ? (
          <Button variant="ghost" className="-mx-2 px-2" onClick={() => setPickup(null)}>
            Use suggested time
          </Button>
        ) : null}
      </div>

      <section aria-label="Price" aria-live="polite">
        {quote.isError && !q ? (
          <ErrorState error={quote.error} onRetry={() => quote.refetch()} title="Couldn't price this order" />
        ) : !q ? (
          <Skeleton className="h-40" />
        ) : (
          <div className={cn("rounded-[14px] border-2 border-edge bg-sheet p-4 shadow-hard", quote.isFetching && "opacity-70")}>
            <p className="text-center font-display text-15 font-extrabold">Canteen receipt</p>
            <div aria-hidden className="my-3 border-t-2 border-dashed border-edge/60" />
            {quote.isError ? (
              <p role="alert" className="mb-3 flex items-start gap-2 font-semibold text-alert-text">
                <CircleAlert className="mt-0.5 size-5 shrink-0" aria-hidden />
                {errorMessage(quote.error)}
              </p>
            ) : null}
            <dl className="space-y-1.5">
              {q.lines.map((line) => (
                <div key={line.menu_item_id} className="flex items-baseline gap-2">
                  <dt className="min-w-0 truncate font-semibold text-muted">
                    {line.name} × {line.qty}
                  </dt>
                  <span aria-hidden className="mb-1 flex-1 border-b-2 border-dotted border-line" />
                  <dd className="shrink-0 font-extrabold tabular-nums">{money(line.line_total)}</dd>
                </div>
              ))}
              <div className="flex items-baseline gap-2">
                <dt className="font-semibold text-muted">Pickup</dt>
                <span aria-hidden className="mb-1 flex-1 border-b-2 border-dotted border-line" />
                <dd className="font-extrabold">{timeOfDay(q.pickup_time)}</dd>
              </div>
            </dl>
            <div aria-hidden className="my-3 border-t-2 border-dashed border-edge/60" />
            <div className="flex items-baseline justify-between">
              <span className="font-display text-17 font-extrabold">Total</span>
              <span className="font-display text-40 leading-none font-extrabold">{money(q.total)}</span>
            </div>
          </div>
        )}
      </section>

      <div>
        <p className="inline-block rounded-[6px] border-2 border-dashed border-edge bg-paper px-2.5 py-1 text-13 font-extrabold">
          Demo payment — no money moves
        </p>
        <Button
          size="lg"
          className="mt-3 w-full text-21"
          disabled={!q || quote.isFetching || quote.isError || pay.isPending}
          onClick={() => q && pay.mutate(q)}
        >
          {pay.isPending ? "Paying…" : q ? `Confirm and pay ${money(q.total)}` : "Confirm and pay"}
        </Button>
        <p className="mt-2 text-center text-13 font-semibold text-muted">You get a token. Show it at the counter.</p>
        {pay.isError ? (
          <p role="alert" className="mt-3 flex items-start gap-2 font-semibold text-alert-text">
            <CircleAlert className="mt-0.5 size-5 shrink-0" aria-hidden />
            {errorMessage(pay.error)}
          </p>
        ) : null}
      </div>
    </div>
  );
}

const ACTIVE: Order["status"][] = ["placed", "preparing", "ready"];

/** Orders on the way first (the newest one highlighted), then finished ones folded away. */
function YourOrders({ orders, now, loading, error, onRetry, onOpen }: {
  orders: Order[];
  now: Date | null;
  loading: boolean;
  error: unknown;
  onRetry: () => void;
  onOpen: (id: number) => void;
}) {
  const heading = <h2 id="orders-heading" className="font-display text-28 font-extrabold">Your orders</h2>;
  if (loading || !now) {
    return (
      <section aria-labelledby="orders-heading">
        {heading}
        <Skeleton className="mt-4 h-36" />
      </section>
    );
  }
  if (error) {
    return (
      <section aria-labelledby="orders-heading">
        {heading}
        <div className="mt-4">
          <ErrorState error={error} onRetry={onRetry} title="Your orders didn't load" />
        </div>
      </section>
    );
  }
  if (!orders.length) return null; // nothing to show yet: the menu is the next step

  const active = orders.filter((o) => ACTIVE.includes(o.status));
  const finished = orders.filter((o) => !ACTIVE.includes(o.status));
  const earlierToday = finished.filter((o) => sameDay(o.pickup_time, now));
  const past = finished.filter((o) => !sameDay(o.pickup_time, now));
  const newest = active.reduce<Order | null>((best, o) => (!best || o.created_at > best.created_at ? o : best), null);
  const ticket = (order: Order) => (
    <button
      key={order.id}
      type="button"
      className="block w-full rounded-surface text-left"
      onClick={() => onOpen(order.id)}
      aria-label={`Token ${order.token_no}. Show details`}
    >
      <OrderPass order={order} now={now} />
    </button>
  );

  return (
    <section aria-labelledby="orders-heading">
      {heading}
      <div className="mt-4 space-y-4">
        {active.length ? (
          <ul className="space-y-5">
            {active.map((order) => (
              <li key={order.id}>
                {order.id === newest?.id ? (
                  <div className="rounded-[22px] border-2 border-edge bg-yellow p-2.5 shadow-hard">
                    <p className="mb-2 px-1 text-13 font-extrabold text-on-fill">Newest order</p>
                    {ticket(order)}
                  </div>
                ) : (
                  ticket(order)
                )}
              </li>
            ))}
          </ul>
        ) : (
          <p className="font-semibold text-muted">Nothing on the way. Order from the menu below.</p>
        )}
        <Collapsed title="Earlier today" count={earlierToday.length}>{earlierToday.map(ticket)}</Collapsed>
        <Collapsed title="Past orders" count={past.length}>{past.map(ticket)}</Collapsed>
      </div>
    </section>
  );
}

export function CanteenPage() {
  const { now } = useClock();
  const desktop = useMediaQuery("(min-width: 1024px)");
  const menu = useQuery({ queryKey: ["canteen", "menu"], queryFn: () => api<MenuData>("/canteen/menu") });
  const mine = useQuery({ queryKey: ["canteen", "mine"], queryFn: () => api<{ orders: Order[] }>("/canteen/orders/mine") });
  const [cart, setCart] = useState<Cart>({});
  const [cartOpen, setCartOpen] = useState(false);
  const [pickup, setPickup] = useState<string | null>(null);
  const [selected, setSelected] = useState<number | null>(null);

  // "Edit" on an agent's proposal opens this screen with its cart and pickup filled in.
  const location = useLocation();
  const prefill = (location.state as { prefill?: CanteenPrefill } | null)?.prefill;
  useEffect(() => {
    if (!prefill) return;
    setCart(prefill.cart);
    setPickup(prefill.pickup);
    if (!window.matchMedia("(min-width: 1024px)").matches) setCartOpen(true);
  }, [location.key]); // once per navigation, not on every render

  const items = menu.data?.items ?? [];
  const menuById = new Map(items.map((i) => [i.id, i]));
  const count = Object.values(cart).reduce((a, b) => a + b, 0);
  const cartTotal = Object.entries(cart).reduce((sum, [id, qty]) => sum + (menuById.get(Number(id))?.price ?? 0) * qty, 0);
  const orders = mine.data?.orders ?? [];

  const setQty = (id: number, qty: number) =>
    setCart((current) => {
      const next = { ...current };
      if (qty <= 0) delete next[id];
      else next[id] = qty;
      return next;
    });

  const onPaid = () => {
    setCart({});
    setPickup(null);
    setCartOpen(false);
  };

  const cartPanel = (
    <CartPanel cart={cart} menuById={menuById} setQty={setQty} pickup={pickup} setPickup={setPickup} onPaid={onPaid} />
  );

  return (
    <div>
      <PageHeading
        title="Canteen"
        subtitle="Order ahead, skip the queue."
        icon={UtensilsCrossed}
        className="bg-yellow text-on-fill"
      />

      <div className="mt-6 grid items-start gap-8 lg:grid-cols-[minmax(0,1.2fr)_minmax(0,1fr)]">
        <div className="min-w-0 space-y-8">
          <YourOrders
            orders={orders}
            now={now}
            loading={mine.isPending}
            error={mine.isError ? mine.error : null}
            onRetry={() => mine.refetch()}
            onOpen={setSelected}
          />

          <section aria-labelledby="menu-heading" className="min-w-0">
            <h2 id="menu-heading" className="font-display text-28 font-extrabold">Menu</h2>
            {menu.isPending ? (
              <div className="mt-4 space-y-3" aria-busy="true" aria-label="Loading the menu">
                {[0, 1, 2, 3].map((i) => (
                  <Skeleton key={i} className="h-20" />
                ))}
              </div>
            ) : menu.isError ? (
              <div className="mt-4">
                <ErrorState error={menu.error} onRetry={() => menu.refetch()} title="The menu didn't load" />
              </div>
            ) : items.length === 0 ? (
              <div className="mt-4">
                <EmptyState icon={UtensilsCrossed} title="No menu yet">
                  The canteen hasn't put up today's menu. Check back soon.
                </EmptyState>
              </div>
            ) : (
              <>
                <nav aria-label="Menu sections" className="mt-3 flex flex-wrap gap-2">
                  {menu.data.categories
                    .filter((c) => items.some((i) => i.category === c))
                    .map((c) => (
                      <a
                        key={c}
                        href={`#menu-${c}`}
                        className="press rounded-full border-2 border-edge bg-sheet px-3 py-1.5 text-15 font-bold shadow-hard-sm"
                      >
                        {categoryName(c)}
                      </a>
                    ))}
                </nav>
                {menu.data.categories.map((category) => {
                  const inCategory = items.filter((i) => i.category === category);
                  if (!inCategory.length) return null;
                  return (
                    <section key={category} id={`menu-${category}`} className="mt-6 scroll-mt-12" aria-label={categoryName(category)}>
                      <h3 className="font-display text-21 font-extrabold">{categoryName(category)}</h3>
                      <ul className="mt-3 grid grid-cols-[minmax(0,1fr)] gap-3 sm:grid-cols-2 lg:grid-cols-[minmax(0,1fr)] xl:grid-cols-2">
                        {inCategory.map((item) => (
                          <MenuCard key={item.id} item={item} qty={cart[item.id] ?? 0} onChange={(qty) => setQty(item.id, qty)} />
                        ))}
                      </ul>
                    </section>
                  );
                })}
              </>
            )}
          </section>
        </div>

        {desktop ? (
          // Stays in view while the menu scrolls; scrolls itself if the window is short.
          <section
            aria-labelledby="cart-heading"
            className="rounded-[20px] border-2 border-edge bg-sheet p-4 shadow-hard sm:p-5 lg:sticky lg:top-6 lg:max-h-[calc(100dvh-3rem)] lg:overflow-y-auto"
          >
            <h2 id="cart-heading" className="mb-4 font-display text-28 font-extrabold">Your order</h2>
            {cartPanel}
          </section>
        ) : null}
      </div>

      {/* Phones: a cart bar above the dock opens the cart as a sheet. */}
      {!desktop && count > 0 ? (
        <div className="fixed inset-x-3 bottom-[calc(9.5rem+env(safe-area-inset-bottom))] z-20 mx-auto max-w-lg">
          <Button
            size="lg"
            className="w-full justify-between border-edge bg-yellow text-on-fill shadow-hard"
            onClick={() => setCartOpen(true)}
          >
            <span className="inline-flex items-center gap-2">
              <ShoppingBag aria-hidden /> View cart · {plural(count, "item")}
            </span>
            <span className="font-display text-21 font-extrabold">{money(cartTotal)}</span>
          </Button>
        </div>
      ) : null}
      {!desktop && count > 0 ? <div aria-hidden className="h-20" /> : null}
      {!desktop ? (
        <Sheet open={cartOpen} onOpenChange={setCartOpen} title="Your order">
          {cartPanel}
        </Sheet>
      ) : null}

      {now ? <OrderSheet order={orders.find((o) => o.id === selected) ?? null} now={now} onClose={() => setSelected(null)} /> : null}
    </div>
  );
}
