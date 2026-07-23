"""Faithfulness eval runner: judge the REAL deployed answer path over the golden set.

Unlike run_retrieval_eval (retrieval only, no LLM), this runs the full deployed
answer path per answerable golden question -- retrieve, the SAME abstention gate
as production, build_prompt, the configured generator -- then grades each answer
with the validated faithfulness judge. The output is an aggregate faithfulness
baseline plus an actionable list of every unsupported claim, because a bare mean
tells you nothing to fix.

The deployed path is REPRODUCED, not re-derived: passes_distance_gate and
build_prompt are imported from production, and the judge sees the exact same
context list passed to build_prompt.

Two kinds of "no score" are counted separately and NEITHER enters the mean:
  - abstained: the retrieval gate skipped generation (nothing relevant retrieved).
  - no-claims: an answer was generated but asserted no factual claims (the judge
    scores it None). The mean is strictly over answers that produced claims.

Negatives are skipped entirely -- they abstain by design and run_retrieval_eval
already scores that.

COST: this makes real API calls -- roughly one generator call + one judge call
per answerable question (~19 + ~19 per full run). Judge retries (once, internally)
can add a few more.

Run from backend/ with the venv active, OPENAI_API_KEY + the judge key set, and
the corpus already ingested (python -m evals.setup_eval_corpus):

    python -m evals.run_faithfulness_eval                 # all answerable, k=RAG_TOP_K
    python -m evals.run_faithfulness_eval --k 10
    python -m evals.run_faithfulness_eval --only t_q3     # one question, for debugging
    python -m evals.run_faithfulness_eval --json evals/results/faithfulness_baseline.json
"""

import argparse
import asyncio
import json
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# Reuse the golden-set loader and Question (with is_negative) rather than
# re-deriving the schema: the golden format has one home, run_retrieval_eval.
from evals.run_retrieval_eval import GOLDEN_PATH, Question, load_golden
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.repositories import document as document_repo
from app.db.repositories import user as user_repo
from app.db.session import AsyncSessionLocal
from app.services.faithfulness import (
    FaithfulnessVerdict,
    MalformedVerdictError,
    judge_faithfulness,
)
from app.services.generation import build_prompt, get_generation_provider
from app.services.retrieval import retrieve
from app.services.retrieval_policy import passes_distance_gate


@dataclass
class QOutcome:
    """One answerable question's result on the deployed path + judge.

    status is one of:
      "scored"    -- answer produced claims; verdict.score is a float (in the mean)
      "no_claims" -- answer generated but asserted nothing; verdict.score is None
      "abstained" -- retrieval gate skipped generation; no answer, no judge call
      "error"     -- judge returned malformed output twice (after its retry)
    """

    q: Question
    status: str
    answer: str | None
    verdict: FaithfulnessVerdict | None
    error_message: str | None
    error_raw: str | None

    @property
    def score(self) -> float | None:
        return self.verdict.score if self.verdict is not None else None

    @property
    def n_claims(self) -> int:
        return len(self.verdict.claims) if self.verdict is not None else 0

    @property
    def unsupported(self) -> list[Any]:
        if self.verdict is None:
            return []
        return [c for c in self.verdict.claims if not c.supported]

    @property
    def faithful(self) -> bool | None:
        """Faithful IFF zero unsupported claims; None unless the answer scored.

        Same granularity-invariant rule as calibration: any unsupported claim
        makes the answer unfaithful, regardless of how many claims the judge
        split it into. A fractional threshold on score would flip the verdict on
        identical reasoning when claim granularity shifts. score stays as a
        severity measure; this boolean is the verdict.
        """
        if self.verdict is None or self.verdict.score is None:
            return None
        return len(self.unsupported) == 0


def _gate_abstains(results: list[Any], max_distance: float) -> bool:
    """Reproduce the production query gate exactly (query.py lines 62-66).

    min() over distances, not results[0], and abstain on empty results -- so the
    eval measures the deployed policy, not a re-derived copy.
    """
    return not results or not passes_distance_gate(
        min(r.distance for r in results), max_distance
    )


