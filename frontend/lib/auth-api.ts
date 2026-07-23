// Thin, typed wrappers over the /api/v1/auth endpoints. These only shape the
// call and its types; header injection and refresh live in the `api` instance.

import { api } from "@/lib/api";
import type {
  LoginRequest,
  RefreshRequest,
  Token,
  UserCreate,
  UserRead,
} from "@/types/api";

const AUTH = "/api/v1/auth";

/** POST /auth/register -> 201 UserRead (409 if the email is taken). */
export async function register(body: UserCreate): Promise<UserRead> {
  const { data } = await api.post<UserRead>(`${AUTH}/register`, body);
  return data;
}

/** POST /auth/login -> 200 Token (401 wrong creds, 403 inactive, 429 rate-limited). */
export async function login(body: LoginRequest): Promise<Token> {
  const { data } = await api.post<Token>(`${AUTH}/login`, body);
  return data;
}

/** POST /auth/refresh -> 200 Token (a NEW pair; the presented token is revoked). */
export async function refresh(body: RefreshRequest): Promise<Token> {
  const { data } = await api.post<Token>(`${AUTH}/refresh`, body);
  return data;
}

/** POST /auth/logout -> 204. Idempotent. */
export async function logout(body: RefreshRequest): Promise<void> {
  await api.post(`${AUTH}/logout`, body);
}

/** GET /auth/me -> 200 UserRead for the bearer token (401 if invalid/expired). */
export async function me(): Promise<UserRead> {
  const { data } = await api.get<UserRead>(`${AUTH}/me`);
  return data;
}
