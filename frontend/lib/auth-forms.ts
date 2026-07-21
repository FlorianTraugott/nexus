// Shared helpers for the login and register forms: client-side validation and
// mapping a thrown client error to user-facing copy. One home so both pages
// stay identical in behaviour.

import { isAxiosError } from "axios";

import { RateLimitError } from "@/lib/api";

// Validate BEFORE submit so a bad email or too-short password never burns one of
// the backend's rate-limited attempts on a guaranteed 422. The server remains the
// authority; these are just a fast local gate.

export function validateEmail(email: string): string | null {
  if (!email.trim()) return "Email is required.";
  // Deliberately loose — a sanity check, not RFC 5322. The server (EmailStr) is
  // authoritative.
  if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
    return "Enter a valid email address.";
  }
  return null;
}

export function validatePassword(password: string): string | null {
  // 8..72 mirrors app/schemas/user.py; 72 is bcrypt's byte ceiling.
  if (password.length < 8) return "Password must be at least 8 characters.";
  if (password.length > 72) return "Password must be at most 72 characters.";
  return null;
}

// Pull a human string out of FastAPI's 422 body, which is either {detail: "..."}
// or {detail: [{msg, loc, ...}]} for request-validation errors.
function extractDetail(data: unknown): string | null {
  if (!data || typeof data !== "object") return null;
  const detail: unknown = (data as { detail?: unknown }).detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail) && detail.length > 0) {
    const first = detail[0];
    if (first && typeof first === "object" && "msg" in first) {
      return String((first as { msg: unknown }).msg);
    }
  }
  return null;
}

// Map a caught error to copy. Note the 429 case tests the RateLimitError CLASS
// that lib/api.ts actually throws — not a status check — because the interceptor
// converts a 429 response into that error before it reaches us.
export function mapAuthError(err: unknown): string {
  if (err instanceof RateLimitError) {
    return "Too many attempts. Please wait a minute.";
  }
  if (isAxiosError(err)) {
    const status = err.response?.status;
    switch (status) {
      case 401:
        return "Incorrect email or password.";
      case 403:
        return "Your account is inactive.";
      case 409:
        return "That email is already registered.";
      case 422:
        return extractDetail(err.response?.data) ?? "Please check your input.";
    }
  }
  return "Something went wrong. Please try again.";
}
