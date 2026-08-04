"use client";

// Chat section layout: the conversation sidebar persists across /chat <->
// /chat/[id] navigations, and ProtectedRoute guards BOTH routes from here —
// including a direct hard-load of /chat/{id} with no session.

import { useState } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useQueryClient } from "@tanstack/react-query";
import { isAxiosError } from "axios";
import { Menu, Plus, Trash2, X } from "lucide-react";

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
            // Always visible, never hover-revealed. In Tailwind v4 the hover
            // variants sit inside @media (hover: hover), so on a touch device
            // group-hover NEVER applies and an opacity-0 base would leave this
            // permanently invisible — unreachable on a phone, not merely
            // awkward. A hover-capability query could restore the reveal, but it
            // depends on the media rule sorting before group-hover, and if that
            // assumption is wrong the control disappears on DESKTOP instead: a
            // worse failure than the one being fixed. Low weight does the same
            // job as hiding, and a delete that only exists on hover is a
            // discoverability problem on desktop anyway.
            className="text-muted-foreground hover:text-destructive"
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
        // The active conversation is marked by an ultramarine edge rather than
        // a fill: the same accent that marks a grounded answer, used once here.
        "relative flex items-center gap-1 rounded-md pr-1 transition-colors",
        isActive
          ? "bg-muted before:absolute before:inset-y-1 before:left-0 before:w-0.5 before:rounded-full before:bg-primary"
          : "hover:bg-muted/60",
      )}
    >
      <Link
        href={`/chat/${conversation.id}`}
        className={cn(
          "min-w-0 flex-1 truncate px-3 py-2 text-sm",
          isActive ? "font-medium" : "text-ink-2",
        )}
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

function ConversationSidebar({ onClose }: { onClose: () => void }) {
  const { data, isPending, isError } = useConversations();

  return (
    // One mounted instance at both sizes: it SLIDES rather than being
    // conditionally rendered, so useConversations keeps its subscription and
    // opening the drawer never remounts (and refetches) the list.
    //
    // `invisible` when closed, not just `-translate-x-full`: an off-screen panel
    // is still in the tab order and the accessibility tree, so a keyboard user
    // at mobile width would tab into a list they cannot see. md:visible restores
    // it on desktop. Transitioning visibility alongside transform gives a real
    // slide-out — visibility flips immediately on show and holds to the end on
    // hide — instead of the panel vanishing before it has moved.
    <aside
      id="conversation-nav"
      aria-label="Conversations"
      className={cn(
        "invisible fixed inset-y-0 left-0 z-50 flex w-64 min-h-0 -translate-x-full flex-col border-r bg-card transition-[transform,visibility] duration-200",
        "md:visible md:relative md:z-auto md:shrink-0 md:translate-x-0",
        "group-data-[nav=open]/chat:visible group-data-[nav=open]/chat:translate-x-0",
      )}
    >
      <div className="flex flex-col gap-4 p-4">
        <div className="flex items-center justify-between gap-2">
          <Link
            href="/"
            className="font-mono text-meta uppercase text-ink-2 transition-colors hover:text-foreground"
          >
            ← Workspace
          </Link>
          <Button
            variant="ghost"
            size="icon-sm"
            aria-label="Close conversations"
            onClick={onClose}
            className="md:hidden"
          >
            <X className="size-4" />
          </Button>
        </div>
        <Link href="/chat" className={cn(buttonVariants(), "w-full")}>
          New chat
        </Link>
      </div>
      <p className="px-4 pb-2 font-mono text-meta uppercase text-ink-2">
        Conversations
      </p>
      <nav className="min-h-0 flex-1 overflow-y-auto px-2 pb-4">
        {isPending && <p className="px-2 text-sm text-ink-2">Loading…</p>}
        {isError && (
          <p className="px-2 text-sm text-destructive">
            Couldn’t load conversations.
          </p>
        )}
        {data && data.length === 0 && (
          <p className="px-2 text-sm text-ink-2">Nothing here yet.</p>
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
  // The ONLY new state in this segment: whether the conversation drawer is open
  // on narrow screens. Purely presentational and layout-local — no data, no
  // stream, no routing behaviour hangs off it.
  const [navOpen, setNavOpen] = useState(false);
  const pathname = usePathname();

  // Close on navigation, or tapping a conversation leaves the overlay covering
  // the transcript it just opened. Also fires on the lazy create's
  // replaceState, which is harmless: the drawer is shut during a send anyway.
  //
  // Adjusted DURING RENDER rather than in an effect (which react-hooks
  // correctly flags): React re-runs this component immediately, before painting,
  // so there is no extra committed render and no frame where the drawer is
  // still open on the new route. Deriving `navOpen` from the pathname it was
  // opened at was the other candidate and is wrong — navigating back to that
  // same path would resurrect the drawer.
  const [lastPathname, setLastPathname] = useState(pathname);
  if (lastPathname !== pathname) {
    setLastPathname(pathname);
    setNavOpen(false);
  }

  return (
    <ProtectedRoute>
      {/* The chat section is its own bounded region so the sidebar and the
          transcript scroll independently and the composer stays pinned. Bounded
          HERE rather than by switching <body> to a fixed height, because <body>
          is shared by every other route. dvh, not vh: mobile browser chrome
          would otherwise push the composer below the visible area.

          min-h-0 appears on EVERY flex child down the chain (this aside, its
          nav, ChatView's main, and main's transcript). A flex item defaults to
          min-height:auto, which refuses to shrink below its content — one
          missing min-h-0 and the nested scroll region silently overflows the
          viewport instead of scrolling. */}
      <div
        data-nav={navOpen ? "open" : "closed"}
        className="group/chat flex h-[100dvh] overflow-hidden"
      >
        <ConversationSidebar onClose={() => setNavOpen(false)} />
        {/* Scrim: dismisses by tap and covers the transcript while the drawer
            is over it. Rendered only when open so it never intercepts pointer
            events at rest, and md:hidden so desktop is untouched. */}
        {navOpen && (
          <div
            role="presentation"
            onClick={() => setNavOpen(false)}
            className="fixed inset-0 z-40 bg-foreground/40 md:hidden"
          />
        )}
        <div className="flex min-h-0 min-w-0 flex-1 flex-col">
          {/* Mobile chrome. New chat sits here as well as in the drawer so the
              primary action stays one tap, not two. */}
          <div className="flex shrink-0 items-center justify-between gap-2 border-b bg-card px-4 py-2.5 md:hidden">
            <Button
              variant="ghost"
              size="sm"
              aria-label="Open conversations"
              aria-expanded={navOpen}
              aria-controls="conversation-nav"
              onClick={() => setNavOpen(true)}
            >
              <Menu className="size-4" />
              Conversations
            </Button>
            <Link
              href="/chat"
              aria-label="New chat"
              className={cn(buttonVariants({ variant: "outline", size: "sm" }))}
            >
              <Plus className="size-4" />
              New
            </Link>
          </div>
          {children}
        </div>
      </div>
    </ProtectedRoute>
  );
}
