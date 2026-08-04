"use client";

// An explicit "start the new-chat view over" signal, owned by the chat layout
// and consumed by /chat.
//
// WHY A ROUTER NAVIGATION IS NOT ENOUGH. After Chat.3b's lazy create, the URL
// reads /chat/{id} via replaceState while the MOUNTED route is still
// app/chat/page.tsx. Deleting that conversation calls router.replace("/chat"),
// which navigates to the route that is already mounted — React reconciles the
// same <ChatView /> in the same position with an unchanged key and PRESERVES its
// state. The transcript of a deleted conversation stays on screen and the view's
// internal live id still points at it, so the next send writes to a conversation
// that no longer exists. (From a real /chat/{id} mount the same call swaps one
// page component for another and does remount, which is why the bug looks
// intermittent.)
//
// KEYING CONTRACT, respected: this token is NOT the live conversation id. It
// changes only when something deliberately resets the session — never during a
// send — so it can safely back a React key, which the live id never can.

import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useState,
} from "react";

interface ChatResetValue {
  /** Changes when the new-chat view must be discarded. Safe to use as a key. */
  token: number;
  /** Discard the new-chat view's state (transcript and live conversation id). */
  reset: () => void;
}

const ChatResetContext = createContext<ChatResetValue | null>(null);

export function ChatResetProvider({ children }: { children: React.ReactNode }) {
  const [token, setToken] = useState(0);
  const reset = useCallback(() => setToken((t) => t + 1), []);
  const value = useMemo(() => ({ token, reset }), [token, reset]);
  return (
    <ChatResetContext.Provider value={value}>
      {children}
    </ChatResetContext.Provider>
  );
}

export function useChatReset(): ChatResetValue {
  const value = useContext(ChatResetContext);
  if (value === null) {
    // Fail loudly: a silent fallback would mean the reset quietly stops working
    // and a deleted conversation keeps its transcript again.
    throw new Error("useChatReset must be used within ChatResetProvider");
  }
  return value;
}
