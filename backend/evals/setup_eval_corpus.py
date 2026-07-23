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

--reingest (the chunking-experiment path) force-re-ingests COMPLETED documents
TEXT-ONLY (include_images=False): chunk parameters have zero effect on images,
and captions are non-deterministic LLM output — preserving them keeps a
same-params re-ingest exactly reproducible and burns no vision calls. The flag
is HARD-SCOPED to the script-created eval account: it verifies the target
user's password hash against EVAL_USER_PASSWORD and refuses anyone else, so a
stray EVAL_USER_EMAIL pointing at a real account can never force-rebuild that
account's chunks.
"""

import argparse
import asyncio
import uuid
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.security import hash_password, verify_password
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
    session: AsyncSession, user_id: uuid.UUID, pdf_path: Path, *, force: bool = False
) -> DocResult:
    """Create-and-ingest, re-ingest, or skip one corpus PDF, idempotently.

    force=True re-ingests even COMPLETED documents, TEXT-ONLY — the
    chunking-experiment path. The heal path (present, not done) keeps the full
    pipeline: an incomplete ingest may genuinely be missing captions.
    """
    filename = pdf_path.name
    existing = {
        d.filename: d for d in await document_repo.list_user_documents(session, user_id)
    }
    doc = existing.get(filename)

    include_images = True
    if doc is not None and doc.status == DocumentStatus.COMPLETED:
        if not force:
            chunks, total, captioned = await _load_counts(session, doc.id, user_id)
            return DocResult(filename, "skipped", chunks, total, captioned)
        # Forced re-chunk of a healthy document: leave images/captions alone.
        include_images = False

    if doc is None:
        doc = await document_repo.create_document(
            session, user_id, filename, DocumentSourceType.PDF
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
    await ingest_document(document_id, include_images=include_images)

    # The ingest ran in its OWN session; this session's identity map still holds
    # the pre-ingest row, so expire it or the summary reports STALE chunk counts
    # (caught in the chunking sweep: V1 re-chunked to 626 but printed 455).
    session.expire_all()
    chunks, total, captioned = await _load_counts(session, document_id, user_id)
    return DocResult(filename, action, chunks, total, captioned)


async def main() -> None:
    arg_parser = argparse.ArgumentParser(description="Eval corpus setup")
    arg_parser.add_argument(
        "--reingest",
        action="store_true",
        help="force text-only re-ingest of COMPLETED docs (chunking experiments)",
    )
    args = arg_parser.parse_args()

    settings = get_settings()
    pdfs = sorted(CORPUS_DIR.glob("*.pdf"))
    if not pdfs:
        raise SystemExit(f"No PDFs found in {CORPUS_DIR}")

    async with AsyncSessionLocal() as session:
        user = await get_or_create_eval_user(session)
        if args.reingest and not verify_password(
            EVAL_USER_PASSWORD, user.hashed_password
        ):
            # --reingest force-deletes and rebuilds chunks; it must be
            # impossible to point it at a real account. Ownership proof: only
            # the account THIS SCRIPT created carries the known eval password.
            raise SystemExit(
                f"Refusing --reingest: {settings.EVAL_USER_EMAIL} is not the "
                "script-created eval account (password hash mismatch)."
            )
        # Plain UUID captured BEFORE any expire_all: expired ORM attribute
        # access is a sync lazy-refresh, which raises MissingGreenlet under
        # the async session (bit us mid-sweep). Values are safe; objects are not.
        user_id = user.id
        print(f"Eval user: {settings.EVAL_USER_EMAIL} ({user_id})")
        print(f"Corpus:    {CORPUS_DIR} ({len(pdfs)} PDFs)")
        print(f"Chunking:  size={settings.CHUNK_SIZE} overlap={settings.CHUNK_OVERLAP}")
        if args.reingest:
            print("Mode:      FORCED text-only re-ingest (images/captions preserved)")
        print()

        results: list[DocResult] = []
        for pdf in pdfs:
            print(f"  processing {pdf.name} ...", flush=True)
            results.append(
                await ensure_document(session, user_id, pdf, force=args.reingest)
            )

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
