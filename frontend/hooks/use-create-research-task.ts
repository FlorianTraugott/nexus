// The research create mutation. No invalidation: there is no task-list query
// to refresh (the backend exposes no list endpoint — recorded deferral).

import { useMutation } from "@tanstack/react-query";

import { createResearchTask } from "@/lib/research-api";

export function useCreateResearchTask() {
  return useMutation({
    mutationFn: (topic: string) => createResearchTask({ topic }),
  });
}
