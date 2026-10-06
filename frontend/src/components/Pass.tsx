import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

type PassProps = {
  /** Agent colour: cyan = print, yellow = canteen. Fill only, always with ink text. */
  tone: "cyan" | "yellow";
  header: ReactNode;
  children: ReactNode;
  className?: string;
};

/** A paper-style pass: coloured header, notches, dashed tear line, details below. */
export function Pass({ tone, header, children, className }: PassProps) {
  return (
    // The hard shadow lives on a wrapper so it follows the notched (masked) shape.
    <div className={cn("drop-hard", className)}>
      <div className="ticket overflow-hidden rounded-[16px] border-2 border-edge bg-sheet">
        <div
          className={cn(
            "flex h-11 items-center justify-between gap-3 px-4 font-display text-17 font-extrabold text-on-fill",
            tone === "cyan" ? "bg-cyan" : "bg-yellow",
          )}
        >
          {header}
        </div>
        <div aria-hidden className="mx-3 border-t-2 border-dashed border-edge/60" />
        <div className="px-4 pt-2.5 pb-3">{children}</div>
      </div>
    </div>
  );
}
