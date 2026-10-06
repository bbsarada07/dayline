import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Check, CircleAlert, UtensilsCrossed } from "lucide-react";
import { Barcode } from "@/components/Barcode";
import { Pass } from "@/components/Pass";
import { Stamp, useBecameWhileShown } from "@/components/Stamp";
import { Button } from "@/components/ui/button";
import { Sheet } from "@/components/ui/sheet";
import { api, errorMessage } from "@/lib/api";
import { useMe } from "@/lib/auth";
import { dayDate, money, sameDay, timeOfDay } from "@/lib/format";
import type { Order, OrderStatus } from "@/lib/types";
import { cn } from "@/lib/utils";

export const ORDER_STATUS_LABEL: Record<OrderStatus, string> = {
  placed: "Order placed",
  preparing: "Being prepared",
  ready: "Ready to collect",
  collected: "Collected",
  cancelled: "Cancelled",
  no_show: "Not collected",
};

const STEPS: OrderStatus[] = ["placed", "preparing", "ready", "collected"];

/** Id of an order's pass on the day line. */
export const orderPassId = (order: Pick<Order, "id">) => `order-${order.id}`;

/** "1:50 pm" today, "Tue 6 Oct, 1:50 pm" on another day. */
function when(value: string, now: Date): string {
  return sameDay(value, now) ? timeOfDay(value) : `${dayDate(value)}, ${timeOfDay(value)}`;
}

/**
 * The Indian food mark: green square with a dot for veg, brown square with a
 * triangle for non-veg. The shape and the hidden text carry the meaning too.
 */
export function VegMark({ veg, className }: { veg: boolean; className?: string }) {
  return (
    <span
      className={cn(
        "inline-flex size-4 shrink-0 items-center justify-center rounded-[3px] border-2 bg-white",
        veg ? "border-[#1f8a4c]" : "border-[#8b3a1a]",
        className,
      )}
    >
      {veg ? (
        <span aria-hidden className="size-1.5 rounded-full bg-[#1f8a4c]" />
      ) : (
        <span aria-hidden className="size-0 border-x-[4px] border-b-[7px] border-x-transparent border-b-[#8b3a1a]" />
      )}
      <span className="sr-only">{veg ? "Veg" : "Non-veg"}</span>
    </span>
  );
}

export function itemsLabel(order: Pick<Order, "items">): string {
  return order.items.map((line) => `${line.name} × ${line.qty}`).join(", ");
}

function StatusStamp({ status, press = false }: { status: OrderStatus; press?: boolean }) {
  if (status === "placed" || status === "preparing") return null;
  const tone = status === "collected" ? "success" : status === "ready" ? "neutral" : "alert";
  return <Stamp text={status === "ready" ? "Ready" : ORDER_STATUS_LABEL[status]} tone={tone} press={press} />;
}

/** The student's ID barcode, to show at the counter when something is ready. */
export function CollectBarcode() {
  const me = useMe().data;
  const code = me?.kind === "student" ? me.card_uid : null;
  if (!code) return null;
  return (
    <div className="mt-4 rounded-[14px] border-2 border-edge p-3">
      <p className="mb-2 font-bold">Show this at the counter, or scan your ID card.</p>
      <Barcode value={code} />
    </div>
  );
}

/** The yellow pass for a canteen order (day line, order list). */
export function OrderPass({ order, now }: { order: Order; now: Date }) {
  const active = order.status === "placed" || order.status === "preparing";
  // Collected while on screen (a scan at the counter): the stamp presses on.
  const justCollected = useBecameWhileShown(order.status, "collected");
  return (
    <Pass
      tone="yellow"
      header={
        <>
          <span className="inline-flex min-w-0 items-center gap-2">
            <UtensilsCrossed className="size-[18px] shrink-0" aria-hidden />
            <span className="truncate">Canteen</span>
          </span>
          <span className="shrink-0 tabular-nums">Token {order.token_no}</span>
        </>
      }
    >
      <div className="flex items-start justify-between gap-3">
        <ul className="min-w-0 space-y-0.5">
          {order.items.map((line) => (
            <li key={line.menu_item_id} className="flex items-center gap-2 font-extrabold">
              <VegMark veg={line.is_veg} />
              <span className="truncate">
                {line.name} × {line.qty}
              </span>
            </li>
          ))}
        </ul>
        <StatusStamp status={order.status} press={justCollected} />
      </div>
      <div className="mt-2.5 flex items-end justify-between gap-3">
        <div className="min-w-0 text-13">
          {active ? <p className="font-bold">{ORDER_STATUS_LABEL[order.status]}</p> : null}
          {order.status === "ready" ? <p className="font-bold">Collect it at the counter</p> : null}
          {order.status !== "cancelled" ? <p className="font-semibold text-muted">Pickup {when(order.pickup_time, now)}</p> : null}
        </div>
        <p className="shrink-0 font-display text-21 font-extrabold">{money(order.total)}</p>
      </div>
    </Pass>
  );
}

