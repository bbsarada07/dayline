import * as Dialog from "@radix-ui/react-dialog";
import { useLocation } from "react-router";
import { Mic, Sparkles, X } from "lucide-react";
import { useMediaQuery } from "@/lib/media";
import { cn } from "@/lib/utils";
import { useAsk } from "./AskContext";
import { AskPanel } from "./AskPanel";

/**
 * Where students reach Dayline's agents:
 * - phones: an ask bar docked above the main nav, opening a full-height sheet;
 * - laptops: the panel on Today, and a floating button on every other screen.
 */
export function AskDock() {
  const ask = useAsk();
  const { pathname } = useLocation();
  const desktop = useMediaQuery("(min-width: 1024px)");
  const onToday = pathname === "/";
  const working = ask.busy;

  return (
    <>
      {/* Phone ask bar, above the dock. */}
      <button
        type="button"
        onClick={() => ask.openSheet()}
        className="press fixed inset-x-3 bottom-[calc(5.75rem+env(safe-area-inset-bottom))] z-20 mx-auto flex min-h-13 max-w-lg items-center gap-2.5 rounded-[16px] border-2 border-edge bg-sheet px-3 text-left shadow-hard lg:hidden"
      >
        <span aria-hidden className="relative inline-flex size-8 shrink-0 -rotate-6 items-center justify-center rounded-[9px] border-2 border-edge bg-hero">
          <span className={cn("size-2.5 rounded-full bg-magenta", working && "pulse-dot")} />
        </span>
        <span className="min-w-0 flex-1 truncate font-semibold text-muted">
          {working ? "Dayline is working…" : "Ask Dayline: “Get me lunch and print this”"}
        </span>
        <Mic className="size-5 shrink-0 text-muted" aria-hidden />
      </button>

      {/* Laptop: floating button off Today (Today has the panel in its side column). */}
      {!onToday ? (
        <button
          type="button"
          onClick={() => ask.openSheet()}
          className="press fixed right-6 bottom-6 z-20 hidden min-h-13 items-center gap-2 rounded-[16px] border-2 border-edge bg-ink px-4 font-display text-17 font-extrabold text-paper shadow-hard-magenta lg:inline-flex"
        >
          <Sparkles className="size-5" aria-hidden /> Ask Dayline
        </button>
      ) : null}

      <Dialog.Root open={ask.sheetOpen && (!desktop || !onToday)} onOpenChange={(open) => (open ? ask.openSheet() : ask.closeSheet())}>
        <Dialog.Portal>
          <Dialog.Overlay className="fixed inset-0 z-40 bg-[rgb(10_11_38/0.55)]" />
          <Dialog.Content
            className={cn(
              "fixed inset-x-0 top-[max(12px,env(safe-area-inset-top))] bottom-0 z-50 flex flex-col rounded-t-[22px] border-t-2 border-edge bg-sheet p-4 pb-[max(16px,env(safe-area-inset-bottom))]",
              "lg:inset-y-4 lg:right-4 lg:left-auto lg:w-[440px] lg:rounded-[20px] lg:border-2 lg:shadow-hard-lg",
            )}
            aria-describedby={undefined}
          >
            <Dialog.Title className="sr-only">Ask Dayline</Dialog.Title>
            <Dialog.Close className="press absolute top-3 right-3 z-10 inline-flex size-11 items-center justify-center rounded-button border-2 border-edge bg-sheet shadow-hard-sm">
              <X className="size-5" aria-hidden />
              <span className="sr-only">Close</span>
            </Dialog.Close>
            <AskPanel className="min-h-0 flex-1 [&>div:first-child]:pr-14" onLeave={ask.closeSheet} autoFocus={desktop} />
          </Dialog.Content>
        </Dialog.Portal>
      </Dialog.Root>
    </>
  );
}
