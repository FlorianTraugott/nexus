"use client";

// For the public auth pages (login/register): once rehydrate has settled and the
// visitor IS authenticated, send them to /. One home so both pages behave
// identically.
//
// Same loading-gate discipline as ProtectedRoute, inverted: while isLoading is
// true we do NOT know whether there is a session, so we must NOT redirect —
// otherwise a hard refresh flashes. Only redirect once loading has settled AND
// the user is authenticated. replace() (not push) so the auth page is not left
// in history behind the dashboard.
//
// Returns true while the page should render a loading placeholder instead of the
// form: during load, and in the brief window after it resolves authenticated but
// before the redirect commits (so the form never flashes for a logged-in user).

import { useEffect } from "react";
import { useRouter } from "next/navigation";

import { useAuthStore } from "@/stores/auth";

export function useRedirectWhenAuthenticated(): boolean {
  const router = useRouter();
  const isLoading = useAuthStore((s) => s.isLoading);
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated);

  useEffect(() => {
    if (!isLoading && isAuthenticated) {
      router.replace("/");
    }
  }, [isLoading, isAuthenticated, router]);

  return isLoading || isAuthenticated;
}
