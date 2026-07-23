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
        </main>
      </div>
    </ProtectedRoute>
  );
}
