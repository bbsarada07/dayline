import { useState, type FormEvent } from "react";
import { Navigate, useNavigate } from "react-router";
import { useQuery } from "@tanstack/react-query";
import { ArrowRight, CalendarClock, ChartNoAxesColumn, CircleAlert, ExternalLink, Printer, Users } from "lucide-react";
import { Brand } from "@/app/layouts";
import { DemoBanner } from "@/components/DemoBanner";
import { Button, buttonVariants } from "@/components/ui/button";
import { Input, Label } from "@/components/ui/input";
import { Sheet } from "@/components/ui/sheet";
import { api, errorMessage } from "@/lib/api";
import { homeFor, useLogin, useMe } from "@/lib/auth";
import { secondLoginUrl } from "@/lib/session";
import type { DemoAccounts } from "@/lib/types";
import { cn } from "@/lib/utils";

type Kind = "student" | "staff";

const ROLE_LABEL = { canteen: "Canteen staff", print: "Print shop staff", admin: "Admin" } as const;

/** What the app does, as three tilted tickets. Feature names only, no sample data. */
function FeatureTickets() {
  const tickets = [
    { icon: CalendarClock, title: "Timetable", line: "Know what's next", tone: "bg-magenta text-white", tilt: "-rotate-6" },
    { icon: Printer, title: "Print", line: "Ready before class", tone: "bg-cyan text-on-fill", tilt: "rotate-3" },
    { icon: ChartNoAxesColumn, title: "Attendance", line: "Know what you can miss", tone: "bg-hero-text text-hero", tilt: "-rotate-2" },
  ];
  return (
    <ul aria-label="What you can do" className="flex flex-wrap gap-3">
      {tickets.map(({ icon: Icon, title, line, tone, tilt }) => (
        <li
          key={title}
          className={cn("flex items-center gap-2.5 rounded-[14px] border-2 border-hero-text px-3 py-2 shadow-[4px_4px_0_0_#000]", tone, tilt)}
        >
          <Icon className="size-5 shrink-0" aria-hidden />
          <span className="leading-tight">
            <span className="block font-display text-17 font-extrabold">{title}</span>
            <span className="block text-13 font-semibold opacity-90">{line}</span>
          </span>
        </li>
      ))}
    </ul>
  );
}

