// The one configured Axios instance for the app. Every call to the backend goes
// through here so that auth-header injection and token refresh live in exactly
// one place.

import axios, {
  AxiosError,
  isAxiosError,
  type AxiosResponse,
  type InternalAxiosRequestConfig,
} from "axios";

import type { Token } from "@/types/api";
import { clearTokens, getAccessToken, getRefreshToken, setTokens } from "@/lib/tokens";

export const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export const api = axios.create({
  baseURL: API_BASE_URL,
  headers: { "Content-Type": "application/json" },
});

// Distinct error type so the UI can say "too many attempts" for a 429 rather
// than misreporting it as "wrong password" (a 401). Thrown from the response
// interceptor; callers can `instanceof RateLimitError`.
export class RateLimitError extends Error {
  constructor(message = "Too many attempts. Please wait and try again.") {
    super(message);
    this.name = "RateLimitError";
  }
}

// The ONE signal that a session is truly dead. Thrown by the response interceptor
// only when /auth/refresh returns a genuine HTTP 401 (the refresh token is
// revoked or invalid). Callers (the auth store) clear tokens ONLY on this — never
// on a cancelled or transient failure, which are not authentication failures.
export class SessionExpiredError extends Error {
  constructor(message = "Your session has expired. Please sign in again.") {
    super(message);
    this.name = "SessionExpiredError";
  }
}

// One home for "does this error mean the session is dead?". A wrapped
// SessionExpiredError, or a genuine 401 that reached the caller unwrapped (e.g. a
// retried request rejected a second time). Used by the store's catch blocks so
// the "session truly dead" definition lives in a single place.
export function isSessionExpiredError(err: unknown): boolean {
  return (
    err instanceof SessionExpiredError ||
    (isAxiosError(err) && err.response?.status === 401)
  );
}

// --- redirect-on-session-loss hook -----------------------------------------
// When refresh fails there is no live session, and the app must send the user to
// /login. We do NOT hard-navigate with window.location here: that couples this
// module to the browser and makes it untestable. Instead the app registers a
// callback (a client component wires it to Next's router.push("/login")).
let onUnauthorized: (() => void) | null = null;

export function setUnauthorizedHandler(handler: (() => void) | null): void {
  onUnauthorized = handler;
}

// Endpoints where a 401 means "bad credentials" or "bad/expired refresh token",
// NOT "expired session". Refreshing here is wrong (and for /auth/refresh itself
// would recurse), so these are excluded from the refresh flow.
const NO_REFRESH_PATHS = [
  "/api/v1/auth/login",
  "/api/v1/auth/register",
  "/api/v1/auth/refresh",
];

function isNoRefreshPath(url: string | undefined): boolean {
  if (!url) return false;
  return NO_REFRESH_PATHS.some((path) => url.includes(path));
}

// Single-flight refresh state. Refresh tokens ROTATE and are SINGLE-USE: the
// backend revokes the presented token the instant it issues a new pair. If two
// concurrent 401s each fired their own refresh, the second would present an
// already-revoked token and fail, logging the user out. So we hold exactly ONE
// in-flight refresh: the first 401 starts it, every concurrent 401 awaits that
// same promise, and all retries use the single new access token it resolves to.
let refreshPromise: Promise<string> | null = null;

// Known residual race (accepted, deferred): refresh tokens rotate and are
// single-use, so the server revokes the old token the moment /auth/refresh is
// received. If a reload lands inside the ~one-RTT refresh round-trip, the page is
// torn down before setTokens() persists the new pair, leaving storage with the
// old — now revoked — token; the next load's refresh then 401s genuinely and logs
// out. This cannot be fully closed client-side. The complete fix is a backend
// reuse-with-leeway grace window (accept a just-rotated token briefly), which
// weakens the single-use rotation guarantee and needs its own approved segment.
//
// Perform the refresh on a BARE axios call (not `api`), so it bypasses this very
// interceptor — otherwise a 401 from refresh would re-enter the refresh logic.
async function performRefresh(): Promise<string> {
  const refreshToken = getRefreshToken();
  if (!refreshToken) {
    throw new Error("No refresh token available");
  }
  const response = await axios.post<Token>(
    `${API_BASE_URL}/api/v1/auth/refresh`,
    { refresh_token: refreshToken },
    { headers: { "Content-Type": "application/json" } },
  );
  setTokens(response.data);
  return response.data.access_token;
}

