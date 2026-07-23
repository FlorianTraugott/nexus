"use client";

// New-chat surface. No key and no initialTurns: a fresh mount, empty
// transcript. Route protection and the sidebar live in the chat layout.
// Chat.3a: sends are stateless; the lazy conversation create is Chat.3b.

import { ChatView } from "@/components/chat-view";

export default function NewChatPage() {
  return <ChatView />;
}
