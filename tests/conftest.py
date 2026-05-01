from __future__ import annotations

import hashlib
from collections.abc import AsyncIterator

import httpx
import pytest
from httpx import ASGITransport
from sqlmodel import SQLModel

import app.shared.embeddings as embeddings_module
from app.shared.embeddings import EmbeddingProvider
from app.shared.config import get_settings
from app.shared.database import close_engine, get_engine, init_engine

from app.documents.models import Document  # noqa: F401


EMBEDDING_DIM = 1536


class FakeEmbeddingProvider(EmbeddingProvider):
    """Deterministic fake: hashes the text to produce a consistent vector."""

    def _fake_vector(self, text: str) -> list[float]:
        h = hashlib.sha256(text.encode()).hexdigest()
        base = [int(c, 16) / 15.0 for c in h]
        vector = (base * (EMBEDDING_DIM // len(base) + 1))[:EMBEDDING_DIM]
        norm = sum(x * x for x in vector) ** 0.5
        return [x / norm for x in vector]

    async def embed(self, text: str) -> list[float]:
        return self._fake_vector(text)

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [self._fake_vector(t) for t in texts]


@pytest.fixture(autouse=True)
def mock_embedding_provider() -> None:
    """Replace the real embedding provider with a fake for all tests."""
    fake = FakeEmbeddingProvider()
    embeddings_module._provider = fake
    yield  # type: ignore[misc]
    embeddings_module._provider = None


@pytest.fixture(autouse=True)
async def _init_db() -> AsyncIterator[None]: 
    """Initialize the DB engine and create tables for each test (avoids event-loop mismatch)."""
    settings = get_settings()
    init_engine(settings.DATABASE_URL)
    async with get_engine().begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    yield
    await close_engine()


@pytest.fixture
async def client() -> AsyncIterator[httpx.AsyncClient]:
    """An HTTPX async client wired directly to the FastAPI app (no network)."""
    from app.main import app

    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://testserver"
    ) as c:
        yield c


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"
