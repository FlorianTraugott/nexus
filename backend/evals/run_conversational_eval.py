"""Conversational (multi-turn) eval runner: measure the DEPLOYED chat path.

The single-turn baselines (run_retrieval_eval, run_faithfulness_eval) never touch
the conversational path added in 9B.2 (follow-up rewrite) and 9B.3 (memory in the
generation prompt). This runner does. Per multi-turn case it creates ONE real
conversation and drives its turns IN ORDER through the EXACT deployed sequence from
query.py -- load history at MEMORY_HISTORY_TURNS, rewrite the follow-up with the
tail REWRITE_HISTORY_TURNS via rewrite_query, retrieve on the REWRITTEN question,
apply the SAME abstention gate (passes_distance_gate), build_prompt with the
ORIGINAL question plus history, generate, judge with judge_faithfulness against the
retrieved context, then persist the turn (user + assistant, committed) so history
exists for the next turn. Production functions are imported, never re-derived.

Three questions it answers, none of which the single-turn harness can:
  1. Rewrite: does the follow-up rewrite resolve the referent? Reported as
     rewrite_changed (did it change the text at all -- a no-op rewrite on a
     pronoun-laden follow-up is a FAILURE, not neutral) AND rewrite_expect_hit
     (does the rewritten query contain an expected substring; ANY-of,
     case-insensitive -- a follow-up label may list alternative acceptable forms).
  2. Retrieval: hit@k and doc-top1, split opener vs follow-up (different
     populations -- a follow-up is only as good as its rewrite). A turn whose gate
     fired is ABSTAINED: its own bucket, neither a hit nor a miss.
  3. Faithfulness: does memory-in-the-prompt cause UNGROUNDED claims? Same
     zero-unsupported-claims verdict rule as run_faithfulness_eval, judged against
     the retrieved context ONLY. The listed unsupported claims are the point.

Conversations are created under the eval user with a namespaced title and DELETED
in a finally block, so a crash mid-run does not strand [eval] conversations.

COST: real API calls -- per turn up to one rewrite + one generator + one judge call.

Run from backend/ with the venv active, OPENAI_API_KEY + the judge key set, and the
corpus ingested (python -m evals.setup_eval_corpus):

    python -m evals.run_conversational_eval --k 5
    python -m evals.run_conversational_eval --only conv-tiers
    python -m evals.run_conversational_eval --k 5 --json evals/results/conversational_baseline.json
"""

import argparse
import asyncio
import json
import sys
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy.ext.asyncio import AsyncSession

# Import the deployed abstention answer so a persisted abstention turn is byte-for-
# byte what production would have written -- the next turn's history must match.
from app.api.v1.query import _NO_ANSWER
from app.core.config import get_settings
from app.db.models import Conversation, MessageRole
from app.db.repositories import conversation as conversation_repo
from app.db.repositories import document as document_repo
from app.db.repositories import user as user_repo
from app.db.session import AsyncSessionLocal
from app.services.faithfulness import (
    FaithfulnessVerdict,
    MalformedVerdictError,
    judge_faithfulness,
)
from app.services.generation import build_prompt, get_generation_provider
from app.services.query_rewrite import rewrite_query
from app.services.retrieval import retrieve
from app.services.retrieval_policy import passes_distance_gate

GOLDEN_PATH = Path(__file__).parent / "golden" / "conversational.yaml"
CONV_TITLE_PREFIX = "[eval] "


@dataclass(frozen=True)
class Turn:
    question: str
    expect_contains: list[str]
    # Substrings the REWRITTEN query should contain; empty for an opener (the
    # rewrite does not fire without history). Scored ANY-of: a follow-up label may
    # list alternative acceptable forms (e.g. "Adaptive" OR "Tier 4").
    expect_rewrite_contains: list[str]
    expect_document: str | None


@dataclass(frozen=True)
class Case:
    id: str
    turns: list[Turn]
    notes: str


