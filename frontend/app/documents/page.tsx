"use client";

// The documents manager: list (status-aware polling), upload, delete.

import { useState, type FormEvent } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { isAxiosError } from "axios";
import { Trash2 } from "lucide-react";

import { useDocuments } from "@/hooks/use-documents";
import { useUploadDocument } from "@/hooks/use-upload-document";
import { useDeleteDocument } from "@/hooks/use-delete-document";
import { PageHeader } from "@/components/page-header";
import { ProtectedRoute } from "@/components/protected-route";
import { StatusBadge } from "@/components/status-badge";
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
import { Input } from "@/components/ui/input";
import { DOCUMENT_STATUS_DISPLAY } from "@/lib/documents";
import { mapDeleteError, mapUploadError } from "@/lib/documents-forms";
import type { DocumentRead } from "@/types/api";

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
            size="icon-sm"
            aria-label={`Delete ${doc.filename}`}
            // Always visible — see the same note in app/chat/layout.tsx: a
            // hover-revealed control is unreachable on touch, because Tailwind
            // v4's hover variants live inside @media (hover: hover).
            className="text-muted-foreground hover:text-destructive"
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
  const { tone, label } = DOCUMENT_STATUS_DISPLAY[doc.status];
  return (
    // A row in a shared surface, not a Card of its own: a list of N boxes is the
    // same "outline around everything" tell, repeated N times.
    <li className="flex items-center gap-4 px-5 py-4 transition-colors hover:bg-muted/40">
      <div className="min-w-0 flex-1">
        <p className="truncate font-medium">{doc.filename}</p>
        <p className="mt-1 font-mono text-meta text-ink-2">
          {doc.chunk_count} chunks · {new Date(doc.created_at).toLocaleString()}
        </p>
      </div>
      <StatusBadge tone={tone} label={label} />
      <DeleteControl doc={doc} />
    </li>
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
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
        <Input
          key={inputKey}
          type="file"
          accept=".pdf,.txt,.text,.md,.markdown"
          disabled={isPending}
          onChange={(e) => {
            setFile(e.target.files?.[0] ?? null);
            reset(); // drop a stale error when a new file is chosen
          }}
          className="sm:max-w-sm"
        />
        <Button
          type="submit"
          disabled={!file || isPending}
          className="sm:shrink-0"
        >
          {isPending ? "Uploading…" : "Upload"}
        </Button>
      </div>
      <p className="font-mono text-meta text-ink-2">
        PDF, TXT or Markdown · up to 25 MB
      </p>
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
    return <p className="text-sm text-ink-2">Loading…</p>;
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
      <div className="rounded-xl bg-card px-6 py-12 text-center shadow-xs">
        <p className="text-section">No documents yet</p>
        <p className="mx-auto mt-2 max-w-sm text-sm text-ink-2">
          Upload a PDF, text or Markdown file above. Once it finishes indexing,
          you can ask questions against it in Chat.
        </p>
      </div>
    );
  }

  return (
    <ul className="divide-y overflow-hidden rounded-xl bg-card shadow-xs">
      {data.map((doc) => (
        <DocumentRow key={doc.id} doc={doc} />
      ))}
    </ul>
  );
}

export default function DocumentsPage() {
  return (
    <ProtectedRoute>
      <main className="mx-auto w-full max-w-4xl flex-1 px-6 py-10">
        <PageHeader
          backHref="/"
          backLabel="Workspace"
          title="Documents"
          description="Your corpus. Everything uploaded here is chunked, embedded and indexed — and it is the only thing answers are allowed to draw on."
        />
        <div className="mt-8">
          <UploadControl />
        </div>
        <div className="mt-8">
          <DocumentsList />
        </div>
      </main>
    </ProtectedRoute>
  );
}
