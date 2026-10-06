import { useNavigate } from "react-router";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { CircleAlert, Pencil, Printer, UtensilsCrossed } from "lucide-react";
import { Stamp } from "@/components/Stamp";
import { Button } from "@/components/ui/button";
import { api, errorMessage } from "@/lib/api";
import { money, timeOfDay, weekdayTime, sameDay } from "@/lib/format";
import type { Order, PrintJob, Proposal } from "@/lib/types";
import { cn } from "@/lib/utils";
import { orderPassId } from "@/features/canteen/canteenShared";
import { printPassId } from "@/features/print/printShared";
import { markNewPass } from "@/features/today/DayLine";
import { useAsk } from "./AskContext";

/** Where "Edit" takes a proposal: the normal screen, filled in (read from location.state). */
export type CanteenPrefill = { cart: Record<number, number>; pickup: string | null };
export type PrintPrefill = {
  upload: { upload_id: string; original_filename: string; pages: number };
  copies: number;
  color: boolean;
  double_sided: boolean;
  deadline: string | null; // "YYYY-MM-DDTHH:mm" college time
};

function when(value: string, now: Date | null): string {
  return now && sameDay(value, now) ? timeOfDay(value) : weekdayTime(value);
}

/**
 * Something an agent prepared: dashed until the student confirms and pays through the
 * normal endpoint. Agents never spend money themselves.
 */
export function ProposalCard({ proposal, now, onLeave }: { proposal: Proposal; now: Date | null; onLeave?: () => void }) {
  const client = useQueryClient();
  const navigate = useNavigate();
  const { confirmed, markConfirmed } = useAsk();
  const done = confirmed[proposal.id] ?? null;
  const setDone = (label: string) => markConfirmed(proposal.id, label);
  const isOrder = proposal.type === "order";

  // Paid through the same endpoints as the Canteen and Print screens; the pass then drops onto the day line.
  const confirm = useMutation({
    mutationFn: async (): Promise<{ passId: string; label: string; area: string }> => {
      if (proposal.type === "order") {
        const order = await api<Order>("/canteen/orders", { method: "POST", body: proposal.body });
        return { passId: orderPassId(order), label: `Token ${order.token_no}`, area: "canteen" };
      }
      const job = await api<PrintJob>("/print/jobs", { method: "POST", body: proposal.body });
      return { passId: printPassId(job), label: job.code, area: "print" };
    },
    onSuccess: ({ passId, label, area }) => {
      markNewPass(passId);
      setDone(label);
      client.invalidateQueries({ queryKey: [area] });
      client.invalidateQueries({ queryKey: ["today"] });
    },
  });

  const edit = () => {
    onLeave?.();
    if (proposal.type === "order") {
      const prefill: CanteenPrefill = {
        cart: Object.fromEntries(proposal.lines.map((l) => [l.menu_item_id, l.qty])),
        pickup: proposal.pickup_time,
      };
      navigate("/canteen", { state: { prefill } });
    } else {
      const prefill: PrintPrefill = {
        upload: { upload_id: proposal.body.upload_id, original_filename: proposal.title, pages: proposal.pages },
        copies: proposal.copies,
        color: proposal.color,
        double_sided: proposal.double_sided,
        deadline: proposal.body.deadline ? proposal.body.deadline.slice(0, 16) : null,
      };
      navigate("/print", { state: { prefill } });
    }
  };

  const cost = proposal.type === "order" ? proposal.total : proposal.cost;
  const Icon = isOrder ? UtensilsCrossed : Printer;

  return (
    <article
      className={cn(
        "relative min-w-0 rounded-[16px] border-2 border-edge bg-sheet p-3.5 transition-shadow",
        done ? cn("border-solid", isOrder ? "shadow-[4px_4px_0_0_var(--yellow)]" : "shadow-hard-cyan") : "border-dashed",
      )}
      aria-label={isOrder ? "Food order to confirm" : "Print job to confirm"}
    >
      <header className="flex items-start justify-between gap-3">
        <p className="flex min-w-0 items-center gap-2">
          <span className={cn("inline-flex size-8 shrink-0 items-center justify-center rounded-[9px] border-2 border-edge text-on-fill", isOrder ? "bg-yellow" : "bg-cyan")}>
            <Icon className="size-4" aria-hidden />
          </span>
          <span className="min-w-0">
            <span className="block text-13 font-bold text-muted">{isOrder ? "Canteen order" : "Print job"}</span>
            <span className="block truncate font-display text-17 font-extrabold">
              {proposal.type === "order" ? proposal.lines.map((l) => `${l.name} × ${l.qty}`).join(", ") : proposal.title}
            </span>
          </span>
        </p>
        {done ? <Stamp text={done} tone="success" press /> : <span className="font-display text-21 font-extrabold tabular-nums">{money(cost)}</span>}
      </header>

      <dl className="mt-2.5 grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-13">
        {proposal.type === "order" ? (
          <>
            <dt className="font-bold text-muted">Pickup</dt>
            <dd className="font-semibold">
              {when(proposal.pickup_time, now)}
              {proposal.pickup_reason ? <span className="text-muted"> · {proposal.pickup_reason}</span> : null}
            </dd>
          </>
        ) : (
          <>
            <dt className="font-bold text-muted">Copies</dt>
            <dd className="font-semibold">
              {proposal.pages} {proposal.pages === 1 ? "page" : "pages"} × {proposal.copies}, {proposal.color ? "colour" : "black and white"},{" "}
              {proposal.double_sided ? "double sided" : "single sided"}
            </dd>
            <dt className="font-bold text-muted">Needed by</dt>
            <dd className="font-semibold">
              {when(proposal.deadline, now)}
              {proposal.deadline_reason ? <span className="text-muted"> · {proposal.deadline_reason}</span> : null}
            </dd>
            <dt className="font-bold text-muted">Ready</dt>
            <dd className="font-semibold">about {when(proposal.est_ready_at, now)}</dd>
          </>
        )}
      </dl>

      {proposal.type === "print" && proposal.warning ? (
        <p className="mt-2 flex items-start gap-1.5 text-13 font-bold text-alert-text">
          <CircleAlert className="mt-0.5 size-4 shrink-0" aria-hidden /> {proposal.warning}
        </p>
      ) : null}

      {confirm.isError ? (
        <p role="alert" className="mt-2 flex items-start gap-1.5 text-13 font-bold text-alert-text">
          <CircleAlert className="mt-0.5 size-4 shrink-0" aria-hidden /> {errorMessage(confirm.error)} Use Edit to change it.
        </p>
      ) : null}

      {done ? (
        <p role="status" className="mt-2.5 text-13 font-bold text-stamp-text">
          Paid. It's on your day line{isOrder ? "; show your ID card at the counter" : ""}.
        </p>
      ) : (
        <div className="mt-3 flex flex-wrap gap-2">
          <Button onClick={() => confirm.mutate()} disabled={confirm.isPending}>
            {confirm.isPending ? "Paying…" : `Confirm and pay ${money(cost)}`}
          </Button>
          <Button variant="secondary" onClick={edit} disabled={confirm.isPending}>
            <Pencil aria-hidden /> Edit
          </Button>
        </div>
      )}
    </article>
  );
}