export function LoginPage() {
  const me = useMe();
  const navigate = useNavigate();
  const login = useLogin();
  const [kind, setKind] = useState<Kind>("student");
  const [username, setUsername] = useState("");
  const [pin, setPin] = useState("");
  const [drawerOpen, setDrawerOpen] = useState(false);
  const demo = useQuery({ queryKey: ["demo-accounts"], queryFn: () => api<DemoAccounts>("/auth/demo-accounts") });
  const second = secondLoginUrl();

  if (me.data) return <Navigate to={homeFor(me.data.role)} replace />;

  const submit = (body: { kind: Kind; username: string; pin: string }) =>
    login.mutate(body, { onSuccess: (user) => navigate(homeFor(user.role), { replace: true }) });

  const onSubmit = (event: FormEvent) => {
    event.preventDefault();
    submit({ kind, username, pin });
  };

  const logInAs = (accountKind: Kind, accountName: string) => {
    if (!demo.data?.pin) return;
    setKind(accountKind);
    setUsername(accountName);
    setPin(demo.data.pin);
    setDrawerOpen(false);
    submit({ kind: accountKind, username: accountName, pin: demo.data.pin });
  };

  const isStudent = kind === "student";

  return (
    <div className="min-h-dvh">
      <DemoBanner />
      <div className="lg:grid lg:min-h-[calc(100dvh-2rem)] lg:grid-cols-[1.1fr_1fr]">
        {/* Poster */}
        <section className="relative overflow-hidden rounded-b-[28px] bg-hero px-5 pt-6 pb-16 text-hero-text lg:rounded-none lg:px-14 lg:py-14">
          <div aria-hidden className="halftone pointer-events-none absolute -top-10 -right-16 size-72 rounded-full text-magenta" />
          <div aria-hidden className="halftone pointer-events-none absolute -bottom-24 -left-16 size-80 rounded-full text-cyan lg:size-[28rem]" />
          <div className="relative">
            <Brand onDark />
            <h1 className="mt-8 font-display text-[44px] leading-[0.95] font-extrabold tracking-tight sm:text-64 lg:mt-20 lg:text-[88px]">
              Your day,
              <br />
              <span className="misprint">on one line.</span>
            </h1>
            <p className="mt-4 max-w-md text-17 text-hero-muted lg:text-21">
              Classes, printouts and attendance for your college, sorted around your timetable.
            </p>
            <div className="mt-7 lg:mt-12">
              <FeatureTickets />
            </div>
          </div>
        </section>

        {/* Form */}
        <section className="relative -mt-8 px-4 pb-10 lg:mt-0 lg:flex lg:items-center lg:justify-center lg:px-10">
          <div className="mx-auto w-full max-w-md">
            <form
              onSubmit={onSubmit}
              className="space-y-5 rounded-[20px] border-2 border-edge bg-sheet p-5 shadow-hard-lg sm:p-6"
              noValidate
            >
              <h2 className="font-display text-28 font-extrabold">Log in</h2>
              <div role="radiogroup" aria-label="I am" className="grid grid-cols-2 gap-1 rounded-[12px] border-2 border-edge bg-tint p-1">
                {(["student", "staff"] as const).map((option) => (
                  <button
                    key={option}
                    type="button"
                    role="radio"
                    aria-checked={kind === option}
                    onClick={() => setKind(option)}
                    className={cn(
                      "min-h-11 rounded-[8px] font-bold text-muted",
                      kind === option && "bg-ink text-paper",
                    )}
                  >
                    {option === "student" ? "Student" : "Staff"}
                  </button>
                ))}
              </div>

              <div className="space-y-2">
                <Label htmlFor="username">{isStudent ? "Roll number" : "Username"}</Label>
                <Input
                  id="username"
                  value={username}
                  onChange={(e) => setUsername(e.target.value)}
                  autoComplete="username"
                  autoCapitalize={isStudent ? "characters" : "none"}
                  placeholder={isStudent ? "e.g. 22CS001" : "e.g. canteen"}
                  required
                />
              </div>

              <div className="space-y-2">
                <Label htmlFor="pin">4-digit PIN</Label>
                <Input
                  id="pin"
                  type="password"
                  inputMode="numeric"
                  autoComplete="current-password"
                  maxLength={4}
                  pattern="\d{4}"
                  value={pin}
                  onChange={(e) => setPin(e.target.value.replace(/\D/g, "").slice(0, 4))}
                  className="tracking-[0.5em]"
                  required
                />
              </div>

              {login.isError ? (
                <p role="alert" className="flex items-start gap-2 font-semibold text-alert-text">
                  <CircleAlert className="mt-0.5 size-5 shrink-0" aria-hidden />
                  {errorMessage(login.error)}
                </p>
              ) : null}

              <Button type="submit" size="lg" className="w-full" disabled={login.isPending || !username.trim() || pin.length !== 4}>
                {login.isPending ? "Logging in…" : "Log in"} <ArrowRight aria-hidden />
              </Button>
            </form>

            {demo.data?.enabled ? (
              <TryTheDemo demo={demo.data} disabled={login.isPending} onPick={logInAs} onMore={() => setDrawerOpen(true)} />
            ) : null}
          </div>
        </section>
      </div>

      {demo.data?.enabled ? (
        <Sheet
          open={drawerOpen}
          onOpenChange={setDrawerOpen}
          title="Demo accounts"
          description={demo.data.pin ? `Seeded placeholder accounts. Every one uses PIN ${demo.data.pin}.` : "Seeded placeholder accounts."}
        >
          <AccountList
            title="Students"
            items={demo.data.students.map((s) => ({ key: s.roll_no, name: s.name, meta: s.roll_no, onPick: () => logInAs("student", s.roll_no) }))}
            disabled={!demo.data.pin || login.isPending}
          />
          <AccountList
            title="Staff"
            items={demo.data.staff.map((s) => ({ key: s.username, name: s.name, meta: ROLE_LABEL[s.role], onPick: () => logInAs("staff", s.username) }))}
            disabled={!demo.data.pin || login.isPending}
          />
          <div className="mt-5 rounded-surface border-2 border-dashed border-edge p-4">
            <p className="font-bold">Two accounts on one computer?</p>
            <p className="mt-1 text-13 text-muted">
              A browser keeps one login at a time.{" "}
              {second ? "Open the second account at this computer's other address; it keeps its own login." : "Use a private window for the second account."}
            </p>
            {second ? (
              <a href={second} target="_blank" rel="noopener" className={buttonVariants({ variant: "secondary", className: "mt-3" })}>
                <ExternalLink aria-hidden /> Open a second login
              </a>
            ) : null}
          </div>
        </Sheet>
      ) : null}
    </div>
  );
}

