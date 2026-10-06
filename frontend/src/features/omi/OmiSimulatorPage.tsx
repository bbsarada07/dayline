import { useEffect, useRef, useState } from "react";
import { Link } from "react-router";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Brain, CircleAlert, LoaderCircle, Mic, MessagesSquare, Send, Sparkles } from "lucide-react";
import { EmptyState } from "@/components/states";
import { Button, buttonVariants } from "@/components/ui/button";
import { Label } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { api, errorMessage } from "@/lib/api";
import { subscribe } from "@/lib/realtime";
import type { AgentReply, OmiMemories, OmiStatus } from "@/lib/types";
import { cn } from "@/lib/utils";
import { useAsk } from "@/features/ask/AskContext";
import { AGENT } from "@/features/ask/Trace";
import { canListen, useListen } from "@/features/ask/voice";
import { OmiActivity, useOmiStatus } from "./omiShared";

const SPEECH_EXAMPLES = [
  "Hey Dayline, get me my usual lunch",
  "Hey Dayline, can I skip DBMS tomorrow?",
  "Hey Dayline, what's my next class?",
  "The lecture today was so long, I need coffee",
];

const SAMPLE_CONVERSATION = `Priya: Did you finish the OS assignment?
You: Not yet. It's due Wednesday, and sir wants a printed copy.
Priya: Also the CN class on Tuesday is cancelled.
You: Nice. I'll return your lab manual tomorrow.
Priya: The weather is so nice today.`;

const WORDS_PER_SEGMENT = 6;
const SECONDS_PER_WORD = 0.35;
const WAIT_FOR_REPLY_MS = 60_000;

type WireCall = { id: number; said: string; status: string };

const STATUS_WORDS: Record<string, string> = {
  listening: "heard “Hey Dayline”, listening",
  request: "request ended at a pause",
  no_wake_phrase: "no wake phrase: dropped",
  duplicate: "duplicate: skipped",
  ignored: "ignored",
  rate_limited: "too many calls",
  accepted: "received; the Listener is reading it",
  skipped: "skipped",
};

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

/** POST to the student's own webhook URL, exactly as Omi's servers do. */
async function postWebhook(path: string, uid: string, body: unknown): Promise<string> {
  const response = await fetch(`${path}&uid=${encodeURIComponent(uid)}`, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Dayline-Simulator": "1" },
    body: JSON.stringify(body),
  });
  if (!response.ok) throw new Error(`The webhook answered HTTP ${response.status}.`);
  return ((await response.json()) as { status: string }).status;
}

function OmiNotification({ reply }: { reply: AgentReply }) {
  const ask = useAsk();
  return (
    <div className="notice-in rounded-[18px] border-2 border-edge bg-hero p-3.5 text-hero-text shadow-hard-magenta" role="status">
      <p className="flex items-center gap-2 text-13 font-bold text-hero-muted">
        <span className="inline-flex size-6 items-center justify-center rounded-[7px] bg-magenta">
          <span className="size-2 rounded-full bg-hero-text" />
        </span>
        Dayline · notification on your Omi
      </p>
      <p className="mt-2 text-17 font-bold">{reply.spoken}</p>
      <p className="mt-2 text-13 font-semibold text-hero-muted">{reply.notification.detail}</p>
      <div className="mt-3 flex flex-wrap items-center gap-1.5">
        {reply.agents.map((agent) => {
          const a = AGENT[agent];
          return (
            <span key={agent} className={cn("inline-flex items-center gap-1 rounded-[8px] border-2 border-hero-text px-2 py-0.5 text-13 font-extrabold", a.fill, a.text)}>
              <a.icon className="size-3.5" aria-hidden /> {a.label}
            </span>
          );
        })}
      </div>
      {reply.proposals.length ? (
        <Button variant="hero" className="mt-3" onClick={() => ask.openSheet()}>
          <Sparkles aria-hidden /> Confirm in Dayline ({reply.proposals.length})
        </Button>
      ) : null}
    </div>
  );
}

