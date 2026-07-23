// Presentation-layer error mapping for the research launcher. Mirrors the
// other *-forms.ts files: transport error classes in, user copy out.

import { isAxiosError } from "axios";

import { RateLimitError } from "@/lib/api";

export function mapCreateResearchError(err: unknown): string {
  if (err instanceof RateLimitError) {
    return "Too many attempts. Please wait a minute.";
  }
  if (isAxiosError(err) && err.response?.status === 422) {
    // The backend's k>max detail is a plain string; Pydantic validation
    // failures are arrays — only surface the string form.
    const detail: unknown = (err.response.data as { detail?: unknown })?.detail;
    if (typeof detail === "string") return detail;
  }
  return "Couldn't start the research task. Please try again.";
}
