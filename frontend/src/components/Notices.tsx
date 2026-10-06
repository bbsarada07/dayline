import { useEffect, useState } from "react";
import { Link, useLocation } from "react-router";
import { Mic, Printer, UtensilsCrossed, X, type LucideIcon } from "lucide-react";
import { subscribe } from "@/lib/realtime";
import { useMediaQuery } from "@/lib/media";
import type { AgentReply, Order, PrintJob } from "@/lib/types";
import { useAsk } from "@/features/ask/AskContext";
import { cn } from "@/lib/utils";

/** `to` opens a screen; `ask` opens Ask Dayline (an Omi reply with something to confirm). */
type Notice = { id: string; text: string; to?: string; ask?: boolean; tone: "cyan" | "yellow" | "hero"; icon: LucideIcon };

/** In-app notices for the student ("Token 16 is ready at the canteen"). No push notifications. */
export function Notices() {
  const [notices, setNotices] = useState<Notice[]>([]);
  const ask = useAsk();
  const { pathname } = useLocation();
  const desktop = useMediaQuery("(min-width: 1024px)");

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
        } else if (event.type === "agent.reply") {
          const reply = event.payload as unknown as AgentReply;
          notice = { id: `omi-${reply.conversation_id}-${Date.now()}`, text: `Omi: ${reply.spoken}`, ask: true, tone: "hero", icon: Mic };
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
            notice.tone === "cyan" ? "shadow-hard-cyan" : notice.tone === "hero" ? "shadow-hard-magenta" : "shadow-[4px_4px_0_0_var(--yellow)]",
          )}
        >
          <span
            className={cn(
              "flex size-11 shrink-0 -rotate-6 items-center justify-center rounded-[12px] border-2 border-edge text-on-fill",
              notice.tone === "cyan" ? "bg-cyan" : notice.tone === "hero" ? "bg-hero text-hero-text" : "bg-yellow",
            )}
            aria-hidden
          >
            <notice.icon className="size-5" />
          </span>
          <p className="min-w-0 flex-1 font-bold">{notice.text}</p>
          {notice.to ? (
            <Link
              to={notice.to}
              onClick={() => dismiss(notice.id)}
              className="press inline-flex min-h-11 shrink-0 items-center rounded-button border-2 border-edge bg-ink px-3 text-15 font-bold text-paper shadow-hard-sm"
            >
              View
            </Link>
          ) : (
            <button
              type="button"
              onClick={() => {
                dismiss(notice.id);
                // Laptops show Ask Dayline beside Today; elsewhere it opens as a sheet.
                if (!(desktop && pathname === "/")) ask.openSheet();
              }}
              className="press inline-flex min-h-11 shrink-0 items-center rounded-button border-2 border-edge bg-ink px-3 text-15 font-bold text-paper shadow-hard-sm"
            >
              Open
            </button>
          )}
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