function SpeechPanel({ status }: { status: OmiStatus }) {
  const [text, setText] = useState(SPEECH_EXAMPLES[0]);
  const [calls, setCalls] = useState<WireCall[]>([]);
  const [sending, setSending] = useState(false);
  const [waiting, setWaiting] = useState(false);
  const [reply, setReply] = useState<AgentReply | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [lastBody, setLastBody] = useState<unknown>(null);
  const timeline = useRef(0); // Omi's own clock: seconds since the "recording" started
  const callId = useRef(0);
  const listen = useListen((spoken) => {
    setText(spoken);
    void send(spoken);
  });

  useEffect(
    () =>
      subscribe((event) => {
        if (event.type !== "agent.reply") return;
        setReply(event.payload as unknown as AgentReply);
        setWaiting(false);
      }),
    [],
  );
  useEffect(() => {
    if (!waiting) return;
    const id = setTimeout(() => {
      setWaiting(false);
      setProblem("No reply yet. The activity log below shows what the server did.");
    }, WAIT_FOR_REPLY_MS);
    return () => clearTimeout(id);
  }, [waiting]);

  /** Speak like Omi: a few words per segment, one webhook call each, with real timing. */
  async function send(said: string) {
    const words = said.trim().split(/\s+/).filter(Boolean);
    if (!words.length || !status.omi_uid) return;
    setSending(true);
    setProblem(null);
    setReply(null);
    let heard = false;
    try {
      for (let i = 0; i < words.length; i += WORDS_PER_SEGMENT) {
        const chunk = words.slice(i, i + WORDS_PER_SEGMENT);
        const start = timeline.current;
        const end = start + chunk.length * SECONDS_PER_WORD;
        timeline.current = end + 0.15;
        const body = {
          session_id: status.omi_uid,
          segments: [{ text: chunk.join(" "), speaker: "SPEAKER_00", speakerId: 0, is_user: true, start: Number(start.toFixed(2)), end: Number(end.toFixed(2)) }],
        };
        setLastBody(body);
        const result = await postWebhook(status.paths.transcript, status.omi_uid, body);
        heard ||= result === "listening" || result === "request";
        setCalls((current) => [{ id: ++callId.current, said: chunk.join(" "), status: result }, ...current].slice(0, 12));
        await sleep(350);
      }
      timeline.current += 5; // a pause, so the next send is a new request
      if (heard) setWaiting(true);
      else setProblem("There was no “Hey Dayline” in that, so the speech was dropped. Nothing was stored.");
    } catch (error) {
      setProblem(errorMessage(error));
    } finally {
      setSending(false);
    }
  }

  return (
    <section aria-labelledby="sim-speech" className="space-y-4 rounded-[20px] border-2 border-edge bg-sheet p-4 shadow-hard sm:p-5">
      <div>
        <h2 id="sim-speech" className="flex items-center gap-2 font-display text-28 font-extrabold">
          <Mic className="size-6" aria-hidden /> Talk to Omi
        </h2>
        <p className="mt-1 font-semibold text-muted">
          Sent to the <b>real-time transcript webhook</b>, a few words at a time, as Omi does while you speak.
        </p>
      </div>
      <div>
        <Label htmlFor="sim-said">What you say</Label>
        <textarea
          id="sim-said"
          value={listen.listening ? listen.heard || "Listening…" : text}
          onChange={(e) => setText(e.target.value)}
          readOnly={listen.listening}
          rows={2}
          maxLength={400}
          className="mt-1.5 w-full rounded-button border-2 border-edge bg-sheet px-3 py-2 text-17 font-semibold"
        />
        <div className="mt-2 flex flex-wrap gap-1.5">
          {SPEECH_EXAMPLES.map((example) => (
            <button
              key={example}
              type="button"
              onClick={() => setText(example)}
              className="press rounded-full border-2 border-edge bg-paper px-2.5 py-1 text-13 font-bold shadow-hard-sm"
            >
              {example}
            </button>
          ))}
        </div>
      </div>
      <div className="flex flex-wrap gap-2">
        <Button onClick={() => send(text)} disabled={sending || waiting || !text.trim()}>
          {sending ? <LoaderCircle className="animate-spin" aria-hidden /> : <Send aria-hidden />}
          {sending ? "Speaking…" : "Send as live speech"}
        </Button>
        {canListen ? (
          <Button
            variant={listen.listening ? "primary" : "secondary"}
            className={cn("touch-none select-none", listen.listening && "pulse-ring")}
            disabled={sending || waiting}
            onPointerDown={(e) => {
              e.currentTarget.setPointerCapture(e.pointerId);
              listen.start();
            }}
            onPointerUp={listen.stop}
            onPointerCancel={listen.stop}
            aria-pressed={listen.listening}
          >
            <Mic aria-hidden /> {listen.listening ? "Release to send" : "Hold to talk"}
          </Button>
        ) : null}
      </div>

      {calls.length ? (
        <ol className="space-y-1 rounded-[12px] border-2 border-dashed border-line p-2.5 font-mono text-[12px]" aria-label="Webhook calls sent">
          {calls.map((call) => (
            <li key={call.id} className="flex flex-wrap gap-x-2">
              <span className="text-muted">POST transcript</span>
              <span className="font-bold">“{call.said}”</span>
              <span className={call.status === "ignored" || call.status === "rate_limited" ? "text-alert-text" : "text-stamp-text"}>
                → {STATUS_WORDS[call.status] ?? call.status}
              </span>
            </li>
          ))}
        </ol>
      ) : null}

      {waiting ? (
        <p role="status" className="flex items-center gap-2 font-bold">
          <LoaderCircle className="size-5 animate-spin" aria-hidden /> Waiting for the pause, then the agents… (about 4 seconds, longer with Lyzr)
        </p>
      ) : null}
      {problem || listen.error ? (
        <p role="alert" className="flex items-start gap-2 font-bold text-alert-text">
          <CircleAlert className="mt-0.5 size-5 shrink-0" aria-hidden /> {problem ?? listen.error}
        </p>
      ) : null}
      {reply ? <OmiNotification reply={reply} /> : null}
      {lastBody ? (
        <details className="text-13">
          <summary className="cursor-pointer font-bold text-muted">The last call's body (Omi's format)</summary>
          <pre className="mt-1 overflow-x-auto rounded-[10px] bg-tint p-2.5 font-mono text-[12px]">{JSON.stringify(lastBody, null, 2)}</pre>
        </details>
      ) : null}
    </section>
  );
}

