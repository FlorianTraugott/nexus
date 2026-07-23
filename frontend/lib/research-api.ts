// Thin, typed wrappers over the /api/v1/research endpoints. Mirrors
// documents-api.ts / conversations-api.ts: only call shape + types; auth lives
// in the `api` instance. NOTE: the backend exposes NO list endpoint —
// list_user_tasks exists in the repo layer but is not routed (recorded backend
// deferral), which is why the task id lives in the URL.

import { api } from "@/lib/api";
import type {
  ResearchRequest,
  ResearchTaskCreated,
  ResearchTaskRead,
} from "@/types/api";

const RESEARCH = "/api/v1/research";

/** POST /research -> 202 ResearchTaskCreated; the run happens in a backend
 *  background task. 422 if k exceeds the backend bound. */
export async function createResearchTask(
  payload: ResearchRequest,
): Promise<ResearchTaskCreated> {
  const { data } = await api.post<ResearchTaskCreated>(RESEARCH, payload);
  return data;
}

/** GET /research/{task_id} -> 200 ResearchTaskRead (404: missing OR another
 *  user's — indistinguishable by backend design). */
export async function getResearchTask(
  taskId: string,
): Promise<ResearchTaskRead> {
  const { data } = await api.get<ResearchTaskRead>(`${RESEARCH}/${taskId}`);
  return data;
}
