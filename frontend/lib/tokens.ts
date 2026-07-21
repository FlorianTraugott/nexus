// The single home for access/refresh token persistence.
//
// Storage is localStorage. NOTE: this is an XSS exposure — any injected script
// can read these tokens. The production answer is httpOnly, Secure cookies the
// JS can never read; we can't do that here because the backend returns the token
// pair in the JSON response body, so the client must hold them. Keeping all
// storage access behind these functions means there is exactly one place to
// change if that decision is revisited.
//
// The pair is stored as ONE JSON value under one key, written and read in a
// single operation. This is defence-in-depth — it rules out a partially-updated
// pair being observed by another tab or a future async writer. It is NOT the fix
// for the reload-logout bug (that was rehydrate() treating a cancelled request as
// an auth failure): two adjacent synchronous setItem calls could never interleave
// with a reload anyway, since unload only happens at task boundaries.
//
// Every accessor is SSR-guarded: Next.js renders these modules on the server,
// where `window`/`localStorage` do not exist. Touching them there throws; we
// return null (or no-op) instead.

import type { Token } from "@/types/api";

const TOKENS_KEY = "nexus.tokens";

interface StoredTokens {
  access_token: string;
  refresh_token: string;
}

function readTokens(): StoredTokens | null {
  if (typeof window === "undefined") return null;
  const raw = window.localStorage.getItem(TOKENS_KEY);
  if (!raw) return null;
  try {
    const parsed = JSON.parse(raw) as Partial<StoredTokens>;
    if (
      typeof parsed?.access_token === "string" &&
      typeof parsed?.refresh_token === "string"
    ) {
      return {
        access_token: parsed.access_token,
        refresh_token: parsed.refresh_token,
      };
    }
    return null;
  } catch {
    return null;
  }
}

export function getAccessToken(): string | null {
  return readTokens()?.access_token ?? null;
}

export function getRefreshToken(): string | null {
  return readTokens()?.refresh_token ?? null;
}

export function setTokens(token: Token): void {
  if (typeof window === "undefined") return;
  const value: StoredTokens = {
    access_token: token.access_token,
    refresh_token: token.refresh_token,
  };
  window.localStorage.setItem(TOKENS_KEY, JSON.stringify(value));
}

export function clearTokens(): void {
  if (typeof window === "undefined") return;
  window.localStorage.removeItem(TOKENS_KEY);
}
