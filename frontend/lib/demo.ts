// Whether this build publishes the shared demo account's credentials, and what
// they are. ONE home, because two things depend on the same condition: the
// DemoCredentials panel renders, and /login hides its "Create one" link. If a
// page re-derived the condition instead of importing from here, the two could
// drift apart — and the bad direction of that drift is silent: link hidden AND
// panel absent leaves a visitor with neither a sign-up nor a way in.
//
// NEXT_PUBLIC_* values are inlined at BUILD time, so these are constants in the
// shipped bundle, not runtime reads. They must be accessed as full static member
// expressions (never destructured off process.env) or the inlining doesn't
// happen and the value is undefined in the browser.

const DEMO_EMAIL = process.env.NEXT_PUBLIC_DEMO_EMAIL;
const DEMO_PASSWORD = process.env.NEXT_PUBLIC_DEMO_PASSWORD;

export interface DemoCredentials {
  email: string;
  password: string;
}

// Null unless BOTH are set and non-empty: half a credential pair is no use to a
// visitor, and rendering a panel with a blank password would look broken rather
// than absent. Absent in local dev, where registration is open anyway.
export function demoCredentials(): DemoCredentials | null {
  if (!DEMO_EMAIL || !DEMO_PASSWORD) return null;
  return { email: DEMO_EMAIL, password: DEMO_PASSWORD };
}

// The guard both pages read. Derived from demoCredentials() rather than
// re-testing the vars, so there is exactly one definition of "published".
export function isDemoAccessPublished(): boolean {
  return demoCredentials() !== null;
}
