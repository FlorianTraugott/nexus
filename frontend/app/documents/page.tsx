"use client";

// The documents manager — READ path (9D.1a). Lists the user's corpus with an
// ingestion-status badge. No polling/upload/delete yet (9D.1b/9D.2/9D.3).

import { useState, type FormEvent } from "react";
import Link from "next/link";
import { useQueryClient } from "@tanstack/react-query";
import { isAxiosError } from "axios";
import { Trash2 } from "lucide-react";

import { useDocuments } from "@/hooks/use-documents";
import { useUploadDocument } from "@/hooks/use-upload-document";
import { useDeleteDocument } from "@/hooks/use-delete-document";
import { ProtectedRoute } from "@/components/protected-route";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from "@/components/ui/alert-dialog";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { mapDeleteError, mapUploadError } from "@/lib/documents-forms";
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

function DeleteControl({ doc }: { doc: DocumentRead }) {
  const [open, setOpen] = useState(false);
  const queryClient = useQueryClient();
  const { mutate, isPending, isError, error, reset } = useDeleteDocument();

  function onConfirm() {
    mutate(doc.id, {
      onSuccess: () => setOpen(false),
      onError: (err) => {
        // The 404 policy, in ONE place. A 404 means the doc is already gone
        // (a concurrent delete, or a stale tab): reconcile the list so the row
        // drops, and close — no scary alert, since "gone" was the goal. Any
        // other error leaves the dialog open with the mapped message below.
        if (isAxiosError(err) && err.response?.status === 404) {
          queryClient.invalidateQueries({ queryKey: ["documents"] });
          setOpen(false);
        }
      },
    });
  }

  return (
    <AlertDialog
      open={open}
      // reset() on open clears a stale error/pending from a prior attempt so the
      // dialog reopens clean.
      onOpenChange={(next) => {
        setOpen(next);
        if (next) reset();
      }}
    >
      <AlertDialogTrigger
        render={
          <Button
            variant="ghost"
            size="icon"
            aria-label={`Delete ${doc.filename}`}
          />
        }
      >
        <Trash2 className="size-4" />
      </AlertDialogTrigger>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>Delete “{doc.filename}”?</AlertDialogTitle>
          <AlertDialogDescription>
            This permanently removes the document and everything indexed from it.
            This can’t be undone.
          </AlertDialogDescription>
        </AlertDialogHeader>
        {isError && (
          <Alert variant="destructive">
            <AlertDescription>{mapDeleteError(error)}</AlertDescription>
          </Alert>
        )}
        <AlertDialogFooter>
          <AlertDialogCancel disabled={isPending}>Cancel</AlertDialogCancel>
          <AlertDialogAction
            variant="destructive"
            disabled={isPending}
            onClick={onConfirm}
          >
            {isPending ? "Deleting…" : "Delete"}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
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
        <div className="flex shrink-0 items-center gap-2">
          <StatusBadge status={doc.status} />
          <DeleteControl doc={doc} />
        </div>
      </CardContent>
    </Card>
  );
}

function UploadControl() {
  const [file, setFile] = useState<File | null>(null);
  // Bumped on success to remount the file input, clearing its native value
  // (ref-free — avoids relying on ref-forwarding through the base-ui Input).
  const [inputKey, setInputKey] = useState(0);
  const { mutate, isPending, isError, error, reset } = useUploadDocument();

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    if (!file) return;
    mutate(file, {
      onSuccess: () => {
        setFile(null);
        setInputKey((k) => k + 1);
      },
    });
  }

  return (
    <form onSubmit={onSubmit} className="flex flex-col gap-3">
      <div className="flex items-center gap-3">
        <Input
          key={inputKey}
          type="file"
          accept=".pdf,.txt,.text,.md,.markdown"
          disabled={isPending}
          onChange={(e) => {
            setFile(e.target.files?.[0] ?? null);
            reset(); // drop a stale error when a new file is chosen
          }}
          className="max-w-sm"
        />
        <Button type="submit" disabled={!file || isPending}>
          {isPending ? "Uploading…" : "Upload"}
        </Button>
      </div>
      {isError && (
        <Alert variant="destructive">
          <AlertTitle>Upload failed</AlertTitle>
          <AlertDescription>{mapUploadError(error)}</AlertDescription>
        </Alert>
      )}
    </form>
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
            <UploadControl />
          </div>
          <div className="mt-6">
            <DocumentsList />
          </div>
        </main>
      </div>
    </ProtectedRoute>
  );
}
