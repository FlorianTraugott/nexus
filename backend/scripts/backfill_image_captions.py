"""Backfill captions + image-vector index for documents ingested before Part 7b.

Documents ingested before 7b.2 have images on disk and rows in document_images,
but caption IS NULL and nothing in the nexus_images collection, so they are
invisible to /vision/search. This one-off, idempotent, resumable script captions
each uncaptioned image with the vision model and indexes it, reusing the exact
ingest code paths.

Run from backend/ with the venv active:

    python -m scripts.backfill_image_captions [--dry-run] [--limit N]

--dry-run reports counts and exits without captioning, embedding, or spending.
--limit N processes at most N images (cheap test on a real corpus).
"""

import argparse
import asyncio
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import joinedload

from app.core.logging import get_logger
from app.db.models import DocumentImage
from app.db.repositories import document as document_repo
from app.db.session import AsyncSessionLocal
from app.services.embeddings import get_embedding_provider
from app.services.ingestion import index_captioned_images
from app.services.vector_store import get_image_vector_store
from app.services.vision import caption_image

log = get_logger(__name__)


async def _run(dry_run: bool, limit: int | None) -> None:
    async with AsyncSessionLocal() as session:
        # Uncaptioned images only. caption IS NULL is the resume marker, so a
        # re-run naturally skips anything already done. joinedload pulls each
        # image's parent document in the same query — we need document.user_id.
        stmt = (
            select(DocumentImage)
            .where(DocumentImage.caption.is_(None))
            .options(joinedload(DocumentImage.document))
            .order_by(DocumentImage.document_id, DocumentImage.image_index)
        )
        if limit is not None:
            stmt = stmt.limit(limit)
        images = list((await session.execute(stmt)).scalars().all())

        total = len(images)
        print(f"Found {total} uncaptioned image(s) to process.")
        if dry_run:
            print("--dry-run: exiting without captioning, embedding, or spending.")
            return
        if total == 0:
            return

        store = get_image_vector_store()
        embedder = get_embedding_provider()

        processed = captioned = skipped = failed = 0
        for image in images:
            processed += 1
            try:
                caption = await caption_image(Path(image.storage_path))
                if caption is None:
                    # Junk / NO_CONTENT / too small: nothing to index, leave NULL.
                    skipped += 1
                    log.info("backfill_skipped_image", image=image.storage_path)
                    continue

                # SCOPE (load-bearing): user_id in the Chroma metadata comes from
                # THIS image's own parent document — never a shared/ambient user.
                # This script runs across every user's documents, so a wrong owner
                # here is a cross-user scope leak in the index.
                document = image.document

                # Ordering is load-bearing: index the vector FIRST, then commit the
                # caption LAST. The caption column is the resume marker, so if we
                # crash after the add but before the commit, the image stays NULL
                # and is retried (upsert makes the re-add idempotent). Committing
                # the caption first would leave a captioned-but-unindexed image:
                # invisible to search AND never retried, since the query only
                # selects caption IS NULL.
                await index_captioned_images(
                    store, embedder, document, [(image, caption)]
                )
                await document_repo.set_image_caption(session, image.id, caption)
                await session.commit()
                captioned += 1
            except Exception:
                # Best-effort per image: one bad image must never abort the run.
                # Roll back so a half-done image stays NULL and is retried.
                await session.rollback()
                failed += 1
                log.warning("backfill_image_failed", image=image.storage_path)

            print(
                f"  processed {processed}/{total} "
                f"(captioned={captioned} skipped={skipped} failed={failed})"
            )

        print(
            "Done. "
            f"processed={processed} captioned={captioned} "
            f"skipped={skipped} failed={failed}"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report counts and exit without captioning, embedding, or spending.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Process at most N images (a cheap test on a real corpus).",
    )
    args = parser.parse_args()
    asyncio.run(_run(dry_run=args.dry_run, limit=args.limit))


if __name__ == "__main__":
    main()
