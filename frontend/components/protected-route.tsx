"use client";

// Wraps protected content and gates it on auth state.
//
// It ONLY READS isLoading/isAuthenticated. It must never call rehydrate():
// AuthProvider already runs rehydrate() once app-wide on mount, so calling it
// here too would fire a duplicate /auth/me on every protected page mount.

import { useEffect } from "react";
import { useRouter } from "next/navigation";

import { useAuthStore } from "@/stores/auth";

export function ProtectedRoute({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const isLoading = useAuthStore((s) => s.isLoading);
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated);

  useEffect(() => {
    // THE LOADING GATE (load-bearing): while isLoading is true we do NOT know yet
    // whether there is a session — rehydrate() is still in flight. Redirecting now
    // would bounce the user to /login on every hard refresh before rehydrate
    // resolves. Only redirect once loading has settled AND there is no session.
    // replace() (not push): the bounced-through page must not enter history, or
    // Back traps the user in a redirect loop.
    if (!isLoading && !isAuthenticated) {
      router.replace("/login");
    }
  }, [isLoading, isAuthenticated, router]);

  // Show the loading state during rehydrate, and also in the brief window after
  // it resolves unauthenticated but before the effect's redirect commits — so
  // protected content never flashes for a logged-out user.
  if (isLoading || !isAuthenticated) {
    return (
      <div className="flex min-h-full flex-1 items-center justify-center p-4 text-sm text-muted-foreground">
        Loading…
      </div>
    );
  }

  return <>{children}</>;
}
