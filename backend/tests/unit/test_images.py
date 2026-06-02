from pathlib import Path

from app.services.images import extract_images

FIXTURES = Path(__file__).parent.parent / "fixtures"


def test_extract_images_from_pdf(tmp_path: Path) -> None:
    images = extract_images(FIXTURES / "sample_with_image.pdf", tmp_path)
    assert len(images) == 1
    only = images[0]
    assert only.page_number == 0
    assert only.image_index == 0
    assert only.path.exists()
    assert only.path.suffix == ".png"


def test_extract_images_from_text_only_pdf(tmp_path: Path) -> None:
    assert extract_images(FIXTURES / "sample.pdf", tmp_path) == []


def test_output_directory_is_created(tmp_path: Path) -> None:
    target = tmp_path / "nested" / "images"
    extract_images(FIXTURES / "sample_with_image.pdf", target)
    assert target.is_dir()
