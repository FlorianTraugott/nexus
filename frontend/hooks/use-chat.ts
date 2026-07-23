// The chat transcript + stream drive (Chat.2). Hand-rolled on purpose: React
// Query models request -> one settled result, not an incremental token feed, so
// the async generator from lib/query-stream.ts is consumed directly and the
// transcript lives in component state.
//
// Every turn is STATELESS (no conversation_id): the backend neither rewrites
// follow-ups nor persists anything, and the transcript resets on navigation.
// Sessions are Chat.3.

import { useCallback, useEffect, useRef, useState } from "react";

import { streamQuery } from "@/lib/query-stream";
import { mapStreamError, STREAM_FAILED_MESSAGE } from "@/lib/chat-forms";
import type { Citation } from "@/types/api";

// "cancelled" is its own bucket, like "abstained": a deliberate abort is not a
// failure and must never render as one (Chat.3's Stop button inherits this).
export type ChatTurnStatus =
  | "streaming"
  | "done"
  | "abstained"
  | "error"
  | "cancelled";

export interface ChatTurn {
  id: number;
  question: string;
  answer: string;
  citations: Citation[];
  status: ChatTurnStatus;
  errorMessage?: string;
}

// initialTurns SEED the transcript once, at mount (hydration from a persisted
// conversation): useState reads its initializer on first render only, so a
// caller re-rendering with different initialTurns has NO effect — deliberate,
// a background refetch can never clobber a live transcript. Re-seeding happens
// only by remount (the caller keys the component by its ROUTE PARAM).
export function useChat(initialTurns: ChatTurn[] = []) {
  const [turns, setTurns] = useState<ChatTurn[]>(initialTurns);
  const [isStreaming, setIsStreaming] = useState(false);
  // One controller per in-flight send; null when nothing is streaming. Also the
  // "one stream at a time" guard.
  const controllerRef = useRef<AbortController | null>(null);
  // Hydrated turns occupy ids 0..n-1; live turns continue from n.
  const nextId = useRef(initialTurns.length);

  // Abort any in-flight stream on unmount: stops the download and settles the
  // generator's finally. Safe under dev StrictMode's mount->cleanup->mount:
  // no send can have happened before first paint, so the ref is null and the
  // extra cleanup is a no-op (verified, not assumed — see Chat.2 verification).
  useEffect(() => {
    return () => controllerRef.current?.abort();
  }, []);

  const send = useCallback(async (question: string) => {
    if (controllerRef.current) return; // one stream at a time
    const controller = new AbortController();
    controllerRef.current = controller;
    setIsStreaming(true);

    const id = nextId.current++;
    setTurns((prev) => [
      ...prev,
      { id, question, answer: "", citations: [], status: "streaming" },
    ]);
    const update = (patch: (turn: ChatTurn) => ChatTurn) =>
      setTurns((prev) => prev.map((t) => (t.id === id ? patch(t) : t)));

    try {
      for await (const event of streamQuery({ question }, controller.signal)) {
        switch (event.type) {
          case "metadata":
            // Retrieval is settled before the first token; sources render now.
            update((t) => ({ ...t, citations: event.citations }));
            break;
          case "token":
            update((t) => ({ ...t, answer: t.answer + event.text }));
            break;
          case "done":
            update((t) => ({ ...t, status: "done" }));
            break;
          case "abstained":
            update((t) => ({ ...t, answer: event.answer, status: "abstained" }));
            break;
          case "error":
            // The backend's typed frame: tokens already shown STAY; the fixed
            // copy marks the answer as incomplete.
            update((t) => ({
              ...t,
              status: "error",
              errorMessage: STREAM_FAILED_MESSAGE,
            }));
            break;
        }
      }
    } catch (err) {
      if (controller.signal.aborted) {
        // OUR abort (unmount today, Stop button in Chat.3): cancellation, not
        // failure — regardless of what error shape the abort surfaced as.
        update((t) => ({ ...t, status: "cancelled" }));
      } else {
        update((t) => ({
          ...t,
          status: "error",
          errorMessage: mapStreamError(err),
        }));
      }
    } finally {
      controllerRef.current = null;
      setIsStreaming(false);
    }
  }, []);

  return { turns, isStreaming, send };
}
