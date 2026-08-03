"""Application settings, loaded from the environment and validated at startup."""

import os
from functools import lru_cache
from typing import Self
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from pydantic import computed_field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_ASYNC_PG_DRIVER = "postgresql+asyncpg"
# libpq-style query params that a managed provider bakes into DATABASE_URL but
# asyncpg does not accept (it configures TLS via connect_args, not the DSN).
# Stripped here; SSL is controlled by DB_SSL_REQUIRE instead.
_ASYNCPG_INCOMPATIBLE_QUERY_KEYS = {"sslmode", "channel_binding"}
_KNOWN_ENVIRONMENTS = {"development", "staging", "production", "test"}


def _normalise_async_dsn(dsn: str) -> str:
    """Coerce a provider-supplied DSN onto the asyncpg driver.

    Managed Postgres hands you `postgres://` or `postgresql://` (and sometimes a
    `?sslmode=require` suffix). SQLAlchemy needs the explicit `+asyncpg` driver,
    and asyncpg rejects the libpq-only query params, so both are rewritten.
    """
    parts = urlsplit(dsn)
    scheme = parts.scheme
    if scheme in ("postgres", "postgresql") or scheme.startswith("postgresql+"):
        scheme = _ASYNC_PG_DRIVER
    query = urlencode(
        [
            (k, v)
            for k, v in parse_qsl(parts.query, keep_blank_values=True)
            if k not in _ASYNCPG_INCOMPATIBLE_QUERY_KEYS
        ]
    )
    return urlunsplit((scheme, parts.netloc, parts.path, query, parts.fragment))


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    ENVIRONMENT: str = "development"
    # Safe-by-default: an unset DEBUG must not enable debug mode (verbose errors,
    # SQL echo) in production. Local dev and Docker set DEBUG=true explicitly.
    DEBUG: bool = False
    CORS_ORIGINS: str = "http://localhost:3000"
    # Behind a platform proxy (Railway), request.client is the proxy, so IP-based
    # rate limits collapse to one bucket. When true, the limiter keys off the real
    # client IP from X-Forwarded-For. Only trust this where a proxy is guaranteed
    # in front of the app (never bind the app port publicly); false locally, where
    # a client could forge the header directly.
    TRUST_PROXY_HEADERS: bool = False

    POSTGRES_USER: str
    POSTGRES_PASSWORD: str
    POSTGRES_DB: str
    POSTGRES_HOST: str = "db"
    POSTGRES_PORT: int = 5432
    # Optional full connection string. Managed Postgres (Railway/Render) hands you
    # one; when set it OVERRIDES the assembled POSTGRES_* URL and is normalised to
    # the asyncpg driver. Left blank locally so the POSTGRES_* parts drive it.
    DATABASE_URL: str = ""
    # Managed Postgres requires TLS; local/Docker Postgres does not. When true the
    # engine connects with SSL (session.py passes connect_args={"ssl": True}).
    DB_SSL_REQUIRE: bool = False

    JWT_SECRET_KEY: str
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # Demo cost-exposure hardening. Set REGISTRATION_ENABLED=false in the public
    # demo so /auth/register returns 403 (default true leaves local dev/tests
    # untouched). The RATE_LIMIT_* values throttle the OpenAI-spending endpoints
    # per authenticated USER (JWT identity). NOTE: buckets are per-(limit, key,
    # endpoint), so /query and /query/stream get SEPARATE 60/hour buckets (120
    # combined), AND on the SHARED demo account that ceiling is GLOBAL across all
    # visitors, not per person — the two facts pull opposite ways, tune with both
    # in mind. This is defense-in-depth against casual abuse; the real spend
    # backstop is the OpenAI project cap (set in the dashboard).
    REGISTRATION_ENABLED: bool = True
    RATE_LIMIT_QUERY: str = "60/hour"
    RATE_LIMIT_VISION: str = "20/hour"
    RATE_LIMIT_RESEARCH: str = "10/hour"

    UPLOAD_DIR: str = "uploads"
    MAX_UPLOAD_SIZE_MB: int = 25
    CHUNK_SIZE: int = 1000
    CHUNK_OVERLAP: int = 200
    RAG_TOP_K: int = 5
    RAG_MAX_TOP_K: int = 20
    # If the best (smallest) retrieval distance is beyond this, the query/vision
    # endpoints abstain rather than answer from irrelevant context — cheap
    # insurance against confabulating from far-off chunks.
    RAG_MAX_DISTANCE: float = 0.5
    # How many prior messages feed the follow-up query rewrite. The referent of a
    # follow-up ("the second one", "it") lives in the last turn or two; more
    # history is token cost without disambiguation benefit.
    REWRITE_HISTORY_TURNS: int = 3
    # How many prior messages feed the GENERATION prompt as conversational framing.
    # Separate from REWRITE_HISTORY_TURNS on purpose: the two jobs differ (rewrite
    # needs just the last turn's referent; generation wants enough dialogue to read
    # the user's intent), so coupling them means tuning one silently breaks the
    # other. The query endpoint loads history ONCE at this (larger) limit and the
    # rewrite slices the last REWRITE_HISTORY_TURNS off it, so this must stay >=
    # REWRITE_HISTORY_TURNS (enforced by the validator below).
    MEMORY_HISTORY_TURNS: int = 6
    VISION_MAX_IMAGES: int = 8
    # Images narrower or shorter than this (px) are skipped before the billable
    # caption call: icons, bullets, and decorative rules carry nothing to index.
    VISION_MIN_IMAGE_PX: int = 100

    EMBEDDING_PROVIDER: str = "openai"
    EMBEDDING_MODEL: str = "text-embedding-3-small"
    EMBEDDING_DIMENSIONS: int = 1536
    OPENAI_API_KEY: str = ""

    CHROMA_PERSIST_DIR: str = "chroma"
    CHROMA_COLLECTION: str = "nexus_chunks"
    # Image captions live in their own collection so the text path is untouched.
    CHROMA_IMAGE_COLLECTION: str = "nexus_images"

    LLM_PROVIDER: str = "openai"
    GENERATION_MODEL: str = "gpt-4.1-mini"
    LLM_MODEL: str = "claude-haiku-4-5-20251001"
    LLM_MAX_TOKENS: int = 1024
    ANTHROPIC_API_KEY: str = ""

    # Faithfulness judge. Deliberately a different model family from the
    # generator (GENERATION_MODEL, gpt-4.1-mini): a judge grading its own
    # family's output prefers its own phrasing, which inflates the score. The
    # judge is Gemini for exactly that reason -- a different family from the
    # OpenAI generator. The vendor changed from Anthropic to Google for billing
    # reasons; the design intent (cross-family judge) did not change. Pinned to
    # an exact model string so the faithfulness baseline stays comparable run to
    # run -- a model swap must be a visible diff, not a silent upgrade under an
    # alias. Gemini is reached through its OpenAI-compatible endpoint
    # (JUDGE_BASE_URL) using GEMINI_API_KEY, so no new SDK is needed. The
    # ANTHROPIC_API_KEY + "anthropic" judge path below is kept as an option.
    JUDGE_PROVIDER: str = "gemini"
    JUDGE_MODEL: str = "gemini-2.5-flash"
    JUDGE_BASE_URL: str = "https://generativelanguage.googleapis.com/v1beta/openai"
    GEMINI_API_KEY: str = ""
    # Its own budget, not LLM_MAX_TOKENS: a per-claim verdict is far longer than
    # an answer, and a truncated reply is invalid JSON rather than a short one.
    JUDGE_MAX_TOKENS: int = 2048

    # Web search. Defaults to the offline no-op "null" provider: live search is
    # a billable external call, so Tavily is explicit opt-in (SEARCH_PROVIDER=
    # tavily) and only used when TAVILY_API_KEY is also set.
    SEARCH_PROVIDER: str = "null"
    SEARCH_MAX_RESULTS: int = 5
    TAVILY_API_KEY: str = ""

    # Retrieval eval harness: the dedicated, reproducible corpus is ingested
    # under this local-only account so eval documents never mix with real users.
    EVAL_USER_EMAIL: str = "eval@nexus.local"

    # Public-demo account (scripts/seed_demo.py). Visitors share this login, so
    # these are not secrets — the demo page shows them. Overridable via env.
    DEMO_USER_EMAIL: str = "demo@nexus.ai"
    DEMO_USER_PASSWORD: str = "demo-nexus-public"

    @field_validator("ENVIRONMENT")
    @classmethod
    def _known_environment(cls, v: str) -> str:
        # Fail loud on a typo ("prod" != "production"): prod-gated behaviour keys
        # off this exact string, so a silent mismatch would bypass those guards.
        if v not in _KNOWN_ENVIRONMENTS:
            raise ValueError(
                f"ENVIRONMENT must be one of {sorted(_KNOWN_ENVIRONMENTS)}, got {v!r}"
            )
        return v

    @model_validator(mode="after")
    def _absolutise_state_paths(self) -> Self:
        # Relative state dirs resolve against the process CWD, which differs
        # between `uvicorn` from backend/ and a container WORKDIR. Resolve once at
        # load so the path is unambiguous (and logged as such); idempotent on the
        # absolute /data/* values production sets.
        self.UPLOAD_DIR = os.path.abspath(self.UPLOAD_DIR)
        self.CHROMA_PERSIST_DIR = os.path.abspath(self.CHROMA_PERSIST_DIR)
        return self

    @model_validator(mode="after")
    def _memory_covers_rewrite_history(self) -> Self:
        # The query endpoint loads history once at MEMORY_HISTORY_TURNS and the
        # rewrite slices REWRITE_HISTORY_TURNS off the tail. If memory were the
        # smaller of the two, the rewrite would silently see less history than it
        # is configured for -- a bug nobody would notice. Fail loudly at startup.
        if self.MEMORY_HISTORY_TURNS < self.REWRITE_HISTORY_TURNS:
            raise ValueError(
                "MEMORY_HISTORY_TURNS "
                f"({self.MEMORY_HISTORY_TURNS}) must be >= REWRITE_HISTORY_TURNS "
                f"({self.REWRITE_HISTORY_TURNS}): the query endpoint loads history "
                "once at MEMORY_HISTORY_TURNS and the rewrite slices its tail."
            )
        return self

    @computed_field  # type: ignore[prop-decorator]
    @property
    def database_url(self) -> str:
        # An explicit DATABASE_URL (managed Postgres) wins over the assembled
        # POSTGRES_* URL; otherwise build the async DSN from the parts.
        if self.DATABASE_URL:
            return _normalise_async_dsn(self.DATABASE_URL)
        return (
            f"{_ASYNC_PG_DRIVER}://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]

    @computed_field  # type: ignore[prop-decorator]
    @property
    def max_upload_size_bytes(self) -> int:
        return self.MAX_UPLOAD_SIZE_MB * 1024 * 1024


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
