"use client";

// New-chat surface. No key, no conversationId, no initialTurns: a fresh mount
// with an empty transcript. The conversation is created lazily on the first
// send (ChatView), and the URL becomes /chat/{id} via replaceState without a
// remount. Route protection and the sidebar live in the chat layout.

import { ChatView } from "@/components/chat-view";

export default function NewChatPage() {
  return <ChatView />;
}