@dataclass
class TurnOutcome:
    case_id: str
    turn_index: int
    is_follow_up: bool
    question: str  # the ORIGINAL question (what build_prompt answers, what persists)
    rewritten_question: str | None  # None on an opener (rewrite did not fire)
    rewrite_changed: bool  # rewritten differs from original (a no-op is a failure)
    # None on an opener or a follow-up with no expect_rewrite_contains label.
    rewrite_expect_hit: bool | None
    abstained: bool  # the gate fired: its OWN bucket, neither retrieval hit nor miss
    retrieval_hit: int | None  # 1/0; None when abstained (excluded from hit@k)
    doc_top1: int | None  # None when abstained or the turn has no expect_document
    top1_doc: str | None
    # scored | no_claims | abstained | error -- same taxonomy as run_faithfulness_eval.
    faith_status: str
    answer: str | None
    verdict: FaithfulnessVerdict | None
    error_message: str | None
    error_raw: str | None

    @property
    def unsupported(self) -> list[Any]:
        if self.verdict is None:
            return []
        return [c for c in self.verdict.claims if not c.supported]

    @property
    def n_claims(self) -> int:
        return len(self.verdict.claims) if self.verdict is not None else 0

    @property
    def score(self) -> float | None:
        return self.verdict.score if self.verdict is not None else None

    @property
    def faithful(self) -> bool | None:
        """Faithful IFF zero unsupported claims; None unless the answer scored.

        Same granularity-invariant rule as run_faithfulness_eval: any unsupported
        claim makes the answer unfaithful regardless of how the judge split it.
        """
        if self.verdict is None or self.verdict.score is None:
            return None
        return len(self.unsupported) == 0


def load_cases(path: Path) -> list[Case]:
    if not path.exists():
        raise SystemExit(f"Golden set not found: {path}")
    raw: Any = yaml.safe_load(path.read_text())
    if not isinstance(raw, list):
        raise SystemExit(f"Golden set must be a YAML list, got {type(raw).__name__}")
    cases: list[Case] = []
    for item in raw:
        raw_turns = item.get("turns") or []
        if not raw_turns:
            raise SystemExit(f"{item.get('id')}: a case needs at least one turn")
        turns = [
            Turn(
                question=str(t["question"]),
                expect_contains=list(t.get("expect_contains") or []),
                expect_rewrite_contains=list(t.get("expect_rewrite_contains") or []),
                expect_document=t.get("expect_document"),
            )
            for t in raw_turns
        ]
        cases.append(
            Case(id=str(item["id"]), turns=turns, notes=str(item.get("notes") or ""))
        )
    return cases


def _contains_any(text: str, needles: list[str]) -> bool:
    low = text.lower()
    return any(n.lower() in low for n in needles)


def _gate_abstains(distances: list[float], max_distance: float) -> bool:
    """Reproduce the production query gate exactly (query.py).

    min() over distances, not results[0], and abstain on empty results.
    """
    return not distances or not passes_distance_gate(min(distances), max_distance)


async def _run_turn(
    session: AsyncSession,
    case_id: str,
    turn_index: int,
    turn: Turn,
    conversation_id: uuid.UUID,
    user_id: uuid.UUID,
    k: int,
    max_distance: float,
    doc_map: dict[uuid.UUID, str],
) -> TurnOutcome:
    """Drive one turn through the EXACT deployed query.py sequence, then persist."""
    settings = get_settings()
    generator = get_generation_provider()
    is_follow_up = turn_index > 0

    # 1. History load ONCE at MEMORY_HISTORY_TURNS (query.py).
    messages = await conversation_repo.list_recent_messages(
        session, conversation_id, settings.MEMORY_HISTORY_TURNS
    )
    memory_history = [(m.role.value, m.content) for m in messages]

    # 2. Rewrite the follow-up using the tail REWRITE_HISTORY_TURNS. Fires only
    #    when history exists -- exactly like the endpoint.
    retrieval_question = turn.question
    rewritten_question: str | None = None
    if memory_history:
        rewritten_question = await rewrite_query(
            turn.question,
            memory_history[-settings.REWRITE_HISTORY_TURNS :],
            generator=generator,
        )
        retrieval_question = rewritten_question
    rewrite_changed = (
        rewritten_question is not None
        and rewritten_question.strip() != turn.question.strip()
    )
    # ANY-of, case-insensitive; only scored on a turn that HAS the label.
    rewrite_expect_hit = (
        _contains_any(rewritten_question, turn.expect_rewrite_contains)
        if rewritten_question is not None and turn.expect_rewrite_contains
        else None
    )

    # 3. Retrieve on the REWRITTEN question.
    results = await retrieve(session, retrieval_question, user_id, k=k)
    top1_doc = doc_map.get(results[0].chunk.document_id) if results else None

    # 4. Abstention gate. An abstained turn is its OWN bucket: no retrieval hit/miss,
    #    no generation, no judge -- exactly as query.py skips generation.
    abstained = _gate_abstains([r.distance for r in results], max_distance)
    retrieval_hit: int | None = None
    doc_top1: int | None = None
    faith_status = "abstained"
    answer: str | None = None
    verdict: FaithfulnessVerdict | None = None
    error_message: str | None = None
    error_raw: str | None = None

    if not abstained:
        retrieval_hit = int(
            any(_contains_any(r.chunk.content, turn.expect_contains) for r in results)
        )
        doc_top1 = (
            None
            if turn.expect_document is None
            else int(top1_doc == turn.expect_document)
        )
        contexts = [r.chunk.content for r in results]
        # build_prompt with the ORIGINAL question + history (query.py).
        system, prompt = build_prompt(
            turn.question, contexts, history=memory_history or None
        )
        answer = await generator.generate(system, prompt)
        try:
            verdict = await judge_faithfulness(answer, contexts)
        except MalformedVerdictError as exc:
            faith_status = "error"
            error_message = str(exc)
            error_raw = exc.raw
        else:
            faith_status = "no_claims" if verdict.score is None else "scored"

    # 5. Persist the turn (user + assistant, committed) so the NEXT turn has
    #    history -- the abstention answer is persisted too, matching _persist_turn.
    await conversation_repo.add_message(
        session, conversation_id, MessageRole.USER, turn.question
    )
    await conversation_repo.add_message(
        session, conversation_id, MessageRole.ASSISTANT, answer or _NO_ANSWER
    )
    await session.commit()

    return TurnOutcome(
        case_id=case_id,
        turn_index=turn_index,
        is_follow_up=is_follow_up,
        question=turn.question,
        rewritten_question=rewritten_question,
        rewrite_changed=rewrite_changed,
        rewrite_expect_hit=rewrite_expect_hit,
        abstained=abstained,
        retrieval_hit=retrieval_hit,
        doc_top1=doc_top1,
        top1_doc=top1_doc,
        faith_status=faith_status,
        answer=answer,
        verdict=verdict,
        error_message=error_message,
        error_raw=error_raw,
    )


