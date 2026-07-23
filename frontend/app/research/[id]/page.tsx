"use client";

// Research task poll + result. The three TERMINAL shapes render as three
// distinct buckets, honest to the backend's asymmetry:
//   1. success            — status "completed", result.report populated
//   2. pipeline failure   — status "completed", result.error non-null: a run
//                           that FINISHED and recorded its own failure (never
//                           styled as a crashed task)
//   3. infrastructure     — status "failed", top-level error, result null
// While pending/running the honest UI is an indeterminate "Researching…":
// the backend persists no per-stage progress (stage lives inside result,
// which is null until terminal) — 4-step progress is a recorded divergence.
// A non-terminal task past the stall ceiling stops polling and renders a
// stalled state with a manual re-check.

import { useParams } from "next/navigation";
import Link from "next/link";
import { isAxiosError } from "axios";

import { useResearchTask } from "@/hooks/use-research-task";
import { isResearchTaskStalled, isTerminalResearchStatus } from "@/lib/research";
import { ProtectedRoute } from "@/components/protected-route";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import type {
  KBFindings,
  ResearchReport,
  ResearchTaskRead,
  ResearchTaskStatus,
  WebSearchFindings,
} from "@/types/api";

// Keyed by EVERY status so a new backend status is a compile error here, not a
// silently blank badge (same discipline as the documents status badge).
const STATUS_BADGE: Record<ResearchTaskStatus, string> = {
  pending: "bg-amber-100 text-amber-800 ring-amber-600/20",
  running: "bg-blue-100 text-blue-800 ring-blue-600/20",
  completed: "bg-green-100 text-green-800 ring-green-600/20",
  failed: "bg-red-100 text-red-800 ring-red-600/20",
};

function StatusBadge({ status }: { status: ResearchTaskStatus }) {
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ring-1 ring-inset",
        STATUS_BADGE[status],
      )}
    >
      {status}
    </span>
  );
}

// Degradations are visible even on success — a silently swallowed warning is
// the "plausible but secretly wrong" failure this project rejects.
function WarningsBanner({ warnings }: { warnings: string[] }) {
  if (warnings.length === 0) return null;
  return (
    <div className="rounded-lg border border-amber-300 bg-amber-50 px-4 py-3 text-sm text-amber-900 dark:border-amber-700 dark:bg-amber-950 dark:text-amber-200">
      <p className="font-medium">This run degraded:</p>
      <ul className="mt-1 list-inside list-disc">
        {warnings.map((w) => (
          <li key={w}>{w}</li>
        ))}
      </ul>
    </div>
  );
}

function ReportView({ report }: { report: ResearchReport }) {
  // Sections as structured text — rendering report.markdown with a real
  // markdown component is a recorded deferral (new dep, decided deliberately).
  return (
    <article className="flex flex-col gap-6">
      <h2 className="font-heading text-lg font-medium">{report.title}</h2>
      {report.sections.map((s) => (
        <section key={s.heading}>
          <h3 className="text-sm font-semibold">{s.heading}</h3>
          <p className="mt-1 text-sm whitespace-pre-wrap">{s.body}</p>
        </section>
      ))}
    </article>
  );
}

