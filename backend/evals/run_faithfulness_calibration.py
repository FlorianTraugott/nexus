"""Judge calibration runner: does the faithfulness judge agree with a human?

This is the gate on trusting the judge. It scores the JUDGE, not the RAG
pipeline: each calibration entry carries a hand-labelled verdict, and we check
whether the judge reaches the same one. Until agreement here is good, the
judge's aggregate faithfulness numbers are not evidence of anything.

No retrieval and no database -- the fixtures carry their own context, so
calibration does not depend on the corpus or the eval user.

Run from backend/ with the venv active and ANTHROPIC_API_KEY set:

    python -m evals.run_faithfulness_calibration
    python -m evals.run_faithfulness_calibration --threshold 0.8
    python -m evals.run_faithfulness_calibration --only unfaithful-1
    python -m evals.run_faithfulness_calibration --json evals/results/judge_calibration.json
"""

import argparse
import asyncio
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from app.core.config import get_settings
from app.services.faithfulness import (
    FaithfulnessVerdict,
    MalformedVerdictError,
    judge_faithfulness,
)

CALIBRATION_PATH = Path(__file__).parent / "faithfulness_calibration.yaml"
# The judge is faithful/unfaithful at this score; 0.5 means "more claims
# supported than not". A calibration run is also how you pick this number.
DEFAULT_THRESHOLD = 0.5


@dataclass(frozen=True)
class Entry:
    id: str
    answer: str
    context: list[str]
    human_faithful: bool
    note: str


@dataclass(frozen=True)
class JudgeError:
    """A calibration entry whose judge call returned unparseable output.

    Recorded as neither a pass nor a fail: it is a judge malfunction, not a
    grading disagreement, so it is kept out of the agreement rate and reported
    on its own. `raw` is the pre-strip judge response for eyeballing.
    """

    entry: Entry
    message: str
    raw: str


@dataclass(frozen=True)
class Outcome:
    entry: Entry
    verdict: FaithfulnessVerdict
    threshold: float

    @property
    def judge_faithful(self) -> bool | None:
        """None for an abstention: no claims means nothing to score."""
        if self.verdict.score is None:
            return None
        return self.verdict.score >= self.threshold

    @property
    def agrees(self) -> bool | None:
        if self.judge_faithful is None:
            return None
        return self.judge_faithful == self.entry.human_faithful


def load_calibration(path: Path) -> list[Entry]:
    if not path.exists():
        raise SystemExit(f"Calibration set not found: {path}")
    raw: Any = yaml.safe_load(path.read_text())
    if not isinstance(raw, list):
        raise SystemExit(
            f"Calibration set must be a YAML list, got {type(raw).__name__}"
        )
    entries: list[Entry] = []
    for item in raw:
        human = item.get("human_faithful")
        if not isinstance(human, bool):
            raise SystemExit(
                f"{item.get('id')}: human_faithful must be true or false, "
                f"got {human!r}"
            )
        entries.append(
            Entry(
                id=str(item["id"]),
                answer=str(item["answer"]),
                context=[str(c) for c in (item.get("context") or [])],
                human_faithful=human,
                note=str(item.get("note") or ""),
            )
        )
    return entries


def _fmt(x: float | None, places: int = 3) -> str:
    return "n/a" if x is None else f"{x:.{places}f}"


def _label(faithful: bool | None) -> str:
    if faithful is None:
        return "abstain"
    return "faithful" if faithful else "unfaithful"


def _print_table(outcomes: list[Outcome]) -> None:
    header = (
        f"{'id':<24}{'human':<13}{'judge':<13}{'score':>7}"
        f"{'claims':>8}  {'agree':<6}"
    )
    print(header)
    print("-" * len(header))
    for o in outcomes:
        agree = "-" if o.agrees is None else ("yes" if o.agrees else "NO")
        print(
            f"{o.entry.id:<24}{_label(o.entry.human_faithful):<13}"
            f"{_label(o.judge_faithful):<13}{_fmt(o.verdict.score):>7}"
            f"{len(o.verdict.claims):>8}  {agree:<6}"
        )


def _print_disagreements(outcomes: list[Outcome]) -> None:
    bad = [o for o in outcomes if o.agrees is False]
    if not bad:
        print("\nNo disagreements.")
        return
    print("\nDisagreements -- read the judge's reasons before touching a label:")
    print("=" * 60)
    for o in bad:
        print(
            f"\n[{o.entry.id}] human={_label(o.entry.human_faithful)} "
            f"judge={_label(o.judge_faithful)} score={_fmt(o.verdict.score)}"
        )
        print(f"  note: {o.entry.note}")
        for c in o.verdict.claims:
            mark = "OK " if c.supported else "NOT"
            print(f"  {mark} {c.claim!r}\n      {c.reason}")


