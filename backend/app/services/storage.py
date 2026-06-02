"""Local file storage for uploaded documents."""

import uuid
from pathlib import Path

import aiofiles

from app.core.config import get_settings


def document_path(document_id: uuid.UUID, filename: str) -> Path:
    upload_dir = Path(get_settings().UPLOAD_DIR)
    return upload_dir / f"{document_id}{Path(filename).suffix}"


async def save_file(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    async with aiofiles.open(path, "wb") as handle:
        await handle.write(content)


async def read_file(path: Path) -> bytes:
    async with aiofiles.open(path, "rb") as handle:
        return await handle.read()


def delete_file(path: Path) -> None:
    path.unlink(missing_ok=True)
