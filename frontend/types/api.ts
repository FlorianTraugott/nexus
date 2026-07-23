// TypeScript mirrors of the backend Pydantic schemas.
// Field names are snake_case ON PURPOSE and must match the backend byte-for-byte
// (app/schemas/user.py, app/schemas/token.py). Do NOT camelCase them: the wire
// format is snake_case, and a renamed field is a silent `undefined` at runtime,
// not a compile error.

/** app/schemas/user.py :: UserRead */
export interface UserRead {
  id: string; // uuid.UUID serialised as a string
  email: string; // EmailStr
  is_active: boolean;
  created_at: string; // datetime serialised as an ISO-8601 string
}

/** app/schemas/token.py :: Token */
export interface Token {
  access_token: string;
  refresh_token: string;
  token_type: string; // always "bearer"
}

/** app/schemas/user.py :: UserCreate — POST /auth/register body */
export interface UserCreate {
  email: string;
  password: string; // 8..72 chars, enforced server-side
}

/** app/schemas/user.py :: UserLogin — POST /auth/login body (JSON, not form-data) */
export interface LoginRequest {
  email: string;
  password: string;
}

/** app/schemas/token.py :: RefreshRequest — POST /auth/refresh and /auth/logout body */
export interface RefreshRequest {
  refresh_token: string;
}

/** FastAPI's error envelope: {"detail": string} for the errors we surface. */
export interface ApiError {
  detail: string;
}

/** app/db/models.py :: DocumentSourceType */
export type DocumentSourceType = "pdf" | "text" | "youtube" | "web";

/** app/db/models.py :: DocumentStatus — pending -> processing -> completed | failed */
export type DocumentStatus = "pending" | "processing" | "completed" | "failed";

/** app/schemas/document.py :: DocumentRead — GET /documents item, snake_case. */
export interface DocumentRead {
  id: string; // uuid.UUID serialised as a string
  filename: string;
  source_type: DocumentSourceType;
  status: DocumentStatus;
  chunk_count: number;
  created_at: string; // datetime serialised as an ISO-8601 string
}

/** app/schemas/query.py :: QueryRequest — POST /query and /query/stream body */
export interface QueryRequest {
  question: string;
  k?: number | null;
  conversation_id?: string | null; // uuid as a string; absent = stateless query
}

/** app/schemas/query.py :: Citation — Chroma cosine distance: LOWER is more relevant */
export interface Citation {
  chunk_id: string; // uuid.UUID serialised as a string
  document_id: string; // uuid.UUID serialised as a string
  chunk_index: number;
  distance: number;
  content_preview: string;
}

/** app/schemas/query.py :: QueryResponse — POST /query (sync) */
export interface QueryResponse {
  answer: string;
  citations: Citation[];
  // Non-null whenever the rewrite step RAN (even if it returned the question
  // unchanged); null only when it never ran (no conversation_id / first turn).
  rewritten_question: string | null;
}

// --- SSE frames for POST /query/stream (app/schemas/query.py) ---
// Each arrives as one `data: <json>\n\n` frame; `type` is the discriminant.
// Sequence: metadata -> (abstained | token* done | token* error).

/** app/schemas/query.py :: StreamMetadata — first frame, known before generation */
export interface StreamMetadata {
  type: "metadata";
  citations: Citation[];
  rewritten_question: string | null;
}

/** app/schemas/query.py :: StreamToken — one answer delta as it arrives */
export interface StreamToken {
  type: "token";
  text: string;
}

/** app/schemas/query.py :: StreamDone — terminal frame of a successful stream */
export interface StreamDone {
  type: "done";
}

/** app/schemas/query.py :: StreamAbstained — terminal; fixed answer, no tokens */
export interface StreamAbstained {
  type: "abstained";
  answer: string;
}

/** app/schemas/query.py :: StreamError — terminal; may arrive after flushed tokens */
export interface StreamError {
  type: "error";
  message: string;
}

export type StreamEvent =
  | StreamMetadata
  | StreamToken
  | StreamDone
  | StreamAbstained
  | StreamError;

