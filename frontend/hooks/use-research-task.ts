// The research task poll — the 9D.1b self-stopping pattern with two additions
// this surface needs:
//
// - a STALL CEILING: the operating conditions changed from 9D.1b (fast
//   in-process ingestion) to a 30-60s background runner whose row can be left
//   RUNNING forever by a server restart. The interval callback checks the
//   data-driven stall policy, so a stalled task stops polling with no timers;
//   a manual refetch() (the page's "Check again") probes once without
//   re-arming the loop while still stalled.
// - NO RETRY on 4xx: the installed query-core defaults to 3 client retries
//   (retryer.js: `config.retry ?? 3`), which would delay a bogus id's
//   not-found state by ~7s of backoff. A 4xx is a definitive answer, not a
//   transient fault.

import { useQuery } from "@tanstack/react-query";
import { isAxiosError } from "axios";

import { getResearchTask } from "@/lib/research-api";
import { isResearchTaskStalled, isTerminalResearchStatus } from "@/lib/research";

const POLL_INTERVAL_MS = 2000;

export function useResearchTask(taskId: string) {
  return useQuery({
    queryKey: ["research", taskId],
    queryFn: () => getResearchTask(taskId),
    refetchInterval: (query) => {
      const task = query.state.data;
      if (!task) return false; // nothing fetched yet -> nothing to poll for
      if (isTerminalResearchStatus(task.status) || isResearchTaskStalled(task)) {
        return false;
      }
      return POLL_INTERVAL_MS;
    },
    retry: (failureCount, error) => {
      // Deliberate small duplication with use-conversation.ts — a shared home
      // can come when a third caller earns it.
      const status = isAxiosError(error) ? error.response?.status : undefined;
      if (status !== undefined && status >= 400 && status < 500) return false;
      return failureCount < 3;
    },
  });
}
