"""End-to-end tests for document endpoints and the ingestion pipeline."""

import shutil
import uuid
from pathlib import Path

import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from tests.fakes import FakeEmbeddingProvider, FakeVisionProvider, ephemeral_store

from app.api.v1.documents import get_ingestion_runner
from app.core.config import get_settings
from app.db.models import (
    DocumentChunk,
    DocumentImage,
    DocumentSourceType,
    DocumentStatus,
    User,
)
from app.db.repositories import document as document_repo
from app.main import app
from app.services import storage
from app.services.ingestion import run_ingestion
from app.services.vector_store import get_vector_store

FIXTURES = Path(__file__).parent.parent / "fixtures"
DOCUMENTS = "/api/v1/documents"
CREDS = {"email": "ada@example.com", "password": "password123"}
OTHER = {"email": "bob@example.com", "password": "password123"}


async def _noop_ingest(document_id: uuid.UUID) -> None:
    return None


class _RecordingStore:
    """Captures delete_by_document calls from the delete endpoint."""

    def __init__(self) -> None:
        self.deleted: list[str] = []

    def delete_by_document(self, document_id: object) -> None:
        self.deleted.append(str(document_id))


async def _register_and_token(client: AsyncClient, creds: dict[str, str]) -> str:
    await client.post("/api/v1/auth/register", json=creds)
    tokens = (await client.post("/api/v1/auth/login", json=creds)).json()
    return str(tokens["access_token"])


def _pdf_upload() -> dict[str, tuple[str, bytes, str]]:
    return {
        "file": (
            "sample.pdf",
            (FIXTURES / "sample.pdf").read_bytes(),
            "application/pdf",
        )
    }


@pytest_asyncio.fixture
async def auth_headers(client, monkeypatch, tmp_path) -> dict[str, str]:  # type: ignore[no-untyped-def]
    # Keep uploaded files out of the repo, and stub the background ingestion:
    # the real one opens its own session against the production engine, which
    # the get_db override can't reach.
    monkeypatch.setattr(get_settings(), "UPLOAD_DIR", str(tmp_path))
    app.dependency_overrides[get_ingestion_runner] = lambda: _noop_ingest
    # Keep the delete endpoint off a real Chroma store by default.
    app.dependency_overrides[get_vector_store] = _RecordingStore
    token = await _register_and_token(client, CREDS)
    return {"Authorization": f"Bearer {token}"}


