// Presentation-side error copy for the chat stream. Mirrors auth-forms.ts /
// documents-forms.ts: transport error classes in, user-facing strings out.
//
// Cancellation NEVER reaches mapStreamError: a deliberate abort is its own
// turn status ("cancelled"), decided in the hook by checking the controller's
// signal — same principle as "a cancelled request is not an authentication
// failure". A user-initiated stop must not render as a failure.

import { SessionExpiredError } from "@/lib/api";
import { StreamHttpError, StreamProtocolError } from "@/lib/query-stream";

// Rendered when the backend's terminal `error` frame arrives: tokens already on
// screen STAY on screen, and this line makes the truncation explicit — the UI
// must not re-hide what the typed frame surfaces.
export const STREAM_FAILED_MESSAGE =
  "Generation failed — this answer is incomplete.";

export function mapStreamError(err: unknown): string {
  if (err instanceof SessionExpiredError) {
    // The registered unauthorized handler is already redirecting to /login;
    // this copy is what the turn shows in the meantime.
    return err.message;
  }
  if (err instanceof StreamHttpError) {
    if (err.status === 429) {
      return "Too many requests. Please wait a moment and try again.";
    }
    // StreamHttpError's message is the FastAPI `detail` when the body had one
    // (e.g. the k>max 422), else a generic status line — both fit for display.
    return err.message;
  }
  if (err instanceof StreamProtocolError) {
    // Includes the no-terminal-frame case: the server died mid-stream without
    // even flushing its error frame.
    return "Connection interrupted — please try again.";
  }
  return "Something went wrong. Please try again.";
}