// The ONE place a refresh is started or joined. Both the axios interceptor and
// the fetch-based stream client (lib/query-stream.ts) call this, so every
// concurrent 401 awaits the SAME module-level promise. There must never be a
// second code path that starts a refresh: with single-use rotating tokens, two
// parallel refreshes revoke each other and log the user out.
//
// The "refresh itself failed with a genuine 401 → session dead" policy lives
// HERE, on the shared promise, so it has one home and fires ONCE per dead
// refresh (not once per waiter): clear tokens FIRST, then signal the redirect,
// then reject every waiter with the typed SessionExpiredError. The .catch runs
// as part of the promise chain BEFORE any waiter's await resumes, so cleanup
// strictly precedes every observer. Any other failure (cancelled request,
// network error, 5xx) rethrows raw — it is NOT an authentication failure and
// the session stays intact.
export function refreshAccessToken(): Promise<string> {
  if (!refreshPromise) {
    refreshPromise = performRefresh()
      .catch((refreshError: unknown) => {
        if (
          isAxiosError(refreshError) &&
          refreshError.response?.status === 401
        ) {
          clearTokens();
          onUnauthorized?.();
          throw new SessionExpiredError();
        }
        throw refreshError;
      })
      .finally(() => {
        refreshPromise = null;
      });
  }
  return refreshPromise;
}

// Attach the access token to every outgoing request when we have one.
api.interceptors.request.use((config: InternalAxiosRequestConfig) => {
  const token = getAccessToken();
  if (token) {
    config.headers.set("Authorization", `Bearer ${token}`);
  }
  return config;
});

// A one-shot retry flag we hang on the request config so a second 401 (e.g. the
// refreshed token is somehow also rejected) does not loop forever.
type RetriableConfig = InternalAxiosRequestConfig & { _retry?: boolean };

api.interceptors.response.use(
  (response: AxiosResponse) => response,
  async (error: AxiosError) => {
    const status = error.response?.status;
    const original = error.config as RetriableConfig | undefined;

    // 429 is surfaced distinctly, never treated as an auth failure.
    if (status === 429) {
      return Promise.reject(new RateLimitError());
    }

    // Only a 401, on a real request we have not already retried, and not on the
    // auth endpoints where 401 means bad credentials.
    if (
      status !== 401 ||
      !original ||
      original._retry ||
      isNoRefreshPath(original.url)
    ) {
      return Promise.reject(error);
    }

    original._retry = true;

    try {
      // Join the single in-flight refresh (or start it if none is running).
      const newAccessToken = await refreshAccessToken();

      original.headers.set("Authorization", `Bearer ${newAccessToken}`);
      return api(original);
    } catch (refreshError) {
      // Session-dead handling (clear tokens, signal the redirect) already ran
      // ON the shared promise inside refreshAccessToken — once per dead
      // refresh, before any waiter resumed. Here we only route the rejection.
      if (refreshError instanceof SessionExpiredError) {
        return Promise.reject(refreshError);
      }
      // A cancelled request (navigation/reload — axios.isCancel / ERR_CANCELED),
      // a network error (no response), or a 5xx is NOT an authentication failure;
      // the tokens may be perfectly valid. Reject the ORIGINAL error WITHOUT
      // clearing tokens or firing onUnauthorized, so the next load/retry recovers.
      // (Treating a cancelled-by-reload request as a logout was the reload bug.)
      return Promise.reject(error);
    }
  },
);