def build_report(
    outcomes: list[Outcome], errors: list[JudgeError], threshold: float
) -> dict[str, Any]:
    settings = get_settings()
    scorable = [o for o in outcomes if o.agrees is not None]
    abstentions = [o for o in outcomes if o.agrees is None]
    agreed = sum(1 for o in scorable if o.agrees)
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "judge_provider": settings.JUDGE_PROVIDER,
        "judge_model": settings.JUDGE_MODEL,
        "generator_model": settings.GENERATION_MODEL,
        "threshold": threshold,
        # n_entries counts everything attempted, errors included, so the parts
        # (scorable + abstentions + errors) reconcile against the whole.
        "n_entries": len(outcomes) + len(errors),
        "n_scorable": len(scorable),
        "n_abstentions": len(abstentions),
        "n_errors": len(errors),
        "agreement": {
            "agreed": agreed,
            "total": len(scorable),
            "rate": agreed / len(scorable) if scorable else None,
        },
        "errors": [
            {
                "id": e.entry.id,
                "message": e.message,
                "raw_preview": e.raw[:500],
            }
            for e in errors
        ],
        "per_entry": [
            {
                "id": o.entry.id,
                "human_faithful": o.entry.human_faithful,
                "judge_faithful": o.judge_faithful,
                "score": o.verdict.score,
                "is_abstention": o.verdict.is_abstention,
                "agrees": o.agrees,
                "claims": [
                    {
                        "claim": c.claim,
                        "supported": c.supported,
                        "reason": c.reason,
                    }
                    for c in o.verdict.claims
                ],
            }
            for o in outcomes
        ],
    }


def print_report(outcomes: list[Outcome], report: dict[str, Any]) -> None:
    print(
        f"\nJudge calibration -- {report['judge_model']} judging "
        f"{report['generator_model']} output"
    )
    print(
        f"({report['n_entries']} entries, {report['n_scorable']} scorable, "
        f"{report['n_abstentions']} abstentions, {report['n_errors']} judge "
        f"errors; threshold {report['threshold']:.2f})\n"
    )
    _print_table(outcomes)
    _print_disagreements(outcomes)

    ag = report["agreement"]
    print("\nAgreement with human labels (abstentions and judge errors excluded)")
    print("-" * 60)
    print(f"  agreed: {ag['agreed']}/{ag['total']}  rate={_fmt(ag['rate'])}")
    print(f"  judge errors: {report['n_errors']}")
    if report["errors"]:
        ids = ", ".join(e["id"] for e in report["errors"])
        print(f"    unparseable output on: {ids} (raw shown above)")
    print(
        "  (the judge is not usable until this is high AND the deliberately\n"
        "   unfaithful entries are caught -- check those rows specifically)"
    )


async def main() -> None:
    parser = argparse.ArgumentParser(description="Faithfulness judge calibration")
    parser.add_argument(
        "--threshold",
        type=float,
        default=DEFAULT_THRESHOLD,
        help=f"score at/above which the judge calls an answer faithful "
        f"(default {DEFAULT_THRESHOLD})",
    )
    parser.add_argument("--json", type=Path, default=None, help="write JSON artifact")
    parser.add_argument("--only", type=str, default=None, help="run a single entry id")
    args = parser.parse_args()

    if not 0.0 <= args.threshold <= 1.0:
        raise SystemExit(f"--threshold must be in [0, 1], got {args.threshold}")

    entries = load_calibration(CALIBRATION_PATH)
    if args.only is not None:
        entries = [e for e in entries if e.id == args.only]
        if not entries:
            raise SystemExit(f"No entry with id {args.only!r}")

    outcomes: list[Outcome] = []
    errors: list[JudgeError] = []
    for entry in entries:
        try:
            verdict = await judge_faithfulness(entry.answer, entry.context)
        except MalformedVerdictError as exc:
            # judge_faithfulness already retried once, so reaching here means the
            # judge malformed its output twice -- a persistent signal, not a
            # one-off flake. It must not abort the run: this is a diagnostic tool
            # and the entries that worked are still the result. Print the raw
            # response so it is clear whether it was truncated, fenced, or
            # genuinely malformed -- that distinction is the debug.
            print(f"\n[{entry.id}] JUDGE_ERROR: {exc}")
            print("  raw judge response (first 500 chars):")
            print(f"  {exc.raw[:500]!r}")
            errors.append(JudgeError(entry=entry, message=str(exc), raw=exc.raw))
            continue
        outcomes.append(Outcome(entry=entry, verdict=verdict, threshold=args.threshold))

    report = build_report(outcomes, errors, args.threshold)
    print_report(outcomes, report)

    if args.json is not None:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(report, indent=2) + "\n")
        print(f"\nWrote {args.json}")


if __name__ == "__main__":
    asyncio.run(main())