async def test_upload_creates_pending_document(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    response = await client.post(DOCUMENTS, files=_pdf_upload(), headers=auth_headers)
    assert response.status_code == 201
    body = response.json()
    assert body["filename"] == "sample.pdf"
    assert body["source_type"] == "pdf"
    assert body["status"] == "pending"
    assert body["chunk_count"] == 0


async def test_upload_requires_authentication(client: AsyncClient) -> None:
    response = await client.post(DOCUMENTS, files=_pdf_upload())
    assert response.status_code in (401, 403)


async def test_upload_rejects_unsupported_type(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    files = {"file": ("photo.png", b"\x89PNG\r\n", "image/png")}
    response = await client.post(DOCUMENTS, files=files, headers=auth_headers)
    assert response.status_code == 415


async def test_upload_rejects_oversized_file(
    client: AsyncClient, auth_headers: dict[str, str], monkeypatch
) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(get_settings(), "MAX_UPLOAD_SIZE_MB", 0)
    response = await client.post(DOCUMENTS, files=_pdf_upload(), headers=auth_headers)
    assert response.status_code == 413


async def test_list_returns_only_my_documents(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    await client.post(DOCUMENTS, files=_pdf_upload(), headers=auth_headers)
    response = await client.get(DOCUMENTS, headers=auth_headers)
    assert response.status_code == 200
    assert len(response.json()) == 1


async def test_get_returns_document(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    created = (
        await client.post(DOCUMENTS, files=_pdf_upload(), headers=auth_headers)
    ).json()
    response = await client.get(f"{DOCUMENTS}/{created['id']}", headers=auth_headers)
    assert response.status_code == 200
    assert response.json()["id"] == created["id"]


async def test_get_missing_document_is_404(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    response = await client.get(f"{DOCUMENTS}/{uuid.uuid4()}", headers=auth_headers)
    assert response.status_code == 404


async def test_cannot_access_another_users_document(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    created = (
        await client.post(DOCUMENTS, files=_pdf_upload(), headers=auth_headers)
    ).json()
    other = {"Authorization": f"Bearer {await _register_and_token(client, OTHER)}"}
    response = await client.get(f"{DOCUMENTS}/{created['id']}", headers=other)
    assert response.status_code == 404


async def test_delete_removes_document(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    created = (
        await client.post(DOCUMENTS, files=_pdf_upload(), headers=auth_headers)
    ).json()
    deleted = await client.delete(f"{DOCUMENTS}/{created['id']}", headers=auth_headers)
    assert deleted.status_code == 204
    after = await client.get(f"{DOCUMENTS}/{created['id']}", headers=auth_headers)
    assert after.status_code == 404


async def _seed_document(db_session: AsyncSession, filename: str) -> uuid.UUID:
    user = User(email=f"{uuid.uuid4()}@example.com", hashed_password="x")
    db_session.add(user)
    await db_session.flush()
    document = await document_repo.create_document(
        db_session, user.id, filename, DocumentSourceType.PDF
    )
    await db_session.commit()
    return document.id


async def test_run_ingestion_processes_pdf(
    db_session: AsyncSession, monkeypatch, tmp_path
) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(get_settings(), "UPLOAD_DIR", str(tmp_path))
    document_id = await _seed_document(db_session, "sample_with_image.pdf")

    destination = storage.document_path(document_id, "sample_with_image.pdf")
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(FIXTURES / "sample_with_image.pdf", destination)

    # Captioning has no injection point in run_ingestion, so fake the vision
    # provider directly to keep the image branch offline (the fixture image is
    # above the min-px gate and would otherwise hit the network).
    monkeypatch.setattr(
        "app.services.vision.get_vision_provider", lambda: FakeVisionProvider()
    )
    embedder = FakeEmbeddingProvider()
    store = ephemeral_store()
    await run_ingestion(
        db_session, document_id, embedder, store, image_store=ephemeral_store()
    )

    document = await document_repo.get_document(db_session, document_id)
    assert document is not None
    assert document.status == DocumentStatus.COMPLETED
    assert document.chunk_count >= 1

    chunks = (
        (
            await db_session.execute(
                select(DocumentChunk).where(DocumentChunk.document_id == document_id)
            )
        )
        .scalars()
        .all()
    )
    assert len(chunks) == document.chunk_count

    # Every chunk was embedded and indexed, tagged with its document and owner.
    assert store.count() == document.chunk_count
    matches = store.query([0.0] * embedder.dimension, k=document.chunk_count)
    assert {m.metadata["document_id"] for m in matches} == {str(document_id)}
    assert all("user_id" in m.metadata for m in matches)

    images = (
        (
            await db_session.execute(
                select(DocumentImage).where(DocumentImage.document_id == document_id)
            )
        )
        .scalars()
        .all()
    )
    assert len(images) == 1


async def test_run_ingestion_marks_failure_when_file_missing(
    db_session: AsyncSession, monkeypatch, tmp_path
) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(get_settings(), "UPLOAD_DIR", str(tmp_path))
    document_id = await _seed_document(db_session, "missing.pdf")

    # No file is placed on disk, so parsing should fail.
    await run_ingestion(
        db_session, document_id, FakeEmbeddingProvider(), ephemeral_store()
    )

    document = await document_repo.get_document(db_session, document_id)
    assert document is not None
    assert document.status == DocumentStatus.FAILED


async def test_run_ingestion_reindex_replaces_vectors(
    db_session: AsyncSession, monkeypatch, tmp_path
) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(get_settings(), "UPLOAD_DIR", str(tmp_path))
    document_id = await _seed_document(db_session, "sample_with_image.pdf")
    destination = storage.document_path(document_id, "sample_with_image.pdf")
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(FIXTURES / "sample_with_image.pdf", destination)

    monkeypatch.setattr(
        "app.services.vision.get_vision_provider", lambda: FakeVisionProvider()
    )
    embedder = FakeEmbeddingProvider()
    store = ephemeral_store()
    image_store = ephemeral_store()
    await run_ingestion(
        db_session, document_id, embedder, store, image_store=image_store
    )
    first_count = store.count()

    # Re-ingesting the same document must not duplicate vectors.
    await run_ingestion(
        db_session, document_id, embedder, store, image_store=image_store
    )
    document = await document_repo.get_document(db_session, document_id)
    assert document is not None
    assert store.count() == first_count == document.chunk_count


async def test_delete_removes_document_vectors(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    created = (
        await client.post(DOCUMENTS, files=_pdf_upload(), headers=auth_headers)
    ).json()
    recording = _RecordingStore()
    app.dependency_overrides[get_vector_store] = lambda: recording

    deleted = await client.delete(f"{DOCUMENTS}/{created['id']}", headers=auth_headers)

    assert deleted.status_code == 204
    assert recording.deleted == [created["id"]]
