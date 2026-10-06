import { CreditCard, LogOut, Monitor, Moon, Sun } from "lucide-react";
import { Brand } from "@/app/layouts";
import { Barcode } from "@/components/Barcode";
import { Button } from "@/components/ui/button";
import { useLogout, useMe } from "@/lib/auth";
import { useTheme, type ThemePref } from "@/lib/theme";
import { cn } from "@/lib/utils";

const THEMES: { value: ThemePref; label: string; icon: typeof Sun }[] = [
  { value: "light", label: "Light", icon: Sun },
  { value: "dark", label: "Dark", icon: Moon },
  { value: "system", label: "Match device", icon: Monitor },
];

function initials(name: string) {
  return name
    .split(" ")
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase())
    .join("");
}

export function ProfilePage() {
  const me = useMe().data;
  const logout = useLogout();
  const { pref, choose } = useTheme();
  if (!me || me.kind !== "student") return null;

  return (
    <div className="mx-auto max-w-xl space-y-6">
      {/* The student's ID card. */}
      <section aria-label="Your ID" className="-rotate-1 overflow-hidden rounded-[22px] border-2 border-edge bg-sheet shadow-hard-lg">
        <div className="relative flex items-center justify-between overflow-hidden bg-hero px-5 py-3 text-hero-text">
          <div aria-hidden className="halftone pointer-events-none absolute -top-6 right-10 size-24 rounded-full text-magenta" />
          <Brand onDark className="relative text-17" />
          <span className="relative text-13 font-bold text-hero-muted">Student ID</span>
        </div>
        <div className="flex items-center gap-4 p-5">
          <span
            aria-hidden
            className="flex size-20 shrink-0 rotate-3 items-center justify-center rounded-[16px] border-2 border-edge bg-magenta font-display text-28 font-extrabold text-white shadow-hard-sm"
          >
            {initials(me.name)}
          </span>
          <div className="min-w-0">
            <h1 className="truncate font-display text-28 leading-tight font-extrabold">{me.name}</h1>
            <p className="font-display text-21 font-extrabold tabular-nums">{me.roll_no}</p>
            <p className="text-13 font-semibold text-muted">
              {me.branch} · Year {me.year} · {me.section}
            </p>
          </div>
        </div>
        <div className="border-t-2 border-dashed border-line px-5 py-4">
          <p className="flex items-start gap-3 font-semibold">
            <CreditCard className="mt-0.5 size-5 shrink-0" aria-hidden />
            {me.card_uid
              ? "Scan this at the canteen counter or print desk to collect what's ready."
              : "No card linked yet. Ask the admin office to enrol your card."}
          </p>
          {me.card_uid ? <Barcode value={me.card_uid} className="mt-3 border-2 border-edge" /> : null}
        </div>
      </section>

      <section className="rounded-[18px] border-2 border-edge bg-sheet p-4 shadow-hard">
        <h2 id="theme-label" className="font-display text-21 font-extrabold">
          Theme
        </h2>
        <div role="radiogroup" aria-labelledby="theme-label" className="mt-3 grid grid-cols-3 gap-2">
          {THEMES.map(({ value, label, icon: Icon }) => {
            const on = pref === value;
            return (
              <button
                key={value}
                type="button"
                role="radio"
                aria-checked={on}
                onClick={() => choose(value)}
                className={cn(
                  "press flex min-h-16 flex-col items-center justify-center gap-1 rounded-[12px] border-2 border-edge px-2 text-13 font-bold",
                  on ? "bg-ink text-paper shadow-hard-sm" : "bg-sheet",
                )}
              >
                <Icon className="size-5" aria-hidden />
                {label}
              </button>
            );
          })}
        </div>
      </section>

      <Button variant="secondary" size="lg" className="w-full" onClick={() => logout.mutate()} disabled={logout.isPending}>
        <LogOut aria-hidden /> Log out
      </Button>
    </div>
  );
}
