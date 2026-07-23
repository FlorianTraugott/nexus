// One conversation with its messages — the hydration source for /chat/[id].
//
// staleTime: Infinity is load-bearing: once mounted, the ChatView's LOCAL turn
// state is the live source of truth (new turns stream into it), so a background
// refetch of this query must never fire mid-session and re-render stale data
// under the transcript. The cache entry is invalidated after a persisted turn
// settles (Chat.3b), so the NEXT mount refetches fresh.

import { useQuery } from "@tanstack/react-query";
import { isAxiosError } from "axios";

import { getConversation } from "@/lib/conversations-api";

export function useConversation(id: string) {
  return useQuery({
    queryKey: ["conversations", id],
    queryFn: () => getConversation(id),
    staleTime: Infinity,
    retry: (failureCount, error) => {
      // A 4xx (404 especially) is a definitive answer, not a transient fault:
      // the installed query-core default (3 retries, exponential backoff)
      // delayed the not-found state by ~7s. Deliberate small duplication with
      // use-research-task.ts — a shared home can come when a third caller
      // earns it.
      const status = isAxiosError(error) ? error.response?.status : undefined;
      if (status !== undefined && status >= 400 && status < 500) return false;
      return failureCount < 3;
    },
  });
}