/** app/db/models.py :: MessageRole — "system" exists in the enum but the query
 *  path only ever persists user/assistant pairs. */
export type MessageRole = "user" | "assistant" | "system";

/** app/schemas/conversation.py :: MessageRead — one persisted message.
 *  NOTE: no rewritten_question and no abstention flag are stored — those exist
 *  only on the live stream wire. */
export interface MessageRead {
  id: string; // uuid.UUID serialised as a string
  role: MessageRole;
  content: string;
  citations: Citation[] | null; // present on assistant turns
  position: number;
  created_at: string; // datetime serialised as an ISO-8601 string
}

/** app/schemas/conversation.py :: ConversationCreate — POST /conversations body */
export interface ConversationCreate {
  title?: string | null; // 1..255 chars; backend defaults to "New conversation"
}

/** app/schemas/conversation.py :: ConversationRead */
export interface ConversationRead {
  id: string; // uuid.UUID serialised as a string
  title: string;
  created_at: string;
  updated_at: string;
}

/** app/schemas/conversation.py :: ConversationDetail — GET /conversations/{id};
 *  messages ordered by position. */
export interface ConversationDetail extends ConversationRead {
  messages: MessageRead[];
}

/** app/db/models.py :: ResearchTaskStatus — pending -> running -> completed | failed */
export type ResearchTaskStatus = "pending" | "running" | "completed" | "failed";

/** app/schemas/research.py :: ResearchStage */
export type ResearchStage =
  | "web_search"
  | "kb_query"
  | "summarise"
  | "report"
  | "done";

/** app/schemas/research.py :: WebSearchHit */
export interface WebSearchHit {
  title: string;
  url: string;
  snippet: string;
  score: number | null; // provider relevance when available
}

/** app/schemas/research.py :: WebSearchFindings */
export interface WebSearchFindings {
  query: string;
  hits: WebSearchHit[];
}

/** app/schemas/research.py :: KBFinding — deliberate SIBLING of Citation
 *  (same shape, decoupled type — mirrors the backend's decoupling). */
export interface KBFinding {
  chunk_id: string;
  document_id: string;
  chunk_index: number;
  distance: number; // cosine distance: LOWER is more relevant
  content_preview: string;
}

/** app/schemas/research.py :: KBFindings */
export interface KBFindings {
  query: string;
  findings: KBFinding[];
}

/** app/schemas/research.py :: Summary */
export interface Summary {
  key_points: string[];
  abstract: string;
}

/** app/schemas/research.py :: ReportSection */
export interface ReportSection {
  heading: string;
  body: string;
}

/** app/schemas/research.py :: ResearchReport */
export interface ResearchReport {
  title: string;
  sections: ReportSection[];
  markdown: string;
}

/** app/schemas/research.py :: ResearchRequest — POST /research body */
export interface ResearchRequest {
  topic: string;
  k?: number | null;
}

/** app/schemas/research.py :: ResearchResponse — the completed run. A recorded
 *  PIPELINE failure rides here as non-null `error` with `report` null. */
export interface ResearchResponse {
  topic: string;
  stage: ResearchStage;
  web: WebSearchFindings | null;
  kb: KBFindings | null;
  summary: Summary | null;
  report: ResearchReport | null;
  warnings: string[];
  error: string | null;
}

/** app/schemas/research.py :: ResearchTaskCreated — POST /research 202 body */
export interface ResearchTaskCreated {
  task_id: string;
  status: ResearchTaskStatus;
}

/** app/schemas/research.py :: ResearchTaskRead — the poll envelope.
 *  result stays null until the run finishes. PIPELINE failure = status
 *  "completed" with the error INSIDE result.error; the top-level `error` is
 *  populated only on INFRASTRUCTURE failure (status "failed", result null). */
export interface ResearchTaskRead {
  task_id: string;
  topic: string;
  status: ResearchTaskStatus;
  result: ResearchResponse | null;
  error: string | null;
  created_at: string;
  updated_at: string;
}
