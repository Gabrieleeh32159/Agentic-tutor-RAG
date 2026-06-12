from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables and `.env`."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    DATABASE_URL: str = (
        "postgresql+asyncpg://challenge:challenge@localhost:5432/challenge_db"
    )

    OPENAI_API_KEY: str = ""
    ANTHROPIC_API_KEY: str = ""

    EMBEDDING_MODEL: str = "text-embedding-3-small"
    CHAT_MODEL: str = "gpt-4o-mini"

    SESSION_TTL_HOURS: int = 24
    CLEANUP_INTERVAL_MINUTES: int = 15
    STALE_PROCESSING_MINUTES: int = 60

    MAX_UPLOAD_BYTES: int = 10 * 1024 * 1024  # 10 MB

    VISION_MODEL: str = "gpt-4o-mini"

    MAX_PDF_PAGES: int = 50
    MAX_OCR_PAGES_PER_DOC: int = 20
    MAX_DOCS_PER_SESSION: int = 20
    MAX_CHUNKS_PER_DOC: int = 500

    CHAT_STREAM_TIMEOUT_SECONDS: int = 120

    FRONTEND_ORIGIN: str = "http://localhost:3000"

    APP_ENV: str = "local"
    LOG_LEVEL: str = "INFO"

    LANGFUSE_PUBLIC_KEY: str = ""
    LANGFUSE_SECRET_KEY: str = ""
    LANGFUSE_HOST: str = "https://cloud.langfuse.com"


@lru_cache
def get_settings() -> Settings:
    return Settings()
