// Shared chrome for the standalone surfaces: /documents, /research and
// /research/[id]. Three real callers, so it is earned rather than speculative.
//
// /chat deliberately does NOT use this. It has a sidebar, which is a different
// kind of chrome; forcing it through here would be the abstraction serving
// itself rather than the surfaces.
//
// It carries a back link and a title only. The dashboard's account email and
// Log out are NOT here: making app chrome consistent across every surface is a
// decision about all of them at once, and it belongs to the dashboard segment
// rather than being half-made from inside a single-surface one.

import Link from "next/link";

export function PageHeader({
  backHref,
  backLabel,
  title,
  description,
  actions,
}: {
  backHref: string;
  backLabel: string;
  title: string;
  description?: string;
  actions?: React.ReactNode;
}) {
  return (
    <header className="flex flex-col gap-4">
      <Link
        href={backHref}
        className="font-mono text-meta uppercase text-ink-2 transition-colors hover:text-foreground"
      >
        ← {backLabel}
      </Link>
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0">
          <h1 className="text-title text-balance">{title}</h1>
          {description && (
            <p className="mt-2 max-w-prose text-sm text-ink-2">{description}</p>
          )}
        </div>
        {actions && <div className="shrink-0">{actions}</div>}
      </div>
    </header>
  );
}
