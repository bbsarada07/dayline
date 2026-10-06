import { useLinkStatus } from "@/lib/realtime";
import { cn } from "@/lib/utils";

const LABEL = { live: "Live", connecting: "Connecting…", offline: "Reconnecting…" } as const;

/** Realtime connection state, in words (never colour alone). */
export function LiveBadge({ className, onDark = false }: { className?: string; onDark?: boolean }) {
  const status = useLinkStatus();
  return (
    <span
      role="status"
      className={cn(
        "inline-flex items-center gap-2 rounded-full border-2 px-2.5 py-0.5 text-13 font-bold",
        onDark ? "border-hero-muted/50 text-hero-text" : "border-edge text-ink",
        className,
      )}
    >
      <span
        aria-hidden
        className={cn(
          "size-2.5 rounded-full",
          status === "live" ? "pulse-dot bg-stamp" : status === "offline" ? "bg-alert" : "bg-hero-muted",
        )}
      />
      {LABEL[status]}
    </span>
  );
}