function ConversationPanel({ status }: { status: OmiStatus }) {
  const [text, setText] = useState(SAMPLE_CONVERSATION);
  const [sent, setSent] = useState<string | null>(null);
  const [kept, setKept] = useState<OmiMemories | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [lastBody, setLastBody] = useState<unknown>(null);
  const conversationId = useRef<string | null>(null);

  useEffect(
    () =>
      subscribe((event) => {
        if (event.type !== "omi.memories") return;
        const memories = event.payload as unknown as OmiMemories;
        if (memories.conversation === conversationId.current) setKept(memories);
      }),
    [],
  );

  const send = useMutation({
    mutationFn: async () => {
      const lines = text.split("\n").map((l) => l.trim()).filter(Boolean);
      let t = 0;
      const segments = lines.map((line) => {
        const match = /^([^:]{1,30}):\s*(.+)$/.exec(line);
        const name = match ? match[1].trim() : "Someone";
        const said = match ? match[2] : line;
        const you = /^(you|me)$/i.test(name);
        const seconds = said.split(/\s+/).length * SECONDS_PER_WORD;
        const segment = {
          text: said, speaker: you ? "SPEAKER_00" : "SPEAKER_01", speakerId: you ? 0 : 1, speaker_name: you ? "You" : name,
          is_user: you, start: Number(t.toFixed(2)), end: Number((t + seconds).toFixed(2)),
        };
        t += seconds + 0.6;
        return segment;
      });
      const now = new Date();
      const id = `sim-${now.getTime().toString(36)}`;
      conversationId.current = id;
      const body = {
        id, created_at: now.toISOString(), started_at: new Date(now.getTime() - t * 1000).toISOString(), finished_at: now.toISOString(),
        transcript_segments: segments,
        structured: { title: "Simulated conversation", overview: "", emoji: "💬", category: "education", action_items: [], events: [] },
        apps_response: [], discarded: false,
      };
      setLastBody(body);
      return postWebhook(status.paths.memory, status.omi_uid!, body);
    },
    onMutate: () => {
      setKept(null);
      setProblem(null);
      setSent(null);
    },
    onSuccess: (result) => {
      setSent(result);
      if (result !== "accepted") setProblem(`The webhook answered “${STATUS_WORDS[result] ?? result}”.`);
    },
    onError: (error) => setProblem(errorMessage(error)),
  });

  const waiting = sent === "accepted" && !kept;
  return (
    <section aria-labelledby="sim-conversation" className="space-y-4 rounded-[20px] border-2 border-edge bg-sheet p-4 shadow-hard sm:p-5">
      <div>
        <h2 id="sim-conversation" className="flex items-center gap-2 font-display text-28 font-extrabold">
          <MessagesSquare className="size-6" aria-hidden /> End a conversation
        </h2>
        <p className="mt-1 font-semibold text-muted">
          Sent to the <b>memory creation webhook</b>, as Omi does when a conversation ends. The Listener keeps at most
          five things that matter; the conversation itself is never stored.
        </p>
      </div>
      <div>
        <Label htmlFor="sim-conv">The conversation (one “Name: words” line each; “You” is you)</Label>
        <textarea
          id="sim-conv"
          value={text}
          onChange={(e) => setText(e.target.value)}
          rows={6}
          maxLength={3000}
          className="mt-1.5 w-full rounded-button border-2 border-edge bg-sheet px-3 py-2 text-15 font-semibold"
        />
      </div>
      <Button onClick={() => send.mutate()} disabled={send.isPending || waiting || !text.trim()}>
        {send.isPending || waiting ? <LoaderCircle className="animate-spin" aria-hidden /> : <Send aria-hidden />}
        {send.isPending ? "Sending…" : waiting ? "Listener is reading…" : "Send conversation"}
      </Button>
      {problem ? (
        <p role="alert" className="flex items-start gap-2 font-bold text-alert-text">
          <CircleAlert className="mt-0.5 size-5 shrink-0" aria-hidden /> {problem}
        </p>
      ) : null}
      {kept ? (
        <div role="status" className="notice-in rounded-[16px] border-2 border-edge bg-paper p-3.5">
          <p className="flex items-center gap-2 font-display text-17 font-extrabold">
            <Brain className="size-5" aria-hidden />
            {kept.items.length ? `Kept ${kept.items.length} thing${kept.items.length === 1 ? "" : "s"}, written by Omi` : "Nothing worth keeping"}
          </p>
          {kept.items.length ? (
            <ul className="mt-2 space-y-1">
              {kept.items.map((item) => (
                <li key={item} className="flex items-start gap-2 font-semibold">
                  <span aria-hidden className="mt-2 size-2 shrink-0 rounded-full bg-magenta" />
                  {item}
                </li>
              ))}
            </ul>
          ) : null}
          <p className="mt-2 text-13 font-semibold text-muted">Read by the {kept.by === "lyzr" ? "Lyzr Listener agent" : "offline listener"}.</p>
          <div className="mt-3 flex flex-wrap gap-2">
            <Link to="/memory" className={buttonVariants({ variant: "secondary" })}>See it in Memory</Link>
            <Link to="/" className={buttonVariants({ variant: "secondary" })}>See Today's nudges</Link>
          </div>
        </div>
      ) : null}
      {lastBody ? (
        <details className="text-13">
          <summary className="cursor-pointer font-bold text-muted">The call's body (Omi's format)</summary>
          <pre className="mt-1 max-h-64 overflow-auto rounded-[10px] bg-tint p-2.5 font-mono text-[12px]">{JSON.stringify(lastBody, null, 2)}</pre>
        </details>
      ) : null}
    </section>
  );
}

