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
  // From the live metadata frame only — never stored on the wire, so hydrated
  // turns don't have it. Rendered ("Searched for: …") only when it differs
  // from the question.
  rewritten_question?: string | null;
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

  // The whole turn lifecycle lives here (Option A): the turn is appended
  // IMMEDIATELY, then the conversation id is resolved via the injected
  // ensureConversationId (the PAGE owns what ensure does — create, title,
  // replaceState — the hook owns when it runs), then the stream drives the
  // turn to a settled status, which is returned so the caller can decide
  // invalidation ("done"/"abstained" = persisted server-side). null = not
  // dispatched (a stream was already in flight).
  //
  // The AbortController is created BEFORE ensure is awaited: from the moment
  // the turn appears, Stop and unmount abort a REAL controller — otherwise a
  // Stop landing during the create round-trip would abort nothing and the
  // answer would stream anyway, and an unmount in that window would let the
  // hook stream into an unmounted component. The signal is also passed to
  // ensure so an abort cancels the create HTTP request itself (best-effort).
  //
  // Contract: an Error thrown by ensureConversationId carries a DISPLAY-READY
  // message (the page owns create policy and its error copy); it becomes the
  // turn's error text.
  const send = useCallback(
    async (
      question: string,
      ensureConversationId: (signal: AbortSignal) => Promise<string>,
    ): Promise<ChatTurnStatus | null> => {
      if (controllerRef.current) return null; // one stream at a time
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
      const cancel = (): ChatTurnStatus => {
        update((t) => ({ ...t, status: "cancelled" }));
        return "cancelled";
      };

      try {
        let conversationId: string;
        try {
          conversationId = await ensureConversationId(controller.signal);
        } catch (err) {
          if (controller.signal.aborted) return cancel();
          update((t) => ({
            ...t,
            status: "error",
            errorMessage:
              err instanceof Error && err.message
                ? err.message
                : "Couldn’t start the conversation. Please try again.",
          }));
          return "error";
        }
        // An abort that raced ensure's resolution: bail before any stream —
        // the user pressed Stop, so no answer may start after it.
        if (controller.signal.aborted) return cancel();

        // Pessimistic default is unreachable in practice: the strict stream
        // client throws on EOF without a terminal frame, so the loop only
        // completes after a terminal frame has set `settled`.
        let settled: ChatTurnStatus = "error";
        try {
          for await (const event of streamQuery(
            { question, conversation_id: conversationId },
            controller.signal,
          )) {
            switch (event.type) {
              case "metadata":
                // Retrieval is settled before the first token; sources render
                // now. rewritten_question exists only on this live frame.
                update((t) => ({
                  ...t,
                  citations: event.citations,
                  rewritten_question: event.rewritten_question,
                }));
                break;
              case "token":
                update((t) => ({ ...t, answer: t.answer + event.text }));
                break;
              case "done":
                settled = "done";
                update((t) => ({ ...t, status: "done" }));
                break;
              case "abstained":
                settled = "abstained";
                update((t) => ({
                  ...t,
                  answer: event.answer,
                  status: "abstained",
                }));
                break;
              case "error":
                // The backend's typed frame: tokens already shown STAY; the
                // fixed copy marks the answer as incomplete.
                settled = "error";
                update((t) => ({
                  ...t,
                  status: "error",
                  errorMessage: STREAM_FAILED_MESSAGE,
                }));
                break;
            }
          }
          return settled;
        } catch (err) {
          if (controller.signal.aborted) {
            // OUR abort (Stop button / unmount): cancellation, not failure —
            // regardless of what error shape the abort surfaced as.
            return cancel();
          }
          update((t) => ({
            ...t,
            status: "error",
            errorMessage: mapStreamError(err),
          }));
          return "error";
        }
      } finally {
        controllerRef.current = null;
        setIsStreaming(false);
      }
    },
    [],
  );

  // Stop = abort the in-flight controller; the send flow routes the abort into
  // the "cancelled" bucket wherever it lands (create window or mid-stream).
  const stop = useCallback(() => {
    controllerRef.current?.abort();
  }, []);

  return { turns, isStreaming, send, stop };
}
