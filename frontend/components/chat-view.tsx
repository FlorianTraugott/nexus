"use client";

// The conversation surface shared by /chat (new chat) and /chat/[id] (existing
// conversation, hydrated via initialTurns). Route protection and the sidebar
// live in app/chat/layout.tsx.
//
// KEYING CONTRACT: the caller keys this component by its MOUNT IDENTITY — the
// route param ([id] page) or nothing at all (/chat). Chat.3b's lazily-created
// live conversation id is internal state and must NEVER back the key: feeding
// it in would remount this view mid-first-send and abort its own stream.

import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type FormEvent,
} from "react";
import { useQueryClient } from "@tanstack/react-query";

import { useChat, type ChatTurn } from "@/hooks/use-chat";
import { useCreateConversation } from "@/hooks/use-create-conversation";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { mapCreateConversationError } from "@/lib/conversations-forms";
import { cn } from "@/lib/utils";
import type { Citation } from "@/types/api";

// Conversation titles are the first question, truncated (backend cap is 255;
// 60 keeps the sidebar readable).
const TITLE_MAX_CHARS = 60;

// How close to the bottom still counts as "following along".
const NEAR_BOTTOM_PX = 100;

const PREVIEW_MAX_CHARS = 220;

// The signature element, in two parts: an ultramarine RAIL down the answer marks
// it as grounded, and a horizontal INDEX of citation markers says in what. Both
// appear the moment the metadata frame lands — before the first token, which the
// SSE contract guarantees — so the sources visibly exist before the words do.
// An abstained turn keeps the rail in muted ink with no index: visibly
// ungrounded, which is honest, rather than visibly broken.
//
// The index is HORIZONTAL, and that is the whole point. Anything arranged
// vertically in the left gutter beside prose gets read as indexing that prose —
// as line numbers — and the collision is acute when the answer is itself a
// numbered list, putting two unrelated numbering systems side by side. Stacking
// the markers at the rail's head did not avoid that false mapping, it only moved
// it from source-to-paragraph to source-to-line. Spreading them further apart
// makes it worse, not better: the column then spans more of the answer and the
// positional reading strengthens. Horizontal enumeration reads as a set.
//
// Rendered as [n] to match exactly the markers the model emits inline, so the
// correspondence is self-evident without a label. (Those markers are emergent
// rather than instructed — see build_prompt; if they ever stop appearing this
// still works as a source index.)
function CitationIndex({ citations }: { citations: Citation[] }) {
  if (citations.length === 0) return null;
  return (
    // aria-hidden: the same numbering is conveyed accessibly by the sources list.
    <ol className="mb-3 flex flex-wrap gap-x-2.5 gap-y-1" aria-hidden="true">
      {citations.map((c, i) => (
        <li key={c.chunk_id} className="font-mono text-meta text-primary">
          [{i + 1}]
        </li>
      ))}
    </ol>
  );
}

// Numbered to match the answer's emergent [n] markers: the citations array
// order IS the numbered-passage order the prompt was built from.
//
// Ranked, not scored. The cosine distance is real and on the wire, but a raw
// distance is uninterpretable at a glance — no scale, no reference point, and
// LOWER means better, which reads backwards. Rank is what a reader can act on;
// the number stays available in the title for anyone who looks.
function Sources({ citations }: { citations: Citation[] }) {
  if (citations.length === 0) return null;
  return (
    <div className="mt-5">
      <p className="font-mono text-meta uppercase text-ink-2">
        Sources · {citations.length}
      </p>
      <ol className="mt-2.5 flex flex-col gap-2.5">
        {citations.map((c, i) => (
          <li
            key={c.chunk_id}
            className="grid grid-cols-[1.25rem_1fr] gap-3"
            title={`Rank ${i + 1} of ${citations.length} · cosine distance ${c.distance.toFixed(4)} (lower is more relevant)`}
          >
            <span className="font-mono text-meta text-primary">{i + 1}</span>
            <p className="text-sm text-ink-2">
              {c.content_preview.length > PREVIEW_MAX_CHARS
                ? `${c.content_preview.slice(0, PREVIEW_MAX_CHARS)}…`
                : c.content_preview}
            </p>
          </li>
        ))}
      </ol>
    </div>
  );
}

