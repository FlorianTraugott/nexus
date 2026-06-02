"""Local file storage for uploaded documents."""

import shutil
import uuid
from pathlib import Path

import aiofiles

from app.core.config import get_settings


def document_path(document_id: uuid.UUID, filename: str) -> Path:
    upload_dir = Path(get_settings().UPLOAD_DIR)
    return upload_dir / f"{document_id}{Path(filename).suffix}"


def image_dir(document_id: uuid.UUID) -> Path:
    return Path(get_settings().UPLOAD_DIR) / "images" / str(document_id)


async def save_file(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    async with aiofiles.open(path, "wb") as handle:
        await handle.write(content)


async def read_file(path: Path) -> bytes:
    async with aiofiles.open(path, "rb") as handle:
        return await handle.read()


def delete_file(path: Path) -> None:
    path.unlink(missing_ok=True)


def delete_document_files(document_id: uuid.UUID, filename: str) -> None:
    """Remove a document's original file and any images extracted from it."""
    delete_file(document_path(document_id, filename))
    shutil.rmtree(image_dir(document_id), ignore_errors=True)
