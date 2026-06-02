"""Extract plain text from uploaded documents."""

from pathlib import Path

from pypdf import PdfReader

from app.db.models import DocumentSourceType


def extract_text(path: Path, source_type: DocumentSourceType) -> str:
    """Pull the raw text out of a file so it can be chunked and embedded."""
    if source_type == DocumentSourceType.PDF:
        return _extract_pdf_text(path)
    # Plain-text uploads: replace undecodable bytes rather than failing the
    # whole ingestion on one bad character.
    return path.read_text(encoding="utf-8", errors="replace").strip()


def _extract_pdf_text(path: Path) -> str:
    reader = PdfReader(str(path))
    pages = [page.extract_text() or "" for page in reader.pages]
    return "\n\n".join(pages).strip()
