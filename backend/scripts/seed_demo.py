"""Idempotent demo seeding for the public deployment.

Populates the shared demo account with a small COMMITTED corpus (so it exists in
the container — the NIST eval corpus is gitignored and does not) and one
pre-seeded COMPLETED research task, so the deployed demo works out of the box at
zero per-visit cost.

This is also the ACCEPTANCE TEST for the state strategy (D2). It writes chunk
vectors into CHROMA_PERSIST_DIR and image files into UPLOAD_DIR — both on the
mounted /data volume in production. If those survive a redeploy the volume is
wired correctly; if the volume is misconfigured, the Part 12.2b startup
consistency check fails loud on the next boot rather than silently abstaining on
every query.

Run ONCE, AFTER the volume is mounted, in the deployed environment:

    railway run python -m scripts.seed_demo     # production (see DEPLOY.md)
    python -m scripts.seed_demo                 # local, from backend/ with venv

Idempotent by design, keyed by filename under the demo user and by the fixed
research-task id: a document already COMPLETED is skipped, and the research task
is inserted only if absent. A second run therefore makes ZERO provider calls, so
re-running on every redeploy is safe and free (proven by running it a second
time with a bogus OPENAI_API_KEY: it completes without contacting OpenAI).
"""

import asyncio
import json
import uuid
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.security import hash_password
from app.db.models import (
    DocumentSourceType,
    DocumentStatus,
    ResearchTask,
    ResearchTaskStatus,
    User,
)
from app.db.repositories import document as document_repo
from app.db.repositories import user as user_repo
from app.db.session import AsyncSessionLocal
from app.services import storage
from app.services.ingestion import ingest_document

DEMO_CORPUS_DIR = Path(__file__).parent / "demo_corpus"
RESEARCH_FIXTURE = Path(__file__).parent / "demo_research_task.json"

# FIXED so the frontend can bake NEXT_PUBLIC_DEMO_RESEARCH_TASK_ID at build time
# WITHOUT waiting for the seed to run (the build-time-baking constraint again):
# the id is known in advance because it is a constant, not generated at seed time.
DEMO_RESEARCH_TASK_ID = uuid.UUID("de300000-0000-4000-a000-000000000001")


def _source_type(path: Path) -> DocumentSourceType:
    return (
        DocumentSourceType.PDF
        if path.suffix.lower() == ".pdf"
        else DocumentSourceType.TEXT
    )


@dataclass
class DocResult:
    filename: str
    action: str  # "created" | "skipped"
    chunk_count: int
    images_total: int
    images_captioned: int


async def get_or_create_demo_user(session: AsyncSession) -> User:
    settings = get_settings()
    user = await user_repo.get_user_by_email(session, settings.DEMO_USER_EMAIL)
    if user is not None:
        return user
    user = await user_repo.create_user(
        session, settings.DEMO_USER_EMAIL, hash_password(settings.DEMO_USER_PASSWORD)
    )
    await session.commit()
    return user


async def _load_counts(
    session: AsyncSession, document_id: uuid.UUID, user_id: uuid.UUID
) -> tuple[int, int, int]:
    doc = await document_repo.get_user_document_with_images(
        session, document_id, user_id
    )
    if doc is None:
        return (0, 0, 0)
    captioned = sum(1 for img in doc.images if img.caption is not None)
    return (doc.chunk_count, len(doc.images), captioned)


async def ensure_document(
    session: AsyncSession, user_id: uuid.UUID, path: Path
) -> DocResult:
    """Create-and-ingest one corpus file, or skip it if already COMPLETED."""
    filename = path.name
    existing = {
        d.filename: d for d in await document_repo.list_user_documents(session, user_id)
    }
    doc = existing.get(filename)

    if doc is not None and doc.status == DocumentStatus.COMPLETED:
        chunks, total, captioned = await _load_counts(session, doc.id, user_id)
        return DocResult(filename, "skipped", chunks, total, captioned)

    if doc is None:
        doc = await document_repo.create_document(
            session, user_id, filename, _source_type(path)
        )
        await storage.save_file(
            storage.document_path(doc.id, filename), path.read_bytes()
        )
        await session.commit()

    document_id = doc.id
    # ingest_document opens its OWN session (like the upload background task); the
    # row above is already committed.
    await ingest_document(document_id)

    # The ingest ran in its own session; expire so we read fresh counts here.
    session.expire_all()
    chunks, total, captioned = await _load_counts(session, document_id, user_id)
    return DocResult(filename, "created", chunks, total, captioned)


async def ensure_research_task(session: AsyncSession, user_id: uuid.UUID) -> str:
    """Insert the pre-seeded COMPLETED research task from the committed fixture.

    Idempotent on the fixed id. Status COMPLETED, so the Part 12.2b stranded-task
    sweep (which only touches RUNNING rows) can never mark it FAILED.
    """
    if await session.get(ResearchTask, DEMO_RESEARCH_TASK_ID) is not None:
        return "skipped"
    if not RESEARCH_FIXTURE.exists():
        print(f"  research fixture {RESEARCH_FIXTURE.name} missing; skipping task seed")
        return "missing_fixture"
    result = json.loads(RESEARCH_FIXTURE.read_text())
    task = ResearchTask(
        id=DEMO_RESEARCH_TASK_ID,
        user_id=user_id,
        topic=result.get("topic", "Project Aurora"),
        status=ResearchTaskStatus.COMPLETED,
        result=result,
    )
    session.add(task)
    await session.commit()
    return "created"


async def main() -> None:
    settings = get_settings()
    files = sorted(
        p for p in DEMO_CORPUS_DIR.iterdir() if p.is_file() and p.name != "README.md"
    )
    if not files:
        raise SystemExit(f"No demo corpus files in {DEMO_CORPUS_DIR}")

    async with AsyncSessionLocal() as session:
        user = await get_or_create_demo_user(session)
        user_id = user.id
        print(f"Demo user:    {settings.DEMO_USER_EMAIL} ({user_id})")
        print(f"Corpus:       {DEMO_CORPUS_DIR} ({len(files)} files)")
        print(f"Research task: {DEMO_RESEARCH_TASK_ID}")
        print()

        results: list[DocResult] = []
        for path in files:
            print(f"  processing {path.name} ...", flush=True)
            results.append(await ensure_document(session, user_id, path))

        task_action = await ensure_research_task(session, user_id)

    created = sum(1 for r in results if r.action == "created")
    skipped = sum(1 for r in results if r.action == "skipped")

    print("\nSummary")
    print("-------")
    for r in results:
        print(
            f"  {r.filename:<32}{r.action:<10}"
            f"chunks={r.chunk_count} images={r.images_total} "
            f"captioned={r.images_captioned}"
        )
    print(f"  research task: {task_action}")
    print(
        f"\ndocuments: {created} created, {skipped} skipped; "
        f"research task {task_action}"
    )


if __name__ == "__main__":
    asyncio.run(main())
