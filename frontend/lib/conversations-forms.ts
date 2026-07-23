// Presentation-layer error mapping for the conversations UI. Mirrors
// documents-forms.ts. 404 is NOT handled here — the delete mutation's onError
// treats it as "already gone" (invalidate + close), so it never reaches this
// copy. This maps the errors that genuinely leave the conversation undeleted.

import { RateLimitError } from "@/lib/api";

export function mapDeleteConversationError(err: unknown): string {
  if (err instanceof RateLimitError) {
    return "Too many attempts. Please wait a minute.";
  }
  return "Couldn't delete the conversation. Please try again.";
}

// Create failures surface as the TURN's error state (the hook renders a thrown
// ensure Error's message), so this copy reads as a failed answer start.
export function mapCreateConversationError(err: unknown): string {
  if (err instanceof RateLimitError) {
    return "Too many attempts. Please wait a minute.";
  }
  return "Couldn't start the conversation. Please try again.";
}
