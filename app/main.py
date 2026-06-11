from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import update
from sqlmodel import SQLModel

from app.chat.models import ChatMessage  # noqa: F401
from app.documents.models import Document, DocumentChunk, DocumentStatus  # noqa: F401
from app.sessions.models import Session  # noqa: F401
from app.shared.config import get_settings
from app.shared.database import close_engine, get_engine, init_engine
from app.shared.errors import register_exception_handlers
from app.shared.logging import RequestIDMiddleware, setup_logging


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    setup_logging(settings.LOG_LEVEL)
    init_engine(settings.DATABASE_URL)

    async with get_engine().begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)

    # Startup reconciliation: mark rows orphaned by a previous restart as failed.
    # Any document still in pending/processing state when the server comes up
    # was left mid-flight by a crash — it will never complete, so surface it as
    # failed/interrupted so clients aren't stuck polling forever.
    async with get_engine().begin() as conn:
        await conn.execute(
            update(Document)
            .where(
                Document.status.in_([DocumentStatus.PENDING, DocumentStatus.PROCESSING])
            )
            .values(
                status=DocumentStatus.FAILED,
                stage=None,
                error_code="interrupted",
                error_message="Processing was interrupted by a server restart.",
            )
        )

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
register_exception_handlers(app)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Request-ID"],
)


@app.get("/health", tags=["system"])
async def health() -> dict[str, str]:
    """Liveness probe. The interviewer will use this to verify the service boots."""
    return {"status": "ok"}


from app.chat.router import router as chat_router  # noqa: E402
from app.documents.router import router as documents_router  # noqa: E402
from app.search.router import router as search_router  # noqa: E402
from app.sessions.router import router as sessions_router  # noqa: E402

app.include_router(documents_router)
app.include_router(search_router)
app.include_router(chat_router)
app.include_router(sessions_router)
