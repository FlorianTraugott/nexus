// The document upload mutation. On success it invalidates ["documents"] so the
// list refetches, the new (non-terminal) doc appears, and the 9D.1b status
// polling re-arms on its own — the upload just triggers that lifecycle from the
// browser.

import { useMutation, useQueryClient } from "@tanstack/react-query";

import { uploadDocument } from "@/lib/documents-api";

export function useUploadDocument() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (file: File) => uploadDocument(file),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["documents"] });
    },
  });
}