function Evidence({
  kb,
  web,
}: {
  kb: KBFindings | null;
  web: WebSearchFindings | null;
}) {
  const hasKb = kb !== null && kb.findings.length > 0;
  const hasWeb = web !== null && web.hits.length > 0;
  if (!hasKb && !hasWeb) return null;
  return (
    <div className="flex flex-col gap-4 border-t pt-4">
      <h3 className="text-sm font-semibold">Evidence</h3>
      {hasKb && (
        <div>
          <p className="text-xs font-medium text-muted-foreground">
            From your documents ({kb.findings.length})
          </p>
          <ol className="mt-1 flex flex-col gap-1">
            {kb.findings.map((f, i) => (
              <li key={f.chunk_id} className="text-xs text-muted-foreground">
                <span className="font-medium">[{i + 1}]</span>{" "}
                {f.content_preview.length > 200
                  ? `${f.content_preview.slice(0, 200)}…`
                  : f.content_preview}
              </li>
            ))}
          </ol>
        </div>
      )}
      {hasWeb && (
        <div>
          <p className="text-xs font-medium text-muted-foreground">
            From the web ({web.hits.length})
          </p>
          <ul className="mt-1 flex flex-col gap-1">
            {web.hits.map((h) => (
              <li key={h.url} className="text-xs text-muted-foreground">
                <a
                  href={h.url}
                  target="_blank"
                  rel="noreferrer"
                  className="font-medium underline-offset-2 hover:underline"
                >
                  {h.title}
                </a>{" "}
                — {h.snippet}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

function TaskBody({
  task,
  onRecheck,
  isRechecking,
}: {
  task: ResearchTaskRead;
  onRecheck: () => void;
  isRechecking: boolean;
}) {
  // Non-terminal: indeterminate progress or the stalled state.
  if (!isTerminalResearchStatus(task.status)) {
    if (isResearchTaskStalled(task)) {
      return (
        <Alert>
          <AlertTitle>This task appears stalled</AlertTitle>
          <AlertDescription>
            <p>
              No progress since{" "}
              {new Date(task.updated_at).toLocaleTimeString()}. It may still
              complete — the server may have restarted mid-run.
            </p>
            <Button
              variant="outline"
              size="sm"
              className="mt-2"
              onClick={onRecheck}
              disabled={isRechecking}
            >
              {isRechecking ? "Checking…" : "Check again"}
            </Button>
          </AlertDescription>
        </Alert>
      );
    }
    return (
      <div className="rounded-xl border border-dashed p-10 text-center">
        <p className="animate-pulse text-sm font-medium">Researching…</p>
        <p className="mt-1 text-sm text-muted-foreground">
          Searching, reading your documents, and writing the report. This
          usually takes under a minute.
        </p>
      </div>
    );
  }

  // Bucket 3: infrastructure failure — the runner itself died.
  if (task.status === "failed") {
    return (
      <Alert variant="destructive">
        <AlertTitle>The task failed</AlertTitle>
        <AlertDescription>
          {task.error ?? "The run could not be executed. Please try again."}
        </AlertDescription>
      </Alert>
    );
  }

  // status "completed" — result is the contract here; guard defensively anyway.
  if (task.result === null) {
    return (
      <Alert variant="destructive">
        <AlertTitle>Completed without a result</AlertTitle>
        <AlertDescription>
          The task finished but returned nothing — this shouldn’t happen.
        </AlertDescription>
      </Alert>
    );
  }

  // Bucket 2: pipeline failure — a run that FINISHED and recorded its own
  // failure. Partial evidence may exist and is still shown.
  if (task.result.error !== null) {
    return (
      <div className="flex flex-col gap-4">
        <Alert variant="destructive">
          <AlertTitle>The pipeline could not complete</AlertTitle>
          <AlertDescription>{task.result.error}</AlertDescription>
        </Alert>
        <WarningsBanner warnings={task.result.warnings} />
        <Evidence kb={task.result.kb} web={task.result.web} />
      </div>
    );
  }

  // Bucket 1: success.
  return (
    <div className="flex flex-col gap-6">
      <WarningsBanner warnings={task.result.warnings} />
      {task.result.report ? (
        <ReportView report={task.result.report} />
      ) : (
        <p className="text-sm text-muted-foreground">
          The run completed without producing a report.
        </p>
      )}
      <Evidence kb={task.result.kb} web={task.result.web} />
    </div>
  );
}

export default function ResearchTaskPage() {
  const { id } = useParams<{ id: string }>();
  const {
    data: task,
    isPending,
    isError,
    error,
    refetch,
    isFetching,
  } = useResearchTask(id);

  return (
    <ProtectedRoute>
      <div className="flex min-h-full flex-1 flex-col">
        <main className="mx-auto w-full max-w-3xl flex-1 px-6 py-8">
          <Link
            href="/research"
            className="text-sm text-muted-foreground hover:text-foreground"
          >
            ← Research
          </Link>
          {isPending && (
            <p className="mt-6 text-sm text-muted-foreground">Loading task…</p>
          )}
          {isError && (
            <Alert variant="destructive" className="mt-6">
              <AlertTitle>
                {isAxiosError(error) && error.response?.status === 404
                  ? "Research task not found"
                  : "Couldn’t load the task"}
              </AlertTitle>
              <AlertDescription>
                {isAxiosError(error) && error.response?.status === 404
                  ? "It may belong to another account, or the link is wrong."
                  : "Please try again."}
              </AlertDescription>
            </Alert>
          )}
          {task && (
            <>
              <div className="mt-2 flex items-center justify-between gap-4">
                <h1 className="font-heading text-xl font-medium">
                  {task.topic}
                </h1>
                <StatusBadge status={task.status} />
              </div>
              <p className="mt-1 text-xs text-muted-foreground">
                Started {new Date(task.created_at).toLocaleString()}
              </p>
              <div className="mt-6">
                <TaskBody
                  task={task}
                  onRecheck={() => void refetch()}
                  isRechecking={isFetching}
                />
              </div>
            </>
          )}
        </main>
      </div>
    </ProtectedRoute>
  );
}
