"use client";

// The conversation surface shared by /chat (new chat) and /chat/[id] (existing
// conversation, hydrated via initialTurns). Extracted unchanged from the Chat.2
// page; route protection and the sidebar live in app/chat/layout.tsx.
//
// KEYING CONTRACT: the caller keys this component by its MOUNT IDENTITY — the
// route param ([id] page) or nothing at all (/chat). Chat.3b's lazily-created
// live conversation id is internal state and must NEVER back the key: feeding
// it in would remount this view mid-first-send and abort its own stream.

import { useRef, useState, type FormEvent } from "react";
import { useQueryClient } from "@tanstack/react-query";

import { useChat, type ChatTurn } from "@/hooks/use-chat";
import { useCreateConversation } from "@/hooks/use-create-conversation";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { mapCreateConversationError } from "@/lib/conversations-forms";
import type { Citation } from "@/types/api";

// Conversation titles are the first question, truncated (backend cap is 255;
// 60 keeps the sidebar readable).
const TITLE_MAX_CHARS = 60;

// Numbered to match the answer's emergent [n] markers: the citations array
// order IS the numbered-passage order the prompt was built from.
function Sources({ citations }: { citations: Citation[] }) {
  if (citations.length === 0) return null;
  return (
    <div className="mt-3 border-t pt-2">
      <p className="text-xs font-medium text-muted-foreground">
        Sources ({citations.length})
      </p>
      <ol className="mt-1 flex flex-col gap-1">
        {citations.map((c, i) => (
          <li key={c.chunk_id} className="text-xs text-muted-foreground">
            <span className="font-medium">[{i + 1}]</span>{" "}
            {c.content_preview.length > 160
              ? `${c.content_preview.slice(0, 160)}…`
              : c.content_preview}
          </li>
        ))}
      </ol>
    </div>
  );
}

function TurnView({ turn }: { turn: ChatTurn }) {
  return (
    <div className="flex flex-col gap-2">
      <div className="max-w-[85%] self-end rounded-lg bg-primary px-3 py-2 text-sm text-primary-foreground">
        {turn.question}
      </div>
      {turn.rewritten_question != null &&
        turn.rewritten_question !== turn.question && (
          // The standalone question retrieval actually used (follow-up rewrite).
          // Shown only when it differs; non-null-but-identical means "the
          // rewrite ran and changed nothing" — no badge for that.
          <p className="max-w-[85%] self-end text-xs text-muted-foreground">
            Searched for: {turn.rewritten_question}
          </p>
        )}
      <Card className="max-w-[85%] self-start py-0">
        <CardContent className="px-4 py-3">
          {turn.status === "abstained" ? (
            // Abstention is its own visual bucket: not an answer, not a failure.
            <p className="text-sm italic text-muted-foreground">{turn.answer}</p>
          ) : (
            (turn.answer || turn.status === "streaming") && (
              <p className="whitespace-pre-wrap text-sm">
                {turn.answer}
                {turn.status === "streaming" && (
                  <span className="animate-pulse">▍</span>
                )}
              </p>
            )
          )}
          {turn.status === "cancelled" && (
            <p className="mt-1 text-xs italic text-muted-foreground">Stopped.</p>
          )}
          {turn.status === "error" && (
            // Tokens already rendered stay above; the failure is explicit, never
            // a silent truncation.
            <Alert variant="destructive" className="mt-2">
              <AlertDescription>{turn.errorMessage}</AlertDescription>
            </Alert>
          )}
          <Sources citations={turn.citations} />
        </CardContent>
      </Card>
    </div>
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
    <form onSubmit={onSubmit} className="flex items-center gap-3">
      <Input
        value={question}
        onChange={(e) => setQuestion(e.target.value)}
        placeholder="Ask a question about your documents…"
        disabled={isStreaming}
        autoFocus
      />
      {isStreaming ? (
        // Stop stays ENABLED while the input is locked — a user-initiated stop
        // lands in the "cancelled" bucket, never rendered as a failure.
        <Button type="button" variant="outline" onClick={onStop}>
          Stop
        </Button>
      ) : (
        <Button type="submit" disabled={!question.trim()}>
          Send
        </Button>
      )}
    </form>
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
    <main className="mx-auto flex w-full max-w-3xl flex-1 flex-col px-6 py-8">
      <div className="flex flex-1 flex-col gap-6">
        {turns.length === 0 ? (
          <div className="rounded-xl border border-dashed p-10 text-center">
            <p className="text-sm font-medium">Ask your first question</p>
            <p className="mt-1 text-sm text-muted-foreground">
              The answer streams in live, with the sources it drew from.
            </p>
          </div>
        ) : (
          turns.map((turn) => <TurnView key={turn.id} turn={turn} />)
        )}
      </div>
      <div className="sticky bottom-0 mt-6 bg-background py-4">
        {/* Every send belongs to a conversation (created lazily on the first
            send of a fresh /chat). The stateless endpoint mode still exists on
            the backend; the UI no longer uses it. */}
        <Composer isStreaming={isStreaming} onSend={handleSend} onStop={stop} />
      </div>
    </main>
  );
}