/** Demo only: drive both Omi webhooks from the browser, through exactly the same code paths. */
export function OmiSimulatorPage() {
  const client = useQueryClient();
  const status = useOmiStatus();
  const connectDemo = useMutation({
    mutationFn: (uid: string) => api<OmiStatus>("/omi/connect", { method: "PUT", body: { uid } }),
    onSuccess: (data) => client.setQueryData(["omi", "status"], data),
  });
  const s = status.data;

  return (
    <div className="mx-auto max-w-6xl">
      <header className="relative overflow-hidden rounded-[24px] border-2 border-edge bg-hero px-5 py-6 text-hero-text shadow-hard-lg sm:px-7">
        <div aria-hidden className="halftone pointer-events-none absolute -top-12 -right-12 size-56 rounded-full text-magenta" />
        <span className="relative inline-block -rotate-2 rounded-[8px] border-2 border-hero-text bg-yellow px-2 py-0.5 text-13 font-extrabold text-on-fill">
          Simulator · no device needed
        </span>
        <h1 className="relative mt-3 font-display text-40 leading-none font-extrabold sm:text-64">Omi simulator</h1>
        <p className="relative mt-2 max-w-2xl text-17 font-semibold text-hero-muted">
          Sends the same webhook calls Omi's servers send, to your own webhook links. Everything after that, from the wake
          phrase to the agents and memory, is the real code path.
        </p>
      </header>

      <div className="mt-6">
        {status.isPending ? (
          <Skeleton className="h-64" />
        ) : status.isError || !s ? (
          <p className="font-semibold text-alert-text">The Omi settings didn't load. {errorMessage(status.error)}</p>
        ) : !s.simulator ? (
          <EmptyState icon={Mic} title="The simulator is only in the demo">
            Connect a real Omi in Profile instead.
          </EmptyState>
        ) : !s.connected ? (
          <EmptyState
            icon={Mic}
            title="Connect an Omi id first"
            action={
              s.demo_uid ? (
                <Button onClick={() => connectDemo.mutate(s.demo_uid!)} disabled={connectDemo.isPending}>
                  Use the demo Omi id
                </Button>
              ) : null
            }
          >
            The webhooks only answer for the Omi id saved on your profile.
          </EmptyState>
        ) : (
          <>
            <p className="mb-4 font-semibold text-muted">
              Sending as Omi id <code className="rounded-[6px] bg-tint px-1.5 py-0.5 font-mono text-13">{s.omi_uid}</code>
              {s.is_demo_uid ? " (the demo id: replies show here instead of on a phone)" : " (your real Omi: replies go to your phone too)"}.
            </p>
            <div className="grid items-start gap-6 lg:grid-cols-2">
              <SpeechPanel status={s} />
              <ConversationPanel status={s} />
            </div>
          </>
        )}
      </div>

      <section aria-labelledby="sim-log" className="mt-8">
        <h2 id="sim-log" className="font-display text-28 font-extrabold">What the server did</h2>
        <p className="font-semibold text-muted">The webhook log: what happened, never what was said.</p>
        <OmiActivity limit={15} className="mt-3" />
      </section>
    </div>
  );
}