def _fmt(x: float | None, places: int = 3) -> str:
    return "n/a" if x is None else f"{x:.{places}f}"


def _print_table(outcomes: list[QOutcome]) -> None:
    header = f"{'id':<10}{'status':<12}{'score':>7}{'claims':>8}{'unsupported':>13}"
    print(header)
    print("-" * len(header))
    for o in outcomes:
        unsupported = "-" if o.verdict is None else str(len(o.unsupported))
        claims = "-" if o.verdict is None else str(o.n_claims)
        print(
            f"{o.q.id:<10}{o.status:<12}{_fmt(o.score):>7}"
            f"{claims:>8}{unsupported:>13}"
        )


def _print_unsupported(outcomes: list[QOutcome]) -> None:
    """The actionable deliverable: every rejected claim, its reason, its question."""
    flagged = [o for o in outcomes if o.unsupported]
    if not flagged:
        print("\nNo unsupported claims.")
        return
    print("\nUnsupported claims — the actionable list (fix these, not the mean):")
    print("=" * 60)
    for o in flagged:
        print(f"\n[{o.q.id}] {o.q.question}")
        for c in o.unsupported:
            print(f"  NOT {c.claim!r}\n      {c.reason}")


def _print_errors(outcomes: list[QOutcome]) -> None:
    errors = [o for o in outcomes if o.status == "error"]
    if not errors:
        return
    print("\nJudge errors — malformed output after the internal retry:")
    print("=" * 60)
    for o in errors:
        print(f"\n[{o.q.id}] {o.error_message}")
        print("  raw judge response (first 500 chars):")
        print(f"  {(o.error_raw or '')[:500]!r}")


def build_report(outcomes: list[QOutcome], k: int) -> dict[str, Any]:
    settings = get_settings()
    scored = [o for o in outcomes if o.status == "scored"]
    no_claims = [o for o in outcomes if o.status == "no_claims"]
    abstained = [o for o in outcomes if o.status == "abstained"]
    errors = [o for o in outcomes if o.status == "error"]
    # Strictly over answers that produced claims. Abstentions and no-claims
    # answers are never folded in as 1.0 -- that would launder a system that
    # answered nothing into a perfect faithfulness score.
    mean = (
        sum(o.score for o in scored if o.score is not None) / len(scored)
        if scored
        else None
    )
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "k": k,
        "rag_max_distance": settings.RAG_MAX_DISTANCE,
        # Recorded so a judge change is visible in the artifact -- the baseline is
        # only comparable run to run against the same judge.
        "judge_provider": settings.JUDGE_PROVIDER,
        "judge_model": settings.JUDGE_MODEL,
        "generator_model": settings.GENERATION_MODEL,
        "n_answerable": len(outcomes),
        # Verdict rule: faithful IFF unsupported_count == 0 (granularity-invariant).
        # mean_faithfulness is a severity summary; the binary counts are the bar.
        "verdict_rule": "faithful_iff_zero_unsupported",
        "mean_faithfulness": mean,
        "n_judged": len(scored),
        "n_faithful": sum(1 for o in scored if o.faithful),
        "n_unfaithful": sum(1 for o in scored if o.faithful is False),
        "n_no_claims": len(no_claims),
        "n_abstained": len(abstained),
        "n_judge_errors": len(errors),
        "per_question": [
            {
                "id": o.q.id,
                "modality": o.q.modality,
                "status": o.status,
                "faithful": o.faithful,
                "score": o.score,
                "n_claims": o.n_claims,
                "n_unsupported": len(o.unsupported),
                "answer": o.answer,
                "claims": [
                    {"claim": c.claim, "supported": c.supported, "reason": c.reason}
                    for c in (o.verdict.claims if o.verdict is not None else [])
                ],
                "error_message": o.error_message,
                "error_raw_preview": (o.error_raw or "")[:500] if o.error_raw else None,
            }
            for o in outcomes
        ],
    }


