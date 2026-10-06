import { useState } from "react";
import { LazyMotion, domAnimation, m, useReducedMotion } from "framer-motion";
import { cn } from "@/lib/utils";

const TONE = {
  success: "border-stamp-text text-stamp-text",
  neutral: "border-ink text-ink",
  alert: "border-alert-text text-alert-text",
} as const;

/**
 * True when `value` is `target` now but wasn't when the component mounted, i.e. it
 * changed while on screen. Pure (no refs in render), so it's StrictMode-safe.
 */
export function useBecameWhileShown<T>(value: T, target: T): boolean {
  const [atMount] = useState(value);
  return value === target && atMount !== target;
}

/**
 * A rubber stamp on a pass ("Collected", "Ready"). With `press`, it presses onto the
 * pass at an angle when it appears (spec 9.1 motion 3); instant with reduced motion.
 */
export function Stamp({ text, tone, press = false }: { text: string; tone: keyof typeof TONE; press?: boolean }) {
  const reduce = useReducedMotion();
  const className = cn(
    "inline-block -rotate-6 rounded-[6px] border-[3px] px-2 py-0.5 font-display text-15 leading-none font-extrabold whitespace-nowrap",
    TONE[tone],
  );
  if (!press || reduce) return <span className={className}>{text}</span>;
  return (
    <LazyMotion features={domAnimation} strict>
      <m.span
        className={className}
        initial={{ scale: 2.4, rotate: -24, opacity: 0 }}
        animate={{ scale: 1, rotate: -6, opacity: 1 }}
        transition={{ type: "spring", duration: 0.32, bounce: 0.35 }}
      >
        {text}
      </m.span>
    </LazyMotion>
  );
}
