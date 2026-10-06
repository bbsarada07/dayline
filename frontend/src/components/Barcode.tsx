import { canEncode, encodeCode128B } from "@/lib/code128";
import { cn } from "@/lib/utils";

const QUIET_MODULES = 10;

/**
 * A scannable Code 128 barcode. Always black bars on a white plate, in both themes:
 * scanners need dark-on-light with a quiet zone either side.
 */
export function Barcode({ value, className, height = 64 }: { value: string; className?: string; height?: number }) {
  if (!canEncode(value)) return null;
  const modules = encodeCode128B(value);
  const width = modules.length + QUIET_MODULES * 2;
  const bars: { x: number; w: number }[] = [];
  for (let i = 0; i < modules.length; i++) {
    if (modules[i] !== "1") continue;
    let run = 1;
    while (modules[i + run] === "1") run++;
    bars.push({ x: QUIET_MODULES + i, w: run });
    i += run - 1;
  }
  return (
    <figure className={cn("rounded-[10px] bg-white px-2 pt-2 pb-1 text-center text-[#14163a]", className)}>
      <svg
        role="img"
        aria-label={`Barcode ${value}`}
        viewBox={`0 0 ${width} ${height}`}
        preserveAspectRatio="none"
        shapeRendering="crispEdges"
        className="block h-16 w-full"
      >
        <rect width={width} height={height} fill="#ffffff" />
        {bars.map((bar) => (
          <rect key={bar.x} x={bar.x} y={0} width={bar.w} height={height} fill="#000000" />
        ))}
      </svg>
      <figcaption className="mt-0.5 font-display text-15 font-extrabold tracking-[0.2em] tabular-nums">{value}</figcaption>
    </figure>
  );
}
