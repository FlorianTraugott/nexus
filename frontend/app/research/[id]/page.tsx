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
import { isAxiosError } from "axios";

import { useResearchTask } from "@/hooks/use-research-task";
import { PageHeader } from "@/components/page-header";
import { ProtectedRoute } from "@/components/protected-route";
import { StatusBadge } from "@/components/status-badge";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import {
  RESEARCH_STATUS_DISPLAY,
  isResearchTaskStalled,
  isTerminalResearchStatus,
} from "@/lib/research";
import type {
  KBFindings,
  ResearchReport,
  ResearchTaskRead,
  Summary,
  WebSearchFindings,
} from "@/types/api";

const PREVIEW_MAX_CHARS = 220;

// Degradations are visible even on success — a silently swallowed warning is
// the "plausible but secretly wrong" failure this project rejects. It uses the
// `warn` tone, which is deliberately NOT a StatusTone: this is a run that
// SUCCEEDED with caveats, so `bad` would overstate it and `neutral` would let
// it be skipped.
function WarningsBanner({ warnings }: { warnings: string[] }) {
  if (warnings.length === 0) return null;
  return (
    <div className="rounded-xl bg-tone-warn-surface px-5 py-4">
      <p className="font-mono text-meta uppercase text-tone-warn">
        This run degraded
      </p>
      <ul className="mt-2 flex flex-col gap-1.5">
        {warnings.map((w) => (
          <li key={w} className="text-sm text-ink-2">
            {w}
          </li>
        ))}
      </ul>
    </div>
  );
}

// The summarise agent's output. It has always been on the wire and was never
// rendered — the page jumped straight from the topic into report sections while
// the pipeline had already produced exactly the lede a report wants.
function SummaryView({ summary }: { summary: Summary }) {
  return (
    <section className="rounded-xl bg-card px-6 py-5 shadow-xs">
      <p className="font-mono text-meta uppercase text-ink-2">Summary</p>
      <p className="mt-3 font-reading text-reading">{summary.abstract}</p>
      {summary.key_points.length > 0 && (
        <ul className="mt-4 flex flex-col gap-2">
          {summary.key_points.map((point) => (
            <li key={point} className="flex gap-3 text-sm">
              <span aria-hidden="true" className="text-primary">
                —
              </span>
              <span className="text-ink-2">{point}</span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function ReportView({ report }: { report: ResearchReport }) {
  // Sections as structured text — rendering report.markdown with a real
  // markdown component is a recorded deferral (new dep, decided deliberately).
  return (
    <article className="flex flex-col gap-8">
      <h2 className="text-title text-balance">{report.title}</h2>
      {report.sections.map((s) => (
        <section key={s.heading}>
          <h3 className="text-section">{s.heading}</h3>
          <p className="mt-2 font-reading text-reading whitespace-pre-wrap">
            {s.body}
          </p>
        </section>
      ))}
    </article>
  );
}

// Ranked, like the chat citations and for the same reason: a raw cosine distance
// has no scale and reads backwards (lower is better). It stays in the title.
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
    <div className="flex flex-col gap-6 border-t pt-6">
      <h3 className="text-section">Evidence</h3>
      {hasKb && (
        <div>
          <p className="font-mono text-meta uppercase text-ink-2">
            From your documents · {kb.findings.length}
          </p>
          <ol className="mt-2.5 flex flex-col gap-2.5">
            {kb.findings.map((f, i) => (
              <li
                key={f.chunk_id}
                className="grid grid-cols-[1.25rem_1fr] gap-3"
                title={`Rank ${i + 1} of ${kb.findings.length} · cosine distance ${f.distance.toFixed(4)} (lower is more relevant)`}
              >
                <span className="font-mono text-meta text-primary">{i + 1}</span>
                <p className="text-sm text-ink-2">
                  {f.content_preview.length > PREVIEW_MAX_CHARS
                    ? `${f.content_preview.slice(0, PREVIEW_MAX_CHARS)}…`
                    : f.content_preview}
                </p>
              </li>
            ))}
          </ol>
        </div>
      )}
      {hasWeb && (
        <div>
          <p className="font-mono text-meta uppercase text-ink-2">
            From the web · {web.hits.length}
          </p>
          <ul className="mt-2.5 flex flex-col gap-2.5">
            {web.hits.map((h) => (
              <li key={h.url} className="text-sm">
                <a
                  href={h.url}
                  target="_blank"
                  rel="noreferrer"
                  className="font-medium text-primary underline-offset-4 hover:underline"
                >
                  {h.title}
                </a>
                <p className="mt-0.5 text-ink-2">{h.snippet}</p>
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
              className="mt-3"
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
      <div className="rounded-xl bg-card px-6 py-12 text-center shadow-xs">
        <p className="animate-pulse text-section">Researching…</p>
        <p className="mx-auto mt-2 max-w-md text-sm text-ink-2">
          Searching, reading your documents, and writing the report. This usually
          takes under a minute, and the page keeps itself up to date.
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
  // failure. Deliberately NOT styled like bucket 3: the framing says the run
  // completed, and whatever evidence it gathered before failing is still real
  // output and stays on the page.
  if (task.result.error !== null) {
    return (
      <div className="flex flex-col gap-6">
        <div>
          <p className="font-mono text-meta uppercase text-ink-2">
            The run completed, then reported a failure
          </p>
          <Alert variant="destructive" className="mt-2">
            <AlertTitle>The pipeline could not finish its report</AlertTitle>
            <AlertDescription>{task.result.error}</AlertDescription>
          </Alert>
        </div>
        <WarningsBanner warnings={task.result.warnings} />
        {task.result.summary && <SummaryView summary={task.result.summary} />}
        <Evidence kb={task.result.kb} web={task.result.web} />
      </div>
    );
  }

  // Bucket 1: success.
  return (
    <div className="flex flex-col gap-8">
      <WarningsBanner warnings={task.result.warnings} />
      {task.result.summary && <SummaryView summary={task.result.summary} />}
      {task.result.report ? (
        <ReportView report={task.result.report} />
      ) : (
        <p className="text-sm text-ink-2">
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

  const notFound = isAxiosError(error) && error.response?.status === 404;

  return (
    <ProtectedRoute>
      <main className="mx-auto w-full max-w-3xl flex-1 px-6 py-10">
        {task ? (
          <PageHeader
            backHref="/research"
            backLabel="Research"
            title={task.topic}
            description={`Started ${new Date(task.created_at).toLocaleString()}`}
            actions={
              <StatusBadge {...RESEARCH_STATUS_DISPLAY[task.status]} />
            }
          />
        ) : (
          <PageHeader
            backHref="/research"
            backLabel="Research"
            title="Research task"
          />
        )}

        <div className="mt-8">
          {isPending && <p className="text-sm text-ink-2">Loading task…</p>}
          {isError && (
            <Alert variant="destructive">
              <AlertTitle>
                {notFound
                  ? "Research task not found"
                  : "Couldn’t load the task"}
              </AlertTitle>
              <AlertDescription>
                {notFound
                  ? "It may belong to another account, or the link is wrong."
                  : "Please try again."}
              </AlertDescription>
            </Alert>
          )}
          {task && (
            <TaskBody
              task={task}
              onRecheck={() => void refetch()}
              isRechecking={isFetching}
            />
          )}
        </div>
      </main>
    </ProtectedRoute>
  );
}
