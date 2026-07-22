// The documents list query. A PLAIN fetch for 9D.1a — no refetchInterval; the
// status-aware polling lands in 9D.1b. The backend already returns newest-first
// (list_user_documents orders by created_at desc), so no client-side sort here.

import { useQuery } from "@tanstack/react-query";

import { listDocuments } from "@/lib/documents-api";

export function useDocuments() {
  return useQuery({ queryKey: ["documents"], queryFn: listDocuments });
}
