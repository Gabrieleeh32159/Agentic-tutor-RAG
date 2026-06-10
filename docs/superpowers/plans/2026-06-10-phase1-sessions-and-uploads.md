# Phase 1: Sessions/Workspace Restructure + Text Uploads — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the education-specific text-ingestion API with a session(workspace)-scoped model: clients create a session, upload txt/md files into it, and chat/search only within that session. Adds the error taxonomy and request-ID logging that all later phases build on.

**Architecture:** A new `sessions` table unifies the old `chat_sessions` with the document workspace; `documents`/`document_chunks`/`chat_messages` all cascade from it. `subject`/`level` disappear from every layer (models, search, agent state, prompts, tests). Upload endpoint sets the Phase-2 contract now (202 + status fields) but processes synchronously in Phase 1. Domain errors raise `AppError` subclasses handled centrally into `{"error": {code, message, request_id}}` envelopes.

**Tech Stack:** FastAPI + SQLModel + pgvector (existing), LangGraph agent (existing), no new dependencies in this phase (`python-multipart` ships with `fastapi[standard]`).

**This is plan 1 of 7.** The approved spec is `docs/superpowers/specs/2026-06-10-ask-your-pdfs-design.md`. Later phases: 2 = parser registry + async ingestion + vision OCR, 3 = TTL sweeper + rate limiting + hardening, 4 = guardrails, 5 = Langfuse, 6 = Next.js frontend, 7 = deploy + docs.

**Environment:** Postgres must be running (`docker compose up -d`). Tests drop/recreate all tables. Run everything from the repo root. Tests need no API keys (conftest fakes).

**IMPORTANT — transitional red window:** This is a restructure. `tests/test_chat.py` is EXPECTED to fail from the end of Task 4 until the end of Task 5 (chat still references subject/level until Task 5 reworks it). Do not "fix" that by reverting Task 4. Each task says exactly which suites must be green at its end.

---

### Task 1: Request-ID logging infrastructure

**Files:**
- Create: `app/shared/logging.py`
- Modify: `app/main.py`
- Test: `tests/test_errors.py` (created here, extended in Task 2)

- [ ] **Step 1: Write the failing test**

Create `tests/test_errors.py`:

```python
from __future__ import annotations

import httpx
import pytest


@pytest.mark.asyncio
async def test_responses_carry_request_id_header(client: httpx.AsyncClient) -> None:
    response = await client.get("/health")
    assert response.status_code == 200
    request_id = response.headers.get("x-request-id")
    assert request_id is not None
    assert len(request_id) == 12
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_errors.py -v`
Expected: FAIL — `assert request_id is not None` (no header yet).

- [ ] **Step 3: Implement the logging module**

Create `app/shared/logging.py`:

```python
from __future__ import annotations

import logging
import uuid
from contextvars import ContextVar

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

request_id_var: ContextVar[str] = ContextVar("request_id", default="-")


def get_request_id() -> str:
    return request_id_var.get()


class RequestIDFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get()
        return True


def setup_logging(level: str) -> None:
    handler = logging.StreamHandler()
    handler.addFilter(RequestIDFilter())
    handler.setFormatter(
        logging.Formatter(
            "%(asctime)s %(levelname)s [%(request_id)s] %(name)s: %(message)s"
        )
    )
    root = logging.getLogger()
    root.setLevel(level.upper())
    root.handlers = [handler]


class RequestIDMiddleware:
    """Pure ASGI middleware (safe with SSE streaming, unlike BaseHTTPMiddleware):
    assigns a request id, exposes it via contextvar and the X-Request-ID header."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = uuid.uuid4().hex[:12]
        token = request_id_var.set(request_id)

        async def send_with_header(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                headers["X-Request-ID"] = request_id
            await send(message)

        try:
            await self.app(scope, receive, send_with_header)
        finally:
            request_id_var.reset(token)
```

- [ ] **Step 4: Wire into `app/main.py`**

In `app/main.py`, replace the `logging.basicConfig(...)` line inside `lifespan` and add the middleware. The top of the file becomes:

```python
from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlmodel import SQLModel

from app.shared.config import get_settings
from app.shared.database import close_engine, get_engine, init_engine
from app.shared.logging import RequestIDMiddleware, setup_logging

from app.documents.models import Document, DocumentChunk  # noqa: F401
from app.chat.models import ChatMessage, ChatSession  # noqa: F401


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
```

(The `import logging` at the top of the old file is no longer needed — remove it.)

After the `app = FastAPI(...)` block and **before** the CORS middleware, add:

```python
app.add_middleware(RequestIDMiddleware)
```

Note: middleware added later runs first in Starlette, so adding RequestIDMiddleware before CORS is fine either way — the request id only needs to wrap route handlers.