function TurnView({ turn }: { turn: ChatTurn }) {
  const abstained = turn.status === "abstained";
  return (
    <article className="flex flex-col gap-4">
      <h2 className="text-section text-balance">{turn.question}</h2>
      {turn.rewritten_question != null &&
        turn.rewritten_question !== turn.question && (
          // The standalone question retrieval actually used (follow-up rewrite).
          // Shown only when it differs; non-null-but-identical means "the
          // rewrite ran and changed nothing" — no badge for that.
          <p className="font-mono text-meta text-ink-2">
            <span className="uppercase">Searched for</span>{" "}
            {turn.rewritten_question}
          </p>
        )}
      {/* The rail is a border on the answer column, not a separate track: with
          the markers gone from the gutter there is nothing to hold there but a
          2px line, and a 28px column to show it wasted ~12% of a 375px
          viewport. It spans the answer AND its sources — they are one grounded
          unit. */}
      <div
        className={cn(
          "border-l-2 pl-5",
          abstained ? "border-border" : "border-primary/30",
        )}
      >
        <CitationIndex citations={turn.citations} />
        <div className="min-w-0">
          {abstained ? (
            // Abstention is its own visual bucket: not an answer, not a failure.
            <p className="font-reading text-reading text-ink-2 italic">
              {turn.answer}
            </p>
          ) : (
            (turn.answer || turn.status === "streaming") && (
              <p className="font-reading text-reading whitespace-pre-wrap">
                {turn.answer}
                {turn.status === "streaming" && (
                  <span className="ml-0.5 inline-block h-[1.1em] w-[2px] translate-y-[0.15em] animate-pulse bg-primary align-middle" />
                )}
              </p>
            )
          )}
          {turn.status === "cancelled" && (
            <p className="mt-2 font-mono text-meta uppercase text-ink-2">
              Stopped
            </p>
          )}
          {turn.status === "error" && (
            // Tokens already rendered stay above; the failure is explicit, never
            // a silent truncation.
            <Alert variant="destructive" className="mt-3">
              <AlertDescription>{turn.errorMessage}</AlertDescription>
            </Alert>
          )}
          <Sources citations={turn.citations} />
        </div>
      </div>
    </article>
  );
}

function Composer({
  isStreaming,
  onSend,
  onStop,
}: {
  isStreaming: boolean;
  onSend: (question: string) => void;
  onStop: () => void;
}) {
  const [question, setQuestion] = useState("");

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    const q = question.trim();
    if (!q || isStreaming) return;
    onSend(q);
    setQuestion("");
  }

  return (
    <div className="shrink-0 border-t bg-card px-6 py-4">
      <form
        onSubmit={onSubmit}
        className="mx-auto flex w-full max-w-[46rem] items-center gap-3"
      >
        <Input
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          placeholder="Ask a question about your documents…"
          disabled={isStreaming}
          autoFocus
          className="h-11"
        />
        {isStreaming ? (
          // Stop stays ENABLED while the input is locked — a user-initiated stop
          // lands in the "cancelled" bucket, never rendered as a failure.
          <Button
            type="button"
            variant="outline"
            size="lg"
            onClick={onStop}
            className="shrink-0"
          >
            Stop
          </Button>
        ) : (
          <Button
            type="submit"
            size="lg"
            disabled={!question.trim()}
            className="shrink-0"
          >
            Send
          </Button>
        )}
      </form>
    </div>
  );
}

