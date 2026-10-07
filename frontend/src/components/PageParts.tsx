import type { ReactNode } from "react";
import { ChevronDown, type LucideIcon } from "lucide-react";
import { cn } from "@/lib/utils";

/** A compact page heading (about 96 px tall): coloured band, icon, title and one line. */
export function PageHeading({ title, subtitle, icon: Icon, className }: {
  title: string;
  subtitle: string;
  icon: LucideIcon;
  /** Background and text colour, e.g. "bg-yellow text-on-fill". */
  className: string;
}) {
  return (
    <header className={cn("flex min-h-24 items-center gap-4 rounded-[20px] border-2 border-edge px-5 py-4 shadow-hard", className)}>
      <span className="flex size-12 shrink-0 items-center justify-center rounded-[12px] border-2 border-edge bg-sheet text-ink">
        <Icon className="size-6" aria-hidden />
      </span>
      <div className="min-w-0">
        <h1 className="font-display text-28 leading-tight font-extrabold">{title}</h1>
        <p className="text-15 font-semibold">{subtitle}</p>
      </div>
    </header>
  );
}

/** A collapsed list of finished tickets, e.g. "Earlier today (2)". */
export function Collapsed({ title, count, children }: { title: string; count: number; children: ReactNode }) {
  if (count === 0) return null;
  return (
    <details className="group rounded-[16px] border-2 border-line bg-sheet">
      <summary className="flex min-h-12 cursor-pointer list-none items-center justify-between gap-3 px-4 font-display text-17 font-extrabold [&::-webkit-details-marker]:hidden">
        <span>
          {title} <span className="text-muted">({count})</span>
        </span>
        <ChevronDown className="size-5 shrink-0 transition-transform group-open:rotate-180" aria-hidden />
      </summary>
      <div className="space-y-4 px-3 pt-1 pb-4">{children}</div>
    </details>
  );
}
