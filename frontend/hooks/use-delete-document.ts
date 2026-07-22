// The document delete mutation. Mirrors useUploadDocument, inverted: on a real
// delete it invalidates ["documents"] so the row drops from the list.
//
// The 404 "already gone" policy is NOT here and NOT in deleteDocument — both stay
// honest. The caller's onError decides it (invalidate + close, no alert), so a
// 404 from a genuine bug (wrong id) is never laundered into a success.

import { useMutation, useQueryClient } from "@tanstack/react-query";

import { deleteDocument } from "@/lib/documents-api";

export function useDeleteDocument() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => deleteDocument(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["documents"] });
    },
  });
}