export function ChatView({
  conversationId,
  initialTurns,
}: {
  conversationId?: string;
  initialTurns?: ChatTurn[];
}) {
  const { turns, isStreaming, send, stop } = useChat(initialTurns);
  const queryClient = useQueryClient();
  const createMutation = useCreateConversation();

  // The LIVE conversation id: request bodies + replaceState ONLY — it must
  // never back a React key (see the keying contract above). A ref, not state:
  // nothing renders from it. Starts as the mount identity when there is one.
  const liveIdRef = useRef<string | null>(conversationId ?? null);
  // Single-flight create: a concurrent first send must never create TWO
  // conversations (same hazard class as the token-refresh single-flight; the
  // disabled composer is too thin a guard for a server-side side effect).
  const createPromiseRef = useRef<Promise<string> | null>(null);

  const scrollRef = useRef<HTMLDivElement>(null);
  // Whether the reader was following along, measured at the LAST SCROLL EVENT —
  // which is necessarily BEFORE the content that triggers the effects below is
  // appended. Reading the position inside the effect would measure the DOM
  // after the append, when the new content has already pushed the bottom
  // further away, and the answer would be wrong in the direction that yanks.
  // Appending below the viewport does not move scrollTop, so it fires no scroll
  // event and cannot overwrite this value. Starts true: a fresh transcript is
  // at its bottom.
  const isNearBottomRef = useRef(true);

  const scrollToBottom = useCallback(() => {
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, []);

  function onTranscriptScroll() {
    const el = scrollRef.current;
    if (!el) return;
    isNearBottomRef.current =
      el.scrollHeight - el.scrollTop - el.clientHeight <= NEAR_BOTTOM_PX;
  }

  // A NEW TURN and an INCOMING TOKEN are different events and must not share an
  // effect — one rule would get the other case wrong.
  const turnCount = turns.length;
  const latestAnswer = turns[turnCount - 1]?.answer ?? "";

  // A turn the user just submitted scrolls to itself UNCONDITIONALLY: they
  // typed it, so they want to see it, wherever they happened to be reading.
  // Also covers mount, landing a hydrated conversation on its latest message.
  useEffect(() => {
    scrollToBottom();
  }, [turnCount, scrollToBottom]);

  // Tokens only follow if the reader was already at the bottom. Someone who
  // scrolled up to re-read an earlier turn must never be yanked back down.
  useEffect(() => {
    if (isNearBottomRef.current) scrollToBottom();
  }, [latestAnswer, scrollToBottom]);

  function ensureConversationId(
    question: string,
    signal: AbortSignal,
  ): Promise<string> {
    if (liveIdRef.current) return Promise.resolve(liveIdRef.current);
    if (!createPromiseRef.current) {
      createPromiseRef.current = (async () => {
        try {
          const conv = await createMutation.mutateAsync({
            title: question.slice(0, TITLE_MAX_CHARS),
            signal,
          });
          liveIdRef.current = conv.id;
          // The URL now reads /chat/{id} while the mount identity stays as it
          // was — deliberate: replaceState integrates with the Next router
          // (usePathname syncs, sidebar highlight moves) WITHOUT a remount, so
          // the stream this send is about to start survives. Resolves at the
          // next real navigation or reload.
          window.history.replaceState(null, "", `/chat/${conv.id}`);
          return conv.id;
        } catch (err) {
          if (signal.aborted) throw err; // abort is routed to "cancelled" upstream
          // Hook contract: a thrown ensure Error carries display-ready copy.
          throw new Error(mapCreateConversationError(err));
        } finally {
          createPromiseRef.current = null;
        }
      })();
    }
    return createPromiseRef.current;
  }

  async function handleSend(question: string) {
    const status = await send(question, (signal) =>
      ensureConversationId(question, signal),
    );
    // Split invalidation: the LIST refreshed at create time (mutation
    // onSuccess). The DETAIL refreshes only after a turn the backend actually
    // PERSISTED (done/abstained); error/cancelled persist nothing server-side,
    // so the cached detail is still accurate.
    const id = liveIdRef.current;
    if (id && (status === "done" || status === "abstained")) {
      queryClient.invalidateQueries({ queryKey: ["conversations", id] });
    }
  }

  return (
    <main className="flex min-h-0 min-w-0 flex-1 flex-col">
      <div
        ref={scrollRef}
        onScroll={onTranscriptScroll}
        className="min-h-0 flex-1 overflow-y-auto px-6 py-10"
      >
        <div className="mx-auto w-full max-w-[46rem]">
          {turns.length === 0 ? (
            <div className="pt-10">
              <h1 className="text-title text-balance">
                Ask your first question
              </h1>
              <p className="mt-3 max-w-prose text-sm text-ink-2">
                The answer streams in a word at a time, against a rail marking
                the passages it drew from. If nothing in your documents supports
                an answer, it says so instead of inventing one.
              </p>
            </div>
          ) : (
            <div className="flex flex-col gap-14">
              {turns.map((turn) => (
                <TurnView key={turn.id} turn={turn} />
              ))}
            </div>
          )}
        </div>
      </div>
      {/* Every send belongs to a conversation (created lazily on the first
          send of a fresh /chat). The stateless endpoint mode still exists on
          the backend; the UI no longer uses it. */}
      <Composer isStreaming={isStreaming} onSend={handleSend} onStop={stop} />
    </main>
  );
}
