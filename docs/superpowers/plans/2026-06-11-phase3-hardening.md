# Phase 3: TTL Cleanup, Rate Limiting, Provider + Stream Hardening — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The service runs unattended on the public internet: expired sessions (and everything they own) are swept automatically, abuse is rate-limited with the standard error envelope, provider calls have explicit timeouts + retries, and a mid-SSE-stream failure ends the stream with a structured error event instead of a leaked exception string.

**Architecture:** A background sweeper task (started/stopped in lifespan alongside graceful ingestion-task shutdown) periodically bulk-deletes expired sessions (Postgres `ON DELETE CASCADE` removes documents/chunks/messages) and reaps documents stuck in pending/processing; the startup reconciliation moves into the same module so it's testable. Rate limiting is slowapi in-memory (exact on a single Render process), disabled via a conftest toggle so the suite isn't throttled. Provider hardening uses the OpenAI SDK / LangChain built-in retry+timeout knobs with explicit values (deviation from the spec's "tenacity": stacking tenacity on top of the SDK's own exponential-backoff retries would double-retry; setting the built-ins explicitly achieves the spec's intent — 3 attempts, exponential backoff, explicit timeouts — without a new dep or retry stacking; documented decision). The chat SSE loop gets `asyncio.timeout` and a structured terminal error event.

**Tech Stack:** slowapi (new dep). No tenacity (see above).

**This is plan 3 of 7.** Spec: `docs/superpowers/specs/2026-06-10-ask-your-pdfs-design.md` (decision 3 = TTL, decision 8 = rate limiting, decision 10 = error/stream hardening). Current state: 93 tests green (~6s), local Docker Postgres running, `.env` → localhost.

**Carry-over items from earlier reviews folded in here:** sweeper also reaps stale processing rows; lifespan cancels in-flight ingestion tasks before disposing the engine; startup reconciliation gets test coverage; the SSE error event stops leaking `str(exc)`.

---

### Task 1: Cleanup module — sweeper, stale-document reaper, testable reconciliation, graceful shutdown

**Files:**
- Create: `app/sessions/cleanup.py`, `tests/test_cleanup.py`
- Modify: `app/shared/config.py`, `app/main.py`, `app/ingestion/service.py`

- [ ] **Step 1: Write the failing tests.** Create `tests/test_cleanup.py`:

```python
from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy import func, select, update

from app.chat.models import ChatMessage
from app.documents.models import Document, DocumentChunk
from app.ingestion.service import wait_for_ingestion
from app.sessions.cleanup import (
    delete_expired_sessions,
    reap_stale_documents,
    reconcile_interrupted_documents,
)
from app.sessions.models import Session
from app.shared.database import get_session_factory


async def _create_session(client: httpx.AsyncClient) -> str:
    response = await client.post("/sessions")
    assert response.status_code == 201
    return response.json()["id"]


async def _seed_session_with_content(client: httpx.AsyncClient) -> str:
    sid = await _create_session(client)
    response = await client.post(
        f"/sessions/{sid}/documents",
        files={"file": ("notes.md", b"A derivative measures change.", "text/markdown")},
    )
    assert response.status_code == 202
    await wait_for_ingestion()
    chat = await client.post(
        "/chat", json={"question": "Hola", "session_id": sid}
    )
    assert chat.status_code == 200
    return sid


async def _backdate_session(session_id: str, hours: int) -> None:
    factory = get_session_factory()
    async with factory() as db:
        await db.execute(
            update(Session)
            .where(Session.id == uuid.UUID(session_id))
            .values(last_activity_at=datetime.now(UTC) - timedelta(hours=hours))
        )
        await db.commit()


async def _count(model) -> int:
    factory = get_session_factory()
    async with factory() as db:
        result = await db.execute(select(func.count()).select_from(model))
        return int(result.scalar_one())


async def test_expired_sessions_are_deleted_with_cascade(
    client: httpx.AsyncClient,
) -> None:
    expired_sid = await _seed_session_with_content(client)
    fresh_sid = await _seed_session_with_content(client)
    await _backdate_session(expired_sid, hours=25)

    factory = get_session_factory()
    async with factory() as db:
        deleted = await delete_expired_sessions(db)
    assert deleted == 1

    # The fresh session and all its children survive; the expired one is gone entirely
    assert await _count(Session) == 1
    assert (await client.get(f"/sessions/{fresh_sid}")).status_code == 200
    assert (await client.get(f"/sessions/{expired_sid}")).status_code == 404
    # Cascade: exactly the fresh session's rows remain
    factory = get_session_factory()
    async with factory() as db:
        docs = await db.execute(select(Document.session_id))
        assert {str(s) for (s,) in docs.all()} == {fresh_sid}
        msgs = await db.execute(select(ChatMessage.session_id))
        assert {str(s) for (s,) in msgs.all()} == {fresh_sid}
    assert await _count(DocumentChunk) > 0  # fresh session's chunks survive


async def test_sweep_is_noop_when_nothing_expired(client: httpx.AsyncClient) -> None:
    await _seed_session_with_content(client)
    factory = get_session_factory()
    async with factory() as db:
        deleted = await delete_expired_sessions(db)
    assert deleted == 0
    assert await _count(Session) == 1


async def test_stale_processing_documents_are_reaped(
    client: httpx.AsyncClient,
) -> None:
    sid = await _create_session(client)
    response = await client.post(
        f"/sessions/{sid}/documents",
        files={"file": ("notes.md", b"content here", "text/markdown")},
    )
    assert response.status_code == 202
    doc_id = response.json()["id"]
    await wait_for_ingestion()

    # Force the row back into processing with an old created_at
    factory = get_session_factory()
    async with factory() as db:
        await db.execute(
            update(Document)
            .where(Document.id == uuid.UUID(doc_id))
            .values(
                status="processing",
                stage="embedding",
                created_at=datetime.now(UTC) - timedelta(hours=2),
            )
        )
        await db.commit()

    async with factory() as db:
        reaped = await reap_stale_documents(db)
    assert reaped == 1

    docs = (await client.get(f"/sessions/{sid}/documents")).json()
    assert docs[0]["status"] == "failed"
    assert docs[0]["error_code"] == "interrupted"


async def test_recent_processing_documents_are_not_reaped(
    client: httpx.AsyncClient,
) -> None:
    sid = await _create_session(client)
    response = await client.post(
        f"/sessions/{sid}/documents",
        files={"file": ("notes.md", b"content here", "text/markdown")},
    )
    doc_id = response.json()["id"]
    await wait_for_ingestion()

    factory = get_session_factory()
    async with factory() as db:
        await db.execute(
            update(Document)
            .where(Document.id == uuid.UUID(doc_id))
            .values(status="processing", stage="embedding")  # created_at stays recent
        )
        await db.commit()

    async with factory() as db:
        reaped = await reap_stale_documents(db)
    assert reaped == 0


async def test_reconcile_interrupted_documents(client: httpx.AsyncClient) -> None:
    """Startup reconciliation fails ALL pending/processing rows regardless of age."""
    sid = await _create_session(client)
    response = await client.post(
        f"/sessions/{sid}/documents",
        files={"file": ("notes.md", b"content here", "text/markdown")},
    )
    doc_id = response.json()["id"]
    await wait_for_ingestion()

    factory = get_session_factory()
    async with factory() as db:
        await db.execute(
            update(Document)
            .where(Document.id == uuid.UUID(doc_id))
            .values(status="pending", stage=None, progress=0)
        )
        await db.commit()

    async with factory() as db:
        count = await reconcile_interrupted_documents(db)
        await db.commit()
    assert count == 1

    docs = (await client.get(f"/sessions/{sid}/documents")).json()
    assert docs[0]["status"] == "failed"
    assert docs[0]["error_code"] == "interrupted"
```

- [ ] **Step 2: Run to verify failure.** `uv run pytest tests/test_cleanup.py -v` → ImportError (`app.sessions.cleanup` missing).

- [ ] **Step 3: Config.** In `app/shared/config.py`, after `SESSION_TTL_HOURS: int = 24` add:

```python
    CLEANUP_INTERVAL_MINUTES: int = 15
    STALE_PROCESSING_MINUTES: int = 60
```

- [ ] **Step 4: Implement `app/sessions/cleanup.py`:**

```python
from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.documents.models import Document, DocumentStatus
from app.sessions.models import Session
from app.shared.config import get_settings
from app.shared.database import get_session_factory

logger = logging.getLogger(__name__)

INTERRUPTED_VALUES = {
    "status": DocumentStatus.FAILED,
    "stage": None,
    "progress": 0,
    "error_code": "interrupted",
    "error_message": "Processing was interrupted.",
}


async def delete_expired_sessions(db: AsyncSession) -> int:
    """Bulk-delete sessions idle past the TTL. Children cascade at the DB level."""
    cutoff = datetime.now(UTC) - timedelta(hours=get_settings().SESSION_TTL_HOURS)
    result = await db.execute(
        delete(Session).where(Session.last_activity_at < cutoff)
    )
    await db.commit()
    return result.rowcount or 0


async def reap_stale_documents(db: AsyncSession) -> int:
    """Fail documents stuck in pending/processing longer than the stale window.

    Covers the gap startup reconciliation can't: a task that died silently
    (e.g. the FAILED-write itself failed) while the process kept running.
    """
    cutoff = datetime.now(UTC) - timedelta(
        minutes=get_settings().STALE_PROCESSING_MINUTES
    )
    result = await db.execute(
        update(Document)
        .where(
            Document.status.in_([DocumentStatus.PENDING, DocumentStatus.PROCESSING]),
            Document.created_at < cutoff,
        )
        .values(**INTERRUPTED_VALUES)
    )
    await db.commit()
    return result.rowcount or 0


async def reconcile_interrupted_documents(db: AsyncSession) -> int:
    """Startup-only: any row still pending/processing was orphaned by a restart."""
    result = await db.execute(
        update(Document)
        .where(
            Document.status.in_([DocumentStatus.PENDING, DocumentStatus.PROCESSING])
        )
        .values(**INTERRUPTED_VALUES)
    )
    return result.rowcount or 0


async def cleanup_loop(stop: asyncio.Event) -> None:
    """Periodic sweeper; runs until `stop` is set. Errors are logged, never fatal."""
    interval = get_settings().CLEANUP_INTERVAL_MINUTES * 60
    while not stop.is_set():
        try:
            factory = get_session_factory()
            async with factory() as db:
                expired = await delete_expired_sessions(db)
                stale = await reap_stale_documents(db)
            if expired or stale:
                logger.info(
                    "Cleanup: removed %d expired sessions, reaped %d stale documents",
                    expired,
                    stale,
                )
        except Exception:
            logger.exception("Cleanup sweep failed; will retry next interval")
        try:
            await asyncio.wait_for(stop.wait(), timeout=interval)
        except TimeoutError:
            continue
```

- [ ] **Step 5: Wire lifespan in `app/main.py`** — replace the inline reconciliation block with the cleanup module, start/stop the sweeper, and shut ingestion down gracefully. The lifespan becomes:

```python
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
```

Imports to add at top: `import asyncio`, `import logging`, `from app.ingestion.service import shutdown_ingestion`, `from app.sessions.cleanup import cleanup_loop, reconcile_interrupted_documents`, `from app.shared.database import get_session_factory` (extend the existing import). Remove the now-unused `update`/`DocumentStatus` imports and the old inline reconciliation code.

- [ ] **Step 6: Graceful ingestion shutdown.** In `app/ingestion/service.py` add:

```python
async def shutdown_ingestion() -> None:
    """Cancel in-flight ingestion tasks and wait for them to settle.

    Cancelled tasks leave pending/processing rows; startup reconciliation
    marks them failed/interrupted on the next boot.
    """
    for task in list(_tasks):
        task.cancel()
    if _tasks:
        await asyncio.gather(*list(_tasks), return_exceptions=True)
```

- [ ] **Step 7: Run.** `uv run pytest tests/test_cleanup.py -v` → 5 PASS. Full suite + lint clean.

- [ ] **Step 8: Commit.**

```bash
git add app/sessions/cleanup.py app/shared/config.py app/main.py app/ingestion/service.py tests/test_cleanup.py
git commit -m "feat: TTL sweeper, stale-document reaper, graceful ingestion shutdown"
```

---

### Task 2: Rate limiting with envelope-formatted 429s

**Files:**
- Modify: `pyproject.toml`, `app/main.py`, `app/documents/router.py`, `app/chat/router.py`, `app/shared/config.py`, `tests/conftest.py`
- Test: `tests/test_rate_limit.py`

- [ ] **Step 1: Add dep.** `pyproject.toml` dependencies: `"slowapi>=0.1.9"`. Run `uv sync`.

- [ ] **Step 2: Write the failing test.** Create `tests/test_rate_limit.py`:

```python
from __future__ import annotations

import httpx


async def test_rate_limit_returns_envelope_429(client: httpx.AsyncClient) -> None:
    """With the limiter enabled and a tiny default limit, requests get a 429 envelope."""
    from app.main import limiter

    limiter.enabled = True
    try:
        # default limit is high; hammer /health until we trip it or hit a sane bound
        last = None
        for _ in range(70):
            last = await client.get("/health")
            if last.status_code == 429:
                break
        assert last is not None and last.status_code == 429
        body = last.json()
        assert body["error"]["code"] == "RATE_LIMITED"
        assert "request_id" in body["error"]
    finally:
        limiter.enabled = False
        limiter.reset()


async def test_rate_limit_disabled_in_tests_by_default(
    client: httpx.AsyncClient,
) -> None:
    for _ in range(70):
        response = await client.get("/health")
    assert response.status_code == 200
```

- [ ] **Step 3: Run to verify failure.** `uv run pytest tests/test_rate_limit.py -v` → ImportError (`limiter` missing).

- [ ] **Step 4: Implement.** In `app/main.py`, after the imports:

```python
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from app.shared.errors import error_envelope

limiter = Limiter(
    key_func=get_remote_address,
    default_limits=["60/minute"],
)
```

After `app = FastAPI(...)`:

```python
app.state.limiter = limiter
app.add_middleware(SlowAPIMiddleware)


@app.exception_handler(RateLimitExceeded)
async def handle_rate_limit(request: Request, exc: RateLimitExceeded) -> JSONResponse:
    return JSONResponse(
        status_code=429,
        content=error_envelope(
            "RATE_LIMITED", f"Rate limit exceeded: {exc.detail}. Try again later."
        ),
    )
```

(Imports: `from fastapi import FastAPI, Request`, `from fastapi.responses import JSONResponse`, `from slowapi.middleware import SlowAPIMiddleware`. **The middleware is required**: slowapi's `default_limits` only apply to undecorated routes through `SlowAPIMiddleware`; the `@limiter.limit` decorators on upload/chat override the default for those routes. Middleware ordering with CORS/RequestID is not sensitive — rate-limit rejections still pass through the request-ID middleware so the envelope gets its id.)

Per-route limits — slowapi needs the `request: Request` parameter present on decorated handlers:
- `app/documents/router.py::upload_document`: add `request: Request` parameter (first param after session_id is fine; import `Request` from fastapi) and decorate with `@limiter.limit("10/hour")` directly under `@router.post(...)`. Import: `from app.main import limiter` would be circular — so DON'T. Instead create the limiter in a new tiny module `app/shared/rate_limit.py`:

```python
from __future__ import annotations

from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(
    key_func=get_remote_address,
    default_limits=["60/minute"],
)
```

and have `app/main.py` import it from there (`from app.shared.rate_limit import limiter`) — routers import from `app.shared.rate_limit` too. Adjust the test import to `from app.shared.rate_limit import limiter`.
- `app/chat/router.py::chat`: already has `request: Request`; decorate with `@limiter.limit("20/minute")`.

- [ ] **Step 5: Disable in tests.** `tests/conftest.py` autouse fixture:

```python
@pytest.fixture(autouse=True)
def _disable_rate_limiting():
    from app.shared.rate_limit import limiter

    limiter.enabled = False
    yield
    limiter.enabled = False
```

(`limiter.reset()` inside the rate-limit test clears the in-memory counters it created.)

- [ ] **Step 6: Run.** `uv run pytest tests/test_rate_limit.py -v` → 2 PASS. FULL suite green (the autouse fixture must keep all other tests unthrottled). Lint clean.

- [ ] **Step 7: Commit.**

```bash
git add -A
git commit -m "feat: slowapi rate limiting with envelope 429s (10/h uploads, 20/min chat, 60/min default)"
```

---

### Task 3: Provider timeouts/retries + mid-SSE failure protocol

**Files:**
- Modify: `app/shared/llm.py`, `app/shared/embeddings.py`, `app/shared/config.py`, `app/chat/router.py`, `tests/conftest.py`
- Test: extend `tests/test_chat.py`

- [ ] **Step 1: Write the failing tests.** Append to `tests/test_chat.py`:

```python
# ---------------------------------------------------------------------------
# Mid-stream failure protocol
# ---------------------------------------------------------------------------


async def test_midstream_failure_emits_structured_error_and_done(
    chat_session: tuple[httpx.AsyncClient, str],
) -> None:
    """An exception inside the agent stream must end with a structured error
    event (no leaked exception text) followed by [DONE], and the user message
    must still be persisted."""
    client, sid = chat_session
    response = await client.post(
        "/chat",
        json={"question": "What is a derivative? TRIGGER_STREAM_FAILURE", "session_id": sid},
    )
    assert response.status_code == 200
    lines = _parse_sse(response.text)

    error_lines = [ln for ln in lines if '"error"' in ln]
    assert len(error_lines) == 1
    payload = json.loads(error_lines[0].removeprefix("data: "))
    assert payload["error"]["code"] == "STREAM_FAILED"
    assert "boom" not in payload["error"]["message"]  # raw exception not leaked
    assert lines[-1] == "data: [DONE]"

    messages = (await client.get(f"/sessions/{sid}/messages")).json()
    assert any(
        m["role"] == "human" and "TRIGGER_STREAM_FAILURE" in m["content"]
        for m in messages
    )
```

- [ ] **Step 2: Teach the fake to fail on demand.** In `tests/conftest.py` `FakeChatModel._stream`, before the tool-call handling add:

```python
        last_human = ""
        for m in reversed(messages):
            if getattr(m, "type", "") == "human" and isinstance(m.content, str):
                last_human = m.content
                break
        if "TRIGGER_STREAM_FAILURE" in last_human:
            raise RuntimeError("boom - simulated mid-stream provider failure")
```

(Note: `_generate` must NOT raise for this keyword — only `_stream` — so the failure happens mid-stream where the SSE loop is already running. Also: "TRIGGER_STREAM_FAILURE" contains no academic keyword conflict, but the question deliberately includes "What is" so the agent path is exercised; the raise happens before tool-call emission, which is fine — the point is an exception inside `astream_events`.)

- [ ] **Step 3: Run to verify failure.** The test fails: the current handler emits `{"error": str(exc)}` (leaked text, wrong shape).

- [ ] **Step 4: Implement the protocol.** In `app/shared/config.py` add:

```python
    CHAT_STREAM_TIMEOUT_SECONDS: int = 120
```

In `app/chat/router.py`, the try/except around the event loop becomes:

```python
            try:
                async with asyncio.timeout(
                    get_settings().CHAT_STREAM_TIMEOUT_SECONDS
                ):
                    async for event in graph.astream_events(initial_state, version="v2"):
                        ...  # (existing body unchanged)
            except TimeoutError:
                logger.exception("Chat stream timed out")
                yield (
                    "data: "
                    + json.dumps(
                        {
                            "error": {
                                "code": "STREAM_TIMEOUT",
                                "message": "The response took too long and was stopped.",
                            }
                        }
                    )
                    + "\n\n"
                )
            except Exception:
                logger.exception("Chat streaming failed")
                yield (
                    "data: "
                    + json.dumps(
                        {
                            "error": {
                                "code": "STREAM_FAILED",
                                "message": "The response could not be completed. Please try again.",
                            }
                        }
                    )
                    + "\n\n"
                )
```

(Add `import asyncio` and `from app.shared.config import get_settings` to the router imports. The persist-before-DONE block and `[DONE]` yield are unchanged — they already run after the except blocks.)

- [ ] **Step 5: Provider timeouts + retries (spec deviation documented in header).**

`app/shared/llm.py` — both models get explicit knobs:

```python
        primary = ChatOpenAI(
            model=settings.CHAT_MODEL,
            api_key=settings.OPENAI_API_KEY,
            streaming=True,
            timeout=60,
            max_retries=2,
        )
```

and in `get_vision_model()`:

```python
        _vision_model = ChatOpenAI(
            model=settings.VISION_MODEL,
            api_key=settings.OPENAI_API_KEY,
            temperature=0,
            timeout=90,
            max_retries=2,
        )
```

(ChatAnthropic fallback gets `timeout=60, max_retries=2` too.)

`app/shared/embeddings.py`:

```python
        self._client = AsyncOpenAI(
            api_key=settings.OPENAI_API_KEY,
            timeout=30.0,
            max_retries=3,
        )
```

Add a one-line comment at each site: `# explicit timeout + SDK exponential-backoff retries (see Phase 3 plan: no tenacity stacking)`.

- [ ] **Step 6: Run.** New test green; FULL suite green; lint clean.

- [ ] **Step 7: Commit.**

```bash
git add -A
git commit -m "feat: stream timeout + structured mid-SSE error events; explicit provider timeouts/retries"
```

---

## Verification (end of Phase 3)

1. `uv run pytest -q` green (~100 tests); `ruff check` + `ruff format --check` clean.
2. Cleanup: seed a session, backdate it in psql, watch the sweeper log line within one interval (or call the function directly — covered by tests).
3. Rate limit manual check: `for i in $(seq 1 70); do curl -s -o /dev/null -w "%{http_code}\n" localhost:8000/health; done` → 429s with envelope after 60 (run server WITHOUT the test fixture, limiter enabled by default).
4. Mid-stream failure: covered by the suite (fake-triggered).

## Out of scope (later phases)

Guardrails (moderation/injection/grounding) → Phase 4; Langfuse → Phase 5; frontend → Phase 6; deploy/docs → Phase 7.
