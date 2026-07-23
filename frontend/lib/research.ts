// Domain policy for research tasks (transport-free, mirrors lib/documents.ts):
// which statuses are terminal, and when a non-terminal task counts as stalled.

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
