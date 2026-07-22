"use client";

// The documents manager — READ path (9D.1a). Lists the user's corpus with an
// ingestion-status badge. No polling/upload/delete yet (9D.1b/9D.2/9D.3).

import Link from "next/link";

import { useDocuments } from "@/hooks/use-documents";
import { ProtectedRoute } from "@/components/protected-route";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Card, CardContent } from "@/components/ui/card";
import { cn } from "@/lib/utils";
import type { DocumentRead, DocumentStatus } from "@/types/api";

// status -> badge classes, keyed by EVERY DocumentStatus. Typed as a Record so a
// new backend status becomes a compile error here, not a silently blank badge —
// fail loud at the boundary.
const STATUS_BADGE: Record<DocumentStatus, string> = {
  pending: "bg-amber-100 text-amber-800 ring-amber-600/20",
  processing: "bg-blue-100 text-blue-800 ring-blue-600/20",
  completed: "bg-green-100 text-green-800 ring-green-600/20",
  failed: "bg-red-100 text-red-800 ring-red-600/20",
};

function StatusBadge({ status }: { status: DocumentStatus }) {
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

function DocumentRow({ doc }: { doc: DocumentRead }) {
  return (
    <Card>
      <CardContent className="flex items-center justify-between gap-4">
        <div className="min-w-0">
          <p className="truncate font-medium">{doc.filename}</p>
          <p className="text-xs text-muted-foreground">
            {doc.chunk_count} chunks · {new Date(doc.created_at).toLocaleString()}
          </p>
        </div>
        <StatusBadge status={doc.status} />
      </CardContent>
    </Card>
  );
}

function DocumentsList() {
  const { data, isPending, isError, error } = useDocuments();

  if (isPending) {
    return <p className="text-sm text-muted-foreground">Loading…</p>;
  }

  if (isError) {
    return (
      <Alert variant="destructive">
        <AlertTitle>Could not load your documents</AlertTitle>
        <AlertDescription>
          {error instanceof Error ? error.message : "Please try again."}
        </AlertDescription>
      </Alert>
    );
  }

  if (data.length === 0) {
    return (
      <div className="rounded-xl border border-dashed p-10 text-center">
        <p className="text-sm font-medium">No documents yet</p>
        <p className="mt-1 text-sm text-muted-foreground">
          Upload a PDF or text file to build your corpus.
        </p>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-3">
      {data.map((doc) => (
        <DocumentRow key={doc.id} doc={doc} />
      ))}
    </div>
  );
}

export default function DocumentsPage() {
  return (
    <ProtectedRoute>
      <div className="flex min-h-full flex-1 flex-col">
        <main className="mx-auto w-full max-w-5xl flex-1 px-6 py-8">
          <Link
            href="/"
            className="text-sm text-muted-foreground hover:text-foreground"
          >
            ← Workspace
          </Link>
          <h1 className="mt-2 font-heading text-xl font-medium">Documents</h1>
          <div className="mt-6">
            <DocumentsList />
          </div>
        </main>
      </div>
    </ProtectedRoute>
  );
}
