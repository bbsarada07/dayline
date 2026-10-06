/**
 * Logins are an httpOnly cookie, so every tab of one browser shares one login.
 * Tabs tell each other when the login changes so none keeps showing an old account.
 */
import type { Me } from "./types";

const channel = typeof BroadcastChannel !== "undefined" ? new BroadcastChannel("dayline-session") : null;

export type SessionMessage = { me: Pick<Me, "kind" | "id" | "name" | "role"> | null };

export function announceSession(me: Me | null) {
  channel?.postMessage({ me: me && { kind: me.kind, id: me.id, name: me.name, role: me.role } } satisfies SessionMessage);
}

export function onSessionChange(listener: (message: SessionMessage) => void): () => void {
  if (!channel) return () => {};
  const handler = (event: MessageEvent<SessionMessage>) => listener(event.data);
  channel.addEventListener("message", handler);
  return () => channel.removeEventListener("message", handler);
}

/**
 * Cookies are per host name, so localhost and 127.0.0.1 hold separate logins.
 * Returns the other address for this computer, or null when there isn't one.
 */
export function secondLoginUrl(): string | null {
  const { protocol, hostname, port } = window.location;
  const other = hostname === "localhost" ? "127.0.0.1" : hostname === "127.0.0.1" ? "localhost" : null;
  return other ? `${protocol}//${other}${port ? `:${port}` : ""}/login` : null;
}
