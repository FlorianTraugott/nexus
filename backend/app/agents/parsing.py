"""Tolerant parsing of model output shared by the structured agents."""


def strip_code_fence(text: str) -> str:
    """Remove a single surrounding markdown code fence, if the model added one.

    Real models sometimes wrap JSON in a ```json ... ``` block despite being
    asked for a bare object. Strip one such fence (and an optional language tag)
    so the payload can be validated; output still invalid afterwards is returned
    unchanged, so the caller's validation raises as before.
    """
    stripped = text.strip()
    if not (stripped.startswith("```") and stripped.endswith("```")):
        return stripped
    inner = stripped[3:-3]
    newline = inner.find("\n")
    if newline != -1 and inner[:newline].strip().isalpha():
        inner = inner[newline + 1 :]
    return inner.strip()
