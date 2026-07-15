"""Reproducible eval-corpus setup: ingest evals/corpus/ under a fixed eval user.

Run from backend/ with the venv active and OPENAI_API_KEY set (ingestion embeds
chunks and captions images via live calls):

    python -m evals.setup_eval_corpus

Idempotent by design. A document is keyed by filename under the eval user:
  - missing            -> create the row, copy the file, ingest (CREATED)
  - present, COMPLETED -> left alone (SKIPPED)
  - present, not done  -> re-ingest the existing row, never a new one (REINGESTED)
So re-running never duplicates documents, and a previously failed/partial ingest
self-heals. This script only READS from the ingestion service; it adds nothing
to it.
"""

import asyncio
import uuid
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.security import hash_password
from app.db.models import DocumentSourceType, DocumentStatus, User
from app.db.repositories import document as document_repo
from app.db.repositories import user as user_repo
from app.db.session import AsyncSessionLocal
from app.services import storage
from app.services.ingestion import ingest_document

CORPUS_DIR = Path(__file__).parent / "corpus"
# Local eval-only account. This password never logs into anything; the eval user
# exists solely to own the fixed corpus. It is not a secret.
EVAL_USER_PASSWORD = "eval-local-only-not-a-real-account"


@dataclass
class DocResult:
    filename: str
    action: str  # "created" | "reingested" | "skipped"
    chunk_count: int
    images_total: int
    images_captioned: int

    @property
    def images_skipped(self) -> int:
        return self.images_total - self.images_captioned


async def get_or_create_eval_user(session: AsyncSession) -> User:
    settings = get_settings()
    user = await user_repo.get_user_by_email(session, settings.EVAL_USER_EMAIL)
    if user is not None:
        return user
    user = await user_repo.create_user(
        session, settings.EVAL_USER_EMAIL, hash_password(EVAL_USER_PASSWORD)
    )
    await session.commit()
    return user


async def _load_counts(
    session: AsyncSession, document_id: uuid.UUID, user_id: uuid.UUID
) -> tuple[int, int, int]:
    """Return (chunk_count, images_total, images_captioned) for a document."""
    doc = await document_repo.get_user_document_with_images(
        session, document_id, user_id
    )
    if doc is None:
        return (0, 0, 0)
    captioned = sum(1 for img in doc.images if img.caption is not None)
    return (doc.chunk_count, len(doc.images), captioned)


async def ensure_document(
    session: AsyncSession, user: User, pdf_path: Path
) -> DocResult:
    """Create-and-ingest, re-ingest, or skip one corpus PDF, idempotently."""
    filename = pdf_path.name
    existing = {
        d.filename: d for d in await document_repo.list_user_documents(session, user.id)
    }
    doc = existing.get(filename)

    if doc is not None and doc.status == DocumentStatus.COMPLETED:
        chunks, total, captioned = await _load_counts(session, doc.id, user.id)
        return DocResult(filename, "skipped", chunks, total, captioned)

    if doc is None:
        doc = await document_repo.create_document(
            session, user.id, filename, DocumentSourceType.PDF
        )
        content = pdf_path.read_bytes()
        await storage.save_file(storage.document_path(doc.id, filename), content)
        await session.commit()
        action = "created"
    else:
        action = "reingested"

    document_id = doc.id
    # ingest_document opens its own session; the row above is already committed,
    # exactly as the HTTP upload handler schedules it as a background task.
    await ingest_document(document_id)

    chunks, total, captioned = await _load_counts(session, document_id, user.id)
    return DocResult(filename, action, chunks, total, captioned)


async def main() -> None:
    settings = get_settings()
    pdfs = sorted(CORPUS_DIR.glob("*.pdf"))
    if not pdfs:
        raise SystemExit(f"No PDFs found in {CORPUS_DIR}")

    async with AsyncSessionLocal() as session:
        user = await get_or_create_eval_user(session)
        print(f"Eval user: {settings.EVAL_USER_EMAIL} ({user.id})")
        print(f"Corpus:    {CORPUS_DIR} ({len(pdfs)} PDFs)\n")

        results: list[DocResult] = []
        for pdf in pdfs:
            print(f"  processing {pdf.name} ...", flush=True)
            results.append(await ensure_document(session, user, pdf))

    created = sum(1 for r in results if r.action == "created")
    reingested = sum(1 for r in results if r.action == "reingested")
    skipped = sum(1 for r in results if r.action == "skipped")

    print("\nSummary")
    print("-------")
    header = (
        f"{'document':<28}{'action':<12}{'chunks':>8}{'imgs':>7}{'capt':>6}{'skip':>6}"
    )
    print(header)
    print("-" * len(header))
    for r in results:
        print(
            f"{r.filename:<28}{r.action:<12}{r.chunk_count:>8}"
            f"{r.images_total:>7}{r.images_captioned:>6}{r.images_skipped:>6}"
        )
    print("-" * len(header))
    print(f"documents: {created} created, {reingested} reingested, {skipped} skipped")
    print(
        f"totals:    {sum(r.chunk_count for r in results)} chunks, "
        f"{sum(r.images_captioned for r in results)} images captioned, "
        f"{sum(r.images_skipped for r in results)} images skipped"
    )


if __name__ == "__main__":
    asyncio.run(main())
