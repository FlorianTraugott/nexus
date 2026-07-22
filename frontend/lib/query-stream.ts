// Fetch-based SSE client for POST /api/v1/query/stream.
//
// The browser's native EventSource is GET-only and cannot send a JSON body or
// an Authorization header, so it cannot consume this endpoint; the stream is
// read with fetch + ReadableStream and the SSE frames parsed by hand. The
// backend's wire format (app/api/v1/query.py::_sse) is exactly
// `data: <json>\n\n` — data: lines only, blank-line delimited, no
// event:/id:/heartbeats — and the parser is deliberately STRICT about that: a
// frame that doesn't parse, an unknown `type`, or a stream that ends without a
// terminal frame THROWS instead of being skipped. Silently dropping a frame is
// the "answer ended" vs "server died" ambiguity the backend's typed error
// frame exists to prevent.
//
// Auth: this module does NOT own refresh. It attaches the current access
// token, and on a pre-stream 401 it JOINS the app's single in-flight refresh
// via refreshAccessToken() (lib/api.ts) and retries the whole POST exactly
// once — mirroring the axios interceptor's retry-once. Once the response is
// streaming, auth is settled: a mid-stream failure is a stream failure (or the
// backend's typed `error` frame, which is yielded as data), never an auth
// retry. Refresh failures propagate as-is: SessionExpiredError for a truly
// dead session, the raw error otherwise.

import { API_BASE_URL, refreshAccessToken } from "@/lib/api";
import { getAccessToken } from "@/lib/tokens";
import type { QueryRequest, StreamEvent } from "@/types/api";

const STREAM_URL = `${API_BASE_URL}/api/v1/query/stream`;

const DATA_PREFIX = "data: ";
const FRAME_DELIMITER = "\n\n";

// The five frame types the backend emits; anything else is a malformed frame.
const EVENT_TYPES = [
  "metadata",
  "token",
  "done",
  "abstained",
  "error",
] as const satisfies readonly StreamEvent["type"][];

const TERMINAL_TYPES: readonly StreamEvent["type"][] = [
  "done",
  "abstained",
  "error",
];

/** Thrown when /query/stream responds non-2xx (after the one 401-refresh
 *  retry). Carries the status so the UI can map it (401, 404, 422, 429, …). */
export class StreamHttpError extends Error {
  constructor(
    public readonly status: number,
    detail: string | null,
  ) {
    super(detail ?? `Stream request failed with status ${status}`);
    this.name = "StreamHttpError";
  }
}

/** Thrown when the byte stream violates the SSE contract: a frame that isn't
 *  `data: <json>`, an unknown `type`, or EOF without a terminal frame. */
export class StreamProtocolError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "StreamProtocolError";
  }
}

function parseFrame(frame: string): StreamEvent {
  if (!frame.startsWith(DATA_PREFIX)) {
    throw new StreamProtocolError(
      `Malformed SSE frame (no data: prefix): ${frame.slice(0, 80)}`,
    );
  }
  let parsed: unknown;
  try {
    parsed = JSON.parse(frame.slice(DATA_PREFIX.length));
  } catch {
    throw new StreamProtocolError(
      `SSE frame payload is not valid JSON: ${frame.slice(0, 80)}`,
    );
  }
  const type = (parsed as { type?: unknown }).type;
  if (
    typeof type !== "string" ||
    !(EVENT_TYPES as readonly string[]).includes(type)
  ) {
    throw new StreamProtocolError(`Unknown SSE event type: ${String(type)}`);
  }
  return parsed as StreamEvent;
}

// POST the stream request with the current access token; on a pre-stream 401,
// join the shared refresh and retry the whole request exactly once. A 401 on
// the retry falls through to the caller as a StreamHttpError — no loop.
async function requestStream(
  request: QueryRequest,
  signal?: AbortSignal,
): Promise<Response> {
  const doFetch = (token: string | null) =>
    fetch(STREAM_URL, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: JSON.stringify(request),
      signal,
    });

  let response = await doFetch(getAccessToken());
  if (response.status === 401) {
    const newToken = await refreshAccessToken();
    response = await doFetch(newToken);
  }
  return response;
}

/**
 * Stream a grounded answer as typed SSE events.
 *
 * Yields frames exactly as the backend sends them (including the terminal
 * `error` frame — it is data; the consumer decides rendering) and THROWS only
 * for genuine transport failures: non-2xx HTTP, an aborted/failed body read, a
 * malformed frame, or EOF without a terminal frame. Cancel by aborting
 * `signal` or breaking out of the for-await loop (both cancel the body read).
 */
export async function* streamQuery(
  request: QueryRequest,
  signal?: AbortSignal,
): AsyncGenerator<StreamEvent, void, undefined> {
  const response = await requestStream(request, signal);

  if (!response.ok) {
    // FastAPI error bodies are {"detail": ...}; fall back to the bare status.
    let detail: string | null = null;
    try {
      const body = (await response.json()) as { detail?: unknown };
      if (typeof body.detail === "string") detail = body.detail;
    } catch {
      // Non-JSON error body; the status alone will have to do.
    }
    throw new StreamHttpError(response.status, detail);
  }
  if (!response.body) {
    throw new StreamProtocolError("Stream response has no body");
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let sawTerminal = false;

  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      // stream: true buffers a UTF-8 sequence split across chunks instead of
      // emitting a replacement char; the string buffer below does the same for
      // a frame split across chunks. Both splits are normal TCP behaviour.
      buffer += decoder.decode(value, { stream: true });

      let boundary: number;
      while ((boundary = buffer.indexOf(FRAME_DELIMITER)) !== -1) {
        const frame = buffer.slice(0, boundary);
        buffer = buffer.slice(boundary + FRAME_DELIMITER.length);
        const event = parseFrame(frame);
        if (TERMINAL_TYPES.includes(event.type)) {
          sawTerminal = true;
        }
        yield event;
      }
    }

    // Flush any partial UTF-8 sequence the decoder is still holding: if bytes
    // remain, the stream ended mid-frame and the leftovers surface here.
    buffer += decoder.decode();
    if (buffer.trim() !== "") {
      throw new StreamProtocolError("Stream ended with an incomplete frame");
    }
    // EOF without done/abstained/error means the server died without even
    // flushing its error frame — fail loudly, never report a truncated answer
    // as complete.
    if (!sawTerminal) {
      throw new StreamProtocolError(
        "Stream ended without a terminal frame (done/abstained/error)",
      );
    }
  } finally {
    // Runs on normal completion, on throw, and when the consumer breaks out of
    // its for-await (which calls .return() on the generator). cancel() tells
    // fetch to stop downloading the body; on an already-errored stream it
    // rejects with the stored error, which is best-effort cleanup noise here.
    await reader.cancel().catch(() => undefined);
  }
}
