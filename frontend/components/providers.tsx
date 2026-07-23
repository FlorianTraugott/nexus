"use client";

// App-wide client providers. Sits OUTSIDE AuthProvider in the root layout so the
// whole tree — auth included — can reach the React Query client.

import { useEffect, useRef, useState } from "react";
import {
  QueryClient,
  QueryClientProvider,
  useQueryClient,
} from "@tanstack/react-query";
import { ReactQueryDevtools } from "@tanstack/react-query-devtools";

import { useAuthStore } from "@/stores/auth";

// Empties the query cache on the authenticated -> unauthenticated EDGE, so one
// user's cached data can never surface for the next user on the same tab.
//
// Reads useQueryClient() + the auth store directly, rather than importing a
// client singleton into stores/auth.ts — the store stays decoupled from React
// Query. The store is global (Zustand, not context), so this only needs to sit
// below QueryClientProvider; its position relative to AuthProvider is irrelevant.
function ClearQueryCacheOnLogout() {
  const queryClient = useQueryClient();
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated);
  const wasAuthenticated = useRef(isAuthenticated);

  useEffect(() => {
    // Fire on the true -> false transition only. Whichever store function trips
    // it clears the cache once — logout(), or a session-dead clear in login()/
    // rehydrate(). The initial mount is not an edge (isAuthenticated starts
    // false), so no clear fires on a cold start and an empty cache is never
    // clobbered.
    if (wasAuthenticated.current && !isAuthenticated) {
      queryClient.clear();
    }
    wasAuthenticated.current = isAuthenticated;
  }, [isAuthenticated, queryClient]);

  return null;
}

export function Providers({ children }: { children: React.ReactNode }) {
  // Created ONCE per client: a fresh QueryClient on every render would discard
  // the cache each time. useState's initializer runs a single time.
  const [queryClient] = useState(() => new QueryClient());

  return (
    <QueryClientProvider client={queryClient}>
      {children}
      <ClearQueryCacheOnLogout />
      {/* Dev-only: the explicit NODE_ENV guard keeps the devtools out of the
          production bundle (verified against the build output, not assumed). */}
      {process.env.NODE_ENV === "development" && (
        <ReactQueryDevtools initialIsOpen={false} />
      )}
    </QueryClientProvider>
  );
}
