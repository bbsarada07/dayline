import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { api, errorMessage } from "@/lib/api";
import { subscribe } from "@/lib/realtime";
import type { AgentHistory, AgentName, AgentReply, PrintUpload, Proposal, TraceEvent } from "@/lib/types";
import { speak, stopSpeaking } from "./voice";
import { streamChat } from "./stream";

export type ChatMessage = {
  id: string;
  role: "user" | "assistant";
  text: string;
  attachment?: string | null;
  events: TraceEvent[];
  proposals: Proposal[];
  agents: AgentName[];
  status: "streaming" | "done" | "error";
  refused?: boolean;
  /** Said to the Omi wearable rather than typed here. */
  via?: "omi";
  /** How the run was answered, from its "run" event (unknown for older history). */
  mode?: "lyzr" | "mock";
};

type AskState = {
  messages: ChatMessage[];
  busy: boolean;
  attachment: PrintUpload | null;
  setAttachment: (upload: PrintUpload | null) => void;
  send: (text: string, options?: { voice?: boolean; attachment?: PrintUpload | null }) => void;
  newChat: () => void;
  /** The ask sheet (phones, and laptop screens other than Today). */
  sheetOpen: boolean;
  openSheet: (draft?: string) => void;
  closeSheet: () => void;
  draft: string;
  setDraft: (text: string) => void;
  muted: boolean;
  setMuted: (muted: boolean) => void;
  /** Proposals already paid for (id -> "Token 12" / "P-0042"), so a card can't be paid twice. */
  confirmed: Record<string, string>;
  markConfirmed: (proposalId: string, label: string) => void;
};

const AskContext = createContext<AskState | null>(null);
const CONVERSATION_KEY = "dayline.conversation";
const MUTE_KEY = "dayline.voiceMuted";

function read(key: string, storage: () => Storage): string | null {
  try {
    return storage().getItem(key);
  } catch {
    return null;
  }
}

function write(key: string, value: string | null, storage: () => Storage) {
  try {
    if (value === null) storage().removeItem(key);
    else storage().setItem(key, value);
  } catch {
    /* private mode: fine, it just isn't remembered */
  }
}

const session = () => window.sessionStorage;
const local = () => window.localStorage;
const newId = () => Math.random().toString(36).slice(2, 10);

function fromHistory(history: AgentHistory): ChatMessage[] {
  return history.messages.map((m) => ({
    id: `h${m.id}`,
    role: m.role,
    text: m.content,
    events: m.trace?.events ?? [],
    proposals: m.trace?.proposals ?? [],
    agents: m.trace?.agents ?? [],
    refused: m.trace?.refused,
    status: "done",
  }));
}

