// The auth store. Holds the current user and derived auth flags for the UI.
//
// Deliberately NO zustand `persist` middleware. tokens.ts is the SINGLE home for
// persistence (localStorage); this store is derived, rehydrated from the server
// via me(). Persisting the user object too would create a second source of truth
// that drifts from the tokens, and — worse — stale persisted state would show a
// "logged in" user after the session was revoked server-side. The store is
// always reconstructed from a live /auth/me call, never from disk.

import { create } from "zustand";

import * as authApi from "@/lib/auth-api";
import { isSessionExpiredError } from "@/lib/api";
import {
  clearTokens,
  getAccessToken,
  getRefreshToken,
  setTokens,
} from "@/lib/tokens";
import type { UserRead } from "@/types/api";

interface AuthState {
  user: UserRead | null;
  isAuthenticated: boolean;
  // Gates protected routes during the initial rehydrate; see rehydrate().
  isLoading: boolean;
  login: (email: string, password: string) => Promise<void>;
  register: (email: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
  rehydrate: () => Promise<void>;
}

export const useAuthStore = create<AuthState>((set, get) => ({
  user: null,
  isAuthenticated: false,
  // Starts true: AuthProvider runs rehydrate() on mount, and until it settles we
  // do not yet know whether there is a session. rehydrate() clears this.
  isLoading: true,

  // login() throws on failure so the calling page can map the error (401/403/429).
  // authApi.login throwing (bad creds) leaves no tokens to clean. Only the rare
  // me()-after-token failure needs the cleanup below.
  login: async (email, password) => {
    const token = await authApi.login({ email, password });
    setTokens(token);
    try {
      const user = await authApi.me();
      set({ user, isAuthenticated: true });
    } catch (err) {
      // Clear only if the session is genuinely dead. A transient me() failure
      // right after a fresh login must not wipe the just-issued tokens.
      if (isSessionExpiredError(err)) {
        clearTokens();
        set({ user: null, isAuthenticated: false });
      }
      throw err;
    }
  },

  // register does NOT authenticate (returns a UserRead), so we log in afterwards.
  // Errors from either step propagate to the page for mapping.
  register: async (email, password) => {
    await authApi.register({ email, password });
    await get().login(email, password);
  },

  // Best-effort: the refresh token may already be revoked and /logout is
  // idempotent, so a failure is ignored. Local state is cleared regardless.
  logout: async () => {
    const refreshToken = getRefreshToken();
    if (refreshToken) {
      try {
        await authApi.logout({ refresh_token: refreshToken });
      } catch {
        // ignore — token may already be revoked; endpoint is idempotent
      }
    }
    clearTokens();
    set({ user: null, isAuthenticated: false });
  },

  // Reconstruct auth state from the server on app load. isLoading is set false in
  // finally ALWAYS — including on error — so protected routes never hang.
  rehydrate: async () => {
    if (!getAccessToken()) {
      set({ user: null, isAuthenticated: false, isLoading: false });
      return;
    }
    try {
      const user = await authApi.me();
      set({ user, isAuthenticated: true });
    } catch (err) {
      // Clear the session ONLY when it is truly dead (SessionExpiredError from the
      // refresh flow, or a genuine 401). A cancelled /auth/me — e.g. a rapid
      // reload aborting the in-flight request — or a transient network error is
      // NOT an auth failure; leave tokens intact so the next load recovers. This
      // was the reload-logout bug: the bare catch treated a cancelled request as
      // a logout.
      if (isSessionExpiredError(err)) {
        clearTokens();
        set({ user: null, isAuthenticated: false });
      }
    } finally {
      // Always, including on error — a stuck isLoading would hang protected routes.
      set({ isLoading: false });
    }
  },
}));
