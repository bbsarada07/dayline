import { useEffect, useSyncExternalStore } from "react";
import { useQueryClient, type QueryClient } from "@tanstack/react-query";

export type RealtimeEvent = { type: string; payload: Record<string, unknown> };

type Listener = (event: RealtimeEvent) => void;
const listeners = new Set<Listener>();

/** Listen to every realtime event (e.g. to show a notice). Returns an unsubscribe function. */
export function subscribe(listener: Listener): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

// --- connection status, readable from any component ---------------------------

export type LinkStatus = "connecting" | "live" | "offline";
let status: LinkStatus = "connecting";
const statusListeners = new Set<() => void>();

function setStatus(next: LinkStatus) {
  if (next === status) return;
  status = next;
  statusListeners.forEach((l) => l());
}

/** "live" while the realtime connection is up. */
export function useLinkStatus(): LinkStatus {
  return useSyncExternalStore(
    (cb) => {
      statusListeners.add(cb);
      return () => statusListeners.delete(cb);
    },
    () => status,
  );
}

// --- cache updates --------------------------------------------------------------

/** Queries that show live data; refetched after any gap in the connection. */
function refreshLive(client: QueryClient) {
  client.invalidateQueries({ queryKey: ["print"], predicate: (q) => q.queryKey[1] !== "quote" });
  client.invalidateQueries({ queryKey: ["canteen"] });
  client.invalidateQueries({ queryKey: ["today"] });
  client.invalidateQueries({ queryKey: ["clock"] });
}

/** Which cached queries each event makes stale. */
function invalidate(client: QueryClient, event: RealtimeEvent) {
  switch (event.type) {
    case "settings.updated":
      // Demo time or thresholds changed: everything time- or setting-based is stale.
      client.invalidateQueries();
      break;
    case "memory.updated":
      // Refresh the list only: a search marks memories as used, which sends this event,
      // so refetching the search here would loop.
      client.invalidateQueries({ queryKey: ["memory", "list"] });
      break;
    case "demo.reset":
      // Someone pressed "Reset demo": all data was re-seeded, so refetch everything.
      client.invalidateQueries();
      break;
    case "print.created":
    case "print.updated":
      // Quotes are left to their own 30-second refresh: the paying student's quote
      // refers to an upload the new job just consumed, so refetching it would fail.
      client.invalidateQueries({ queryKey: ["print"], predicate: (q) => q.queryKey[1] !== "quote" });
      client.invalidateQueries({ queryKey: ["today"] });
      client.invalidateQueries({ queryKey: ["collect"] });
      break;
    case "order.created":
    case "order.updated":
    case "menu.updated":
      // Unlike print, a canteen quote uses nothing up, so refresh it too: the receipt and
      // the pay button must show today's price and stock.
      client.invalidateQueries({ queryKey: ["canteen"] });
      if (event.type !== "menu.updated") client.invalidateQueries({ queryKey: ["today"] });
      if (event.type !== "menu.updated") client.invalidateQueries({ queryKey: ["collect"] });
      break;
    default:
      break;
  }
}

const PING_EVERY_MS = 15_000;
const PONG_WITHIN_MS = 6_000;
const POLL_WHILE_OFFLINE_MS = 10_000;

/**
 * One WebSocket per session, kept honest:
 * - pings every 15 s; no pong within 6 s means the connection is dead (common after a
 *   phone sleeps or a laptop lid closes) and it reconnects at once;
 * - reconnects immediately when the tab becomes visible or the network comes back;
 * - after any gap, refetches live data so missed events don't leave the screen stale;
 * - while offline, refetches live data every 10 s as a fallback.
 * `sessionKey` changes on login/logout so the socket picks up the new cookie.
 */
export function useRealtime(sessionKey: string) {
  const client = useQueryClient();

  useEffect(() => {
    let socket: WebSocket | null = null;
    let retry: ReturnType<typeof setTimeout> | undefined;
    let pongTimer: ReturnType<typeof setTimeout> | undefined;
    let attempts = 0;
    let stopped = false;
    let hadConnection = false;

    function drop(current: WebSocket) {
      current.onopen = current.onmessage = current.onclose = current.onerror = null;
      try {
        current.close();
      } catch {
        /* already closed */
      }
    }

    function connect() {
      if (stopped) return;
      clearTimeout(retry);
      clearTimeout(pongTimer);
      if (socket) drop(socket);
      setStatus(hadConnection ? "offline" : "connecting");
      const scheme = location.protocol === "https:" ? "wss" : "ws";
      const current = new WebSocket(`${scheme}://${location.host}/ws`);
      socket = current;

      current.onopen = () => {
        if (hadConnection) refreshLive(client);
        hadConnection = true;
        attempts = 0;
        setStatus("live");
      };
      current.onmessage = (message) => {
        clearTimeout(pongTimer);
        try {
          const event = JSON.parse(message.data) as RealtimeEvent;
          if (event.type === "pong") return;
          invalidate(client, event);
          listeners.forEach((listener) => listener(event));
        } catch {
          /* ignore malformed messages */
        }
      };
      current.onclose = () => {
        if (socket !== current || stopped) return;
        setStatus("offline");
        const delay = Math.min(15_000, 1_000 * 2 ** attempts) + Math.random() * 500;
        attempts += 1;
        retry = setTimeout(connect, delay);
      };
    }

    /** Ping; if the server doesn't answer quickly, treat the socket as dead. */
    function check() {
      if (stopped) return;
      if (!socket || socket.readyState === WebSocket.CLOSED) {
        connect();
        return;
      }
      if (socket.readyState !== WebSocket.OPEN) return;
      try {
        socket.send("ping");
      } catch {
        connect();
        return;
      }
      clearTimeout(pongTimer);
      pongTimer = setTimeout(() => {
        attempts = 0;
        connect();
      }, PONG_WITHIN_MS);
    }

    /** Woke up or came back online: verify the link now and catch up on missed events. */
    function onWake() {
      if (document.visibilityState !== "visible") return;
      attempts = 0;
      refreshLive(client);
      check();
    }

    const ping = setInterval(check, PING_EVERY_MS);
    const poll = setInterval(() => {
      if (status !== "live") refreshLive(client);
    }, POLL_WHILE_OFFLINE_MS);

    connect();
    document.addEventListener("visibilitychange", onWake);
    window.addEventListener("online", onWake);
    window.addEventListener("focus", onWake);
    return () => {
      stopped = true;
      clearTimeout(retry);
      clearTimeout(pongTimer);
      clearInterval(ping);
      clearInterval(poll);
      document.removeEventListener("visibilitychange", onWake);
      window.removeEventListener("online", onWake);
      window.removeEventListener("focus", onWake);
      if (socket) drop(socket);
    };
  }, [client, sessionKey]);
}