/** One conversation with Dayline, shared by the ask bar, the sheet and the Today panel. */
export function AskProvider({ children }: { children: ReactNode }) {
  const client = useQueryClient();
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [busy, setBusy] = useState(false);
  const [attachment, setAttachment] = useState<PrintUpload | null>(null);
  const [sheetOpen, setSheetOpen] = useState(false);
  const [draft, setDraft] = useState("");
  const [confirmed, setConfirmed] = useState<Record<string, string>>({});
  const [muted, setMutedState] = useState(() => read(MUTE_KEY, local) === "1");
  const conversation = useRef<string | null>(read(CONVERSATION_KEY, session));
  const abort = useRef<AbortController | null>(null);

  // Pick up this tab's conversation after a reload.
  useEffect(() => {
    const id = conversation.current;
    if (!id) return;
    api<AgentHistory>(`/agent/history?conversation_id=${encodeURIComponent(id)}`)
      .then((history) => setMessages((current) => (current.length ? current : fromHistory(history))))
      .catch(() => undefined);
  }, []);

  useEffect(() => () => abort.current?.abort(), []);

  // Something said to Omi was answered: show it here too, so its proposal cards can be confirmed.
  useEffect(
    () =>
      subscribe((event) => {
        if (event.type !== "agent.reply") return;
        const reply = event.payload as unknown as AgentReply;
        setMessages((current) => [
          ...current,
          { id: newId(), role: "user", text: reply.message, events: [], proposals: [], agents: [], status: "done", via: "omi" },
          {
            id: newId(), role: "assistant", text: reply.reply, events: reply.events, proposals: reply.proposals,
            agents: reply.agents, refused: reply.refused, status: "done", via: "omi",
          },
        ]);
      }),
    [],
  );

  const update = useCallback((id: string, change: (m: ChatMessage) => ChatMessage) => {
    setMessages((current) => current.map((m) => (m.id === id ? change(m) : m)));
  }, []);

  const send = useCallback(
    (text: string, options: { voice?: boolean; attachment?: PrintUpload | null } = {}) => {
      const message = text.trim();
      if (!message || busy) return;
      const file = options.attachment !== undefined ? options.attachment : attachment;
      const replyId = newId();
      stopSpeaking();
      setDraft("");
      setAttachment(null);
      setBusy(true);
      setMessages((current) => [
        ...current,
        { id: newId(), role: "user", text: message, attachment: file?.original_filename, events: [], proposals: [], agents: [], status: "done" },
        { id: replyId, role: "assistant", text: "", events: [], proposals: [], agents: [], status: "streaming" },
      ]);

      const controller = new AbortController();
      abort.current = controller;
      let usedMemory = false;
      streamChat(
        {
          message,
          conversation_id: conversation.current ?? undefined,
          upload_id: file?.upload_id,
          voice: options.voice ?? false,
        },
        (event) => {
          if (event.type === "run") {
            update(replyId, (m) => ({ ...m, mode: event.mode }));
            conversation.current = event.conversation_id;
            write(CONVERSATION_KEY, event.conversation_id, session);
            return;
          }
          if (event.type === "memory_write" || event.type === "memory_read") usedMemory = true;
          if (event.type === "proposal") {
            // An agent that proposes twice replaces its earlier card.
            update(replyId, (m) => ({
              ...m,
              proposals: [...m.proposals.filter((p) => p.type !== event.proposal.type), event.proposal],
            }));
            return;
          }
          if (event.type === "final") {
            update(replyId, (m) => ({
              ...m,
              text: event.reply,
              proposals: event.proposals,
              agents: event.agents,
              refused: event.refused,
              status: "done",
            }));
            if (options.voice && !read(MUTE_KEY, local)) speak(event.reply);
            return;
          }
          if (event.type === "error") {
            update(replyId, (m) => ({ ...m, text: event.message, status: "error" }));
            return;
          }
          update(replyId, (m) => ({ ...m, events: [...m.events, event] }));
        },
        controller.signal,
      )
        .catch((error) => update(replyId, (m) => ({ ...m, text: errorMessage(error), status: "error" })))
        .finally(() => {
          setBusy(false);
          update(replyId, (m) => (m.status === "streaming" ? { ...m, text: "Dayline stopped before answering. Try again.", status: "error" } : m));
          if (usedMemory) client.invalidateQueries({ queryKey: ["memory"] });
        });
    },
    [attachment, busy, client, update],
  );

  const newChat = useCallback(() => {
    abort.current?.abort();
    stopSpeaking();
    conversation.current = null;
    write(CONVERSATION_KEY, null, session);
    setMessages([]);
    setAttachment(null);
    setDraft("");
  }, []);

  const value = useMemo<AskState>(
    () => ({
      messages,
      busy,
      attachment,
      setAttachment,
      send,
      newChat,
      sheetOpen,
      openSheet: (text?: string) => {
        if (text !== undefined) setDraft(text);
        setSheetOpen(true);
      },
      closeSheet: () => setSheetOpen(false),
      draft,
      setDraft,
      muted,
      setMuted: (value: boolean) => {
        setMutedState(value);
        write(MUTE_KEY, value ? "1" : null, local);
        if (value) stopSpeaking();
      },
      confirmed,
      markConfirmed: (proposalId: string, label: string) => setConfirmed((c) => ({ ...c, [proposalId]: label })),
    }),
    [messages, busy, attachment, send, newChat, sheetOpen, draft, muted, confirmed],
  );

  return <AskContext.Provider value={value}>{children}</AskContext.Provider>;
}

export function useAsk(): AskState {
  const value = useContext(AskContext);
  if (!value) throw new Error("useAsk must be used inside AskProvider");
  return value;
}
