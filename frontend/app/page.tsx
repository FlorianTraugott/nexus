"use client";

import Link from "next/link";

import { useAuthStore } from "@/stores/auth";
import { LogoutButton } from "@/components/logout-button";
import { ProtectedRoute } from "@/components/protected-route";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";

// The three surfaces. Copy names the OUTCOME a person gets, not the machinery
// that produces it — "run the multi-agent research pipeline" describes our
// implementation, which is no help to someone deciding where to click. `meta`
// is the one thing each surface actually hands back.
//
// href is required now: every surface has a route, and the optional-href
// branching this array used to carry was dead.
const FEATURES: {
  title: string;
  description: string;
  meta: string;
  href: string;
}[] = [
  {
    title: "Chat",
    description:
      "Ask a question and get an answer built from your own documents, with the passages it drew on.",
    meta: "Streamed answer · citations",
    href: "/chat",
  },
  {
    title: "Documents",
    description:
      "Add and manage the material everything else answers from. Uploads are chunked, embedded and indexed.",
    meta: "PDF · text · Markdown",
    href: "/documents",
  },
  {
    title: "Research",
    description:
      "Hand over a topic and get back a written report, with the evidence it was assembled from attached.",
    meta: "Structured report · under a minute",
    href: "/research",
  },
];

function DashboardHeader() {
  const email = useAuthStore((s) => s.user?.email);

  return (
    <header className="border-b bg-card">
      <div className="mx-auto flex w-full max-w-5xl items-center justify-between gap-4 px-6 py-3">
        <span className="font-mono text-meta uppercase text-ink-2">Nexus</span>
        <div className="flex items-center gap-4">
          {email && (
            <span className="hidden truncate text-sm text-ink-2 sm:block">
              {email}
            </span>
          )}
          <LogoutButton />
        </div>
      </div>
    </header>
  );
}

export default function Home() {
  return (
    <ProtectedRoute>
      <div className="flex min-h-full flex-1 flex-col">
        <DashboardHeader />
        <main className="mx-auto w-full max-w-5xl flex-1 px-6 py-12">
          <h1 className="text-title text-balance">Workspace</h1>
          <p className="mt-3 max-w-prose text-sm text-ink-2">
            Three ways in. Everything here answers from the documents you
            upload — and says so when nothing in them fits.
          </p>
          <div className="mt-10 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {FEATURES.map((feature) => (
              <Link
                key={feature.title}
                href={feature.href}
                className="block transition-shadow hover:shadow-sm"
              >
                <Card className="h-full">
                  <CardHeader>
                    <CardTitle>{feature.title}</CardTitle>
                    <CardDescription>{feature.description}</CardDescription>
                  </CardHeader>
                  <CardContent>
                    <p className="font-mono text-meta uppercase text-primary">
                      {feature.meta}
                    </p>
                  </CardContent>
                </Card>
              </Link>
            ))}
          </div>
        </main>
      </div>
    </ProtectedRoute>
  );
}
