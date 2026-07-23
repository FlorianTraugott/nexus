// The conversation delete mutation. Mirrors useDeleteDocument: invalidates the
// list on a real delete; the 404 "already gone" policy stays in the caller's
// onError so a 404 from a genuine bug is never laundered into success.

import { useMutation, useQueryClient } from "@tanstack/react-query";

import { deleteConversation } from "@/lib/conversations-api";

export function useDeleteConversation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => deleteConversation(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["conversations"] });
    },
  });
}
