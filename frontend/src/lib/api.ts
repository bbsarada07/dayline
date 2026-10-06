/** Fetch wrapper for /api: JSON in and out, 10-second timeout, plain-language errors. */

export const APP_NAME = __APP_NAME__;

const TIMEOUT_MS = 10_000;

export class ApiError extends Error {
  readonly code: string;
  readonly status: number;

  constructor(status: number, code: string, message: string) {
    super(message);
    this.status = status;
    this.code = code;
  }
}

type Options = { method?: string; body?: unknown; signal?: AbortSignal; timeoutMs?: number };

export async function api<T>(
  path: string,
  { method = "GET", body, signal, timeoutMs = TIMEOUT_MS }: Options = {},
): Promise<T> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort("timeout"), timeoutMs);
  const isForm = body instanceof FormData;
  signal?.addEventListener("abort", () => controller.abort(signal.reason));

  let response: Response;
  try {
    response = await fetch(`/api${path}`, {
      method,
      credentials: "same-origin",
      headers: body === undefined || isForm ? undefined : { "Content-Type": "application/json" },
      body: body === undefined ? undefined : isForm ? body : JSON.stringify(body),
      signal: controller.signal,
    });
  } catch {
    if (controller.signal.reason === "timeout") {
      throw new ApiError(0, "timeout", "The server took too long to answer. Check your connection and try again.");
    }
    throw new ApiError(0, "network", `Can't reach ${APP_NAME}. Check you're on the same Wi-Fi as the server, then try again.`);
  } finally {
    clearTimeout(timer);
  }

  const data = await response.json().catch(() => null);
  if (!response.ok) {
    const error = data?.error;
    throw new ApiError(
      response.status,
      error?.code ?? "error",
      error?.message ?? "Something went wrong on the server. Please try again.",
    );
  }
  return data as T;
}

export function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "Something went wrong. Please try again.";
}
