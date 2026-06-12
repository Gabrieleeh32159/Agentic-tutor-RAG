from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIASGIMiddleware
from sqlmodel import SQLModel

from app.chat.models import ChatMessage  # noqa: F401
from app.documents.models import Document, DocumentChunk  # noqa: F401
from app.ingestion.service import shutdown_ingestion
from app.sessions.cleanup import cleanup_loop, reconcile_interrupted_documents
from app.sessions.models import Session  # noqa: F401
from app.shared.config import get_settings
from app.shared.database import (
    close_engine,
    get_engine,
    get_session_factory,
    init_engine,
)
from app.shared.errors import error_envelope, register_exception_handlers
from app.shared.logging import RequestIDMiddleware, setup_logging
from app.shared.rate_limit import limiter


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    setup_logging(settings.LOG_LEVEL)
    init_engine(settings.DATABASE_URL)

    async with get_engine().begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)

    factory = get_session_factory()
    async with factory() as db:
        interrupted = await reconcile_interrupted_documents(db)
        await db.commit()
    if interrupted:
        logging.getLogger(__name__).warning(
            "Marked %d interrupted documents as failed on startup", interrupted
        )

    stop_cleanup = asyncio.Event()
    cleanup_task = asyncio.create_task(cleanup_loop(stop_cleanup))

    try:
        yield
    finally:
        stop_cleanup.set()
        await cleanup_task
        await shutdown_ingestion()
        await close_engine()


app = FastAPI(
    title="Educational Content RAG Service",
    version="0.1.0",
    lifespan=lifespan,
)

app.state.limiter = limiter
app.add_middleware(SlowAPIASGIMiddleware)
app.add_middleware(RequestIDMiddleware)
register_exception_handlers(app)
settings = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.frontend_origins,
    allow_origin_regex=settings.FRONTEND_ORIGIN_REGEX or None,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Request-ID"],
)


@app.exception_handler(RateLimitExceeded)
async def handle_rate_limit(request: Request, exc: RateLimitExceeded) -> JSONResponse:
    return JSONResponse(
        status_code=429,
        content=error_envelope(
            "RATE_LIMITED", f"Rate limit exceeded: {exc.detail}. Try again later."
        ),
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
