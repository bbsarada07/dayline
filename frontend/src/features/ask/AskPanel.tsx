import { useEffect, useRef, useState, type FormEvent } from "react";
import { useMutation } from "@tanstack/react-query";
import {
  ArrowUp, ChartNoAxesColumn, CircleAlert, FileText, Mic, Paperclip, Printer, RotateCcw, Sparkles, UtensilsCrossed,
  Volume2, VolumeX, X,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { api, errorMessage } from "@/lib/api";
import { useClock } from "@/lib/clock";
import type { PrintUpload } from "@/lib/types";
import { cn } from "@/lib/utils";
import { useAsk, type ChatMessage } from "./AskContext";
import { ProposalCard } from "./ProposalCard";
import { AGENT, Trace } from "./Trace";
import { canListen, canSpeak, useListen } from "./voice";

const MAX_BYTES = 20 * 1024 * 1024;

type Example = { text: string; why: string; sample?: boolean };
const EXAMPLES: Example[] = [
  { text: "Get me lunch and print this before my next class", why: "Canteen, Print and Timetable together.", sample: true },
  { text: "Can I skip DBMS tomorrow?", why: "Worked out from your real attendance." },
  { text: "Order my usual", why: "Your usual for today, from memory." },
];

function Bubble({ message, now, onLeave, primaryProposal }: {
  message: ChatMessage;
  now: Date | null;
  onLeave?: () => void;
  primaryProposal: string | null;
}) {
  if (message.role === "user") {
    return (
      <li className="ml-auto max-w-[85%] rounded-[16px] rounded-br-[4px] border-2 border-edge bg-ink px-3.5 py-2.5 text-paper shadow-hard-sm">
        {message.via === "omi" ? (
          <p className="mb-1 flex items-center gap-1 text-13 font-extrabold tracking-wide uppercase opacity-80">
            <Mic className="size-3.5" aria-hidden /> Said to Omi
          </p>
        ) : null}
        <p className="font-semibold break-words">{message.text}</p>
        {message.attachment ? (
          <p className="mt-1 flex items-center gap-1 text-13 font-bold opacity-80">
            <FileText className="size-3.5" aria-hidden /> {message.attachment}
          </p>
        ) : null}
      </li>
    );
  }
  const finished = message.status !== "streaming";
  return (
    <li className="max-w-full space-y-2.5">
      <Trace events={message.events} finished={finished} mode={message.mode} via={message.via} />
      {message.text ? (
        <p
          className={cn(
            "rounded-[16px] rounded-bl-[4px] border-2 border-edge bg-sheet px-3.5 py-2.5 text-15 font-semibold break-words shadow-hard-sm",
            message.status === "error" && "border-alert-text text-alert-text",
          )}
        >
          {message.status === "error" ? <CircleAlert className="mr-1.5 inline size-4 align-[-2px]" aria-hidden /> : null}
          {message.text}
        </p>
      ) : null}
      {message.proposals.length ? (
        <div className="space-y-2.5">
          {message.proposals.map((p) => (
            <ProposalCard key={p.id} proposal={p} now={now} onLeave={onLeave} primary={p.id === primaryProposal} />
          ))}
        </div>
      ) : null}
    </li>
  );
}

function TryThis({ onPick, demoMode, busy }: { onPick: (example: Example) => void; demoMode: boolean; busy: boolean }) {
  return (
    <section aria-labelledby="try-this" className="relative overflow-hidden rounded-[16px] border-2 border-edge bg-paper p-3.5">
      <h3 id="try-this" className="relative flex items-center gap-1.5 font-display text-17 font-extrabold">
        <Sparkles className="size-4" aria-hidden /> Try this
      </h3>
      <ul className="relative mt-2 space-y-2">
        {EXAMPLES.map((example) => (
          <li key={example.text}>
            <button
              type="button"
              disabled={busy}
              onClick={() => onPick(example)}
              className="press w-full rounded-[12px] border-2 border-edge bg-sheet px-3 py-2 text-left shadow-hard-sm disabled:opacity-60"
            >
              <span className="block font-bold">“{example.text}”</span>
              <span className="mt-0.5 block text-13 font-semibold text-muted">
                {example.sample && demoMode ? "Attaches a sample PDF. " : ""}
                {example.why}
              </span>
            </button>
          </li>
        ))}
      </ul>
    </section>
  );
}

/**
 * Ask Dayline: type, talk or tap a shortcut; watch the agents work; confirm what they
 * prepared. `onLeave` closes the surrounding sheet when a card navigates away.
 */
export function AskPanel({ className, onLeave, autoFocus = false, shortcuts = true }: {
  className?: string;
  onLeave?: () => void;
  autoFocus?: boolean;
  /** The Print / Order food / Attendance chips. Off on Today, which has its own nudges. */
  shortcuts?: boolean;
}) {
  const ask = useAsk();
  const { now, demoMode } = useClock();
  const fileInput = useRef<HTMLInputElement>(null);
  const textInput = useRef<HTMLInputElement>(null);
  const list = useRef<HTMLDivElement>(null);
  const [pickError, setPickError] = useState<string | null>(null);
  const listen = useListen((text) => ask.send(text, { voice: true }));

  const upload = useMutation({
    mutationFn: (file: File) => {
      const form = new FormData();
      form.append("file", file);
      return api<PrintUpload>("/print/uploads", { method: "POST", body: form, timeoutMs: 120_000 });
    },
    onSuccess: (data) => ask.setAttachment(data),
  });
  const sample = useMutation({ mutationFn: () => api<PrintUpload>("/agent/sample-file", { method: "POST" }) });

  // Keep the newest message in view as the trace grows.
  const last = ask.messages.at(-1);
  useEffect(() => {
    list.current?.scrollTo({ top: list.current.scrollHeight, behavior: "smooth" });
  }, [ask.messages.length, last?.events.length, last?.text, last?.proposals.length]);

  useEffect(() => {
    if (autoFocus) textInput.current?.focus();
  }, [autoFocus]);

  const onPicked = (file: File | undefined) => {
    setPickError(null);
    upload.reset();
    if (!file) return;
    if (file.size > MAX_BYTES) {
      setPickError("That PDF is bigger than 20 MB. Compress it or split it, then try again.");
      return;
    }
    upload.mutate(file);
  };

  const submit = (event: FormEvent) => {
    event.preventDefault();
    ask.send(ask.draft);
  };

  const pickExample = (example: Example) => {
    if (!example.sample || !demoMode) {
      ask.send(example.text); // outside the demo, Print asks for a file
      return;
    }
    sample.mutate(undefined, { onSuccess: (file) => ask.send(example.text, { attachment: file }) });
  };

  const shortcut = (kind: "print" | "food" | "attendance") => {
    if (kind === "attendance") ask.send("What's my attendance?");
    else if (kind === "food") ask.send("Get me my usual lunch");
    else {
      ask.setDraft("Print this before my next class");
      fileInput.current?.click();
    }
  };

  const busy = ask.busy || upload.isPending || sample.isPending;
  // The first card still waiting to be paid holds the screen's one primary button.
  const waiting = ask.messages.flatMap((m) => m.proposals).find((p) => !ask.confirmed[p.id])?.id ?? null;
  const problem = pickError ?? (upload.isError ? errorMessage(upload.error) : sample.isError ? errorMessage(sample.error) : listen.error);

  return (
    <div className={cn("flex min-h-0 flex-col", className)}>
      <div className="flex items-center justify-between gap-2">
        <h2 className="flex items-center gap-2 font-display text-21 font-extrabold">
          <span aria-hidden className="relative inline-flex size-7 items-center justify-center rounded-[8px] border-2 border-edge bg-hero">
            <span className="size-2.5 rounded-full bg-magenta" />
          </span>
          Ask Dayline
        </h2>
        <div className="flex items-center gap-1">
          {canSpeak ? (
            <Button
              variant="ghost"
              size="icon"
              onClick={() => ask.setMuted(!ask.muted)}
              aria-pressed={ask.muted}
              aria-label={ask.muted ? "Spoken replies are off. Turn on" : "Spoken replies are on. Turn off"}
            >
              {ask.muted ? <VolumeX aria-hidden /> : <Volume2 aria-hidden />}
            </Button>
          ) : null}
          {ask.messages.length ? (
            <Button variant="ghost" size="icon" onClick={ask.newChat} aria-label="Start a new conversation">
              <RotateCcw aria-hidden />
            </Button>
          ) : null}
        </div>
      </div>

      <div ref={list} className="mt-3 min-h-0 flex-1 overflow-y-auto overscroll-contain pr-1">
        {ask.messages.length === 0 ? (
          <div className="space-y-3">
            <p className="font-semibold text-muted">
              Classes, food and printouts in one sentence. Dayline asks the right agents and shows you what they did.
            </p>
            <TryThis onPick={pickExample} demoMode={demoMode} busy={busy} />
          </div>
        ) : (
          <ol className="space-y-4 pb-1" aria-label="Conversation">
            {ask.messages.map((message) => (
              <Bubble key={message.id} message={message} now={now} onLeave={onLeave} primaryProposal={waiting} />
            ))}
          </ol>
        )}
      </div>

      <div className="mt-3 space-y-2">
        {shortcuts ? (
          <div className="flex flex-wrap gap-1.5" role="group" aria-label="Shortcuts">
            {(
              [
                ["print", "Print a file", Printer, "bg-cyan text-on-fill"],
                ["food", "Order food", UtensilsCrossed, "bg-yellow text-on-fill"],
                ["attendance", "Attendance", ChartNoAxesColumn, "bg-magenta text-white"],
              ] as const
            ).map(([kind, label, Icon, tone]) => (
              <button
                key={kind}
                type="button"
                disabled={busy}
                onClick={() => shortcut(kind)}
                className={cn("press inline-flex min-h-9 shrink-0 items-center gap-1.5 rounded-full border-2 border-edge px-3 text-13 font-extrabold shadow-hard-sm disabled:opacity-60", tone)}
              >
                <Icon className="size-3.5" aria-hidden /> {label}
              </button>
            ))}
          </div>
        ) : null}

        {ask.attachment || upload.isPending ? (
          <p className="flex items-center justify-between gap-2 rounded-[10px] border-2 border-dashed border-edge bg-paper px-2.5 py-1.5 text-13 font-bold">
            <span className="flex min-w-0 items-center gap-1.5">
              <FileText className="size-4 shrink-0" aria-hidden />
              <span className="truncate">
                {upload.isPending ? "Uploading…" : `${ask.attachment?.original_filename} · ${ask.attachment?.pages} pages`}
              </span>
            </span>
            {ask.attachment ? (
              <button type="button" onClick={() => ask.setAttachment(null)} className="inline-flex size-7 items-center justify-center rounded-[6px] hover:bg-tint">
                <X className="size-4" aria-hidden />
                <span className="sr-only">Remove the attached file</span>
              </button>
            ) : null}
          </p>
        ) : null}

        {problem ? (
          <p role="alert" className="flex items-start gap-1.5 text-13 font-bold text-alert-text">
            <CircleAlert className="mt-0.5 size-4 shrink-0" aria-hidden /> {problem}
          </p>
        ) : null}

        <form onSubmit={submit} className="flex items-center gap-1.5">
          <input
            ref={fileInput}
            type="file"
            accept="application/pdf,.pdf"
            className="sr-only"
            tabIndex={-1}
            aria-hidden
            onChange={(e) => {
              onPicked(e.target.files?.[0]);
              e.target.value = "";
            }}
          />
          <Button variant="secondary" size="icon" onClick={() => fileInput.current?.click()} disabled={busy} aria-label="Attach a PDF to print">
            <Paperclip aria-hidden />
          </Button>
          <label htmlFor="ask-input" className="sr-only">Ask Dayline</label>
          <input
            id="ask-input"
            ref={textInput}
            value={listen.listening ? listen.heard || "Listening…" : ask.draft}
            onChange={(e) => ask.setDraft(e.target.value)}
            readOnly={listen.listening}
            maxLength={1000}
            autoComplete="off"
            placeholder={ask.attachment ? "What should Print do with it?" : "Ask Dayline…"}
            className="min-h-11 min-w-0 flex-1 rounded-button border-2 border-edge bg-sheet px-3 text-15 font-semibold placeholder:text-muted focus:outline-none focus-visible:outline-3 focus-visible:outline-offset-2"
          />
          {canListen ? (
            <Button
              variant={listen.listening ? "primary" : "secondary"}
              size="icon"
              disabled={ask.busy}
              aria-label={listen.listening ? "Listening. Release to send" : "Hold to talk"}
              aria-pressed={listen.listening}
              className={cn("touch-none select-none", listen.listening && "pulse-ring")}
              onPointerDown={(e) => {
                e.currentTarget.setPointerCapture(e.pointerId);
                listen.start();
              }}
              onPointerUp={listen.stop}
              onPointerCancel={listen.stop}
              onKeyDown={(e) => {
                if ((e.key === " " || e.key === "Enter") && !e.repeat) {
                  e.preventDefault();
                  if (listen.listening) listen.stop();
                  else listen.start();
                }
              }}
            >
              <Mic aria-hidden />
            </Button>
          ) : null}
          <Button type="submit" size="icon" variant={waiting ? "secondary" : "primary"} disabled={busy || !ask.draft.trim()} aria-label="Send">
            <ArrowUp aria-hidden />
          </Button>
        </form>
        <p className="text-13 font-semibold text-muted">
          Agents prepare; you confirm. Nothing is paid for until you press confirm.
          {last && last.role === "assistant" && last.agents.length ? (
            <span className="sr-only"> Last answer from {last.agents.map((a) => AGENT[a].label).join(", ")}.</span>
          ) : null}
        </p>
      </div>
    </div>
  );
}
