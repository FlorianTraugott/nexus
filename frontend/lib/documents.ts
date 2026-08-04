// Frontend domain policy for documents — the one address for status knowledge.
// Distinct from lib/documents-api.ts (HTTP) and types/api.ts (wire mirrors):
// "which statuses mean done" is a frontend classification the backend schema
// doesn't express. The 9D.1a status->color badge map and any 9D.2/9D.3 status
// logic will move here too; for now it holds only the terminal check.

import type { StatusTone } from "@/components/status-badge";
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

// Status -> how it should read, as ONE exhaustive Record so a new backend status
// is a compile error HERE, in the file that owns DocumentStatus — not a blank
// badge, and not an error in a shared presentation component that has no
// business knowing this enum.
//
// Labels stay faithful to the backend's vocabulary: capitalisation only, never
// renamed to something the API doesn't say. "processing" is deliberately
// indeterminate — the backend exposes no per-stage document progress, so a
// progress bar here would be invented, not measured.
export const DOCUMENT_STATUS_DISPLAY: Record<
  DocumentStatus,
  { tone: StatusTone; label: string }
> = {
  pending: { tone: "neutral", label: "Pending" },
  processing: { tone: "active", label: "Processing" },
  completed: { tone: "good", label: "Completed" },
  failed: { tone: "bad", label: "Failed" },
};
