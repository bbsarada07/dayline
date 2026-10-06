import { ApiError, APP_NAME } from "@/lib/api";
import type { TraceEvent } from "@/lib/types";

/** A run can call several agents in turn; give it time, but not forever. */
const RUN_TIMEOUT_MS = 120_000;

export type ChatBody = { message: string; conversation_id?: string; upload_id?: string; voice?: boolean };

/**
 * POST /api/agent/chat and read its Server-Sent Events as they arrive.
 * EventSource can't POST, so this reads the response body stream by hand.
 */
export async function streamChat(body: ChatBody, onEvent: (event: TraceEvent) => void, signal?: AbortSignal) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort("timeout"), RUN_TIMEOUT_MS);
  signal?.addEventListener("abort", () => controller.abort(signal.reason));

  try {
    let response: Response;
    try {
      response = await fetch("/api/agent/chat", {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
        body: JSON.stringify(body),
        signal: controller.signal,
      });
    } catch {
      throw new ApiError(0, "network", `Can't reach ${APP_NAME}. Check your connection and try again.`);
    }
    if (!response.ok || !response.body) {
      const data = await response.json().catch(() => null);
      throw new ApiError(response.status, data?.error?.code ?? "error", data?.error?.message ?? "Dayline couldn't answer. Try again.");
    }

    const reader = response.body.pipeThrough(new TextDecoderStream()).getReader();
    let buffer = "";
    for (;;) {
      let chunk: ReadableStreamReadResult<string>;
      try {
        chunk = await reader.read();
      } catch {
        if (controller.signal.reason === "timeout") throw new ApiError(0, "timeout", "Dayline took too long. Try again.");
        throw new ApiError(0, "network", "The connection dropped. Try again.");
      }
      if (chunk.done) break;
      buffer += chunk.value.replace(/\r\n/g, "\n");
      let end: number;
      while ((end = buffer.indexOf("\n\n")) !== -1) {
        const block = buffer.slice(0, end);
        buffer = buffer.slice(end + 2);
        const type = /^event: (.+)$/m.exec(block)?.[1];
        const data = /^data: (.*)$/m.exec(block)?.[1];
        if (type && data) onEvent({ ...JSON.parse(data), type } as TraceEvent);
      }
    }
  } finally {
    clearTimeout(timer);
  }
}
