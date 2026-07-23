"use client";

// Chat view (Chat.2): single-turn streaming Q&A over /query/stream. Each
// question is stateless and independent (no conversation_id); the transcript is
// page-local. Sessions, history, and a Stop button are Chat.3.

import { useState, type FormEvent } from "react";
import Link from "next/link";

import { useChat, type ChatTurn } from "@/hooks/use-chat";
import { ProtectedRoute } from "@/components/protected-route";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import type { Citation } from "@/types/api";

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
  disabled,
  onSend,
}: {
  disabled: boolean;
  onSend: (question: string) => void;
}) {
  const [question, setQuestion] = useState("");

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    const q = question.trim();
    if (!q || disabled) return;
    onSend(q);
    setQuestion("");
  }

  return (
    <form onSubmit={onSubmit} className="flex items-center gap-3">
      <Input
        value={question}
        onChange={(e) => setQuestion(e.target.value)}
        placeholder="Ask a question about your documents…"
        disabled={disabled}
        autoFocus
      />
      <Button type="submit" disabled={disabled || !question.trim()}>
        {disabled ? "Answering…" : "Send"}
      </Button>
    </form>
  );
}

export default function ChatPage() {
  const { turns, isStreaming, send } = useChat();

  return (
    <ProtectedRoute>
      <div className="flex min-h-full flex-1 flex-col">
        <main className="mx-auto flex w-full max-w-3xl flex-1 flex-col px-6 py-8">
          <div>
            <Link
              href="/"
              className="text-sm text-muted-foreground hover:text-foreground"
            >
              ← Workspace
            </Link>
            <h1 className="mt-2 font-heading text-xl font-medium">Chat</h1>
            <p className="mt-1 text-xs text-muted-foreground">
              Answers are grounded in your documents. Each question is answered
              independently — conversation memory arrives with sessions.
            </p>
          </div>
          <div className="mt-6 flex flex-1 flex-col gap-6">
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
            <Composer disabled={isStreaming} onSend={send} />
          </div>
        </main>
      </div>
    </ProtectedRoute>
  );
}
