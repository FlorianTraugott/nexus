from app.services.chunker import chunk_text


def test_empty_text_returns_no_chunks() -> None:
    assert chunk_text("") == []
    assert chunk_text("   \n  ") == []


def test_short_text_is_a_single_chunk() -> None:
    assert chunk_text("hello world", chunk_size=1000) == ["hello world"]


def test_long_text_splits_into_multiple_chunks() -> None:
    text = "word " * 1000
    chunks = chunk_text(text, chunk_size=1000, overlap=200)
    assert len(chunks) > 1
    assert all(chunk for chunk in chunks)
    assert all(len(chunk) <= 1000 for chunk in chunks)


def test_consecutive_chunks_share_the_overlap() -> None:
    # No separators, so the window can't snap to a boundary and we get a clean
    # sliding window whose overlap region is exact and checkable.
    text = "ABCDEFGHIJ" * 300
    chunks = chunk_text(text, chunk_size=1000, overlap=200)
    assert len(chunks) > 1
    for earlier, later in zip(chunks, chunks[1:], strict=False):
        assert earlier[-200:] == later[:200]


def test_snapping_prefers_paragraph_breaks() -> None:
    first = "A" * 600
    second = "B" * 600
    chunks = chunk_text(f"{first}\n\n{second}", chunk_size=800, overlap=100)
    # the first chunk should end at the blank line, not mid-way through the B's
    assert chunks[0] == first


def test_early_boundary_does_not_collapse_the_step() -> None:
    # An early paragraph break used to make _snap_to_boundary cut near the
    # window start, dropping the step to one character and exploding a real
    # document into tens of thousands of tiny chunks. The step must stay near
    # chunk_size - overlap regardless of where the break falls.
    text = "Title\n\n" + "word " * 4000
    chunks = chunk_text(text, chunk_size=1000, overlap=200)
    assert len(chunks) < 40  # ~len/step, not thousands
    assert min(len(chunk) for chunk in chunks) > 200  # no degenerate slivers
