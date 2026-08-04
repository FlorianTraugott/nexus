// The shared demo account's credentials, shown so a visitor can get past the
// sign-in wall without an account — the demo fails at step zero if nobody
// notices them, so this is a prominent panel, not a footnote.
//
// Presentational and prop-free: it reads the build-time guard itself and renders
// nothing when the credentials aren't published, so a caller writes
// <DemoCredentials /> with no conditional logic of its own.
//
// WHY A PASSWORD IN THE PUBLIC BUNDLE IS ACCEPTABLE HERE — and the condition
// that makes it so. The demo runs with REGISTRATION_ENABLED=false against ONE
// shared, deliberately disposable account whose corpus is re-seedable
// (backend/scripts/seed_demo.py). Those two decisions are a PAIR, not
// independent settings. If registration is ever reopened, or the account stops
// being disposable, this panel has to go with it: a bundled credential for an
// account that ordinary users also sign into is a real problem, not a demo
// convenience.

import { demoCredentials } from "@/lib/demo";

export function DemoCredentials() {
  const demo = demoCredentials();
  if (demo === null) return null;

  return (
    <div className="rounded-xl border-l-[3px] border-primary bg-card px-5 py-4 shadow-xs">
      <p className="font-mono text-meta uppercase text-primary">Demo access</p>
      <p className="mt-1.5 text-sm text-ink-2">
        Sign in with these. The account is shared and already loaded with
        documents.
      </p>
      {/* select-all so one click grabs the whole value — these exist to be
          copied into the fields below. */}
      <dl className="mt-3.5 grid grid-cols-[auto_1fr] items-baseline gap-x-5 gap-y-2">
        <dt className="font-mono text-meta uppercase text-ink-2">Email</dt>
        <dd className="select-all font-mono text-sm">{demo.email}</dd>
        <dt className="font-mono text-meta uppercase text-ink-2">Password</dt>
        <dd className="select-all font-mono text-sm">{demo.password}</dd>
      </dl>
    </div>
  );
}
