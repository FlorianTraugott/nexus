// Thin, typed wrappers over the /api/v1/conversations endpoints. Mirrors
// documents-api.ts: only call shape + types; auth header injection and refresh
// live in the `api` instance. Honest mirrors — a 404 rejects like any status;
// "already gone" policy lives in the caller's onError.

import { api } from "@/lib/api";
import type {
  ConversationCreate,
  ConversationDetail,
  ConversationRead,
} from "@/types/api";

const CONVERSATIONS = "/api/v1/conversations";

/** GET /conversations -> 200 ConversationRead[] for the bearer user.
 *  Ordered created_at DESC by the backend — a resumed old conversation does
 *  NOT float to the top (updated_at ordering is a recorded backend deferral). */
export async function listConversations(): Promise<ConversationRead[]> {
  const { data } = await api.get<ConversationRead[]>(CONVERSATIONS);
  return data;
}

/** GET /conversations/{id} -> 200 ConversationDetail (404: missing OR another
 *  user's — indistinguishable by backend design). */
export async function getConversation(id: string): Promise<ConversationDetail> {
  const { data } = await api.get<ConversationDetail>(`${CONVERSATIONS}/${id}`);
  return data;
}

/** POST /conversations -> 201 ConversationRead. Title optional (backend
 *  defaults to "New conversation"). The optional signal lets the lazy
 *  create-on-first-send be aborted with the turn it belongs to. */
export async function createConversation(
  payload: ConversationCreate = {},
  signal?: AbortSignal,
): Promise<ConversationRead> {
  const { data } = await api.post<ConversationRead>(CONVERSATIONS, payload, {
    signal,
  });
  return data;
}

/** DELETE /conversations/{id} -> 204 (no body). A 404 REJECTS — this stays a
 *  truthful mirror; the mutation's onError decides "already gone". */
export async function deleteConversation(id: string): Promise<void> {
  await api.delete(`${CONVERSATIONS}/${id}`);
}
