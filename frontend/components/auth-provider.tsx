"use client";

// The client boundary that sits inside the server-component root layout. On
// mount it (1) reconstructs auth state from the server via rehydrate(), and
// (2) registers the api.ts unauthorized handler so a failed token refresh sends
// the user to /login. Nothing here renders UI; it only wires runtime behaviour.

import { useEffect } from "react";
import { useRouter } from "next/navigation";

import { setUnauthorizedHandler } from "@/lib/api";
import { useAuthStore } from "@/stores/auth";

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const rehydrate = useAuthStore((s) => s.rehydrate);

  useEffect(() => {
    // No hard window.location — keep redirection in Next's router so it stays a
    // client-side transition (and testable).
    setUnauthorizedHandler(() => router.push("/login"));
    rehydrate();
    return () => setUnauthorizedHandler(null);
  }, [router, rehydrate]);

  return <>{children}</>;
}
