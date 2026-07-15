"""Retrieval eval runner: score the golden set against live retrieval.

No LLM generation here — this measures retrieval only, so a change to chunking,
top-k, or the embedding model produces a number you can compare run to run.

Run from backend/ with the venv active, OPENAI_API_KEY set, and the corpus
already ingested (python -m evals.setup_eval_corpus):

    python -m evals.run_retrieval_eval                # all questions, k=RAG_TOP_K
    python -m evals.run_retrieval_eval --k 10
    python -m evals.run_retrieval_eval --only t_q3    # one question, for debugging
    python -m evals.run_retrieval_eval --json runs/latest.json

It only READS from retrieve()/image_retrieve(); it changes nothing in them.
"""

import argparse
import asyncio
import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.repositories import document as document_repo
from app.db.repositories import user as user_repo
from app.db.session import AsyncSessionLocal
from app.services.image_retrieval import image_retrieve
from app.services.retrieval import retrieve

GOLDEN_PATH = Path(__file__).parent / "golden" / "retrieval.yaml"
SNIPPET_CHARS = 120


@dataclass(frozen=True)
class Question:
    id: str
    question: str
    modality: str  # "text" | "image"
    expect_document: str | None
    expect_contains: list[str]
    notes: str

    @property
    def is_negative(self) -> bool:
        # A negative should not be answerable: no target doc, no target text.
        return self.expect_document is None and not self.expect_contains

    @property
    def is_hard(self) -> bool:
        return "HARD" in self.notes.upper()


@dataclass(frozen=True)
class Hit:
    rank: int  # 1-indexed position in the retrieved list
    document: str
    distance: float
    text: str  # chunk content (text) or image caption (image)

    @property
    def snippet(self) -> str:
        return " ".join(self.text.split())[:SNIPPET_CHARS]


@dataclass
class QResult:
    q: Question
    hits: list[Hit]
    # None for negatives (hit/MRR/doc_top1 are not scored for them).
    hit: int | None
    rank: int | None
    doc_top1: int | None
    top1_doc: str | None
    top1_distance: float | None


def load_golden(path: Path) -> list[Question]:
    if not path.exists():
        raise SystemExit(f"Golden set not found: {path}")
    raw: Any = yaml.safe_load(path.read_text())
    if not isinstance(raw, list):
        raise SystemExit(f"Golden set must be a YAML list, got {type(raw).__name__}")
    questions: list[Question] = []
    for item in raw:
        modality = item["modality"]
        if modality not in ("text", "image"):
            raise SystemExit(f"{item.get('id')}: bad modality {modality!r}")
        questions.append(
            Question(
                id=str(item["id"]),
                question=str(item["question"]),
                modality=modality,
                expect_document=item.get("expect_document"),
                expect_contains=list(item.get("expect_contains") or []),
                notes=str(item.get("notes") or ""),
            )
        )
    return questions


def _contains_any(text: str, needles: list[str]) -> bool:
    low = text.lower()
    return any(n.lower() in low for n in needles)


async def _hits_for(
    session: AsyncSession,
    q: Question,
    user_id: uuid.UUID,
    k: int,
    doc_map: dict[uuid.UUID, str],
) -> list[Hit]:
    """Run the right retrieval path and normalise results to Hit rows."""
    if q.modality == "text":
        chunks = await retrieve(session, q.question, user_id, k=k)
        return [
            Hit(
                rank=i + 1,
                document=doc_map.get(c.chunk.document_id, "<unknown>"),
                distance=c.distance,
                text=c.chunk.content,
            )
            for i, c in enumerate(chunks)
        ]
    images = await image_retrieve(session, q.question, user_id, k=k)
    return [
        Hit(
            rank=i + 1,
            document=doc_map.get(img.image.document_id, "<unknown>"),
            distance=img.distance,
            text=img.image.caption or "",
        )
        for i, img in enumerate(images)
    ]


def score(q: Question, hits: list[Hit]) -> QResult:
    top1_doc = hits[0].document if hits else None
    top1_distance = hits[0].distance if hits else None

    if q.is_negative:
        return QResult(q, hits, None, None, None, top1_doc, top1_distance)

    first_rank: int | None = None
    for h in hits:
        if _contains_any(h.text, q.expect_contains):
            first_rank = h.rank
            break
    hit = 1 if first_rank is not None else 0
    doc_top1 = 1 if hits and hits[0].document == q.expect_document else 0
    return QResult(q, hits, hit, first_rank, doc_top1, top1_doc, top1_distance)


def _agg(results: list[QResult]) -> dict[str, Any]:
    n = len(results)
    if n == 0:
        return {"n": 0, "hit_rate": None, "mrr": None, "doc_top1_acc": None}
    hit_rate = sum(r.hit or 0 for r in results) / n
    mrr = sum((1.0 / r.rank if r.rank else 0.0) for r in results) / n
    doc_top1 = sum(r.doc_top1 or 0 for r in results) / n
    return {"n": n, "hit_rate": hit_rate, "mrr": mrr, "doc_top1_acc": doc_top1}


def _fmt(x: float | None, places: int = 3) -> str:
    return "n/a" if x is None else f"{x:.{places}f}"