def _rate(values: list[int]) -> float | None:
    return sum(values) / len(values) if values else None


def _fmt(x: float | None, places: int = 3) -> str:
    return "n/a" if x is None else f"{x:.{places}f}"


def _print_table(outcomes: list[TurnOutcome]) -> None:
    header = (
        f"{'case':<20}{'turn':<5}{'kind':<10}{'rw?':<5}{'rw-hit':<8}"
        f"{'ret':<5}{'d1':<4}{'faith':<11}{'unsup':>6}"
    )
    print(header)
    print("-" * len(header))
    for o in outcomes:
        kind = "follow-up" if o.is_follow_up else "opener"
        rw = "-" if not o.is_follow_up else ("yes" if o.rewrite_changed else "NO")
        rw_hit = "-" if o.rewrite_expect_hit is None else str(int(o.rewrite_expect_hit))
        ret = "-" if o.retrieval_hit is None else str(o.retrieval_hit)
        d1 = "-" if o.doc_top1 is None else str(o.doc_top1)
        unsup = "-" if o.verdict is None else str(len(o.unsupported))
        print(
            f"{o.case_id:<20}{o.turn_index:<5}{kind:<10}{rw:<5}{rw_hit:<8}"
            f"{ret:<5}{d1:<4}{o.faith_status:<11}{unsup:>6}"
        )


def _print_rewrites(outcomes: list[TurnOutcome]) -> None:
    follow_ups = [o for o in outcomes if o.is_follow_up]
    if not follow_ups:
        return
    print("\nRewrites (follow-up turns) — original -> rewritten:")
    print("=" * 60)
    for o in follow_ups:
        flag = "changed" if o.rewrite_changed else "NO-OP (failure on a follow-up)"
        hit = (
            ""
            if o.rewrite_expect_hit is None
            else f"  expect_hit={int(o.rewrite_expect_hit)}"
        )
        print(f"\n[{o.case_id} t{o.turn_index}] {flag}{hit}")
        print(f"  original:  {o.question!r}")
        print(f"  rewritten: {o.rewritten_question!r}")


def _print_unsupported(outcomes: list[TurnOutcome]) -> None:
    """The actionable deliverable: did memory-in-the-prompt cause ungrounded claims?"""
    flagged = [o for o in outcomes if o.unsupported]
    if not flagged:
        print("\nNo unsupported claims.")
        return
    print("\nUnsupported claims — the actionable list (memory must not add facts):")
    print("=" * 60)
    for o in flagged:
        print(f"\n[{o.case_id} t{o.turn_index}] {o.question}")
        for c in o.unsupported:
            print(f"  NOT {c.claim!r}\n      {c.reason}")


