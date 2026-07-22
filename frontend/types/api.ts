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
