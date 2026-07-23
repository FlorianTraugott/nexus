"use client";

// Chat section layout: the conversation sidebar persists across /chat <->
// /chat/[id] navigations, and ProtectedRoute guards BOTH routes from here —
// including a direct hard-load of /chat/{id} with no session.

import { useState } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useQueryClient } from "@tanstack/react-query";
import { isAxiosError } from "axios";
import { Trash2 } from "lucide-react";

import { useConversations } from "@/hooks/use-conversations";
import { useDeleteConversation } from "@/hooks/use-delete-conversation";
import { ProtectedRoute } from "@/components/protected-route";
import { Alert, AlertDescription } from "@/components/ui/alert";
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
import { Button, buttonVariants } from "@/components/ui/button";
import { mapDeleteConversationError } from "@/lib/conversations-forms";
import { cn } from "@/lib/utils";
import type { ConversationRead } from "@/types/api";

function DeleteConversationControl({
  conversation,
  isActive,
}: {
  conversation: ConversationRead;
  isActive: boolean;
}) {
  const [open, setOpen] = useState(false);
  const router = useRouter();
  const queryClient = useQueryClient();
  const { mutate, isPending, isError, error, reset } = useDeleteConversation();

  // Deleting the ACTIVE conversation must not leave the user on a dead route.
  function afterGone() {
    setOpen(false);
    if (isActive) router.replace("/chat");
  }

  function onConfirm() {
    mutate(conversation.id, {
      onSuccess: afterGone,
      onError: (err) => {
        // "Already gone" policy, one place (same as documents): 404 means the
        // goal state is reached — reconcile the list and close quietly.
        if (isAxiosError(err) && err.response?.status === 404) {
          queryClient.invalidateQueries({ queryKey: ["conversations"] });
          afterGone();
        }
      },
    });
  }

  return (
    <AlertDialog
      open={open}
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
            aria-label={`Delete ${conversation.title}`}
            className="opacity-0 group-hover/row:opacity-100 focus-visible:opacity-100"
          />
        }
      >
        <Trash2 className="size-3.5" />
      </AlertDialogTrigger>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>Delete “{conversation.title}”?</AlertDialogTitle>
          <AlertDialogDescription>
            This permanently removes the conversation and its messages. This
            can’t be undone.
          </AlertDialogDescription>
        </AlertDialogHeader>
        {isError && (
          <Alert variant="destructive">
            <AlertDescription>
              {mapDeleteConversationError(error)}
            </AlertDescription>
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

function ConversationRow({ conversation }: { conversation: ConversationRead }) {
  // usePathname syncs with BOTH real navigations and history.replaceState
  // (Chat.3b's lazy create), so the active highlight tracks either.
  const pathname = usePathname();
  const isActive = pathname === `/chat/${conversation.id}`;

  return (
    <div
      className={cn(
        "group/row flex items-center gap-1 rounded-md pr-1",
        isActive ? "bg-muted" : "hover:bg-muted/50",
      )}
    >
      <Link
        href={`/chat/${conversation.id}`}
        className="min-w-0 flex-1 truncate px-2 py-1.5 text-sm"
        title={conversation.title}
      >
        {conversation.title}
      </Link>
      <DeleteConversationControl
        conversation={conversation}
        isActive={isActive}
      />
    </div>
  );
}

function ConversationSidebar() {
  const { data, isPending, isError } = useConversations();

  return (
    <aside className="flex w-64 shrink-0 flex-col border-r">
      <div className="flex flex-col gap-3 p-4">
        <Link
          href="/"
          className="text-sm text-muted-foreground hover:text-foreground"
        >
          ← Workspace
        </Link>
        <Link
          href="/chat"
          className={cn(buttonVariants({ variant: "outline", size: "sm" }))}
        >
          New chat
        </Link>
      </div>
      <nav className="flex-1 overflow-y-auto px-2 pb-4">
        {isPending && (
          <p className="px-2 text-sm text-muted-foreground">Loading…</p>
        )}
        {isError && (
          <p className="px-2 text-sm text-destructive">
            Couldn’t load conversations.
          </p>
        )}
        {data && data.length === 0 && (
          <p className="px-2 text-sm text-muted-foreground">
            No conversations yet.
          </p>
        )}
        {data && data.length > 0 && (
          <div className="flex flex-col gap-0.5">
            {data.map((c) => (
              <ConversationRow key={c.id} conversation={c} />
            ))}
          </div>
        )}
      </nav>
    </aside>
  );
}

export default function ChatLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <ProtectedRoute>
      <div className="flex min-h-full flex-1">
        <ConversationSidebar />
        {children}
      </div>
    </ProtectedRoute>
  );
}
