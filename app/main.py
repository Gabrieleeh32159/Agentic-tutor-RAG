from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlmodel import SQLModel

from app.shared.config import get_settings
from app.shared.database import close_engine, get_engine, init_engine

from app.documents.models import Document  # noqa: F401


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    logging.basicConfig(level=settings.LOG_LEVEL.upper())
    init_engine(settings.DATABASE_URL)

    async with get_engine().begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)

    try:
        yield
    finally:
        await close_engine()


app = FastAPI(
    title="Educational Content RAG Service",
    version="0.1.0",
    lifespan=lifespan,
)


@app.get("/health", tags=["system"])
async def health() -> dict[str, str]:
    """Liveness probe. The interviewer will use this to verify the service boots."""
    return {"status": "ok"}


# TODO (candidate):
# Wire your feature routers here, e.g.:
#   from app.documents.router import router as documents_router
#   app.include_router(documents_router)

from app.documents.router import router as documents_router
from app.search.router import router as search_router
from app.chat.router import router as chat_router

app.include_router(documents_router)
app.include_router(search_router)
app.include_router(chat_router)