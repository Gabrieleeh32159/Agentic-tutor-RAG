from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def init_engine(database_url: str) -> None:
    """Initialize the async engine and session factory. Call once at startup."""
    global _engine, _session_factory
    _engine = create_async_engine(database_url, echo=False, future=True)
    _session_factory = async_sessionmaker(
        bind=_engine, expire_on_commit=False, class_=AsyncSession
    )


async def close_engine() -> None:
    global _engine
    if _engine is not None:
        await _engine.dispose()
        _engine = None


def get_engine() -> AsyncEngine:
    if _engine is None:
        raise RuntimeError("Database engine is not initialized.")
    return _engine


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency yielding an `AsyncSession`. Use via `Depends(get_session)`."""
    if _session_factory is None:
        raise RuntimeError(
            "Database engine is not initialized. Call init_engine() first."
        )
    async with _session_factory() as session:
        yield session