Also delete the stale `# TODO (candidate):` comment block above the router imports while you're in the file.

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/test_errors.py -v`
Expected: PASS

- [ ] **Step 6: Run the full suite to confirm nothing broke**

Run: `uv run pytest && uv run ruff check .`
Expected: all tests PASS, no lint errors.

- [ ] **Step 7: Commit**

```bash
git add app/shared/logging.py app/main.py tests/test_errors.py
git commit -m "feat: request-id middleware + structured logging"
```

---

### Task 2: Error taxonomy with structured envelope

**Files:**
- Create: `app/shared/errors.py`
- Modify: `app/main.py`
- Test: `tests/test_errors.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_errors.py`:

```python
@pytest.mark.asyncio
async def test_app_error_returns_structured_envelope(client: httpx.AsyncClient) -> None:
    """AppError subclasses must render as {"error": {code, message, request_id}}."""
    from app.main import app
    from app.shared.errors import SessionNotFoundError

    @app.get("/_test/raise-app-error")
    async def _raise() -> None:
        raise SessionNotFoundError("Session abc not found")

    try:
        response = await client.get("/_test/raise-app-error")
    finally:
        app.router.routes = [
            r for r in app.router.routes
            if getattr(r, "path", "") != "/_test/raise-app-error"
        ]

    assert response.status_code == 404
    body = response.json()
    assert body["error"]["code"] == "SESSION_NOT_FOUND"
    assert body["error"]["message"] == "Session abc not found"
    assert body["error"]["request_id"] == response.headers["x-request-id"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_errors.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.shared.errors'` (or ImportError).

- [ ] **Step 3: Implement the error taxonomy**

Create `app/shared/errors.py`:

```python
from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.shared.logging import get_request_id


class AppError(Exception):
    """Base for domain errors that map to a structured HTTP error envelope."""

    code: str = "APP_ERROR"
    status_code: int = 500

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class SessionNotFoundError(AppError):
    code = "SESSION_NOT_FOUND"
    status_code = 404


class SessionExpiredError(AppError):
    code = "SESSION_EXPIRED"
    status_code = 410


class DocumentNotFoundError(AppError):
    code = "DOCUMENT_NOT_FOUND"
    status_code = 404


class UnsupportedFileTypeError(AppError):
    code = "UNSUPPORTED_FILE_TYPE"
    status_code = 415


class FileTooLargeError(AppError):
    code = "FILE_TOO_LARGE"
    status_code = 413


class PageLimitExceededError(AppError):
    code = "PAGE_LIMIT_EXCEEDED"
    status_code = 413


class ParseFailedError(AppError):
    code = "PARSE_FAILED"
    status_code = 422


class GuardrailBlockedError(AppError):
    code = "GUARDRAIL_BLOCKED"
    status_code = 400


class ProviderUnavailableError(AppError):
    code = "PROVIDER_UNAVAILABLE"
    status_code = 503


def error_envelope(code: str, message: str) -> dict:
    return {
        "error": {
            "code": code,
            "message": message,
            "request_id": get_request_id(),
        }
    }


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def handle_app_error(_: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=error_envelope(exc.code, exc.message),
        )
```

(`PageLimitExceededError`, `ParseFailedError`, `GuardrailBlockedError`, `ProviderUnavailableError` are not raised until Phases 2–4 — defining the full taxonomy now keeps later phases additive.)

- [ ] **Step 4: Wire into `app/main.py`**

Add the import near the other `app.shared` imports:

```python
from app.shared.errors import register_exception_handlers
```

And immediately after the `app.add_middleware(RequestIDMiddleware)` line:

```python
register_exception_handlers(app)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/test_errors.py -v`
Expected: PASS (both tests).

- [ ] **Step 6: Commit**

```bash
git add app/shared/errors.py app/main.py tests/test_errors.py
git commit -m "feat: AppError taxonomy with structured error envelope"
```

---

### Task 3: Sessions module (workspace model + CRUD)

**Files:**
- Create: `app/sessions/__init__.py`, `app/sessions/models.py`, `app/sessions/service.py`, `app/sessions/router.py`
- Modify: `app/shared/config.py`, `app/main.py`, `tests/conftest.py`
- Test: `tests/test_sessions.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_sessions.py`:

```python
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from sqlalchemy import update

from app.sessions.models import Session
from app.shared.database import get_session_factory


async def _backdate_session(session_id: str, days: int) -> None:
    """Set last_activity_at into the past, directly in the DB."""
    factory = get_session_factory()
    async with factory() as db:
        await db.execute(
            update(Session)
            .where(Session.id == uuid.UUID(session_id))
            .values(last_activity_at=datetime.now(timezone.utc) - timedelta(days=days))
        )
        await db.commit()


@pytest.mark.asyncio
async def test_create_session(client: httpx.AsyncClient) -> None:
    response = await client.post("/sessions")
    assert response.status_code == 201
    data = response.json()
    uuid.UUID(data["id"])
    assert data["title"] is None
    assert "created_at" in data
    assert "last_activity_at" in data


@pytest.mark.asyncio
async def test_get_session(client: httpx.AsyncClient) -> None:
    created = (await client.post("/sessions")).json()
    response = await client.get(f"/sessions/{created['id']}")
    assert response.status_code == 200
    assert response.json()["id"] == created["id"]


@pytest.mark.asyncio
async def test_get_unknown_session_returns_404_envelope(
    client: httpx.AsyncClient,
) -> None:
    response = await client.get(f"/sessions/{uuid.uuid4()}")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "SESSION_NOT_FOUND"


@pytest.mark.asyncio
async def test_get_expired_session_returns_410(client: httpx.AsyncClient) -> None:
    created = (await client.post("/sessions")).json()
    await _backdate_session(created["id"], days=2)

    response = await client.get(f"/sessions/{created['id']}")
    assert response.status_code == 410
    assert response.json()["error"]["code"] == "SESSION_EXPIRED"


@pytest.mark.asyncio
async def test_get_session_touches_activity(client: httpx.AsyncClient) -> None:
    created = (await client.post("/sessions")).json()
    # Backdate by less than the TTL, then read: activity must move forward.
    await _backdate_session(created["id"], days=0)
    before = (await client.get(f"/sessions/{created['id']}")).json()
    after = (await client.get(f"/sessions/{created['id']}")).json()
    assert after["last_activity_at"] >= before["last_activity_at"]


@pytest.mark.asyncio
async def test_delete_session(client: httpx.AsyncClient) -> None:
    created = (await client.post("/sessions")).json()
    response = await client.delete(f"/sessions/{created['id']}")
    assert response.status_code == 204

    response = await client.get(f"/sessions/{created['id']}")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_delete_unknown_session_returns_404(client: httpx.AsyncClient) -> None:
    response = await client.delete(f"/sessions/{uuid.uuid4()}")
    assert response.status_code == 404
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_sessions.py -v`
Expected: FAIL at collection — `ModuleNotFoundError: No module named 'app.sessions'`.

- [ ] **Step 3: Implement the sessions module**

Create `app/sessions/__init__.py` (empty file).

Create `app/sessions/models.py`:

```python
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from pydantic import BaseModel
from sqlalchemy import Column, DateTime, Text
from sqlmodel import Field, SQLModel


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Session(SQLModel, table=True):
    __tablename__ = "sessions"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    title: str | None = Field(default=None, sa_column=Column(Text, nullable=True))
    created_at: datetime = Field(
        default_factory=utcnow,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    last_activity_at: datetime = Field(
        default_factory=utcnow,
        sa_column=Column(DateTime(timezone=True), nullable=False, index=True),
    )


class SessionResponse(BaseModel):
    id: uuid.UUID
    title: str | None
    created_at: datetime
    last_activity_at: datetime
```

Create `app/sessions/service.py`:

```python
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.sessions.models import Session
from app.shared.config import get_settings
from app.shared.errors import SessionExpiredError, SessionNotFoundError


async def create_session(db: AsyncSession) -> Session:
    session = Session()
    db.add(session)
    await db.commit()
    await db.refresh(session)
    return session


def _is_expired(session: Session) -> bool:
    ttl = timedelta(hours=get_settings().SESSION_TTL_HOURS)
    last = session.last_activity_at
    if last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) - last > ttl


async def get_active_session(db: AsyncSession, session_id: uuid.UUID) -> Session:
    """Return the session or raise SessionNotFoundError / SessionExpiredError."""
    session = await db.get(Session, session_id)
    if session is None:
        raise SessionNotFoundError(f"Session {session_id} not found")
    if _is_expired(session):
        raise SessionExpiredError(f"Session {session_id} has expired")
    return session


async def touch_session(db: AsyncSession, session: Session) -> None:
    session.last_activity_at = datetime.now(timezone.utc)
    db.add(session)
    await db.commit()


async def update_session_title(db: AsyncSession, session: Session, title: str) -> None:
    session.title = title[:120]
    db.add(session)
    await db.commit()


async def delete_session(db: AsyncSession, session_id: uuid.UUID) -> None:
    session = await db.get(Session, session_id)
    if session is None:
        raise SessionNotFoundError(f"Session {session_id} not found")
    await db.delete(session)
    await db.commit()
```

Create `app/sessions/router.py`:

```python
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.sessions import service
from app.sessions.models import SessionResponse
from app.shared.database import get_session

router = APIRouter(prefix="/sessions", tags=["sessions"])


@router.post("", response_model=SessionResponse, status_code=status.HTTP_201_CREATED)
async def create_session(db: AsyncSession = Depends(get_session)) -> SessionResponse:
    session = await service.create_session(db)
    return SessionResponse.model_validate(session, from_attributes=True)


@router.get("/{session_id}", response_model=SessionResponse)
async def get_session_detail(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_session),
) -> SessionResponse:
    session = await service.get_active_session(db, session_id)
    await service.touch_session(db, session)
    return SessionResponse.model_validate(session, from_attributes=True)


@router.delete("/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_session(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_session),
) -> None:
    await service.delete_session(db, session_id)
```

- [ ] **Step 4: Add the TTL setting**

In `app/shared/config.py`, after `CHAT_MODEL: str = "gpt-4o-mini"` add:

```python
    SESSION_TTL_HOURS: int = 24
```

- [ ] **Step 5: Wire into `app/main.py` and `tests/conftest.py`**

In `app/main.py`, add to the model imports at the top (needed so `create_all` sees the table):

```python
from app.sessions.models import Session  # noqa: F401
```

And with the router includes at the bottom:

```python
from app.sessions.router import router as sessions_router

app.include_router(sessions_router)
```

In `tests/conftest.py`, add next to the other model imports:

```python
from app.sessions.models import Session  # noqa: F401
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/test_sessions.py -v`
Expected: PASS (all 7).

- [ ] **Step 7: Full suite + lint**

Run: `uv run pytest && uv run ruff check .`
Expected: all green (this task is purely additive).

- [ ] **Step 8: Commit**

```bash
git add app/sessions/ app/shared/config.py app/main.py tests/conftest.py tests/test_sessions.py
git commit -m "feat: sessions module - workspace model with TTL-aware CRUD"
```

---

### Task 4: Documents rework — session-scoped schema + txt/md upload + search scoping

This is the breaking task: `Document` loses `title/content/subject/level` and gains the session FK + status fields; `POST /documents`(+`/bulk`) are replaced by `POST /sessions/{id}/documents`; `/search` requires `session_id`. **At the end of this task `tests/test_chat.py` is EXPECTED red** (chat still sends subject/level and creates its own ChatSession) — Task 5 fixes it.

**Files:**
- Modify: `app/documents/models.py`, `app/documents/service.py`, `app/documents/router.py`, `app/search/models.py`, `app/search/service.py`, `app/search/router.py`, `app/sessions/models.py`, `app/sessions/router.py`, `app/shared/config.py`
- Test: rewrite `tests/test_documents.py`, rewrite `tests/test_search.py`
- Delete: `scripts/ingest_documents.py`, `data/documents.jsonl`

- [ ] **Step 1: Write the failing document tests**

Replace the entire contents of `tests/test_documents.py` with:

```python
from __future__ import annotations

import uuid

import httpx
import pytest

MD_CONTENT = b"# Calculus Notes\n\nA derivative measures how a function changes as its input changes."


async def _create_session(client: httpx.AsyncClient) -> str:
    response = await client.post("/sessions")
    assert response.status_code == 201
    return response.json()["id"]


def _upload(name: str, content: bytes, mime: str) -> dict:
    return {"file": (name, content, mime)}


@pytest.mark.asyncio
async def test_upload_markdown_document(client: httpx.AsyncClient) -> None:
    sid = await _create_session(client)
    response = await client.post(
        f"/sessions/{sid}/documents",
        files=_upload("notes.md", MD_CONTENT, "text/markdown"),
    )
    assert response.status_code == 202

    data = response.json()
    assert data["filename"] == "notes.md"
    assert data["mime_type"] == "text/markdown"
    assert data["size_bytes"] == len(MD_CONTENT)
    assert data["status"] == "ready"  # Phase 1 processes inline
    assert data["chunk_count"] >= 1
    assert data["error_code"] is None


@pytest.mark.asyncio
async def test_upload_txt_document(client: httpx.AsyncClient) -> None:
    sid = await _create_session(client)
    response = await client.post(
        f"/sessions/{sid}/documents",
        files=_upload("plain.txt", b"Cells contain organelles.", "text/plain"),
    )
    assert response.status_code == 202
    assert response.json()["status"] == "ready"


@pytest.mark.asyncio
async def test_upload_unsupported_type_returns_415(client: httpx.AsyncClient) -> None:
    sid = await _create_session(client)
    response = await client.post(
        f"/sessions/{sid}/documents",
        files=_upload("malware.exe", b"MZ...", "application/octet-stream"),
    )
    assert response.status_code == 415
    assert response.json()["error"]["code"] == "UNSUPPORTED_FILE_TYPE"


@pytest.mark.asyncio
async def test_upload_oversized_file_returns_413(client: httpx.AsyncClient) -> None:
    sid = await _create_session(client)
    big = b"x" * (10 * 1024 * 1024 + 1)
    response = await client.post(
        f"/sessions/{sid}/documents",
        files=_upload("big.txt", big, "text/plain"),
    )
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "FILE_TOO_LARGE"


@pytest.mark.asyncio
async def test_upload_invalid_utf8_returns_422(client: httpx.AsyncClient) -> None:
    sid = await _create_session(client)
    response = await client.post(
        f"/sessions/{sid}/documents",
        files=_upload("binary.txt", b"\xff\xfe\x00\x01", "text/plain"),
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "PARSE_FAILED"


@pytest.mark.asyncio
async def test_upload_to_unknown_session_returns_404(client: httpx.AsyncClient) -> None:
    response = await client.post(
        f"/sessions/{uuid.uuid4()}/documents",
        files=_upload("notes.md", MD_CONTENT, "text/markdown"),
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "SESSION_NOT_FOUND"


@pytest.mark.asyncio
async def test_list_documents(client: httpx.AsyncClient) -> None:
    sid = await _create_session(client)
    await client.post(
        f"/sessions/{sid}/documents",
        files=_upload("notes.md", MD_CONTENT, "text/markdown"),
    )
    response = await client.get(f"/sessions/{sid}/documents")
    assert response.status_code == 200
    docs = response.json()
    assert len(docs) == 1
    assert docs[0]["filename"] == "notes.md"


@pytest.mark.asyncio
async def test_list_documents_is_session_scoped(client: httpx.AsyncClient) -> None:
    sid_a = await _create_session(client)
    sid_b = await _create_session(client)
    await client.post(
        f"/sessions/{sid_a}/documents",
        files=_upload("notes.md", MD_CONTENT, "text/markdown"),
    )
    response = await client.get(f"/sessions/{sid_b}/documents")
    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.asyncio
async def test_delete_document(client: httpx.AsyncClient) -> None:
    sid = await _create_session(client)
    doc = (
        await client.post(
            f"/sessions/{sid}/documents",
            files=_upload("notes.md", MD_CONTENT, "text/markdown"),
        )
    ).json()

    response = await client.delete(f"/sessions/{sid}/documents/{doc['id']}")
    assert response.status_code == 204

    docs = (await client.get(f"/sessions/{sid}/documents")).json()
    assert docs == []


@pytest.mark.asyncio
async def test_delete_document_wrong_session_returns_404(
    client: httpx.AsyncClient,
) -> None:
    sid_a = await _create_session(client)
    sid_b = await _create_session(client)
    doc = (
        await client.post(
            f"/sessions/{sid_a}/documents",
            files=_upload("notes.md", MD_CONTENT, "text/markdown"),
        )
    ).json()

    response = await client.delete(f"/sessions/{sid_b}/documents/{doc['id']}")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "DOCUMENT_NOT_FOUND"


@pytest.mark.asyncio
async def test_session_detail_includes_documents(client: httpx.AsyncClient) -> None:
    sid = await _create_session(client)
    await client.post(
        f"/sessions/{sid}/documents",
        files=_upload("notes.md", MD_CONTENT, "text/markdown"),
    )
    response = await client.get(f"/sessions/{sid}")
    assert response.status_code == 200
    data = response.json()
    assert len(data["documents"]) == 1
    assert data["documents"][0]["filename"] == "notes.md"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_documents.py -v`
Expected: FAIL — 404s on `/sessions/{sid}/documents` (route doesn't exist yet).

- [ ] **Step 3: Rework `app/documents/models.py`**

Replace the entire file with:

```python
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import StrEnum

from pgvector.sqlalchemy import Vector
from pydantic import BaseModel
from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text
from sqlmodel import Field, SQLModel


class DocumentStatus(StrEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"


class Document(SQLModel, table=True):
    __tablename__ = "documents"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    session_id: uuid.UUID = Field(
        sa_column=Column(
            ForeignKey("sessions.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
    )
    filename: str = Field(sa_column=Column(Text, nullable=False))
    mime_type: str = Field(sa_column=Column(String(100), nullable=False))
    size_bytes: int = Field(sa_column=Column(Integer, nullable=False))
    page_count: int | None = Field(default=None)
    chunk_count: int = Field(default=0)
    status: str = Field(
        default=DocumentStatus.PENDING,
        sa_column=Column(String(12), nullable=False),
    )
    stage: str | None = Field(default=None, sa_column=Column(String(12), nullable=True))
    progress: int = Field(default=0)
    error_code: str | None = Field(
        default=None, sa_column=Column(String(40), nullable=True)
    )
    error_message: str | None = Field(
        default=None, sa_column=Column(Text, nullable=True)
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )


class DocumentChunk(SQLModel, table=True):
    __tablename__ = "document_chunks"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    document_id: uuid.UUID = Field(
        sa_column=Column(
            ForeignKey("documents.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
    )
    chunk_index: int = Field(default=0)
    page_number: int | None = Field(default=None)
    chunk_text: str = Field(sa_column=Column(Text, nullable=False))
    embedding: list[float] = Field(
        sa_column=Column(Vector(1536), nullable=False),
    )


class DocumentResponse(BaseModel):
    id: uuid.UUID
    filename: str
    mime_type: str
    size_bytes: int
    page_count: int | None
    chunk_count: int
    status: str
    stage: str | None
    progress: int
    error_code: str | None
    error_message: str | None
    created_at: datetime
```

- [ ] **Step 4: Rework `app/documents/service.py`**

Replace the entire file with:

```python
from __future__ import annotations

import logging
import uuid

from langchain_text_splitters import RecursiveCharacterTextSplitter
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.documents.models import Document, DocumentChunk, DocumentStatus
from app.shared.embeddings import get_embedding_provider
from app.shared.errors import DocumentNotFoundError

logger = logging.getLogger(__name__)

_splitter = RecursiveCharacterTextSplitter(
    separators=["\n\n", "\n", r"(?<=\. )"],
    is_separator_regex=True,
    chunk_size=300,
    chunk_overlap=50,
)


def build_enriched_text(filename: str, chunk: str, page_number: int | None = None) -> str:
    """Text that actually gets embedded: file context + chunk content."""
    location = f" | Page: {page_number}" if page_number is not None else ""
    return f"File: {filename}{location}\nContent: {chunk}"


async def create_pending_document(
    db: AsyncSession,
    *,
    session_id: uuid.UUID,
    filename: str,
    mime_type: str,
    size_bytes: int,
) -> Document:
    document = Document(
        session_id=session_id,
        filename=filename,
        mime_type=mime_type,
        size_bytes=size_bytes,
        status=DocumentStatus.PENDING,
    )
    db.add(document)
    await db.commit()
    await db.refresh(document)
    return document


async def process_text_document(
    db: AsyncSession, document: Document, text: str
) -> Document:
    """Chunk, embed and persist extracted text. Marks the document ready or failed.

    Phase 2 replaces the caller with an async background task; the status
    transitions here are already the final contract.
    """
    try:
        document.status = DocumentStatus.PROCESSING
        document.stage = "embedding"
        db.add(document)
        await db.commit()

        chunks = _splitter.split_text(text)
        enriched = [build_enriched_text(document.filename, c) for c in chunks]
        provider = get_embedding_provider()
        embeddings = await provider.embed_batch(enriched) if enriched else []

        db.add_all(
            [
                DocumentChunk(
                    document_id=document.id,
                    chunk_index=i,
                    chunk_text=chunk,
                    embedding=embedding,
                )
                for i, (chunk, embedding) in enumerate(zip(chunks, embeddings))
            ]
        )
        document.chunk_count = len(chunks)
        document.status = DocumentStatus.READY
        document.stage = None
        document.progress = 100
        db.add(document)
        await db.commit()
    except Exception:
        logger.exception("Failed to process document %s", document.id)
        await db.rollback()
        document.status = DocumentStatus.FAILED
        document.stage = None
        document.error_code = "processing_failed"
        document.error_message = "Failed to process the document."
        db.add(document)
        await db.commit()
    await db.refresh(document)
    return document


async def list_documents(db: AsyncSession, session_id: uuid.UUID) -> list[Document]:
    result = await db.execute(
        select(Document)
        .where(Document.session_id == session_id)
        .order_by(Document.created_at)
    )
    return list(result.scalars().all())


async def delete_document(
    db: AsyncSession, session_id: uuid.UUID, document_id: uuid.UUID
) -> None:
    document = await db.get(Document, document_id)
    if document is None or document.session_id != session_id:
        raise DocumentNotFoundError(f"Document {document_id} not found")
    await db.delete(document)
    await db.commit()
```

- [ ] **Step 5: Rework `app/documents/router.py`**

Replace the entire file with:

```python
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.documents.models import DocumentResponse
from app.documents.service import (
    create_pending_document,
    delete_document,
    list_documents,
    process_text_document,
)
from app.sessions.service import get_active_session, touch_session
from app.shared.config import get_settings
from app.shared.database import get_session
from app.shared.errors import (
    FileTooLargeError,
    ParseFailedError,
    UnsupportedFileTypeError,
)

router = APIRouter(prefix="/sessions/{session_id}/documents", tags=["documents"])

# Phase 1 supports plain-text formats only; Phase 2 adds the parser registry
# (pdf/docx/xlsx/images) behind the same endpoint.
TEXT_EXTENSIONS = {".txt": "text/plain", ".md": "text/markdown"}


def _extension(filename: str) -> str:
    dot = filename.rfind(".")
    return filename[dot:].lower() if dot != -1 else ""


@router.post("", response_model=DocumentResponse, status_code=status.HTTP_202_ACCEPTED)
async def upload_document(
    session_id: uuid.UUID,
    file: UploadFile,
    db: AsyncSession = Depends(get_session),
) -> DocumentResponse:
    session = await get_active_session(db, session_id)

    filename = file.filename or "upload"
    ext = _extension(filename)
    if ext not in TEXT_EXTENSIONS:
        supported = ", ".join(sorted(TEXT_EXTENSIONS))
        raise UnsupportedFileTypeError(
            f"Unsupported file type '{ext or filename}'. Supported: {supported}"
        )

    data = await file.read()
    settings = get_settings()
    if len(data) > settings.MAX_UPLOAD_BYTES:
        limit_mb = settings.MAX_UPLOAD_BYTES // (1024 * 1024)
        raise FileTooLargeError(f"File exceeds the {limit_mb} MB limit")

    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ParseFailedError("File is not valid UTF-8 text") from exc

    document = await create_pending_document(
        db,
        session_id=session_id,
        filename=filename,
        mime_type=TEXT_EXTENSIONS[ext],
        size_bytes=len(data),
    )
    # Phase 1 processes inline; Phase 2 moves this into a background task,
    # which is why the endpoint already returns 202 + status fields.
    document = await process_text_document(db, document, text)
    await touch_session(db, session)
    return DocumentResponse.model_validate(document, from_attributes=True)


@router.get("", response_model=list[DocumentResponse])
async def get_documents(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_session),
) -> list[DocumentResponse]:
    await get_active_session(db, session_id)
    documents = await list_documents(db, session_id)
    return [
        DocumentResponse.model_validate(d, from_attributes=True) for d in documents
    ]


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_document(
    session_id: uuid.UUID,
    document_id: uuid.UUID,
    db: AsyncSession = Depends(get_session),
) -> None:
    await get_active_session(db, session_id)
    await delete_document(db, session_id, document_id)
```

- [ ] **Step 6: Add the upload size setting**

In `app/shared/config.py`, after `SESSION_TTL_HOURS: int = 24` add:

```python
    MAX_UPLOAD_BYTES: int = 10 * 1024 * 1024  # 10 MB
```

- [ ] **Step 7: Session detail includes document summaries**

In `app/sessions/models.py`, add `from app.documents.models import DocumentResponse` with the other imports at the top (safe: `app/documents/models.py` imports nothing from `app/sessions`, so there is no cycle), and define below `SessionResponse`:

```python
class SessionDetailResponse(SessionResponse):
    documents: list[DocumentResponse] = []
```

In `app/sessions/router.py`, change the GET handler to return the detail response:

```python
from app.documents.service import list_documents
from app.sessions.models import SessionDetailResponse, SessionResponse


@router.get("/{session_id}", response_model=SessionDetailResponse)
async def get_session_detail(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_session),
) -> SessionDetailResponse:
    session = await service.get_active_session(db, session_id)
    await service.touch_session(db, session)
    documents = await list_documents(db, session_id)
    return SessionDetailResponse(
        id=session.id,
        title=session.title,
        created_at=session.created_at,
        last_activity_at=session.last_activity_at,
        documents=[
            DocumentResponse.model_validate(d, from_attributes=True)
            for d in documents
        ],
    )
```

(Add `from app.documents.models import DocumentResponse` to the router imports.)

- [ ] **Step 8: Write the failing search tests**

Replace the entire contents of `tests/test_search.py` with:

```python
from __future__ import annotations

import uuid

import httpx
import pytest


async def _create_session(client: httpx.AsyncClient) -> str:
    response = await client.post("/sessions")
    assert response.status_code == 201
    return response.json()["id"]


async def _upload_md(client: httpx.AsyncClient, sid: str, name: str, text: str) -> None:
    response = await client.post(
        f"/sessions/{sid}/documents",
        files={"file": (name, text.encode(), "text/markdown")},
    )
    assert response.status_code == 202
    assert response.json()["status"] == "ready"


@pytest.fixture
async def seeded_session(client: httpx.AsyncClient) -> tuple[httpx.AsyncClient, str]:
    sid = await _create_session(client)
    await _upload_md(
        client, sid, "derivatives.md",
        "A derivative measures how a function changes as its input changes.",
    )
    await _upload_md(
        client, sid, "cells.md",
        "Eukaryotic cells contain membrane-bound organelles.",
    )
    return client, sid


@pytest.mark.asyncio
async def test_search_returns_results(
    seeded_session: tuple[httpx.AsyncClient, str],
) -> None:
    client, sid = seeded_session
    response = await client.get(
        "/search", params={"q": "calculus derivatives", "session_id": sid}
    )
    assert response.status_code == 200

    data = response.json()
    assert len(data) > 0
    result = data[0]
    assert "document_id" in result
    assert "filename" in result
    assert "score" in result
    assert "chunks" in result
    assert len(result["chunks"]) > 0
    chunk = result["chunks"][0]
    assert "chunk_id" in chunk
    assert "chunk_text" in chunk
    assert "score" in chunk


@pytest.mark.asyncio
async def test_search_is_session_scoped(
    seeded_session: tuple[httpx.AsyncClient, str],
) -> None:
    client, _ = seeded_session
    other_sid = await _create_session(client)
    response = await client.get(
        "/search", params={"q": "derivatives", "session_id": other_sid}
    )
    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.asyncio
async def test_search_respects_limit(
    seeded_session: tuple[httpx.AsyncClient, str],
) -> None:
    client, sid = seeded_session
    response = await client.get(
        "/search", params={"q": "science", "session_id": sid, "limit": 1}
    )
    assert response.status_code == 200
    assert len(response.json()) <= 1


@pytest.mark.asyncio
async def test_search_requires_session_id(
    seeded_session: tuple[httpx.AsyncClient, str],
) -> None:
    client, _ = seeded_session
    response = await client.get("/search", params={"q": "math"})
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_search_missing_query(
    seeded_session: tuple[httpx.AsyncClient, str],
) -> None:
    client, sid = seeded_session
    response = await client.get("/search", params={"session_id": sid})
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_search_limit_too_high(
    seeded_session: tuple[httpx.AsyncClient, str],
) -> None:
    client, sid = seeded_session
    response = await client.get(
        "/search", params={"q": "math", "session_id": sid, "limit": 50}
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_search_results_have_score(
    seeded_session: tuple[httpx.AsyncClient, str],
) -> None:
    client, sid = seeded_session
    response = await client.get(
        "/search", params={"q": "derivative", "session_id": sid}
    )
    assert response.status_code == 200
    for result in response.json():
        assert isinstance(result["score"], float)
        assert 0 <= result["score"] <= 1


@pytest.mark.asyncio
async def test_search_unknown_session_returns_empty(
    seeded_session: tuple[httpx.AsyncClient, str],
) -> None:
    """Searching a non-existent session id is not an error - just no results."""
    client, _ = seeded_session
    response = await client.get(
        "/search", params={"q": "derivative", "session_id": str(uuid.uuid4())}
    )
    assert response.status_code == 200
    assert response.json() == []
```

- [ ] **Step 9: Rework the search module**

Replace `app/search/models.py` with:

```python
from __future__ import annotations

import uuid

from sqlmodel import SQLModel


class SearchChunk(SQLModel):
    chunk_id: uuid.UUID
    chunk_text: str
    score: float


class SearchResult(SQLModel):
    document_id: uuid.UUID
    filename: str
    score: float
    chunks: list[SearchChunk]
```

Replace `app/search/service.py` with:

```python
from __future__ import annotations

import uuid
from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.documents.models import Document, DocumentChunk, DocumentStatus
from app.search.models import SearchChunk, SearchResult
from app.shared.embeddings import get_embedding_provider


async def search_documents(
    session: AsyncSession,
    query: str,
    session_id: uuid.UUID,
    limit: int = 5,
) -> list[SearchResult]:
    provider = get_embedding_provider()
    query_embedding = await provider.embed(query)

    distance = DocumentChunk.embedding.cosine_distance(query_embedding)
    score_expr = (1 - distance).label("score")

    stmt = (
        select(
            DocumentChunk.id.label("chunk_id"),
            DocumentChunk.document_id,
            DocumentChunk.chunk_text,
            Document.filename,
            score_expr,
        )
        .join(Document, DocumentChunk.document_id == Document.id)
        .where(Document.session_id == session_id)
        .where(Document.status == DocumentStatus.READY)
        .order_by(distance)
        .limit(limit * 3)
    )

    result = await session.execute(stmt)
    rows = result.all()

    # Group chunk hits back into per-document results
    doc_map: dict[str, dict] = {}
    doc_chunks: defaultdict[str, list[SearchChunk]] = defaultdict(list)

    for row in rows:
        doc_id = str(row.document_id)
        chunk_score = round(row.score, 4)

        doc_chunks[doc_id].append(
            SearchChunk(
                chunk_id=row.chunk_id,
                chunk_text=row.chunk_text,
                score=chunk_score,
            )
        )

        if doc_id not in doc_map or chunk_score > doc_map[doc_id]["score"]:
            doc_map[doc_id] = {
                "document_id": row.document_id,
                "filename": row.filename,
                "score": chunk_score,
            }

    sorted_docs = sorted(doc_map.values(), key=lambda d: d["score"], reverse=True)[
        :limit
    ]

    return [
        SearchResult(
            **doc,
            chunks=sorted(
                doc_chunks[str(doc["document_id"])],
                key=lambda c: c.score,
                reverse=True,
            ),
        )
        for doc in sorted_docs
    ]
```

Replace `app/search/router.py` with:

```python
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.search.models import SearchResult
from app.search.service import search_documents
from app.shared.database import get_session

router = APIRouter(prefix="/search", tags=["search"])


@router.get("", response_model=list[SearchResult])
async def search(
    q: str = Query(..., min_length=1),
    session_id: uuid.UUID = Query(...),
    limit: int = Query(5, ge=1, le=20),
    session: AsyncSession = Depends(get_session),
) -> list[SearchResult]:
    return await search_documents(
        session=session,
        query=q,
        session_id=session_id,
        limit=limit,
    )
```

- [ ] **Step 10: Delete the obsolete bulk-ingest tooling**

```bash
git rm scripts/ingest_documents.py data/documents.jsonl
```

(If `data/` is then empty, that's fine — git tracks no empty dirs.)

- [ ] **Step 11: Run document + search tests**

Run: `uv run pytest tests/test_documents.py tests/test_search.py tests/test_sessions.py tests/test_errors.py tests/test_health.py -v`
Expected: ALL PASS.

Run: `uv run pytest tests/test_chat.py -v`
Expected: FAIL (chat not yet reworked — this is the planned red window; Task 5 fixes it).

Run: `uv run ruff check .`
Expected: clean.

- [ ] **Step 12: Commit**

```bash
git add -A
git commit -m "feat!: session-scoped documents with multipart upload; search requires session_id

BREAKING: removes POST /documents(+/bulk), subject/level fields, and the
bulk-ingest script. test_chat.py is red until the chat rework lands (next commit)."
```

---

### Task 5: Chat rework — session-bound agent, routes moved, subject/level gone

**Files:**
- Modify: `app/chat/models.py`, `app/chat/repository.py`, `app/chat/service.py`, `app/chat/tools.py`, `app/chat/prompts.py`, `app/chat/router.py`, `app/sessions/router.py`, `app/main.py`, `tests/conftest.py`
- Test: rewrite `tests/test_chat.py`

- [ ] **Step 1: Write the failing tests**

Replace the entire contents of `tests/test_chat.py` with:

```python
from __future__ import annotations

import json
import uuid

import httpx
import pytest

MD_DERIVATIVES = b"A derivative measures how a function changes as its input changes."
MD_CELLS = b"Eukaryotic cells contain membrane-bound organelles."


async def _create_session(client: httpx.AsyncClient) -> str:
    response = await client.post("/sessions")
    assert response.status_code == 201
    return response.json()["id"]


@pytest.fixture
async def chat_session(client: httpx.AsyncClient) -> tuple[httpx.AsyncClient, str]:
    """A session seeded with two ready documents."""
    sid = await _create_session(client)
    for name, content in [("derivatives.md", MD_DERIVATIVES), ("cells.md", MD_CELLS)]:
        response = await client.post(
            f"/sessions/{sid}/documents",
            files={"file": (name, content, "text/markdown")},
        )
        assert response.status_code == 202
    return client, sid


def _parse_sse(body: str) -> list[str]:
    return [line for line in body.split("\n") if line.startswith("data: ")]


def _collect_tokens(lines: list[str]) -> str:
    tokens: list[str] = []
    for line in lines:
        data = line.removeprefix("data: ")
        if data == "[DONE]":
            break
        parsed = json.loads(data)
        if "token" in parsed:
            tokens.append(parsed["token"])
    return "".join(tokens)


# ---------------------------------------------------------------------------
# Academic questions (tool calling path)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_returns_streaming_response(
    chat_session: tuple[httpx.AsyncClient, str],
) -> None:
    client, sid = chat_session
    response = await client.post(
        "/chat", json={"question": "What is a derivative?", "session_id": sid}
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")


@pytest.mark.asyncio
async def test_chat_stream_contains_session_id(
    chat_session: tuple[httpx.AsyncClient, str],
) -> None:
    client, sid = chat_session
    response = await client.post(
        "/chat", json={"question": "What is a derivative?", "session_id": sid}
    )
    lines = _parse_sse(response.text)
    first = json.loads(lines[0].removeprefix("data: "))
    assert first["session_id"] == sid


@pytest.mark.asyncio
async def test_chat_stream_contains_sources_with_filename(
    chat_session: tuple[httpx.AsyncClient, str],
) -> None:
    client, sid = chat_session
    response = await client.post(
        "/chat", json={"question": "What is a derivative?", "session_id": sid}
    )
    lines = _parse_sse(response.text)
    sources_lines = [ln for ln in lines if '"sources"' in ln]
    assert len(sources_lines) > 0
    parsed = json.loads(sources_lines[0].removeprefix("data: "))
    assert len(parsed["sources"]) > 0
    src = parsed["sources"][0]
    assert "document_id" in src
    assert "filename" in src
    assert "score" in src


@pytest.mark.asyncio
async def test_chat_stream_full_answer_and_done(
    chat_session: tuple[httpx.AsyncClient, str],
) -> None:
    client, sid = chat_session
    response = await client.post(
        "/chat", json={"question": "What is a derivative?", "session_id": sid}
    )
    lines = _parse_sse(response.text)
    assert _collect_tokens(lines) == "This is a test answer."
    assert lines[-1] == "data: [DONE]"


@pytest.mark.asyncio
async def test_chat_only_searches_own_session(
    chat_session: tuple[httpx.AsyncClient, str],
) -> None:
    """A fresh session with no documents must not see the seeded docs."""
    client, _ = chat_session
    empty_sid = await _create_session(client)
    response = await client.post(
        "/chat", json={"question": "What is a derivative?", "session_id": empty_sid}
    )
    assert response.status_code == 200
    lines = _parse_sse(response.text)
    sources_lines = [ln for ln in lines if '"sources"' in ln]
    for line in sources_lines:
        parsed = json.loads(line.removeprefix("data: "))
        assert parsed["sources"] == []


# ---------------------------------------------------------------------------
# Casual questions (no tool calling)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_casual_no_search(client: httpx.AsyncClient) -> None:
    sid = await _create_session(client)
    response = await client.post("/chat", json={"question": "Hola", "session_id": sid})
    assert response.status_code == 200
    lines = _parse_sse(response.text)
    assert [ln for ln in lines if '"sources"' in ln] == []
    assert len(_collect_tokens(lines)) > 0
    assert lines[-1] == "data: [DONE]"


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_messages_persisted(
    chat_session: tuple[httpx.AsyncClient, str],
) -> None:
    client, sid = chat_session
    await client.post(
        "/chat", json={"question": "What is a derivative?", "session_id": sid}
    )

    response = await client.get(f"/sessions/{sid}/messages")
    assert response.status_code == 200
    messages = response.json()
    assert len(messages) >= 2
    assert messages[0]["role"] == "human"
    assert messages[0]["content"] == "What is a derivative?"
    ai_messages = [m for m in messages if m["role"] == "ai" and m["content"]]
    assert len(ai_messages) >= 1


@pytest.mark.asyncio
async def test_chat_tool_messages_persisted(
    chat_session: tuple[httpx.AsyncClient, str],
) -> None:
    client, sid = chat_session
    await client.post(
        "/chat", json={"question": "What is a derivative?", "session_id": sid}
    )

    messages = (await client.get(f"/sessions/{sid}/messages")).json()
    roles = [m["role"] for m in messages]
    assert "tool" in roles, f"ToolMessages not persisted. Roles: {roles}"
    ai_with_tools = [m for m in messages if m["role"] == "ai" and m.get("tool_calls")]
    assert len(ai_with_tools) >= 1


@pytest.mark.asyncio
async def test_chat_multiturn_with_tools(
    chat_session: tuple[httpx.AsyncClient, str],
) -> None:
    client, sid = chat_session
    r1 = await client.post(
        "/chat", json={"question": "What is a derivative?", "session_id": sid}
    )
    assert r1.status_code == 200

    r2 = await client.post("/chat", json={"question": "Thanks!", "session_id": sid})
    assert r2.status_code == 200
    lines = _parse_sse(r2.text)
    assert [ln for ln in lines if '"error"' in ln] == []
    assert lines[-1] == "data: [DONE]"


@pytest.mark.asyncio
async def test_chat_sets_session_title(
    chat_session: tuple[httpx.AsyncClient, str],
) -> None:
    client, sid = chat_session
    await client.post(
        "/chat", json={"question": "What is a derivative?", "session_id": sid}
    )
    detail = (await client.get(f"/sessions/{sid}")).json()
    assert detail["title"] == "What is a derivative?"


# ---------------------------------------------------------------------------
# Validation & session binding
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_requires_session_id(client: httpx.AsyncClient) -> None:
    response = await client.post("/chat", json={"question": "Hello"})
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_chat_unknown_session_returns_404(client: httpx.AsyncClient) -> None:
    response = await client.post(
        "/chat", json={"question": "Hello", "session_id": str(uuid.uuid4())}
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "SESSION_NOT_FOUND"


@pytest.mark.asyncio
async def test_chat_missing_question(client: httpx.AsyncClient) -> None:
    sid = await _create_session(client)
    response = await client.post("/chat", json={"session_id": sid})
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_chat_empty_question(client: httpx.AsyncClient) -> None:
    sid = await _create_session(client)
    response = await client.post("/chat", json={"question": "", "session_id": sid})
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_messages_endpoint_unknown_session(client: httpx.AsyncClient) -> None:
    response = await client.get(f"/sessions/{uuid.uuid4()}/messages")
    assert response.status_code == 404
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_chat.py -v`
Expected: FAIL (422s become 404s, `/sessions/{sid}/messages` missing, etc.).

- [ ] **Step 3: Rework `app/chat/models.py`**

Replace the entire file with (ChatSession deleted; messages FK now → `sessions`; AgentState carries `session_id`):

```python
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import StrEnum
from typing import Annotated, TypedDict

from langgraph.graph import add_messages
from pydantic import BaseModel, Field
from sqlalchemy import Column, DateTime, ForeignKey, Index, String, Text
from sqlmodel import Field as SQLField
from sqlmodel import SQLModel


class NodeName(StrEnum):
    AGENT = "agent"
    TOOLS = "tools"


# ---------------------------------------------------------------------------
# DB tables
# ---------------------------------------------------------------------------


class ChatMessage(SQLModel, table=True):
    __tablename__ = "chat_messages"
    __table_args__ = (
        Index("ix_chat_messages_session_created", "session_id", "created_at"),
    )

    id: uuid.UUID = SQLField(default_factory=uuid.uuid4, primary_key=True)
    session_id: uuid.UUID = SQLField(
        sa_column=Column(
            ForeignKey("sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
    )
    role: str = SQLField(sa_column=Column(String(10), nullable=False))
    content: str = SQLField(sa_column=Column(Text, nullable=False, server_default=""))
    tool_calls: str | None = SQLField(
        default=None, sa_column=Column(Text, nullable=True)
    )
    tool_call_id: str | None = SQLField(
        default=None, sa_column=Column(String(64), nullable=True)
    )
    created_at: datetime = SQLField(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )


# ---------------------------------------------------------------------------
# API request / response schemas
# ---------------------------------------------------------------------------


class ChatRequest(BaseModel):
    question: str = Field(min_length=1, max_length=4000)
    session_id: uuid.UUID


class ChatMessageResponse(BaseModel):
    id: uuid.UUID
    role: str
    content: str
    tool_calls: str | None = None
    tool_call_id: str | None = None
    created_at: datetime


# ---------------------------------------------------------------------------
# LangGraph agent state
# ---------------------------------------------------------------------------


class AgentState(TypedDict, total=False):
    """Agent state: conversation messages plus the session scope for retrieval."""

    messages: Annotated[list, add_messages]
    session_id: str
```

- [ ] **Step 4: Trim `app/chat/repository.py`**

Remove the session CRUD functions (`create_session`, `get_session_by_id`, `update_session_title`, `list_sessions`, `delete_session`) — they live in `app/sessions/service.py` now. The file keeps only message persistence. Replace the entire file with:

```python
from __future__ import annotations

import json
import uuid

from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.chat.models import ChatMessage


async def load_session_messages(
    session: AsyncSession,
    session_id: uuid.UUID,
) -> list[BaseMessage]:
    result = await session.execute(
        select(ChatMessage)
        .where(ChatMessage.session_id == session_id)
        .order_by(ChatMessage.created_at)
    )
    rows = result.scalars().all()
    messages: list[BaseMessage] = []
    for row in rows:
        if row.role == "human":
            messages.append(HumanMessage(content=row.content))
        elif row.role == "ai":
            tc = json.loads(row.tool_calls) if row.tool_calls else []
            messages.append(AIMessage(content=row.content, tool_calls=tc))
        elif row.role == "tool":
            messages.append(
                ToolMessage(content=row.content, tool_call_id=row.tool_call_id or "")
            )
        elif row.role == "system":
            messages.append(SystemMessage(content=row.content))
    return messages


async def save_messages(
    session: AsyncSession,
    session_id: uuid.UUID,
    messages: list[BaseMessage],
) -> None:
    for msg in messages:
        if isinstance(msg, HumanMessage):
            role = "human"
        elif isinstance(msg, ToolMessage):
            role = "tool"
        elif isinstance(msg, AIMessage):
            role = "ai"
        elif isinstance(msg, SystemMessage):
            role = "system"
        else:
            role = msg.type
        content = (
            msg.content if isinstance(msg.content, str) else json.dumps(msg.content)
        )
        tool_calls_json: str | None = None
        tool_call_id: str | None = None

        if isinstance(msg, AIMessage) and msg.tool_calls:
            tool_calls_json = json.dumps(msg.tool_calls)
        if isinstance(msg, ToolMessage):
            tool_call_id = msg.tool_call_id

        row = ChatMessage(
            session_id=session_id,
            role=role,
            content=content,
            tool_calls=tool_calls_json,
            tool_call_id=tool_call_id,
        )
        session.add(row)
    await session.commit()


async def get_session_messages(
    session: AsyncSession,
    session_id: uuid.UUID,
) -> list[ChatMessage]:
    result = await session.execute(
        select(ChatMessage)
        .where(ChatMessage.session_id == session_id)
        .order_by(ChatMessage.created_at)
    )
    return list(result.scalars().all())
```

- [ ] **Step 5: Update `app/chat/service.py` re-exports**

Replace the import-from-repository block and `__all__` (lines 14–41 of the current file) with:

```python
from app.chat.repository import (
    get_session_messages,
    load_session_messages,
    save_messages,
)
from app.chat.tools import make_search_tool
from app.shared.llm import get_chat_model

logger = logging.getLogger(__name__)

__all__ = [
    "SYSTEM_PROMPT",
    "build_graph",
    "get_session_messages",
    "load_session_messages",
    "save_messages",
]
```

Everything from `# Agent graph` down (`_make_agent_node`, `build_graph`) is unchanged.

- [ ] **Step 6: Update `app/chat/tools.py`**

Replace the `subject`/`level` injected parameters with `session_id`, and reference `filename` instead of `title`. The changed parts:

`_format_results` becomes:

```python
def _format_results(results: list[SearchResult]) -> str:
    """Format search results into a text block for the LLM."""
    parts: list[str] = []
    idx = 1
    for doc in results:
        for chunk in doc.chunks:
            parts.append(f"[{idx}] File: {doc.filename}\n{chunk.chunk_text}")
            idx += 1
    return "\n\n".join(parts) if parts else "No results found."
```

The tool signature and search params become:

```python
    @tool
    async def search_documents(
        query: str,
        session_id: Annotated[str, InjectedState("session_id")],
        config: RunnableConfig | None = None,
    ) -> str:
        """Search the user's uploaded documents for content relevant to their question. Use this tool whenever the user asks about the content of their documents or any factual/knowledge question."""
        current_query = query

        for attempt in range(MAX_RETRIES + 1):
            # --- 1. Search ---
            params: dict[str, str | int] = {
                "q": current_query,
                "limit": CONTEXT_LIMIT,
                "session_id": session_id,
            }

            response = await http_client.get("/search", params=params)
            response.raise_for_status()
            results = [SearchResult.model_validate(item) for item in response.json()]
```

And the `sources` payload built from results becomes:

```python
            sources = [
                {
                    "document_id": str(doc.document_id),
                    "filename": doc.filename,
                    "score": doc.score,
                    "chunks": [
                        {
                            "chunk_id": str(c.chunk_id),
                            "chunk_text": c.chunk_text,
                            "score": c.score,
                        }
                        for c in doc.chunks
                    ],
                }
                for doc in results
            ]
```

The grading / rewrite / custom-event logic below is unchanged.

- [ ] **Step 7: Update `app/chat/prompts.py`**

Replace `SYSTEM_PROMPT`, `GRADER_PROMPT`, and `REWRITE_PROMPT` with (constants below them unchanged):

```python
SYSTEM_PROMPT = (
    "You are a friendly and helpful AI assistant that answers questions about "
    "the documents the user has uploaded to this session.\n\n"
    "## Conversation\n"
    "- For greetings, casual chat, follow-up questions, or clarifications, "
    "respond naturally and warmly WITHOUT using the search tool.\n"
    "- When continuing a conversation, consider the previous context.\n\n"
    "## Document questions\n"
    "- Use the search_documents tool for questions about the content of the "
    "user's documents, or any factual/knowledge-based question.\n"
    "- Base your answer on the retrieved content. Cite sources inline using "
    "[filename] format, e.g. 'According to [report.pdf], revenue grew 12%.'\n"
    "- If no relevant content is found in the documents, say so honestly.\n\n"
    "## Format\n"
    "- ALWAYS respond in well-structured Markdown.\n"
    "- Use headers (##, ###), bold, bullet points, and numbered lists to organize content.\n"
    "- For math equations, ALWAYS use LaTeX wrapped in dollar signs: "
    "inline math with $...$ and block math with $$...$$.\n"
    "  Example: 'The derivative is $f'(x) = 2x$' or a block:\n"
    "  $$\\frac{dy}{dx} = f'(g(x)) \\cdot g'(x)$$\n"
    "- Never write raw LaTeX without dollar sign delimiters."
)

GRADER_PROMPT = (
    "You are a relevance grader. Given a user question and excerpts retrieved "
    "from their uploaded documents, determine if the excerpts contain information "
    "relevant to the question. Be lenient: if the excerpts are even partially "
    "related or provide useful context, respond 'yes'. Only respond 'no' if they "
    "are completely unrelated. Respond with exactly 'yes' or 'no'."
)

REWRITE_PROMPT = (
    "You are a query rewriter for a document search engine. "
    "The original query did not return relevant results. "
    "Rewrite it using synonyms, broader/narrower terms, or alternative phrasing "
    "to improve retrieval. Keep the same intent. "
    "Return only the rewritten question, nothing else."
)
```

- [ ] **Step 8: Rework `app/chat/router.py`**

Replace the entire file with (session CRUD endpoints removed — they live in the sessions router; `event_stream` body is unchanged except where noted):

```python
from __future__ import annotations

import json
import logging

import httpx
from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from httpx import ASGITransport
from langchain_core.messages import HumanMessage, SystemMessage
from sqlalchemy.ext.asyncio import AsyncSession

from app.chat.models import ChatRequest, NodeName
from app.chat.service import (
    SYSTEM_PROMPT,
    build_graph,
    load_session_messages,
    save_messages,
)
from app.sessions.service import (
    get_active_session,
    touch_session,
    update_session_title,
)
from app.shared.database import get_session, get_session_factory

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/chat", tags=["chat"])


@router.post("")
async def chat(
    body: ChatRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> StreamingResponse:
    # --- Session binding (raises 404/410 via AppError handlers) ---
    chat_session = await get_active_session(session, body.session_id)
    session_id = chat_session.id

    # --- Load history + build state ---
    history = await load_session_messages(session, session_id)
    user_msg = HumanMessage(content=body.question)
    all_messages = [SystemMessage(content=SYSTEM_PROMPT)] + history + [user_msg]

    initial_state = {
        "messages": all_messages,
        "session_id": str(session_id),
    }

    # --- Auto-title on first message + activity touch ---
    if chat_session.title is None:
        await update_session_title(session, chat_session, body.question)
    await touch_session(session, chat_session)

    async def event_stream():
        transport = ASGITransport(app=request.app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://internal"
        ) as http_client:
            graph = build_graph(http_client)

            # Emit session_id first
            yield f"data: {json.dumps({'session_id': str(session_id)})}\n\n"

            new_messages: list = []

            try:
                async for event in graph.astream_events(initial_state, version="v2"):
                    kind = event["event"]

                    # --- Custom events from search tool ---
                    if kind == "on_custom_event":
                        name = event.get("name", "")

                        if name == "search_results":
                            data = event["data"]
                            sources = data.get("sources", [])
                            query = data.get("query", "")
                            attempt = data.get("attempt", 0)
                            yield f"data: {json.dumps({'step': 'retrieve', 'detail': f'Search attempt {attempt}: found {len(sources)} documents for \"{query}\"'})}\n\n"
                            yield f"data: {json.dumps({'sources': sources})}\n\n"

                        elif name == "grade_result":
                            data = event["data"]
                            is_relevant = data.get("is_relevant", False)
                            grade_query = data.get("query", "")
                            relevance_text = "relevant" if is_relevant else "not relevant"
                            yield f"data: {json.dumps({'step': 'grade_documents', 'is_relevant': is_relevant, 'query': grade_query, 'detail': f'Results for \"{grade_query}\" are {relevance_text}'})}\n\n"

                        elif name == "query_rewrite":
                            data = event["data"]
                            new_query = data.get("new_query", "")
                            attempt = data.get("attempt", 0)
                            yield f"data: {json.dumps({'step': 'rewrite_query', 'retry': attempt, 'new_question': new_query, 'detail': f'Rewriting query (attempt {attempt}): {new_query}'})}\n\n"

                    # --- Stream tokens from agent LLM ---
                    if kind == "on_chat_model_stream" and "agent_llm" in event.get("tags", []):
                        chunk = event["data"]["chunk"]
                        token = (
                            chunk.content
                            if hasattr(chunk, "content")
                            else str(chunk)
                        )
                        if token:
                            yield f"data: {json.dumps({'token': token})}\n\n"

                    # --- Capture messages from agent and tools for persistence ---
                    if kind == "on_chain_end" and event.get("name") in (
                        NodeName.AGENT,
                        NodeName.TOOLS,
                    ):
                        output = event["data"].get("output", {})
                        msgs = output.get("messages", [])
                        new_messages.extend(msgs)

            except Exception as exc:
                logger.exception("Chat streaming failed")
                yield f"data: {json.dumps({'error': str(exc)})}\n\n"

            # --- Persist new messages BEFORE yielding [DONE] ---
            # (After the last yield, the client may disconnect and cancel the generator)
            try:
                async with get_session_factory()() as db:
                    msgs_to_save = [user_msg] + new_messages
                    await save_messages(db, session_id, msgs_to_save)
            except Exception:
                logger.exception("Failed to save messages")

            yield "data: [DONE]\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
    )
```

(Note: the `query_rewrite` handler reads `data.get("attempt", 0)` — the tool dispatches the key `attempt`, matching the existing behavior.)

- [ ] **Step 9: Add the messages endpoint to the sessions router**

In `app/sessions/router.py`, add the imports:

```python
from app.chat.models import ChatMessageResponse
from app.chat.repository import get_session_messages
```

And the endpoint:

```python
@router.get("/{session_id}/messages", response_model=list[ChatMessageResponse])
async def get_messages(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_session),
) -> list[ChatMessageResponse]:
    session = await service.get_active_session(db, session_id)
    await service.touch_session(db, session)
    messages = await get_session_messages(db, session_id)
    return [
        ChatMessageResponse(
            id=m.id,
            role=m.role,
            content=m.content,
            tool_calls=m.tool_calls,
            tool_call_id=m.tool_call_id,
            created_at=m.created_at,
        )
        for m in messages
    ]
```

- [ ] **Step 10: Update model imports in `app/main.py` and `tests/conftest.py`**

In `app/main.py`, the model import block becomes:

```python
from app.documents.models import Document, DocumentChunk  # noqa: F401
from app.sessions.models import Session  # noqa: F401
from app.chat.models import ChatMessage  # noqa: F401
```

In `tests/conftest.py`, the model import block becomes:

```python
from app.documents.models import Document, DocumentChunk  # noqa: F401
from app.sessions.models import Session  # noqa: F401
from app.chat.models import ChatMessage  # noqa: F401
```

(`ChatSession` no longer exists — both files previously imported it.)

- [ ] **Step 11: Run the full suite**

Run: `uv run pytest -v`
Expected: ALL PASS — including the previously-red `tests/test_chat.py`.

Run: `uv run ruff check . && uv run ruff format --check .`
Expected: clean. If `ruff format --check` flags files you touched, run `uv run ruff format <those files>` and re-run tests.

- [ ] **Step 12: Commit**

```bash
git add -A
git commit -m "feat!: chat bound to workspace sessions; subject/level removed everywhere

BREAKING: POST /chat requires session_id; /chat/sessions* endpoints replaced
by /sessions/{id}(/messages). Agent tool now session-scopes retrieval."
```

---

### Task 6: Dev tooling — reset script + Streamlit dev tool rewrite

**Files:**
- Create: `scripts/reset_db.py`
- Modify: `scripts/streamlit_app.py` (full rewrite), `CLAUDE.md` (commands section only)

- [ ] **Step 1: Create `scripts/reset_db.py`**

```python
"""Drop and recreate all tables. DESTRUCTIVE - wipes all data.

Used for the schema cutover on environments where tables already exist
(create_all never alters existing tables). Run once per environment:

    uv run python scripts/reset_db.py
"""

from __future__ import annotations

import asyncio

from sqlmodel import SQLModel

from app.chat.models import ChatMessage  # noqa: F401
from app.documents.models import Document, DocumentChunk  # noqa: F401
from app.sessions.models import Session  # noqa: F401
from app.shared.config import get_settings
from app.shared.database import close_engine, get_engine, init_engine


async def main() -> None:
    settings = get_settings()
    init_engine(settings.DATABASE_URL)
    async with get_engine().begin() as conn:
        await conn.run_sync(SQLModel.metadata.drop_all)
        await conn.run_sync(SQLModel.metadata.create_all)
    await close_engine()
    print("Database schema reset.")


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 2: Verify it runs against local Postgres**

Run: `docker compose up -d && uv run python scripts/reset_db.py`
Expected output: `Database schema reset.`

- [ ] **Step 3: Rewrite the Streamlit dev tool**

Replace the entire contents of `scripts/streamlit_app.py` with:

```python
"""Internal dev tool: exercises the session + upload + chat SSE API.

The real user-facing UI is the Next.js app in /web (Phase 6).
Run with:
    uv run streamlit run scripts/streamlit_app.py
"""

from __future__ import annotations

import json

import httpx
import streamlit as st

API_URL = "http://localhost:8000"

st.set_page_config(page_title="Ask your PDFs (dev)", page_icon="📄", layout="wide")
st.title("📄 Ask your PDFs — dev tool")

# ---------------------------------------------------------------------------
# Sidebar: session + documents
# ---------------------------------------------------------------------------

with st.sidebar:
    st.header("Session")

    if st.button("➕ New session"):
        try:
            resp = httpx.post(f"{API_URL}/sessions", timeout=10.0)
            resp.raise_for_status()
            st.session_state["session_id"] = resp.json()["id"]
            st.session_state["messages"] = []
            st.rerun()
        except httpx.HTTPError as exc:
            st.error(f"Cannot create session: {exc}")

    session_id = st.session_state.get("session_id")
    if not session_id:
        st.info("Create a session to begin.")
    else:
        st.caption(f"Session: `{session_id}`")

        uploaded = st.file_uploader(
            "Upload a document (.txt / .md)", type=["txt", "md"]
        )
        if uploaded is not None and st.button("Ingest file"):
            resp = httpx.post(
                f"{API_URL}/sessions/{session_id}/documents",
                files={"file": (uploaded.name, uploaded.getvalue(), uploaded.type)},
                timeout=120.0,
            )
            if resp.status_code == 202:
                st.success(f"{uploaded.name}: {resp.json()['status']}")
            else:
                st.error(f"{resp.status_code}: {resp.text}")

        st.divider()
        st.subheader("Documents")
        try:
            docs = httpx.get(
                f"{API_URL}/sessions/{session_id}/documents", timeout=10.0
            ).json()
            if isinstance(docs, list):
                for doc in docs:
                    icon = {"ready": "✅", "failed": "❌"}.get(doc["status"], "⏳")
                    st.write(f"{icon} {doc['filename']} ({doc['chunk_count']} chunks)")
            else:
                st.warning(docs)
        except httpx.HTTPError:
            st.warning(f"Cannot reach API at {API_URL}")

        st.divider()
        if st.button("🗑️ Delete session"):
            httpx.delete(f"{API_URL}/sessions/{session_id}", timeout=10.0)
            st.session_state.pop("session_id", None)
            st.session_state["messages"] = []
            st.rerun()

# ---------------------------------------------------------------------------
# Chat
# ---------------------------------------------------------------------------

if "messages" not in st.session_state:
    st.session_state["messages"] = []

for msg in st.session_state["messages"]:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

if question := st.chat_input("Ask about your documents…"):
    if not st.session_state.get("session_id"):
        st.error("Create a session first.")
        st.stop()

    st.session_state["messages"].append({"role": "user", "content": question})
    with st.chat_message("user"):
        st.markdown(question)

    payload = {
        "question": question,
        "session_id": st.session_state["session_id"],
    }

    with st.chat_message("assistant"):
        flow_container = st.container()
        answer_placeholder = st.empty()
        answer_tokens: list[str] = []
        current_answer = ""

        try:
            with httpx.stream(
                "POST", f"{API_URL}/chat", json=payload, timeout=120.0
            ) as response:
                if response.status_code != 200:
                    response.read()
                    st.error(f"API error {response.status_code}: {response.text}")
                else:
                    for line in response.iter_lines():
                        if not line.startswith("data: "):
                            continue
                        data = line.removeprefix("data: ")
                        if data == "[DONE]":
                            break

                        parsed = json.loads(data)

                        if "sources" in parsed:
                            sources = parsed["sources"]
                            with flow_container, st.expander(
                                f"📚 Retrieved {len(sources)} documents"
                            ):
                                for src in sources:
                                    st.markdown(
                                        f"**{src['filename']}** — "
                                        f"score {src['score'] * 100:.1f}%"
                                    )
                                    for chunk in src.get("chunks", [])[:3]:
                                        st.caption(
                                            f"↳ ({chunk['score']:.4f}) "
                                            f"{chunk['chunk_text'][:200]}…"
                                        )
                        elif "step" in parsed:
                            with flow_container:
                                st.info(f"{parsed['step']}: {parsed.get('detail', '')}")
                        elif "token" in parsed:
                            answer_tokens.append(parsed["token"])
                            current_answer = "".join(answer_tokens)
                            answer_placeholder.markdown(current_answer + "▌")
                        elif "error" in parsed:
                            st.error(f"Error: {parsed['error']}")

            if current_answer:
                answer_placeholder.markdown(current_answer)

        except httpx.ConnectError:
            st.error(
                f"Cannot connect to {API_URL}. "
                "Start the API: `uv run fastapi dev app/main.py`"
            )

    if current_answer:
        st.session_state["messages"].append(
            {"role": "assistant", "content": current_answer}
        )
```

- [ ] **Step 4: Update the Commands section of `CLAUDE.md`**

In `CLAUDE.md`, in the `## Commands` code block: remove the line
`uv run python scripts/ingest_documents.py   # bulk-load data/documents.jsonl via POST /documents/bulk (server must be up)`
and add in its place:

```
uv run python scripts/reset_db.py            # DESTRUCTIVE: drop + recreate all tables (schema cutover)
```

(Do not rewrite the architecture sections — the full CLAUDE.md/README rewrite is Phase 7.)

- [ ] **Step 5: Manual smoke test of the full flow**

Start the API: `uv run fastapi dev app/main.py` (background it or use another terminal). Then:

```bash
SID=$(curl -s -X POST localhost:8000/sessions | python3 -c "import sys,json;print(json.load(sys.stdin)['id'])")
printf '# Calculus\nA derivative measures how a function changes.' > /tmp/notes.md
curl -s -X POST "localhost:8000/sessions/$SID/documents" -F "file=@/tmp/notes.md;type=text/markdown" | python3 -m json.tool
curl -s "localhost:8000/search?q=derivative&session_id=$SID" | python3 -m json.tool
curl -sN -X POST localhost:8000/chat -H 'Content-Type: application/json' \
  -d "{\"question\": \"What is a derivative?\", \"session_id\": \"$SID\"}" | head -40
```

Expected: upload returns `"status": "ready"`; search returns one result with `filename: "notes.md"`; chat streams `session_id`, `step`/`sources` events, tokens, then `data: [DONE]`. (Chat requires a real `OPENAI_API_KEY` in `.env` — if unavailable, verify only session/upload/search and rely on the test suite for chat.)

- [ ] **Step 6: Run everything**

Run: `uv run pytest && uv run ruff check . && uv run ruff format --check .`
Expected: all green.

- [ ] **Step 7: Commit**

```bash
git add scripts/reset_db.py scripts/streamlit_app.py CLAUDE.md
git commit -m "feat: reset_db cutover script; streamlit rewritten as session/upload dev tool"
```

---

## Verification (end of Phase 1)

1. `uv run pytest` — full suite green, no API keys needed.
2. `uv run ruff check . && uv run ruff format --check .` — clean.
3. Manual curl flow from Task 6 Step 5 — session → upload → poll list → search → chat stream.
4. Cross-session isolation: repeat the search with a second session id — must return `[]`.
5. `uv run streamlit run scripts/streamlit_app.py` — create session, upload `.md`, chat, delete session.

## Out of scope for this plan (later phases)

- PDF/docx/xlsx/image parsing, async background ingestion, vision OCR → Phase 2
- TTL sweeper task, slowapi rate limiting, tenacity retries, SSE mid-stream error protocol → Phase 3
- Moderation/injection/grounding guardrails → Phase 4
- Langfuse → Phase 5; Next.js `/web` → Phase 6; deploy/docs rewrite → Phase 7
