"use client";

// Log out, and the navigation that must follow it.
//
// ONE home for both halves on purpose: stores/auth.ts deliberately clears
// session state WITHOUT navigating — the caller decides where to go — so every
// call site has to remember the same second step. That is exactly the kind of
// two-part contract that drifts once it is written twice, and a call site that
// forgot the redirect would leave a logged-out user sitting on a protected page
// until ProtectedRoute noticed.

import { useRouter } from "next/navigation";

import { useAuthStore } from "@/stores/auth";
import { Button } from "@/components/ui/button";

export function LogoutButton({
  size = "sm",
  className,
}: {
  size?: React.ComponentProps<typeof Button>["size"];
  className?: string;
}) {
  const router = useRouter();
  const logout = useAuthStore((s) => s.logout);

  async function onLogout() {
    await logout();
    router.replace("/login");
  }

  return (
    <Button
      variant="outline"
      size={size}
      onClick={onLogout}
      className={className}
    >
      Log out
    </Button>
  );
}
