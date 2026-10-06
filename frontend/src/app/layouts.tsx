import { NavLink, Outlet } from "react-router";
import { Brain, CalendarClock, ChartNoAxesColumn, LogOut, Printer, User, UtensilsCrossed, type LucideIcon } from "lucide-react";
import { DemoBanner } from "@/components/DemoBanner";
import { LiveBadge } from "@/components/LiveBadge";
import { Notices } from "@/components/Notices";
import { Button } from "@/components/ui/button";
import { AskDock } from "@/features/ask/AskDock";
import { AskProvider } from "@/features/ask/AskContext";
import { APP_NAME } from "@/lib/api";
import { useLogout, useMe } from "@/lib/auth";
import { cn } from "@/lib/utils";

type NavItem = { to: string; label: string; icon: LucideIcon };

const STUDENT_NAV: NavItem[] = [
  { to: "/", label: "Today", icon: CalendarClock },
  { to: "/canteen", label: "Canteen", icon: UtensilsCrossed },
  { to: "/print", label: "Print", icon: Printer },
  { to: "/attendance", label: "Attendance", icon: ChartNoAxesColumn },
  { to: "/memory", label: "Memory", icon: Brain },
  { to: "/profile", label: "Profile", icon: User },
];
// The phone dock has room for four; Profile (and Memory, from Profile) is reached from the avatar on Today.
const DOCK_NAV = STUDENT_NAV.filter((item) => item.to !== "/profile" && item.to !== "/memory");

/** Logo: a tilted ink tile with the day line and its "now" dot, plus the name. */
export function Brand({ className, onDark = false }: { className?: string; onDark?: boolean }) {
  return (
    <span className={cn("inline-flex items-center gap-2.5 font-display text-21 font-extrabold tracking-tight", className)}>
      <span
        aria-hidden
        className={cn(
          "relative inline-flex size-9 -rotate-6 items-center justify-center rounded-[10px] border-2",
          onDark ? "border-hero-text bg-hero" : "border-edge bg-hero shadow-hard-sm",
        )}
      >
        <span className="absolute inset-y-1.5 left-1/2 w-1 -translate-x-1/2 rounded-full bg-magenta" />
        <span className="relative size-3 rounded-full border-2 border-hero bg-magenta" />
      </span>
      {APP_NAME}
    </span>
  );
}

/** Student shell: floating dock (with the ask bar above it) on phones, ink rail from 1024 px. */
export function StudentLayout() {
  const me = useMe().data;
  return (
    <AskProvider>
      <div className="min-h-dvh">
        <DemoBanner />
        <Notices />
        <div className="lg:flex">
          <aside className="hidden text-hero-text lg:sticky lg:top-0 lg:flex lg:h-dvh lg:w-64 lg:shrink-0 lg:flex-col lg:bg-hero lg:px-4 lg:py-6">
            <Brand onDark className="px-2 text-28" />
            <nav aria-label="Main" className="mt-10 flex flex-col gap-2">
              {STUDENT_NAV.map((item) => (
                <NavLink
                  key={item.to}
                  to={item.to}
                  end={item.to === "/"}
                  className={({ isActive }) =>
                    cn(
                      "press flex min-h-12 items-center gap-3 rounded-[12px] border-2 border-transparent px-3 text-17 font-bold text-hero-muted hover:border-hero-muted hover:text-hero-text",
                      isActive && "border-hero-text bg-hero-text text-hero shadow-[4px_4px_0_0_var(--magenta)] hover:text-hero",
                    )
                  }
                >
                  <item.icon className="size-5" aria-hidden />
                  {item.label}
                </NavLink>
              ))}
            </nav>
            <div className="mt-auto rounded-[14px] border-2 border-hero-muted/40 p-3">
              <p className="truncate font-bold">{me?.name}</p>
              <p className="text-13 text-hero-muted">{me?.kind === "student" ? me.roll_no : null}</p>
              <LiveBadge className="mt-2" onDark />
            </div>
          </aside>
          <main className="mx-auto w-full max-w-6xl min-w-0 px-4 pt-4 pb-52 sm:px-6 lg:px-10 lg:pt-8 lg:pb-12">
            <Outlet />
          </main>
        </div>
        <nav aria-label="Main" className="fixed inset-x-3 bottom-3 z-20 pb-[env(safe-area-inset-bottom)] lg:hidden">
          <ul className="mx-auto flex max-w-lg gap-1 rounded-[20px] border-2 border-edge bg-hero p-1.5 shadow-hard">
            {DOCK_NAV.map((item) => (
              <li key={item.to} className="flex-1">
                <NavLink
                  to={item.to}
                  end={item.to === "/"}
                  className={({ isActive }) =>
                    cn(
                      "flex min-h-14 flex-col items-center justify-center gap-0.5 rounded-[14px] text-13 font-bold text-hero-muted",
                      isActive && "bg-hero-text text-hero",
                    )
                  }
                >
                  <item.icon className="size-5" aria-hidden />
                  {item.label}
                </NavLink>
              </li>
            ))}
          </ul>
        </nav>
        <AskDock />
      </div>
    </AskProvider>
  );
}

/** Staff and admin shell: an ink top bar with the account, live status and log out. */
export function StaffLayout() {
  const me = useMe().data;
  const logout = useLogout();
  return (
    <div className="min-h-dvh">
      <DemoBanner />
      <header className="bg-hero text-hero-text">
        <div className="mx-auto flex max-w-7xl items-center justify-between gap-3 px-4 py-3 sm:px-6">
          <Brand onDark />
          <div className="flex min-w-0 items-center gap-3">
            <LiveBadge onDark className="hidden sm:inline-flex" />
            <span className="hidden truncate font-semibold text-hero-muted md:inline">{me?.name}</span>
            <Button variant="hero" onClick={() => logout.mutate()} disabled={logout.isPending}>
              <LogOut aria-hidden /> Log out
            </Button>
          </div>
        </div>
      </header>
      <main className="mx-auto w-full max-w-7xl px-4 py-6 sm:px-6">
        <Outlet />
      </main>
    </div>
  );
}
