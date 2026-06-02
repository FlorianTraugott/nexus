"""Tests for the file storage service."""

import uuid
from pathlib import Path

from app.services import storage


async def test_save_read_delete_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "nested" / "file.bin"
    await storage.save_file(path, b"hello world")
    assert path.exists()
    assert await storage.read_file(path) == b"hello world"
    storage.delete_file(path)
    assert not path.exists()


def test_document_path_uses_id_and_extension() -> None:
    document_id = uuid.uuid4()
    path = storage.document_path(document_id, "quarterly report.pdf")
    assert path.name == f"{document_id}.pdf"


def test_delete_missing_file_is_safe(tmp_path: Path) -> None:
    storage.delete_file(tmp_path / "does-not-exist.bin")
