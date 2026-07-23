// The documents list query. Status-aware polling (9D.1b): poll while any doc is
// still ingesting, and self-stop once every doc is terminal. The backend already
// returns newest-first (list_user_documents orders by created_at desc), so no
// client-side sort here.

import { useQuery } from "@tanstack/react-query";

import { listDocuments } from "@/lib/documents-api";
import { isTerminalDocumentStatus } from "@/lib/documents";

const POLL_INTERVAL_MS = 2000;

export function useDocuments() {
  return useQuery({
    queryKey: ["documents"],
    queryFn: listDocuments,
    // refetchInterval as a FUNCTION OF THE DATA (v5: the callback gets the Query,
    // data via query.state.data, which is DocumentRead[] | undefined before the
    // first successful fetch). Poll only while a doc is still ingesting; return
    // false once all are terminal so it self-stops. undefined/[] => false: no
    // known in-flight work, so no polling until a fetch says otherwise.
    refetchInterval: (query) => {
      const docs = query.state.data;
      const anyInFlight = docs?.some((d) => !isTerminalDocumentStatus(d.status));
      return anyInFlight ? POLL_INTERVAL_MS : false;
    },
  });
}
