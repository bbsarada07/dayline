import { clsx, type ClassValue } from "clsx";
import { extendTailwindMerge } from "tailwind-merge";

// Teach tailwind-merge our custom type scale so text-15 and text-ink don't clash.
const twMerge = extendTailwindMerge({
  extend: { classGroups: { "font-size": [{ text: ["13", "15", "17", "21", "28", "40", "64"] }] } },
});

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}
