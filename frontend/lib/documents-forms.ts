// Presentation-layer error mapping for the documents forms — the upload control's
// thrown-error -> user copy. Mirrors lib/auth-forms.ts::mapAuthError: a
// RateLimitError CLASS check (lib/api.ts converts a 429 before we see it), then a
// status switch on the raw AxiosError, then a fallback. Transport imports
// (axios/RateLimitError) live HERE, not in lib/documents.ts, which is
// transport-free domain policy.

import { isAxiosError } from "axios";

import { RateLimitError } from "@/lib/api";

// Fixed copy per status — the backend's 400/413/415 have clear, stable meanings,
// so (unlike auth's 422) there's no need to extract a server detail string. The
// 413 copy names the 25 MB limit from the backend (MAX_UPLOAD_SIZE_MB).
export function mapUploadError(err: unknown): string {
  if (err instanceof RateLimitError) {
    return "Too many attempts. Please wait a minute.";
  }
  if (isAxiosError(err)) {
    switch (err.response?.status) {
      case 415:
        return "Unsupported file type. Upload a PDF, .txt, or .md file.";
      case 413:
        return "File is too large. The maximum size is 25 MB.";
      case 400:
        return "That file has no name. Please choose another file.";
    }
  }
  return "Upload failed. Please try again.";
}
