/**
 * SSE streaming client for the chat endpoint.
 *
 * The backend sends `data: <json>` lines (standard SSE format, single-event type).
 * We do a hand-rolled line parser (~30 lines) to keep deps lean.
 *
 * Usage:
 *   const abort = new AbortController();
 *   await streamChat("What is photosynthesis?", sessionId, {
 *     onEvent: (event) => { ... },
 *     signal: abort.signal,
 *   });
 */

import {
  ApiError,
  type ApiErrorEnvelope,
  type ChatEvent,
} from "./types";

const BASE_URL =
  (process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000").replace(/\/$/, "");

export interface StreamChatOptions {
  /** Called for every parsed ChatEvent (including SessionIdEvent, StepEvent, etc.) */
  onEvent: (event: ChatEvent) => void;
  /** Optional AbortController signal — call abort.abort() to cancel mid-stream */
  signal?: AbortSignal;
}

/**
 * POST /chat and stream SSE events to `onEvent`.
 *
 * - Non-200 response → parse error envelope → throw ApiError BEFORE streaming.
 * - [DONE] sentinel → resolve.
 * - Stream end without [DONE] → also resolve (graceful).
 * - AbortError propagates to caller.
 */
export async function streamChat(
  question: string,
  sessionId: string,
  options: StreamChatOptions
): Promise<void> {
  const { onEvent, signal } = options;

  const res = await fetch(`${BASE_URL}/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ question, session_id: sessionId }),
    signal,
  });

  // Non-200 comes as a plain JSON error envelope (e.g. 400 GUARDRAIL_BLOCKED)
  // Handle it BEFORE touching the body as a stream.
  if (!res.ok) {
    let body: unknown;
    try {
      body = await res.json();
    } catch {
      throw new ApiError("UNKNOWN", res.statusText || "Chat request failed", res.status);
    }
    const envelope = body as Partial<ApiErrorEnvelope>;
    const code = envelope?.error?.code ?? "UNKNOWN";
    const message = envelope?.error?.message ?? "Chat request failed";
    throw new ApiError(code, message, res.status);
  }

  if (!res.body) {
    throw new ApiError("UNKNOWN", "Response has no body", 0);
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });

    // SSE lines are separated by \n. Process complete lines.
    const lines = buffer.split("\n");
    // Keep the last (potentially incomplete) fragment in buffer
    buffer = lines.pop() ?? "";

    for (const line of lines) {
      const trimmed = line.trim();
      if (!trimmed) continue;          // blank lines between events — skip

      if (trimmed.startsWith("data:")) {
        const payload = trimmed.slice(5).trim();

        if (payload === "[DONE]") {
          reader.cancel();
          return;
        }

        // Parse and dispatch the event
        let parsed: unknown;
        try {
          parsed = JSON.parse(payload);
        } catch {
          // Malformed line — skip silently
          continue;
        }

        onEvent(parsed as ChatEvent);
      }
      // Other SSE fields (event:, id:, retry:) — not used by this backend, skip
    }
  }

  // Stream ended without [DONE] — that's fine, just resolve
}
