import { useEffect, useState } from "react";
import { useLocation } from "react-router";
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CircleAlert, Clock, Minus, Plus, ShoppingBag, UtensilsCrossed } from "lucide-react";
import { EmptyState, ErrorState } from "@/components/states";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/input";
import { Sheet } from "@/components/ui/sheet";
import { Skeleton } from "@/components/ui/skeleton";
import { api, errorMessage } from "@/lib/api";
import { useClock } from "@/lib/clock";
import { money, plural, timeOfDay } from "@/lib/format";
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
        <Button className="shrink-0" onClick={() => onChange(1)}>
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
        <ShoppingBag className="mx-auto size-8 -rotate-6" aria-hidden />
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
        <p className="inline-block -rotate-1 rounded-[6px] border-2 border-dashed border-edge bg-paper px-2.5 py-1 text-13 font-extrabold">
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

function TokenConfirmation({ order, onDismiss }: { order: Order; onDismiss: () => void }) {
  return (
    <div role="status" className="relative -rotate-1 overflow-hidden rounded-[20px] border-2 border-edge bg-yellow p-5 text-on-fill shadow-hard-lg">
      <div aria-hidden className="halftone pointer-events-none absolute -top-8 -right-8 size-36 rounded-full text-on-fill" />
      <p className="relative font-bold">You're in. Your token is</p>
      <p className="relative font-display text-64 leading-none font-extrabold">{order.token_no}</p>
      <p className="relative mt-2 font-bold">
        Pickup {timeOfDay(order.pickup_time)}. You'll get a notice here when it's ready.
      </p>
      <Button variant="secondary" className="relative mt-3" onClick={onDismiss}>
        Order something else
      </Button>
    </div>
  );
}

export function CanteenPage() {
  const { now } = useClock();
  const desktop = useMediaQuery("(min-width: 1024px)");
  const menu = useQuery({ queryKey: ["canteen", "menu"], queryFn: () => api<MenuData>("/canteen/menu") });
  const mine = useQuery({ queryKey: ["canteen", "mine"], queryFn: () => api<{ orders: Order[] }>("/canteen/orders/mine") });
  const [cart, setCart] = useState<Cart>({});
  const [cartOpen, setCartOpen] = useState(false);
  const [created, setCreated] = useState<Order | null>(null);
  const [pickup, setPickup] = useState<string | null>(null);
  const [selected, setSelected] = useState<number | null>(null);

  // "Edit" on an agent's proposal opens this screen with its cart and pickup filled in.
  const location = useLocation();
  const prefill = (location.state as { prefill?: CanteenPrefill } | null)?.prefill;
  useEffect(() => {
    if (!prefill) return;
    setCart(prefill.cart);
    setPickup(prefill.pickup);
    setCreated(null);
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

  const onPaid = (order: Order) => {
    setCart({});
    setPickup(null);
    setCartOpen(false);
    setCreated(order);
  };

  const cartPanel = (
    <CartPanel cart={cart} menuById={menuById} setQty={setQty} pickup={pickup} setPickup={setPickup} onPaid={onPaid} />
  );

  return (
    <div>
      <header className="relative overflow-hidden rounded-[24px] border-2 border-edge bg-yellow px-5 py-6 text-on-fill shadow-hard-lg sm:px-7">
        <div aria-hidden className="halftone pointer-events-none absolute -top-10 -right-10 size-52 rounded-full text-on-fill" />
        <UtensilsCrossed aria-hidden className="absolute right-5 bottom-4 size-20 -rotate-12 opacity-20 sm:size-28" />
        <h1 className="relative font-display text-40 leading-none font-extrabold sm:text-64">Canteen</h1>
        <p className="relative mt-2 max-w-md text-17 font-semibold">Order ahead and skip the queue. Pick it up when you're free.</p>
      </header>

      {created ? (
        <div className="mt-6">
          <TokenConfirmation order={created} onDismiss={() => setCreated(null)} />
        </div>
      ) : null}

      <div className="mt-7 grid items-start gap-8 lg:grid-cols-[minmax(0,1.2fr)_minmax(0,1fr)]">
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

        <div className="min-w-0 space-y-8 lg:sticky lg:top-6">
          {desktop ? (
            <section aria-labelledby="cart-heading" className="rounded-[20px] border-2 border-edge bg-sheet p-4 shadow-hard sm:p-5">
              <h2 id="cart-heading" className="mb-4 font-display text-28 font-extrabold">Your order</h2>
              {cartPanel}
            </section>
          ) : null}

          <section aria-labelledby="orders-heading">
            <h2 id="orders-heading" className="font-display text-28 font-extrabold">Your orders</h2>
            <div className="mt-4">
              {mine.isPending || !now ? (
                <Skeleton className="h-36" />
              ) : mine.isError ? (
                <ErrorState error={mine.error} onRetry={() => mine.refetch()} title="Your orders didn't load" />
              ) : orders.length === 0 ? (
                <EmptyState icon={UtensilsCrossed} title="No orders yet">
                  Add something from the menu. You get a token and pick it up when you're free.
                </EmptyState>
              ) : (
                <ul className="space-y-5">
                  {orders.map((order, index) => (
                    <li key={order.id} className={cn("transition-transform hover:rotate-0", index % 2 ? "rotate-1" : "-rotate-1")}>
                      <button
                        type="button"
                        className="block w-full rounded-surface text-left"
                        onClick={() => setSelected(order.id)}
                        aria-label={`Token ${order.token_no}. Show details`}
                      >
                        <OrderPass order={order} now={now} />
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </section>
        </div>
      </div>

      {/* Phones: a cart bar above the dock opens the cart as a sheet. */}
      {!desktop && count > 0 ? (
        <div className="fixed inset-x-3 bottom-[6.25rem] z-20 mx-auto max-w-lg pb-[env(safe-area-inset-bottom)]">
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
      {!desktop ? (
        <Sheet open={cartOpen} onOpenChange={setCartOpen} title="Your order">
          {cartPanel}
        </Sheet>
      ) : null}

      {now ? <OrderSheet order={orders.find((o) => o.id === selected) ?? null} now={now} onClose={() => setSelected(null)} /> : null}
    </div>
  );
}
