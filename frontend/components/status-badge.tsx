// A status pill, keyed on a TONE rather than on any particular status enum.
//
// Tone is shared presentation; "which status is good news" is domain knowledge
// and stays in the file that owns the enum (lib/documents.ts, lib/research.ts),
// each as an exhaustive Record over its own union. That split is the whole point:
// a badge that knew both enums would move the compile error away from the file
// that owns the status, or dissolve it entirely. As it stands, adding a backend
// status still breaks the build in exactly the right place.
//
// Four tones, chosen to cover both enums with nothing speculative:
//   neutral  queued, not started       active  in flight
//   good     finished successfully     bad     finished badly

import { cn } from "@/lib/utils";

export type StatusTone = "neutral" | "active" | "good" | "bad";

const TONE_CLASSES: Record<StatusTone, string> = {
  neutral: "bg-tone-neutral-surface text-tone-neutral",
  active: "bg-tone-active-surface text-tone-active",
  good: "bg-tone-good-surface text-tone-good",
  bad: "bg-tone-bad-surface text-tone-bad",
};

export function StatusBadge({
  tone,
  label,
  className,
}: {
  tone: StatusTone;
  label: string;
  className?: string;
}) {
  return (
    <span
      className={cn(
        "inline-flex shrink-0 items-center rounded-full px-2.5 py-1 font-mono text-meta uppercase",
        TONE_CLASSES[tone],
        className,
      )}
    >
      {label}
    </span>
  );
}
