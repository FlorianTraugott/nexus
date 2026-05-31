"""Application configuration.

Settings are loaded from environment variables (and the `.env` file in
development) and validated by Pydantic at startup. If a required variable is
missing or has the wrong type, the app fails immediately with a clear error
rather than breaking mysteriously later — this is "fail fast" configuration.

Usage:
    from app.core.config import get_settings
    settings = get_settings()
    print(settings.POSTGRES_DB)
"""

from functools import lru_cache

from pydantic import computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """All application settings, validated and typed."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        # Ignore env vars we haven't modelled yet (e.g. keys added in later parts)
        extra="ignore",
    )

    # ─── Application ───────────────────────────────────────
    ENVIRONMENT: str = "development"
    DEBUG: bool = True
    # Comma-separated in the env; parsed into a list by the property below.
    CORS_ORIGINS: str = "http://localhost:3000"

    # ─── Database ──────────────────────────────────────────
    POSTGRES_USER: str
    POSTGRES_PASSWORD: str
    POSTGRES_DB: str
    POSTGRES_HOST: str = "db"
    POSTGRES_PORT: int = 5432

    @computed_field  # type: ignore[prop-decorator]
    @property
    def database_url(self) -> str:
        """Async SQLAlchemy connection string, built from the parts above.

        Building it from components (rather than storing one big URL) keeps a
        single source of truth and avoids the URL drifting out of sync with the
        individual POSTGRES_* values.
        """
        return (
            f"postgresql+asyncpg://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def cors_origins_list(self) -> list[str]:
        """CORS_ORIGINS as a clean list of origins."""
        return [
            origin.strip() for origin in self.CORS_ORIGINS.split(",") if origin.strip()
        ]


@lru_cache
def get_settings() -> Settings:
    """Return a cached Settings instance.

    `@lru_cache` ensures the `.env` file is read and validated only once, and
    that every caller shares the same settings object. Used directly and as a
    FastAPI dependency.
    """
    return Settings()  # type: ignore[call-arg]
