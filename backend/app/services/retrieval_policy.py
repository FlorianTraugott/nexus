"""Retrieval abstention policy: one home for the distance gate.

A query-layer policy, deliberately kept out of retrieval.py/image_retrieval.py:
those return raw ranked results, and each answering endpoint decides whether the
best hit is close enough to answer from. Type-agnostic (plain float in) so the
same comparison serves both the text and image callers without importing either
retrieval type.
"""


def passes_distance_gate(best_distance: float, max_distance: float) -> bool:
    """True if the closest hit is within the abstention threshold (<=)."""
    return best_distance <= max_distance
