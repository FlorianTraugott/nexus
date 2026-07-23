"use client";

// Existing-conversation surface: hydrates the transcript from
// GET /conversations/{id} and seeds ChatView with it.
//
// The ChatView key is the ROUTE PARAM — the MOUNT IDENTITY, fixed for the life
// of this mount (navigating /chat/a -> /chat/b changes it and correctly
// remounts + re-seeds). Chat.3b's lazily-created live conversation id is
// ChatView-internal and never reaches this key, so a first-send create can
// never remount the view and abort its own stream.

import { useParams } from "next/navigation";
import { isAxiosError } from "axios";

import { useConversation } from "@/hooks/use-conversation";
import { mapMessagesToTurns } from "@/lib/conversations";
import { ChatView } from "@/components/chat-view";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";

export default function ConversationPage() {
  const { id } = useParams<{ id: string }>();
  const { data, isPending, isError, error } = useConversation(id);

  if (isPending) {
    return (
      <main className="mx-auto w-full max-w-3xl flex-1 px-6 py-8">
        <p className="text-sm text-muted-foreground">Loading conversation…</p>
      </main>
    );
  }

  if (isError) {
    const notFound = isAxiosError(error) && error.response?.status === 404;
    return (
      <main className="mx-auto w-full max-w-3xl flex-1 px-6 py-8">
        <Alert variant="destructive">
          <AlertTitle>
            {notFound ? "Conversation not found" : "Couldn’t load conversation"}
          </AlertTitle>
          <AlertDescription>
            {notFound
              ? "It may have been deleted, or the link is wrong."
              : "Please try again."}
          </AlertDescription>
        </Alert>
      </main>
    );
  }

  return <ChatView key={id} initialTurns={mapMessagesToTurns(data.messages)} />;
}
