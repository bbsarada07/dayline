import { useEffect, useState } from "react";
import { Link } from "react-router";
import { Printer, UtensilsCrossed, X, type LucideIcon } from "lucide-react";
import { subscribe } from "@/lib/realtime";
import type { Order, PrintJob } from "@/lib/types";
import { cn } from "@/lib/utils";

type Notice = { id: string; text: string; to: string; tone: "cyan" | "yellow"; icon: LucideIcon };

/** In-app notices for the student ("Token 16 is ready at the canteen"). No push notifications. */
export function Notices() {
  const [notices, setNotices] = useState<Notice[]>([]);

  useEffect(
    () =>
      subscribe((event) => {
        let notice: Notice | null = null;
        if (event.type === "print.updated") {
          const job = event.payload as unknown as PrintJob;
          if (job.status === "ready") {
            notice = { id: `print-${job.id}`, text: `${job.code} is ready at the print shop.`, to: "/print", tone: "cyan", icon: Printer };
          }
        } else if (event.type === "order.updated") {
          const order = event.payload as unknown as Order;
          if (order.status === "ready") {
            notice = { id: `order-${order.id}`, text: `Token ${order.token_no} is ready at the canteen.`, to: "/canteen", tone: "yellow", icon: UtensilsCrossed };
          }
        }
        if (notice) {
          const next = notice;
          setNotices((current) => [next, ...current.filter((n) => n.id !== next.id)].slice(0, 3));
        }
      }),
    [],
  );

  const dismiss = (id: string) => setNotices((current) => current.filter((n) => n.id !== id));

  return (
    <div
      role="status"
      aria-live="polite"
      className="pointer-events-none fixed inset-x-0 top-10 z-40 mx-auto flex w-full max-w-md flex-col gap-2 px-4"
    >
      {notices.map((notice) => (
        <div
          key={notice.id}
          className={cn(
            "notice-in pointer-events-auto flex items-center gap-3 rounded-[16px] border-2 border-edge bg-sheet p-2.5",
            notice.tone === "cyan" ? "shadow-hard-cyan" : "shadow-[4px_4px_0_0_var(--yellow)]",
          )}
        >
          <span
            className={cn(
              "flex size-11 shrink-0 -rotate-6 items-center justify-center rounded-[12px] border-2 border-edge text-on-fill",
              notice.tone === "cyan" ? "bg-cyan" : "bg-yellow",
            )}
            aria-hidden
          >
            <notice.icon className="size-5" />
          </span>
          <p className="min-w-0 flex-1 font-bold">{notice.text}</p>
          <Link
            to={notice.to}
            onClick={() => dismiss(notice.id)}
            className="press inline-flex min-h-11 shrink-0 items-center rounded-button border-2 border-edge bg-ink px-3 text-15 font-bold text-paper shadow-hard-sm"
          >
            View
          </Link>
          <button
            type="button"
            onClick={() => dismiss(notice.id)}
            className="inline-flex size-11 shrink-0 items-center justify-center rounded-button hover:bg-tint"
          >
            <X className="size-5" aria-hidden />
            <span className="sr-only">Dismiss</span>
          </button>
        </div>
      ))}
    </div>
  );
}
