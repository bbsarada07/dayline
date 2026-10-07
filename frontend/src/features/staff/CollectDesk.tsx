import { useEffect, useRef, useState, type FormEvent } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { CircleAlert, CircleCheck, Hourglass, ScanBarcode, Volume2, VolumeX, type LucideIcon } from "lucide-react";
import { Button } from "@/components/ui/button";
import { api, errorMessage } from "@/lib/api";
import { timeOfDay } from "@/lib/format";
import { subscribe } from "@/lib/realtime";
import type { CollectCandidates, CollectResult, CollectStatus } from "@/lib/types";
import { cn } from "@/lib/utils";

const BANNER_MS = 4_000;
const SOUND_KEY = "collect-sound";

type Look = { title: string; icon: LucideIcon; className: string };

const LOOK: Record<Exclude<CollectStatus, "ignored">, Look> = {
  collected: { title: "Collected", icon: CircleCheck, className: "bg-stamp text-white" },
  not_ready: { title: "Not ready yet", icon: Hourglass, className: "bg-hero text-hero-text" },
  nothing_to_collect: { title: "Nothing to collect", icon: CircleAlert, className: "bg-alert text-white" },
  unknown_card: { title: "Unknown card", icon: CircleAlert, className: "bg-alert text-white" },
};

function explain(result: CollectResult, station: "canteen" | "print"): string {
  if (result.status === "unknown_card") return "This barcode isn't on any student's ID card. Check the card and scan again.";
  if (result.status === "nothing_to_collect") {
    return station === "canteen" ? "No food orders for this student today." : "No printouts waiting for this student.";
  }
  return result.lines.join(" · ");
}

// --- sounds: generated, so nothing to download --------------------------------

let audio: AudioContext | null = null;

function beep(frequency: number, start: number, length: number, type: OscillatorType = "square") {
  if (!audio) return;
  const osc = audio.createOscillator();
  const gain = audio.createGain();
  osc.type = type;
  osc.frequency.value = frequency;
  gain.gain.setValueAtTime(0.0001, audio.currentTime + start);
  gain.gain.exponentialRampToValueAtTime(0.18, audio.currentTime + start + 0.01);
  gain.gain.exponentialRampToValueAtTime(0.0001, audio.currentTime + start + length);
  osc.connect(gain).connect(audio.destination);
  osc.start(audio.currentTime + start);
  osc.stop(audio.currentTime + start + length + 0.02);
}

/** Rising double beep for success, two short beeps for "not ready", a low buzz for failure. */
function playFor(status: CollectStatus) {
  try {
    audio ??= new AudioContext();
    void audio.resume();
  } catch {
    return;
  }
  if (status === "collected") {
    beep(880, 0, 0.09, "sine");
    beep(1320, 0.11, 0.14, "sine");
  } else if (status === "not_ready") {
    beep(660, 0, 0.08);
    beep(660, 0.14, 0.08);
  } else if (status !== "ignored") {
    beep(180, 0, 0.42, "sawtooth");
  }
}

function readSound(): boolean {
  try {
    return localStorage.getItem(SOUND_KEY) !== "off";
  } catch {
    return true;
  }
}

/**
 * The collection desk: a USB barcode scanner types the student's ID code and
 * presses Enter. The field keeps focus so staff never have to click before scanning.
 */