def _print_table(results: list[QResult]) -> None:
    header = (
        f"{'id':<10}{'mod':<6}{'hit':<5}{'rank':<6}{'top1-doc':<28}{'top1-dist':>10}"
    )
    print(header)
    print("-" * len(header))
    for r in results:
        hit = "-" if r.hit is None else str(r.hit)
        rank = "-" if r.rank is None else str(r.rank)
        top1 = (r.top1_doc or "-")[:27]
        print(
            f"{r.q.id:<10}{r.q.modality:<6}{hit:<5}{rank:<6}"
            f"{top1:<28}{_fmt(r.top1_distance):>10}"
        )


def _print_misses(results: list[QResult]) -> None:
    misses = [r for r in results if r.hit == 0]
    if not misses:
        print("\nNo misses.")
        return
    print("\nMisses — what came back instead (top 3):")
    print("=" * 60)
    for r in misses:
        print(f"\n[{r.q.id}] {r.q.question}")
        print(f"  expect_document: {r.q.expect_document}")
        print(f"  expect_contains: {r.q.expect_contains}")
        if not r.hits:
            print("  (nothing retrieved)")
            continue
        for h in r.hits[:3]:
            print(
                f"  #{h.rank} {h.document}  dist={h.distance:.4f}\n"
                f"      {h.snippet!r}"
            )


def _print_aggregate(label: str, agg: dict[str, Any]) -> None:
    print(
        f"  {label:<18} n={agg['n']:<3}  "
        f"hit@k={_fmt(agg['hit_rate'])}  "
        f"MRR={_fmt(agg['mrr'])}  "
        f"doc-top1={_fmt(agg['doc_top1_acc'])}"
    )


def _print_negatives(
    negatives: list[QResult], mean_answerable_top1: float | None
) -> None:
    print("\nNegatives — top-hit distance (no threshold applied; see the spread):")
    print("-" * 60)
    for r in negatives:
        print(f"  {r.q.id:<10} top1-dist={_fmt(r.top1_distance, 4)}  ({r.q.question})")
    print(
        f"\n  mean top1-distance, ANSWERABLE questions: "
        f"{_fmt(mean_answerable_top1, 4)}"
    )
    print("  (compare: do negatives sit at clearly larger distances?)")


def build_report(results: list[QResult], k: int) -> dict[str, Any]:
    answerable = [r for r in results if not r.q.is_negative]
    negatives = [r for r in results if r.q.is_negative]
    answerable_top1 = [
        r.top1_distance for r in answerable if r.top1_distance is not None
    ]
    mean_answerable_top1 = (
        sum(answerable_top1) / len(answerable_top1) if answerable_top1 else None
    )
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "k": k,
        "n_questions": len(results),
        "n_answerable": len(answerable),
        "n_negative": len(negatives),
        "overall": _agg(answerable),
        "by_modality": {
            "text": _agg([r for r in answerable if r.q.modality == "text"]),
            "image": _agg([r for r in answerable if r.q.modality == "image"]),
        },
        "by_difficulty": {
            "hard": _agg([r for r in answerable if r.q.is_hard]),
            "normal": _agg([r for r in answerable if not r.q.is_hard]),
        },
        "negatives": {
            "mean_answerable_top1_distance": mean_answerable_top1,
            "per_question": [
                {"id": r.q.id, "top1_distance": r.top1_distance} for r in negatives
            ],
        },
        "per_question": [
            {
                "id": r.q.id,
                "modality": r.q.modality,
                "is_negative": r.q.is_negative,
                "is_hard": r.q.is_hard,
                "expect_document": r.q.expect_document,
                "expect_contains": r.q.expect_contains,
                "hit": r.hit,
                "rank": r.rank,
                "doc_top1": r.doc_top1,
                "top1_doc": r.top1_doc,
                "top1_distance": r.top1_distance,
                "retrieved": [
                    {
                        "rank": h.rank,
                        "document": h.document,
                        "distance": h.distance,
                        "snippet": h.snippet,
                    }
                    for h in r.hits[:3]
                ],
            }
            for r in results
        ],
    }


def print_report(results: list[QResult], report: dict[str, Any]) -> None:
    print(f"\nRetrieval eval — k={report['k']}, {report['n_questions']} questions")
    print(f"({report['n_answerable']} answerable, {report['n_negative']} negatives)\n")

    _print_table(results)
    _print_misses(results)

    print("\nAggregates (answerable only)")
    print("-" * 60)
    _print_aggregate("overall", report["overall"])
    _print_aggregate("text", report["by_modality"]["text"])
    _print_aggregate("image", report["by_modality"]["image"])
    _print_aggregate("HARD", report["by_difficulty"]["hard"])
    _print_aggregate("normal", report["by_difficulty"]["normal"])

    negatives = [r for r in results if r.q.is_negative]
    if negatives:
        _print_negatives(
            negatives, report["negatives"]["mean_answerable_top1_distance"]
        )


async def main() -> None:
    parser = argparse.ArgumentParser(description="Retrieval eval runner")
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

        results: list[QResult] = []
        for q in questions:
            hits = await _hits_for(session, q, user.id, k, doc_map)
            results.append(score(q, hits))

    report = build_report(results, k)
    print_report(results, report)

    if args.json is not None:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(report, indent=2))
        print(f"\nWrote {args.json}")


if __name__ == "__main__":
    asyncio.run(main())
