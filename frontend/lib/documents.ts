// Frontend domain policy for documents — the one address for status knowledge.
// Distinct from lib/documents-api.ts (HTTP) and types/api.ts (wire mirrors):
// "which statuses mean done" is a frontend classification the backend schema
// doesn't express. The 9D.1a status->color badge map and any 9D.2/9D.3 status
// logic will move here too; for now it holds only the terminal check.

import type { DocumentStatus } from "@/types/api";

// The statuses at which ingestion is finished (success or failure). `satisfies`
// makes a typo'd or non-member literal a COMPILE error and ties this set to the
// DocumentStatus union — add a status there and the check stays honest.
export const TERMINAL_DOCUMENT_STATUSES = [
  "completed",
  "failed",
] as const satisfies readonly DocumentStatus[];

export function isTerminalDocumentStatus(status: DocumentStatus): boolean {
  return (TERMINAL_DOCUMENT_STATUSES as readonly DocumentStatus[]).includes(
    status,
  );
}