def _print_errors(outcomes: list[TurnOutcome]) -> None:
    errors = [o for o in outcomes if o.faith_status == "error"]
    if not errors:
        return
    print("\nJudge errors — malformed output after the internal retry:")
    print("=" * 60)
    for o in errors:
        print(f"\n[{o.case_id} t{o.turn_index}] {o.error_message}")
        print(f"  raw (first 500): {(o.error_raw or '')[:500]!r}")


def build_report(outcomes: list[TurnOutcome], k: int) -> dict[str, Any]:
    settings = get_settings()
    openers = [o for o in outcomes if not o.is_follow_up]
    follow_ups = [o for o in outcomes if o.is_follow_up]

    # Rewrite metrics live on follow-ups only (an opener never rewrites).
    rewrite_labelled = [o for o in follow_ups if o.rewrite_expect_hit is not None]
    scored = [o for o in outcomes if o.faith_status == "scored"]
    no_claims = [o for o in outcomes if o.faith_status == "no_claims"]
    abstained = [o for o in outcomes if o.faith_status == "abstained"]
    errors = [o for o in outcomes if o.faith_status == "error"]
    mean = (
        sum(o.score for o in scored if o.score is not None) / len(scored)
        if scored
        else None
    )

    def _hit_rate(group: list[TurnOutcome]) -> float | None:
        # Abstained turns excluded: neither hit nor miss.
        return _rate([o.retrieval_hit for o in group if o.retrieval_hit is not None])

    def _doc_top1(group: list[TurnOutcome]) -> float | None:
        return _rate([o.doc_top1 for o in group if o.doc_top1 is not None])

    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "k": k,
        "rag_max_distance": settings.RAG_MAX_DISTANCE,
        "memory_history_turns": settings.MEMORY_HISTORY_TURNS,
        "rewrite_history_turns": settings.REWRITE_HISTORY_TURNS,
        # Recorded so a model swap is visible in the artifact -- comparable run to
        # run only against the same generator + judge.
        "judge_provider": settings.JUDGE_PROVIDER,
        "judge_model": settings.JUDGE_MODEL,
        "generator_model": settings.GENERATION_MODEL,
        "n_turns": len(outcomes),
        "n_openers": len(openers),
        "n_follow_ups": len(follow_ups),
        "rewrite": {
            "n_follow_ups": len(follow_ups),
            "changed_rate": _rate([int(o.rewrite_changed) for o in follow_ups]),
            "n_labelled": len(rewrite_labelled),
            "expect_hit_rate": _rate(
                [int(bool(o.rewrite_expect_hit)) for o in rewrite_labelled]
            ),
        },
        "retrieval": {
            "opener_hit_rate": _hit_rate(openers),
            "follow_up_hit_rate": _hit_rate(follow_ups),
            "opener_doc_top1": _doc_top1(openers),
            "follow_up_doc_top1": _doc_top1(follow_ups),
            "opener_abstained": sum(1 for o in openers if o.abstained),
            "follow_up_abstained": sum(1 for o in follow_ups if o.abstained),
        },
        "faithfulness": {
            "verdict_rule": "faithful_iff_zero_unsupported",
            "mean_faithfulness": mean,
            "n_judged": len(scored),
            "n_faithful": sum(1 for o in scored if o.faithful),
            "n_unfaithful": sum(1 for o in scored if o.faithful is False),
            "n_no_claims": len(no_claims),
            "n_abstained": len(abstained),
            "n_judge_errors": len(errors),
        },
        "per_turn": [
            {
                "case_id": o.case_id,
                "turn_index": o.turn_index,
                "is_follow_up": o.is_follow_up,
                "question": o.question,
                "rewritten_question": o.rewritten_question,
                "rewrite_changed": o.rewrite_changed,
                "rewrite_expect_hit": o.rewrite_expect_hit,
                "abstained": o.abstained,
                "retrieval_hit": o.retrieval_hit,
                "doc_top1": o.doc_top1,
                "top1_doc": o.top1_doc,
                "faith_status": o.faith_status,
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


def print_report(outcomes: list[TurnOutcome], report: dict[str, Any]) -> None:
    print(
        f"\nConversational eval — {report['judge_model']} judging "
        f"{report['generator_model']} answers (k={report['k']})"
    )
    print(
        f"({report['n_turns']} turns: {report['n_openers']} openers, "
        f"{report['n_follow_ups']} follow-ups)\n"
    )

    _print_table(outcomes)
    _print_rewrites(outcomes)
    _print_unsupported(outcomes)
    _print_errors(outcomes)

    rw = report["rewrite"]
    ret = report["retrieval"]
    fa = report["faithfulness"]
    print("\nAggregates")
    print("-" * 60)
    print("  Rewrite (follow-up turns)")
    print(f"    changed rate:            {_fmt(rw['changed_rate'])} (no-op = failure)")
    print(
        f"    expect-hit rate:         {_fmt(rw['expect_hit_rate'])} "
        f"(over {rw['n_labelled']} labelled, ANY-of)"
    )
    print("  Retrieval hit@k (opener vs follow-up are different populations)")
    print(
        f"    openers:                 {_fmt(ret['opener_hit_rate'])} "
        f"(abstained: {ret['opener_abstained']})"
    )
    print(
        f"    follow-ups:              {_fmt(ret['follow_up_hit_rate'])} "
        f"(abstained: {ret['follow_up_abstained']})"
    )
    print(f"    doc-top1 openers:        {_fmt(ret['opener_doc_top1'])}")
    print(f"    doc-top1 follow-ups:     {_fmt(ret['follow_up_doc_top1'])}")
    print("  Faithfulness (multi-turn answers; 0 unsupported = faithful)")
    print(f"    mean severity (judged):  {_fmt(fa['mean_faithfulness'])}")
    print(
        f"    judged: {fa['n_judged']}  faithful: {fa['n_faithful']}  "
        f"unfaithful: {fa['n_unfaithful']}"
    )
    print(
        f"    abstained: {fa['n_abstained']}  no-claims: {fa['n_no_claims']}  "
        f"judge errors: {fa['n_judge_errors']} (all excluded from the mean)"
    )


async def _run_case(
    session: AsyncSession,
    case: Case,
    conversation: Conversation,
    user_id: uuid.UUID,
    k: int,
    max_distance: float,
    doc_map: dict[uuid.UUID, str],
) -> list[TurnOutcome]:
    outcomes: list[TurnOutcome] = []
    for i, turn in enumerate(case.turns):
        outcomes.append(
            await _run_turn(
                session,
                case.id,
                i,
                turn,
                conversation.id,
                user_id,
                k,
                max_distance,
                doc_map,
            )
        )
    return outcomes


async def main() -> None:
    parser = argparse.ArgumentParser(description="Conversational (multi-turn) eval")
    parser.add_argument("--k", type=int, default=None, help="top-k (default RAG_TOP_K)")
    parser.add_argument("--json", type=Path, default=None, help="write JSON artifact")
    parser.add_argument("--only", type=str, default=None, help="run a single case id")
    args = parser.parse_args()

    settings = get_settings()
    k = args.k if args.k is not None else settings.RAG_TOP_K
    if k <= 0:
        raise SystemExit(f"--k must be positive, got {k}")
    max_distance = settings.RAG_MAX_DISTANCE

    cases = load_cases(GOLDEN_PATH)
    if args.only is not None:
        cases = [c for c in cases if c.id == args.only]
        if not cases:
            raise SystemExit(f"No case with id {args.only!r}")

    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    outcomes: list[TurnOutcome] = []
    async with AsyncSessionLocal() as session:
        user = await user_repo.get_user_by_email(session, settings.EVAL_USER_EMAIL)
        if user is None:
            raise SystemExit(
                f"Eval user {settings.EVAL_USER_EMAIL} not found — "
                "run: python -m evals.setup_eval_corpus"
            )
        doc_map = {
            d.id: d.filename
            for d in await document_repo.list_user_documents(session, user.id)
        }

        # Registered for deletion in the finally: a crash mid-run must not strand
        # [eval] conversations under the eval user.
        created: list[Conversation] = []
        try:
            for i, case in enumerate(cases, start=1):
                print(f"[{i}/{len(cases)}] {case.id} ...", file=sys.stderr)
                conversation = await conversation_repo.create_conversation(
                    session, user.id, title=f"{CONV_TITLE_PREFIX}{case.id} {stamp}"
                )
                await session.commit()
                created.append(conversation)
                outcomes.extend(
                    await _run_case(
                        session, case, conversation, user.id, k, max_distance, doc_map
                    )
                )
        finally:
            # Clear any half-open transaction from a mid-turn failure before delete.
            await session.rollback()
            for conversation in created:
                await conversation_repo.delete_conversation(session, conversation)
            if created:
                await session.commit()
                print(
                    f"Cleaned up {len(created)} eval conversation(s).", file=sys.stderr
                )

    report = build_report(outcomes, k)
    print_report(outcomes, report)

    if args.json is not None:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(report, indent=2) + "\n")
        print(f"\nWrote {args.json}")


if __name__ == "__main__":
    asyncio.run(main())
