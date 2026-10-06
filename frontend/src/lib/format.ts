/** Date and time formatting. Everything is shown in college time (Asia/Kolkata). */

const TZ = "Asia/Kolkata";

const timeFmt = new Intl.DateTimeFormat("en-IN", { timeZone: TZ, hour: "numeric", minute: "2-digit", hour12: true });
const dayFmt = new Intl.DateTimeFormat("en-GB", { timeZone: TZ, weekday: "short", day: "numeric", month: "short" });
const weekdayFmt = new Intl.DateTimeFormat("en-GB", { timeZone: TZ, weekday: "short" });
const hourFmt = new Intl.DateTimeFormat("en-GB", { timeZone: TZ, hour: "numeric", hourCycle: "h23" });
const partsFmt = new Intl.DateTimeFormat("en-CA", {
  timeZone: TZ, year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hourCycle: "h23",
});

type DateLike = Date | string;
const toDate = (value: DateLike) => (typeof value === "string" ? new Date(value) : value);

/** "9:00" (no am/pm), for the day line's time column. */
export function clockTime(value: DateLike): string {
  return timeFmt.formatToParts(toDate(value)).filter((p) => p.type === "hour" || p.type === "minute" || p.type === "literal")
    .map((p) => p.value).join("").trim();
}

/** "2:00 pm". */
export function timeOfDay(value: DateLike): string {
  return timeFmt.format(toDate(value)).replace(/\s?([ap])\.?m\.?/i, " $1m").toLowerCase();
}

/** "Mon 5 Oct". */
export function dayDate(value: DateLike): string {
  return dayFmt.format(toDate(value)).replace(",", "");
}

/** "Mon 12:20", used by the demo time banner. */
export function weekdayTime(value: DateLike): string {
  return `${weekdayFmt.format(toDate(value))} ${clockTime(value)}`;
}

/** Hour of day (0–23) in college time. */
export function hourOfDay(value: DateLike): number {
  return Number(hourFmt.format(toDate(value)));
}

/** Local date and time strings for <input type="date"> and <input type="time">. */
export function localInputs(value: DateLike): { date: string; time: string } {
  const parts = Object.fromEntries(partsFmt.formatToParts(toDate(value)).map((p) => [p.type, p.value]));
  return { date: `${parts.year}-${parts.month}-${parts.day}`, time: `${parts.hour}:${parts.minute}` };
}

/** "50 min", "1 h", "1 h 20 min". */
export function duration(minutes: number): string {
  const m = Math.max(0, Math.round(minutes));
  if (m < 60) return `${m} min`;
  const h = Math.floor(m / 60);
  const rest = m % 60;
  return rest ? `${h} h ${rest} min` : `${h} h`;
}

export function minutesBetween(from: DateLike, to: DateLike): number {
  return (toDate(to).getTime() - toDate(from).getTime()) / 60_000;
}

export function greeting(now: DateLike): string {
  const hour = hourOfDay(now);
  if (hour < 12) return "Good morning";
  if (hour < 17) return "Good afternoon";
  return "Good evening";
}

/** "70%" or "69.4%". */
export function percent(value: number): string {
  return `${Number.isInteger(value) ? value : value.toFixed(1)}%`;
}

export function plural(n: number, one: string, many = `${one}s`): string {
  return `${n} ${n === 1 ? one : many}`;
}

/** Paise to "₹24" or "₹24.50". */
export function money(paise: number): string {
  const rupees = paise / 100;
  return `₹${Number.isInteger(rupees) ? rupees : rupees.toFixed(2)}`;
}

/** "in 12 min", "now", "8 min late". */
export function timeLeft(now: Date, until: DateLike): string {
  const minutes = Math.round(minutesBetween(now, until));
  if (minutes === 0) return "now";
  return minutes > 0 ? `in ${duration(minutes)}` : `${duration(-minutes)} late`;
}

/** True when `value` falls on the same college-time date as `now`. */
export function sameDay(value: DateLike, now: DateLike): boolean {
  return localInputs(value).date === localInputs(now).date;
}