function Steps({ status }: { status: OrderStatus }) {
  const reached = STEPS.indexOf(status);
  if (reached < 0) return <StatusStamp status={status} />;
  return (
    <ol className="grid grid-cols-4 gap-1.5" aria-label="Progress">
      {STEPS.map((step, index) => {
        const done = index <= reached;
        return (
          <li key={step} className="min-w-0">
            <span className={cn("block h-3 rounded-full border-2 border-edge", done ? "bg-yellow" : "bg-sheet")} aria-hidden />
            <span className={cn("mt-1.5 flex items-start gap-1 text-13", done ? "font-extrabold" : "font-semibold text-muted")}>
              {index === reached ? <Check className="mt-0.5 size-3.5 shrink-0" aria-hidden /> : null}
              <span>{ORDER_STATUS_LABEL[step]}</span>
              {index === reached ? <span className="sr-only">(current step)</span> : null}
            </span>
          </li>
        );
      })}
    </ol>
  );
}

/** Full details of one order, with cancel while it's still placed. */
export function OrderSheet({ order, now, onClose }: { order: Order | null; now: Date; onClose: () => void }) {
  const client = useQueryClient();
  const [confirming, setConfirming] = useState(false);
  const cancel = useMutation({
    mutationFn: (id: number) => api<Order>(`/canteen/orders/${id}/cancel`, { method: "POST" }),
    onSuccess: () => {
      setConfirming(false);
      client.invalidateQueries({ queryKey: ["canteen"] });
      client.invalidateQueries({ queryKey: ["today"] });
    },
  });

  const close = () => {
    setConfirming(false);
    cancel.reset();
    onClose();
  };

  return (
    <Sheet open={order !== null} onOpenChange={(open) => !open && close()} title={order ? `Token ${order.token_no}` : ""}>
      {order ? (
        <div>
          <Steps status={order.status} />
          {order.status === "ready" ? <CollectBarcode /> : null}
          <ul className="mt-4 divide-y-2 divide-dashed divide-line">
            {order.items.map((line) => (
              <li key={line.menu_item_id} className="flex items-center justify-between gap-3 py-2">
                <span className="flex min-w-0 items-center gap-2 font-bold">
                  <VegMark veg={line.is_veg} />
                  <span className="break-words">
                    {line.name} × {line.qty}
                  </span>
                </span>
                <span className="shrink-0 font-bold tabular-nums">{money(line.unit_price * line.qty)}</span>
              </li>
            ))}
          </ul>
          <dl className="mt-2 divide-y-2 divide-dashed divide-line border-t-2 border-edge">
            <div className="flex justify-between gap-4 py-2">
              <dt className="font-semibold text-muted">Pickup</dt>
              <dd className="font-bold">{when(order.pickup_time, now)}</dd>
            </div>
            {order.ready_at ? (
              <div className="flex justify-between gap-4 py-2">
                <dt className="font-semibold text-muted">Ready at</dt>
                <dd className="font-bold">{when(order.ready_at, now)}</dd>
              </div>
            ) : null}
            {order.collected_at ? (
              <div className="flex justify-between gap-4 py-2">
                <dt className="font-semibold text-muted">Collected at</dt>
                <dd className="font-bold">{when(order.collected_at, now)}</dd>
              </div>
            ) : null}
            <div className="flex justify-between gap-4 py-2">
              <dt className="font-semibold text-muted">Total</dt>
              <dd className="font-bold">
                {money(order.total)} <span className="font-semibold text-muted">(demo payment)</span>
              </dd>
            </div>
          </dl>

          {order.status === "placed" && !confirming ? (
            <Button variant="secondary" className="mt-4" onClick={() => setConfirming(true)}>
              Cancel order
            </Button>
          ) : null}
          {order.status === "placed" && confirming ? (
            <div className="mt-4 rounded-[14px] border-2 border-edge bg-tint p-4">
              <p className="font-extrabold">Cancel token {order.token_no}?</p>
              <p className="mt-1 text-muted">The kitchen won't make it. This was a demo payment, so no money moves.</p>
              <div className="mt-3 flex flex-wrap gap-2">
                <Button onClick={() => cancel.mutate(order.id)} disabled={cancel.isPending}>
                  {cancel.isPending ? "Cancelling…" : "Cancel order"}
                </Button>
                <Button variant="ghost" onClick={() => setConfirming(false)} disabled={cancel.isPending}>
                  Keep order
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
