"""Split text into overlapping chunks for embedding."""


def chunk_text(text: str, chunk_size: int = 1000, overlap: int = 200) -> list[str]:
    """Slice text into overlapping windows, preferring natural boundaries.

    The overlap carries context across chunk edges so a passage split mid-idea
    still retrieves well.
    """
    text = text.strip()
    if not text:
        return []
    if len(text) <= chunk_size:
        return [text]

    chunks: list[str] = []
    start = 0
    length = len(text)
    while start < length:
        end = min(start + chunk_size, length)
        if end < length:
            end = _snap_to_boundary(text, start, end)
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= length:
            break
        # step forward but keep `overlap` characters of the previous window;
        # the +1 floor guarantees progress even with awkward boundaries
        start = max(end - overlap, start + 1)
    return chunks


def _snap_to_boundary(text: str, start: int, end: int) -> int:
    """Move the cut to the last paragraph/sentence/word break in the window.

    Only accept a break in the latter half of the window. Snapping to an early
    break would leave `end - overlap` at or behind `start`, collapsing the step
    to one character and exploding the chunk count on real-world text.
    """
    window = text[start:end]
    midpoint = len(window) // 2
    for separator in ("\n\n", "\n", ". ", " "):
        index = window.rfind(separator)
        if index >= midpoint:
            return start + index + len(separator)
    return end