const ROLE_HINT = {
  student: "Ask Dayline for lunch and a printout in one sentence, or try the Omi simulator from Profile.",
  canteen: "Watch orders arrive live, move tickets along, and hand food over with a scan.",
  print: "Work through the print queue by deadline and hand printouts over with a scan.",
} as const;

/** Demo deployments: one tap into each role, with what to try there. */
function TryTheDemo({ demo, disabled, onPick, onMore }: {
  demo: DemoAccounts;
  disabled: boolean;
  onPick: (kind: Kind, username: string) => void;
  onMore: () => void;
}) {
  const student = demo.students[0];
  const canteen = demo.staff.find((s) => s.role === "canteen");
  const print = demo.staff.find((s) => s.role === "print");
  const picks = [
    student && { key: "student", kind: "student" as const, username: student.roll_no, name: student.name, role: "Student", hint: ROLE_HINT.student, tone: "bg-magenta text-white" },
    canteen && { key: "canteen", kind: "staff" as const, username: canteen.username, name: canteen.name, role: "Canteen staff", hint: ROLE_HINT.canteen, tone: "bg-yellow text-on-fill" },
    print && { key: "print", kind: "staff" as const, username: print.username, name: print.name, role: "Print shop", hint: ROLE_HINT.print, tone: "bg-cyan text-on-fill" },
  ].filter(Boolean) as { key: string; kind: Kind; username: string; name: string; role: string; hint: string; tone: string }[];

  return (
    <section aria-labelledby="try-demo" className="mt-6">
      <h2 id="try-demo" className="font-display text-21 font-extrabold">Try the demo</h2>
      <p className="text-13 font-semibold text-muted">
        One tap logs you in{demo.pin ? ` (every demo account uses PIN ${demo.pin})` : ""}.
      </p>
      <ul className="mt-3 grid gap-3">
        {picks.map((pick) => (
          <li key={pick.key}>
            <button
              type="button"
              disabled={disabled || !demo.pin}
              onClick={() => onPick(pick.kind, pick.username)}
              className="press flex w-full items-start gap-3 rounded-[14px] border-2 border-edge bg-sheet p-3 text-left shadow-hard-sm disabled:opacity-60"
            >
              <span className={cn("mt-0.5 shrink-0 rounded-[8px] border-2 border-edge px-2 py-0.5 text-13 font-extrabold", pick.tone)}>
                {pick.role}
              </span>
              <span className="min-w-0">
                <span className="block font-extrabold">Log in as {pick.name}</span>
                <span className="block text-13 font-semibold text-muted">{pick.hint}</span>
              </span>
            </button>
          </li>
        ))}
      </ul>
      <div className="mt-3 flex justify-center">
        <Button variant="ghost" onClick={onMore}>
          <Users aria-hidden /> All demo accounts
        </Button>
      </div>
    </section>
  );
}

function AccountList({ title, items, disabled }: {
  title: string;
  items: { key: string; name: string; meta: string; onPick: () => void }[];
  disabled: boolean;
}) {
  return (
    <section className="mt-2 first:mt-0">
      <h3 className="mt-3 text-17 font-extrabold">{title}</h3>
      <ul className="mt-2 grid gap-2">
        {items.map((item) => (
          <li key={item.key}>
            <button
              type="button"
              className="press flex min-h-12 w-full items-center justify-between gap-3 rounded-[12px] border-2 border-edge bg-sheet px-3 py-2 text-left shadow-hard-sm disabled:opacity-60"
              onClick={item.onPick}
              disabled={disabled}
            >
              <span className="min-w-0 truncate font-bold">Log in as {item.name}</span>
              <span className="shrink-0 text-13 text-muted tabular-nums">{item.meta}</span>
            </button>
          </li>
        ))}
      </ul>
    </section>
  );
}