export function CollectDesk({ station }: { station: "canteen" | "print" }) {
  const input = useRef<HTMLInputElement>(null);
  const [code, setCode] = useState("");
  const [banner, setBanner] = useState<CollectResult | null>(null);
  const [recent, setRecent] = useState<CollectResult[]>([]);
  const [sound, setSound] = useState(readSound);
  const [simStudent, setSimStudent] = useState("");
  const shown = useRef(new Set<string>());
  const soundRef = useRef(sound);
  soundRef.current = sound;

  const candidates = useQuery({
    queryKey: ["collect", "candidates"],
    queryFn: () => api<CollectCandidates>("/collect/candidates"),
  });

  /** Show a result once, whether it came back from our own scan or from another screen at this desk. */
  const show = (result: CollectResult) => {
    if (result.status === "ignored" || shown.current.has(result.id)) return;
    shown.current.add(result.id);
    setBanner(result);
    setRecent((list) => [result, ...list].slice(0, 6));
    if (soundRef.current) playFor(result.status);
  };

  const scan = useMutation({
    mutationFn: (value: string) => api<CollectResult>("/collect/scan", { method: "POST", body: { code: value } }),
    onSuccess: show,
  });
  const simulate = useMutation({
    mutationFn: (studentId: number) => api<CollectResult>("/collect/simulate", { method: "POST", body: { student_id: studentId } }),
    onSuccess: show,
  });

  // Results from other screens at the same desk (e.g. a second laptop at the counter).
  useEffect(
    () =>
      subscribe((event) => {
        if (event.type !== "tap.result") return;
        const result = event.payload as unknown as CollectResult;
        if (result.station === station) show(result);
      }),
    [station],
  );

  // The banner stays 4 seconds after the latest result.
  useEffect(() => {
    if (!banner) return;
    const id = setTimeout(() => setBanner(null), BANNER_MS);
    return () => clearTimeout(id);
  }, [banner]);

  // Keep the scan field focused so a scan is never typed into something else (a scanner
  // ends with Enter, which would press a focused button). Refocus after pointer clicks on
  // anything that isn't a text field or select, and when focus drops to the page.
  // Keyboard users who Tab away are left alone, so nothing is trapped.
  useEffect(() => {
    const textEntry = (el: Element | null) => !!el?.closest("input, select, textarea, [contenteditable=true]");
    const dialogOpen = () => !!document.querySelector("[role=dialog]");
    const focusField = () => input.current?.focus({ preventScroll: true });
    const afterClick = () =>
      setTimeout(() => {
        if (!textEntry(document.activeElement) && !dialogOpen()) focusField();
      }, 0);
    const afterBlur = () =>
      setTimeout(() => {
        const active = document.activeElement;
        if ((!active || active === document.body) && !dialogOpen()) focusField();
      }, 0);
    const field = input.current;
    field?.addEventListener("blur", afterBlur);
    window.addEventListener("focus", afterBlur);
    document.addEventListener("click", afterClick);
    focusField();
    return () => {
      field?.removeEventListener("blur", afterBlur);
      window.removeEventListener("focus", afterBlur);
      document.removeEventListener("click", afterClick);
    };
  }, []);

  const onSubmit = (event: FormEvent) => {
    event.preventDefault();
    const value = code.trim();
    setCode("");
    if (value) scan.mutate(value);
  };

  const toggleSound = () => {
    const next = !sound;
    setSound(next);
    try {
      localStorage.setItem(SOUND_KEY, next ? "on" : "off");
    } catch {
      /* the choice still applies for this visit */
    }
  };

  const error = scan.error ?? simulate.error;
  const demo = candidates.data?.demo_mode;
  const look = banner && banner.status !== "ignored" ? LOOK[banner.status] : null;
  const what = station === "canteen" ? "food" : "printouts";

  return (
    <section aria-labelledby={`desk-${station}`} className="rounded-[20px] border-2 border-edge bg-sheet p-4 shadow-hard sm:p-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 id={`desk-${station}`} className="flex items-center gap-2 font-display text-28 font-extrabold">
          <ScanBarcode className="size-8" aria-hidden /> Collect
        </h2>
        <Button variant="secondary" onClick={toggleSound} aria-pressed={sound}>
          {sound ? <Volume2 aria-hidden /> : <VolumeX aria-hidden />} {sound ? "Sound on" : "Sound off"}
        </Button>
      </div>
      <p className="mt-1 font-semibold text-muted">
        Scan the barcode on the student's ID card. Everything ready for them ({what}) is handed over.
      </p>

      <div className="mt-4 grid gap-3 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
        <form onSubmit={onSubmit}>
          <label htmlFor={`scan-${station}`} className="block text-15 font-bold">
            Scan ID card
          </label>
          <input
            ref={input}
            id={`scan-${station}`}
            value={code}
            onChange={(e) => setCode(e.target.value)}
            autoComplete="off"
            autoCorrect="off"
            autoCapitalize="characters"
            spellCheck={false}
            enterKeyHint="go"
            placeholder="Waiting for a scan…"
            className="mt-1 min-h-14 w-full rounded-button border-[3px] border-edge bg-paper px-3 font-display text-21 font-extrabold tracking-widest text-ink placeholder:font-sans placeholder:text-17 placeholder:font-semibold placeholder:tracking-normal placeholder:text-muted focus-visible:shadow-hard-sm"
          />
          <p className="mt-1 text-13 font-semibold text-muted">The scanner types the code and presses Enter. You can also type it.</p>
        </form>

        {demo ? (
          <div className="rounded-[14px] border-2 border-dashed border-edge p-3">
            <label htmlFor={`sim-${station}`} className="block text-15 font-bold">
              Simulate scan <span className="font-semibold text-muted">(demo, no scanner needed)</span>
            </label>
            <div className="mt-1 flex flex-wrap gap-2">
              <select
                id={`sim-${station}`}
                value={simStudent}
                onChange={(e) => setSimStudent(e.target.value)}
                className="min-h-12 min-w-48 flex-1 rounded-button border-2 border-edge bg-sheet px-2 text-15 font-bold text-ink"
              >
                <option value="">Choose a student…</option>
                {candidates.data?.students.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.name} · {s.roll_no}
                    {s.ready ? ` · ${s.ready} ready` : s.waiting ? ` · ${s.waiting} not ready` : ""}
                  </option>
                ))}
              </select>
              <Button className="min-h-12" disabled={!simStudent || simulate.isPending} onClick={() => simulate.mutate(Number(simStudent))}>
                <ScanBarcode aria-hidden /> Simulate scan
              </Button>
            </div>
          </div>
        ) : null}
      </div>

      {error ? (
        <p role="alert" className="mt-3 flex items-start gap-2 font-semibold text-alert-text">
          <CircleAlert className="mt-0.5 size-5 shrink-0" aria-hidden />
          {errorMessage(error)}
        </p>
      ) : null}

      {recent.length ? (
        <div className="mt-4">
          <h3 className="text-15 font-extrabold">Recent scans</h3>
          <ul className="mt-1 divide-y-2 divide-dashed divide-line">
            {recent.map((r) => (
              <li key={r.id} className="flex flex-wrap items-baseline justify-between gap-x-3 py-1.5 text-15">
                <span className="min-w-0 font-bold">
                  {r.name ?? "Unknown card"} <span className="font-semibold text-muted">· {LOOK[r.status as Exclude<CollectStatus, "ignored">].title}</span>
                </span>
                <span className="text-13 font-semibold text-muted tabular-nums">{timeOfDay(r.at)}</span>
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      {/* The result: large, for 4 seconds, in words and colour (never colour alone). */}
      <div role="status" aria-live="assertive" className="pointer-events-none fixed inset-x-0 top-12 z-40 flex justify-center px-4">
        {banner && look ? (
          <div
            className={cn(
              "notice-in pointer-events-auto w-full max-w-2xl rounded-[20px] border-[3px] border-edge p-5 shadow-hard-lg",
              look.className,
            )}
          >
            <p className="flex items-center gap-3 font-display text-40 leading-none font-extrabold">
              <look.icon className="size-10 shrink-0" aria-hidden /> {look.title}
            </p>
            {banner.name ? (
              <p className="mt-2 font-display text-28 font-extrabold">
                {banner.name} <span className="font-sans text-17 font-bold opacity-90">· {banner.roll_no}</span>
              </p>
            ) : null}
            <p className="mt-1 text-17 font-bold">{explain(banner, station)}</p>
          </div>
        ) : null}
      </div>
    </section>
  );
}
