// Domain policy for conversations (transport-free, mirrors lib/documents.ts):
// mapping persisted wire messages into the chat view's turn model.

import type { ChatTurn } from "@/hooks/use-chat";
import type { MessageRead } from "@/types/api";

// Pair flat, position-ordered messages into user+assistant turns. _persist_turn
// writes a turn atomically (user then assistant), so pairing is by adjacency;
// the loop is tolerant anyway — an unpaired user tail or a stray assistant
// message becomes its own turn rather than crashing hydration. "system" is in
// the enum but never persisted by the query path; skipped defensively.
//
// A persisted abstention is indistinguishable on the wire from a normal answer
// (no stored flag; string-matching the backend's fixed copy would be policy
// built on an implementation detail), so every hydrated turn is status "done".
// The honest fix is a backend abstention flag — a recorded deferral.
export function mapMessagesToTurns(messages: MessageRead[]): ChatTurn[] {
  const turns: ChatTurn[] = [];
  let open: ChatTurn | null = null;
  for (const m of messages) {
    if (m.role === "user") {
      open = {
        id: turns.length,
        question: m.content,
        answer: "",
        citations: [],
        status: "done",
      };
      turns.push(open);
    } else if (m.role === "assistant") {
      if (open && open.answer === "") {
        open.answer = m.content;
        open.citations = m.citations ?? [];
      } else {
        turns.push({
          id: turns.length,
          question: "",
          answer: m.content,
          citations: m.citations ?? [],
          status: "done",
        });
      }
      open = null;
    }
  }
  return turns;
}
