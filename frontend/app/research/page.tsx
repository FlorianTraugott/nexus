"use client";

// Research launcher: a topic in -> 202 + task id -> navigate to the poll page.
// Plain router.push — nothing streams client-side here, so the remount is
// harmless (unlike chat's replaceState situation).

import { useState, type FormEvent } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";

import { useCreateResearchTask } from "@/hooks/use-create-research-task";
import { ProtectedRoute } from "@/components/protected-route";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { mapCreateResearchError } from "@/lib/research-forms";

// The pre-seeded demo research task (scripts/seed_demo.py). Baked at BUILD time,
// so it is only set in the deployed demo; absent in local dev, where the card
// simply does not render. No fallback: an unset var means "no example report".
const DEMO_RESEARCH_TASK_ID = process.env.NEXT_PUBLIC_DEMO_RESEARCH_TASK_ID;

export default function ResearchPage() {
  const router = useRouter();
  const [topic, setTopic] = useState("");
  const { mutate, isPending, isError, error } = useCreateResearchTask();

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    const t = topic.trim();
    if (!t || isPending) return;
    mutate(t, {
      onSuccess: (created) => router.push(`/research/${created.task_id}`),
    });
  }

  return (
    <ProtectedRoute>
      <div className="flex min-h-full flex-1 flex-col">
        <main className="mx-auto w-full max-w-3xl flex-1 px-6 py-8">
          <Link
            href="/"
            className="text-sm text-muted-foreground hover:text-foreground"
          >
            ← Workspace
          </Link>
          <h1 className="mt-2 font-heading text-xl font-medium">Research</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Runs the multi-agent pipeline over your documents (and web search,
            when configured) and writes a structured report.
          </p>
          <form onSubmit={onSubmit} className="mt-6 flex items-center gap-3">
            <Input
              value={topic}
              onChange={(e) => setTopic(e.target.value)}
              placeholder="What should be researched?"
              disabled={isPending}
              autoFocus
            />
            <Button type="submit" disabled={isPending || !topic.trim()}>
              {isPending ? "Starting…" : "Start research"}
            </Button>
          </form>
          {isError && (
            <Alert variant="destructive" className="mt-4">
              <AlertTitle>Couldn’t start</AlertTitle>
              <AlertDescription>{mapCreateResearchError(error)}</AlertDescription>
            </Alert>
          )}
          {DEMO_RESEARCH_TASK_ID && (
            <div className="mt-8 rounded-lg border p-4">
              <p className="text-sm font-medium">See an example report</p>
              <p className="mt-1 text-sm text-muted-foreground">
                A completed research run over the demo documents — no wait, no
                cost.
              </p>
              <Link
                href={`/research/${DEMO_RESEARCH_TASK_ID}`}
                className="mt-3 inline-block text-sm font-medium text-primary hover:underline"
              >
                View the example report →
              </Link>
            </div>
          )}
        </main>
      </div>
    </ProtectedRoute>
  );
}
