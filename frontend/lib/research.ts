// Domain policy for research tasks (transport-free, mirrors lib/documents.ts):
// which statuses are terminal, and when a non-terminal task counts as stalled.

import type { StatusTone } from "@/components/status-badge";
import type { ResearchTaskRead, ResearchTaskStatus } from "@/types/api";

export const TERMINAL_RESEARCH_STATUSES = [
  "completed",
  "failed",
] as const satisfies readonly ResearchTaskStatus[];

export function isTerminalResearchStatus(status: ResearchTaskStatus): boolean {
  return (TERMINAL_RESEARCH_STATUSES as readonly ResearchTaskStatus[]).includes(
    status,
  );
}

// Status -> how it should read. Sibling of DOCUMENT_STATUS_DISPLAY, and separate
// on purpose: the shared StatusBadge takes a TONE and knows no status enum, so a
// new backend status stays a compile error HERE, in the file that owns
// ResearchTaskStatus. Labels are the backend's own words, capitalised.
//
// "running" is deliberately paired with an indeterminate treatment on the page:
// `stage` lives inside `result`, which is null until the task is terminal, and
// the row persists no per-transition progress — so a step indicator would be
// invented rather than measured.
export const RESEARCH_STATUS_DISPLAY: Record<
  ResearchTaskStatus,
  { tone: StatusTone; label: string }
> = {
  pending: { tone: "neutral", label: "Pending" },
  running: { tone: "active", label: "Running" },
  completed: { tone: "good", label: "Completed" },
  failed: { tone: "bad", label: "Failed" },
};

// Stall ceiling. A run finishes in well under a minute, but the backend commits
// RUNNING BEFORE the pipeline and only the runner's own except marks FAILED — a
// server restart mid-pipeline leaves the row RUNNING forever, and polling it
// every 2s indefinitely is the failure mode. Measured from updated_at (the last
// observable status transition, server truth — so the ceiling survives reload);
// 5 minutes is generous enough to absorb slow runs and modest clock skew.
export const RESEARCH_STALL_AFTER_MS = 5 * 60 * 1000;

export function isResearchTaskStalled(
  task: ResearchTaskRead,
  now: number = Date.now(),
): boolean {
  if (isTerminalResearchStatus(task.status)) return false;
  return now - new Date(task.updated_at).getTime() > RESEARCH_STALL_AFTER_MS;
}
