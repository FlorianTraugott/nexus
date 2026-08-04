"use client";

// New-chat surface. No key, no conversationId, no initialTurns: a fresh mount
// with an empty transcript. The conversation is created lazily on the first
// send (ChatView), and the URL becomes /chat/{id} via replaceState without a
// remount. Route protection and the sidebar live in the chat layout.

import { ChatView } from "@/components/chat-view";
import { useChatReset } from "@/components/chat-reset";

export default function NewChatPage() {
  // Keyed by the reset token, NOT by the live conversation id: the token changes
  // only on a deliberate reset (deleting the conversation being viewed), never
  // during a send, so it can back a key where the live id never could.
  const { token } = useChatReset();
  return <ChatView key={token} />;
}
