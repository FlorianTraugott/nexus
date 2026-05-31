"""Nexus AI — application entry point.

PART 1 NOTE
-----------
This is a deliberately minimal placeholder so the Docker stack boots and CI
has something to import. It is REPLACED in Part 2 with a proper application
factory (`create_app()`), typed settings, structured logging, and a database
connection. Do not build on this file directly — treat it as a smoke test that
the container, port mapping, and CI all work end to end.
"""

from fastapi import FastAPI

app = FastAPI(title="Nexus AI", version="0.1.0")


@app.get("/health")
def health() -> dict[str, str]:
    """Liveness probe. Returns 200 if the process is up."""
    return {"status": "ok"}


@app.get("/")
def root() -> dict[str, str]:
    """Placeholder root. Confirms the stack is wired correctly."""
    return {"message": "Nexus AI is running. Real app arrives in Part 2."}
