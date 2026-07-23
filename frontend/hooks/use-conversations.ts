// The conversation list query (sidebar). Plain fetch, no polling — the list
// changes only through this client's own creates/deletes, which invalidate it.

import { useQuery } from "@tanstack/react-query";

import { listConversations } from "@/lib/conversations-api";

export function useConversations() {
  return useQuery({
    queryKey: ["conversations"],
    queryFn: listConversations,
  });
}
