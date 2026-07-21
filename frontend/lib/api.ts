// The one configured Axios instance for the app. Every call to the backend goes
// through here so that auth-header injection and token refresh live in exactly
// one place.

import axios, {
  AxiosError,
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
      if (!refreshPromise) {
        refreshPromise = performRefresh().finally(() => {
          refreshPromise = null;
        });
      }
      const newAccessToken = await refreshPromise;

      original.headers.set("Authorization", `Bearer ${newAccessToken}`);
      return api(original);
    } catch (refreshError) {
      // Refresh failed -> the session is gone. Clear tokens and let the app
      // redirect. Reject with the ORIGINAL error so callers see the real 401.
      clearTokens();
      onUnauthorized?.();
      return Promise.reject(error);
    }
  },
);
