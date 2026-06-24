from pathlib import Path

from app.db.models import DocumentSourceType
from app.services.parser import extract_text

FIXTURES = Path(__file__).parent.parent / "fixtures"


def test_extract_text_from_plain_text(tmp_path: Path) -> None:
    file = tmp_path / "notes.txt"
    file.write_text("Hello from a text file.", encoding="utf-8")
    assert extract_text(file, DocumentSourceType.TEXT) == "Hello from a text file."


def test_extract_text_handles_bad_bytes(tmp_path: Path) -> None:
    file = tmp_path / "broken.txt"
    file.write_bytes(b"valid text \xff\xfe more text")
    # invalid bytes are replaced, not fatal
    result = extract_text(file, DocumentSourceType.TEXT)
    assert "valid text" in result
    assert "more text" in result


def test_extract_text_from_pdf() -> None:
    result = extract_text(FIXTURES / "sample.pdf", DocumentSourceType.PDF)
    assert "Nexus" in result
    assert "chunked" in result
