// One conversation with its messages — the hydration source for /chat/[id].
//
// staleTime: Infinity is load-bearing: once mounted, the ChatView's LOCAL turn
// state is the live source of truth (new turns stream into it), so a background
// refetch of this query must never fire mid-session and re-render stale data
// under the transcript. The cache entry is invalidated after a persisted turn
// settles (Chat.3b), so the NEXT mount refetches fresh.

import { useQuery } from "@tanstack/react-query";

import { getConversation } from "@/lib/conversations-api";

export function useConversation(id: string) {
  return useQuery({
    queryKey: ["conversations", id],
    queryFn: () => getConversation(id),
    staleTime: Infinity,
  });
}