def print_report(outcomes: list[QOutcome], report: dict[str, Any]) -> None:
    print(
        f"\nFaithfulness eval — {report['judge_model']} judging "
        f"{report['generator_model']} answers (k={report['k']})"
    )
    print(f"({report['n_answerable']} answerable questions)\n")

    _print_table(outcomes)
    _print_unsupported(outcomes)
    _print_errors(outcomes)

    print("\nAggregates")
    print("-" * 60)
    print("  verdict rule: faithful IFF 0 unsupported claims (score is severity only)")
    print(
        f"  mean faithfulness (severity, judged answers only): "
        f"{_fmt(report['mean_faithfulness'])}"
    )
    print(f"  judged (produced claims): {report['n_judged']}")
    print(f"    fully faithful (0 unsupported claims): {report['n_faithful']}")
    print(f"    unfaithful (>=1 unsupported claim):    {report['n_unfaithful']}")
    print(f"  abstained: {report['n_abstained']} (excluded from mean)")
    print(
        f"  no-claims answers: {report['n_no_claims']} "
        f"(generated but asserted nothing; excluded from mean)"
    )
    print(f"  judge errors: {report['n_judge_errors']}")


async def _run_one(
    session: AsyncSession, q: Question, user_id: Any, k: int, max_distance: float
) -> QOutcome:
    results = await retrieve(session, q.question, user_id, k=k)
    if _gate_abstains(list(results), max_distance):
        return QOutcome(q, "abstained", None, None, None, None)

    # The judge sees the exact context list passed to build_prompt -- grading the
    # deployed answer against the deployed context, nothing re-derived.
    contexts = [r.chunk.content for r in results]
    system, prompt = build_prompt(q.question, contexts)
    generator = get_generation_provider()
    answer = await generator.generate(system, prompt)

    try:
        verdict = await judge_faithfulness(answer, contexts)
    except MalformedVerdictError as exc:
        # Already retried once inside judge_faithfulness. Record and count it;
        # one bad judge reply must not abort a whole-golden-set run.
        return QOutcome(q, "error", answer, None, str(exc), exc.raw)

    status = "no_claims" if verdict.score is None else "scored"
    return QOutcome(q, status, answer, verdict, None, None)


async def main() -> None:
    parser = argparse.ArgumentParser(description="Faithfulness eval runner")
    parser.add_argument("--k", type=int, default=None, help="top-k (default RAG_TOP_K)")
    parser.add_argument("--json", type=Path, default=None, help="write JSON artifact")
    parser.add_argument(
        "--only", type=str, default=None, help="run a single question id"
    )
    args = parser.parse_args()

    settings = get_settings()
    k = args.k if args.k is not None else settings.RAG_TOP_K
    if k <= 0:
        raise SystemExit(f"--k must be positive, got {k}")

    questions = load_golden(GOLDEN_PATH)
    if args.only is not None:
        questions = [q for q in questions if q.id == args.only]
        if not questions:
            raise SystemExit(f"No question with id {args.only!r}")
    # Skip negatives entirely: they abstain by design, scored by run_retrieval_eval.
    answerable = [q for q in questions if not q.is_negative]
    if not answerable:
        raise SystemExit("No answerable questions to judge (all negatives?).")

    max_distance = settings.RAG_MAX_DISTANCE
    async with AsyncSessionLocal() as session:
        user = await user_repo.get_user_by_email(session, settings.EVAL_USER_EMAIL)
        if user is None:
            raise SystemExit(
                f"Eval user {settings.EVAL_USER_EMAIL} not found — "
                "run: python -m evals.setup_eval_corpus"
            )
        # Touch documents so a mis-scoped user surfaces here, not mid-run.
        await document_repo.list_user_documents(session, user.id)

        outcomes: list[QOutcome] = []
        for i, q in enumerate(answerable, start=1):
            print(f"[{i}/{len(answerable)}] {q.id} ...", file=sys.stderr)
            outcomes.append(await _run_one(session, q, user.id, k, max_distance))

    report = build_report(outcomes, k)
    print_report(outcomes, report)

    if args.json is not None:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(report, indent=2) + "\n")
        print(f"\nWrote {args.json}")


if __name__ == "__main__":
    asyncio.run(main())
