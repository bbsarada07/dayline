import { Clock } from "lucide-react";
import { useClock } from "@/lib/clock";
import { weekdayTime } from "@/lib/format";

/** Shown on every screen while an admin has set demo time. */
export function DemoBanner() {
  const { now, demo } = useClock();
  if (!demo || !now) return null;
  return (
    <div
      role="status"
      className="sticky top-0 z-30 flex min-h-8 items-center justify-center gap-2 border-b-2 border-edge bg-magenta px-4 py-1 text-13 font-bold text-white"
    >
      <Clock className="size-4" aria-hidden />
      Demo time: {weekdayTime(now)}
    </div>
  );
}
