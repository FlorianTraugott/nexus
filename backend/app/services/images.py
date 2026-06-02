"""Extract embedded images from PDF documents."""

from dataclasses import dataclass
from pathlib import Path

from pypdf import PdfReader

from app.core.logging import get_logger

log = get_logger(__name__)


@dataclass
class ExtractedImage:
    page_number: int
    image_index: int
    path: Path


def extract_images(pdf_path: Path, output_dir: Path) -> list[ExtractedImage]:
    """Save embedded PDF images as PNGs, skipping any that fail to decode.

    Re-encoding to PNG normalises the odd colour spaces PDFs sometimes use so
    downstream vision models get a format they can read.
    """
    reader = PdfReader(str(pdf_path))
    output_dir.mkdir(parents=True, exist_ok=True)

    extracted: list[ExtractedImage] = []
    index = 0
    for page_number, page in enumerate(reader.pages):
        for image in page.images:
            try:
                pil_image = image.image
                if pil_image is None:
                    continue
                destination = output_dir / f"image_{page_number}_{index}.png"
                pil_image.save(destination, format="PNG")
            except Exception:
                # One unreadable image shouldn't abort the whole document.
                log.warning(
                    "image_extraction_failed", pdf=str(pdf_path), page=page_number
                )
                continue
            extracted.append(
                ExtractedImage(
                    page_number=page_number, image_index=index, path=destination
                )
            )
            index += 1
    return extracted
