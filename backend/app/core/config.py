"""Application settings, loaded from the environment and validated at startup."""

from functools import lru_cache

from pydantic import computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    ENVIRONMENT: str = "development"
    DEBUG: bool = True
    CORS_ORIGINS: str = "http://localhost:3000"

    POSTGRES_USER: str
    POSTGRES_PASSWORD: str
    POSTGRES_DB: str
    POSTGRES_HOST: str = "db"
    POSTGRES_PORT: int = 5432

    JWT_SECRET_KEY: str
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

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

    @computed_field  # type: ignore[prop-decorator]
    @property
    def database_url(self) -> str:
        return (
            f"postgresql+asyncpg://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
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
