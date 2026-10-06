import type { ReactNode } from "react";
import { CircleAlert, RotateCw, type LucideIcon } from "lucide-react";
import { Button } from "@/components/ui/button";
import { errorMessage } from "@/lib/api";

/** A failed request: what happened, and a way forward. */
export function ErrorState({ error, onRetry, title = "This didn't load" }: { error: unknown; onRetry: () => void; title?: string }) {
  return (
    <div role="alert" className="rounded-surface border-2 border-edge bg-sheet p-5 shadow-hard">
      <div className="flex items-start gap-3">
        <span className="flex size-10 shrink-0 items-center justify-center rounded-button bg-alert text-white" aria-hidden>
          <CircleAlert className="size-5" />
        </span>
        <div className="min-w-0">
          <p className="font-display text-21 font-extrabold">{title}</p>
          <p className="mt-1 text-muted">{errorMessage(error)}</p>
          <Button variant="secondary" className="mt-4" onClick={onRetry}>
            <RotateCw aria-hidden /> Try again
          </Button>
        </div>
      </div>
    </div>
  );
}

/** Nothing here yet: what the screen is for, and the first action. */
export function EmptyState({ icon: Icon, title, children, action }: { icon: LucideIcon; title: string; children: ReactNode; action?: ReactNode }) {
  return (
    <div className="relative overflow-hidden rounded-surface border-2 border-dashed border-edge bg-sheet p-6 text-center">
      <div aria-hidden className="halftone pointer-events-none absolute -top-6 -right-6 size-28 rounded-full text-magenta" />
      <span className="relative mx-auto flex size-14 -rotate-6 items-center justify-center rounded-[14px] border-2 border-edge bg-paper shadow-hard-sm">
        <Icon className="size-7" aria-hidden />
      </span>
      <p className="relative mt-4 font-display text-21 font-extrabold">{title}</p>
      <div className="relative mx-auto mt-1 max-w-sm text-muted">{children}</div>
      {action ? <div className="relative mt-5 flex justify-center">{action}</div> : null}
    </div>
  );
}
