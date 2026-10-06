import { cn } from "@/lib/utils";

/** Placeholder block shaped like the content that will replace it. */
export function Skeleton({ className }: { className?: string }) {
  return (
    <div
      aria-hidden
      className={cn("animate-pulse rounded-surface border-2 border-dashed border-line bg-tint motion-reduce:animate-none", className)}
    />
  );
}
