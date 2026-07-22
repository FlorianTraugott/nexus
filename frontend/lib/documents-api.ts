// Thin, typed wrappers over the /api/v1/documents endpoints. Like auth-api.ts,
// these only shape the call and its types; header injection and refresh live in
// the `api` instance. Read path only for 9D.1a — delete/upload land in 9D.2/9D.3.

import { api } from "@/lib/api";
import type { DocumentRead } from "@/types/api";

const DOCUMENTS = "/api/v1/documents";

/** GET /documents -> 200 DocumentRead[] for the bearer user, newest-first. */
export async function listDocuments(): Promise<DocumentRead[]> {
  const { data } = await api.get<DocumentRead[]>(DOCUMENTS);
  return data;
}

/** GET /documents/{id} -> 200 DocumentRead (404 if not the caller's / missing). */
export async function getDocument(id: string): Promise<DocumentRead> {
  const { data } = await api.get<DocumentRead>(`${DOCUMENTS}/${id}`);
  return data;
}
