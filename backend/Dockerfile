# Multi-stage production image. The dev-tool reduction comes from installing
# requirements.txt (runtime only) rather than requirements-dev.txt; the builder
# stage exists to keep the final image a clean venv with no pip cache or build
# artifacts. Both stages share the SAME base tag so the copied venv is ABI-valid.

FROM python:3.12-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Install runtime deps into a self-contained venv we can copy wholesale.
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt


FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH"

WORKDIR /app

COPY --from=builder /opt/venv /opt/venv
# .dockerignore keeps .env, chroma/, uploads/, tests/, evals/, and caches out of
# the build context, so this copies application code + alembic migrations only.
COPY . .

# Run as an unprivileged user. The state dirs (CHROMA_PERSIST_DIR / UPLOAD_DIR)
# live on a mounted volume in production, not in the image.
RUN useradd --create-home --uid 10001 appuser && chown -R appuser /app
USER appuser

EXPOSE 8000

# No --reload in production. Migrations are D3's pre-deploy responsibility, run
# in a separate container off this image before the app goes live.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
