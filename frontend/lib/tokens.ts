// The single home for access/refresh token persistence.
//
// Storage is localStorage. NOTE: this is an XSS exposure — any injected script
// can read these tokens. The production answer is httpOnly, Secure cookies the
// JS can never read; we can't do that here because the backend returns the token
// pair in the JSON response body, so the client must hold them. Keeping all
// storage access behind these four functions means there is exactly one place to
// change if that decision is revisited.
//
// Every accessor is SSR-guarded: Next.js renders these modules on the server,
// where `window`/`localStorage` do not exist. Touching them there throws; we
// return null (or no-op) instead.

import type { Token } from "@/types/api";

const ACCESS_KEY = "nexus.access_token";
const REFRESH_KEY = "nexus.refresh_token";

export function getAccessToken(): string | null {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem(ACCESS_KEY);
}

export function getRefreshToken(): string | null {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem(REFRESH_KEY);
}

export function setTokens(token: Token): void {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(ACCESS_KEY, token.access_token);
  window.localStorage.setItem(REFRESH_KEY, token.refresh_token);
}

export function clearTokens(): void {
  if (typeof window === "undefined") return;
  window.localStorage.removeItem(ACCESS_KEY);
  window.localStorage.removeItem(REFRESH_KEY);
}
