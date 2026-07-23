// The conversation create mutation. The LIST invalidation lives here — one
// home: the conversation exists server-side the moment the POST returns, so
// the sidebar refreshes immediately (mid-stream on a first send), never lagged
// to turn-settle. (Detail invalidation is separate and settle-timed — see
// ChatView.) The variables carry an optional AbortSignal so a Stop during the
// create round-trip cancels the HTTP request too (best-effort: if the abort
// loses the race to the server, an orphan empty conversation can exist — a
// recorded limitation).

import { useMutation, useQueryClient } from "@tanstack/react-query";

import { createConversation } from "@/lib/conversations-api";
import type { ConversationRead } from "@/types/api";

export function useCreateConversation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      title,
      signal,
    }: {
      title?: string;
      signal?: AbortSignal;
    }): Promise<ConversationRead> => createConversation({ title }, signal),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["conversations"] });
    },
  });
}
