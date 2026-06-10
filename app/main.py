from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlmodel import SQLModel

from app.chat.models import ChatMessage, ChatSession  # noqa: F401
from app.documents.models import Document, DocumentChunk  # noqa: F401
from app.shared.config import get_settings
from app.shared.database import close_engine, get_engine, init_engine
from app.shared.logging import RequestIDMiddleware, setup_logging


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    setup_logging(settings.LOG_LEVEL)
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

app.add_middleware(RequestIDMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health", tags=["system"])
async def health() -> dict[str, str]:
    """Liveness probe. The interviewer will use this to verify the service boots."""
    return {"status": "ok"}


from app.chat.router import router as chat_router  # noqa: E402
from app.documents.router import router as documents_router  # noqa: E402
from app.search.router import router as search_router  # noqa: E402

app.include_router(documents_router)
app.include_router(search_router)
app.include_router(chat_router)
