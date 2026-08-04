"use client";

// Research launcher: a topic in -> 202 + task id -> navigate to the poll page.
// Plain router.push — nothing streams client-side here, so the remount is
// harmless (unlike chat's replaceState situation).

import { useState, type FormEvent } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";

import { useCreateResearchTask } from "@/hooks/use-create-research-task";
import { PageHeader } from "@/components/page-header";
import { ProtectedRoute } from "@/components/protected-route";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { mapCreateResearchError } from "@/lib/research-forms";

// The pre-seeded demo research task (scripts/seed_demo.py). Baked at BUILD time,
// so it is only set in the deployed demo; absent in local dev, where the card
// simply does not render. No fallback: an unset var means "no example report".
const DEMO_RESEARCH_TASK_ID = process.env.NEXT_PUBLIC_DEMO_RESEARCH_TASK_ID;

// The four agents the pipeline actually runs, in order. Named because the run is
// otherwise a black box for 30-60 seconds — this sets the expectation up front,
// which is the honest substitute for the live progress the backend cannot report.
const PIPELINE_STEPS = [
  "Searches the web (when a provider is configured)",
  "Queries your document corpus",
  "Summarises what both turned up",
  "Writes a structured report",
];

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
      <main className="mx-auto w-full max-w-3xl flex-1 px-6 py-10">
        <PageHeader
          backHref="/"
          backLabel="Workspace"
          title="Research"
          description="Four agents run in sequence over your documents and the web, then write a report with its evidence attached. A run takes under a minute."
        />

        <form onSubmit={onSubmit} className="mt-8 flex flex-col gap-3">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
            <Input
              value={topic}
              onChange={(e) => setTopic(e.target.value)}
              placeholder="What should be researched?"
              disabled={isPending}
              autoFocus
              className="h-11"
            />
            <Button
              type="submit"
              size="lg"
              disabled={isPending || !topic.trim()}
              className="sm:shrink-0"
            >
              {isPending ? "Starting…" : "Start research"}
            </Button>
          </div>
        </form>
        {isError && (
          <Alert variant="destructive" className="mt-4">
            <AlertTitle>Couldn’t start</AlertTitle>
            <AlertDescription>{mapCreateResearchError(error)}</AlertDescription>
          </Alert>
        )}

        <ol className="mt-8 flex flex-col gap-2.5">
          {PIPELINE_STEPS.map((step, i) => (
            <li key={step} className="flex gap-3 text-sm text-ink-2">
              {/* Numbered because the pipeline genuinely IS a sequence — each
                  agent consumes the previous one's output. */}
              <span className="font-mono text-meta text-primary">{i + 1}</span>
              {step}
            </li>
          ))}
        </ol>

        {DEMO_RESEARCH_TASK_ID && (
          <div className="mt-10 rounded-xl bg-card px-5 py-4 shadow-xs">
            <p className="text-section">See a finished report</p>
            <p className="mt-1.5 text-sm text-ink-2">
              A completed run over the demo documents — no wait, no cost.
            </p>
            <Link
              href={`/research/${DEMO_RESEARCH_TASK_ID}`}
              className="mt-3 inline-block text-sm font-medium text-primary underline-offset-4 hover:underline"
            >
              View the example report →
            </Link>
          </div>
        )}
      </main>
    </ProtectedRoute>
  );
}
