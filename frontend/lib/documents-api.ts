// Thin, typed wrappers over the /api/v1/documents endpoints. Like auth-api.ts,
// these only shape the call and its types; header injection and refresh live in
// the `api` instance. Read path (9D.1a) + upload (9D.2); delete lands in 9D.3.

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

/**
 * POST /documents -> 201 DocumentRead. Multipart upload; the doc starts in a
 * non-terminal status (ingestion is a background task on the backend).
 * Errors: 400 (no filename), 413 (> 25 MB), 415 (unsupported suffix).
 */
export async function uploadDocument(file: File): Promise<DocumentRead> {
  const form = new FormData();
  // Field name "file" matches the backend's UploadFile param (documents.py).
  form.append("file", file);
  const { data } = await api.post<DocumentRead>(DOCUMENTS, form, {
    // Unset the `api` instance's default "application/json" so the browser
    // computes "multipart/form-data; boundary=…" itself. NEVER hardcode the
    // string — a boundary-less Content-Type makes FastAPI reject the body.
    // (Verified on the wire in the network tab, not assumed.) Bearer + refresh
    // are untouched — same `api` instance, so this call is still authenticated.
    headers: { "Content-Type": undefined },
  });
  return data;
}
