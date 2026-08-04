"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";

import { useAuthStore } from "@/stores/auth";
import { ProtectedRoute } from "@/components/protected-route";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";

// Feature surfaces on the dashboard. `href` is set once a surface has a route;
// Chat/Research stay static placeholders until their Part 9 segments land.
const FEATURES: { title: string; description: string; href?: string }[] = [
  {
    title: "Chat",
    description: "Ask questions grounded in your documents.",
    href: "/chat",
  },
  {
    title: "Documents",
    description: "Upload and manage your corpus.",
    href: "/documents",
  },
  {
    title: "Research",
    description: "Run the multi-agent research pipeline.",
    href: "/research",
  },
];

function DashboardHeader() {
  const router = useRouter();
  const email = useAuthStore((s) => s.user?.email);
  const logout = useAuthStore((s) => s.logout);

  async function onLogout() {
    // The store clears session state but does not navigate — the caller does.
    await logout();
    router.replace("/login");
  }

  return (
    <header className="flex items-center justify-between border-b px-6 py-3">
      <span className="font-heading text-base font-medium">Nexus</span>
      <div className="flex items-center gap-3">
        {email && (
          <span className="text-sm text-muted-foreground">{email}</span>
        )}
        <Button variant="outline" size="sm" onClick={onLogout}>
          Log out
        </Button>
      </div>
    </header>
  );
}

export default function Home() {
  return (
    <ProtectedRoute>
      <div className="flex min-h-full flex-1 flex-col">
        <DashboardHeader />
        <main className="mx-auto w-full max-w-5xl flex-1 px-6 py-8">
          <h1 className="font-heading text-xl font-medium">Workspace</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Coming in Part 9.
          </p>
          <div className="mt-6 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {FEATURES.map((feature) => {
              const card = (
                <Card
                  key={feature.title}
                  className={
                    feature.href
                      ? "transition-shadow hover:shadow-sm"
                      : undefined
                  }
                >
                  <CardHeader>
                    <CardTitle>{feature.title}</CardTitle>
                    <CardDescription>{feature.description}</CardDescription>
                  </CardHeader>
                </Card>
              );
              if (!feature.href) return card;
              return (
                <Link key={feature.title} href={feature.href} className="block">
                  {card}
                </Link>
              );
            })}
          </div>
        </main>
      </div>
    </ProtectedRoute>
  );
}
