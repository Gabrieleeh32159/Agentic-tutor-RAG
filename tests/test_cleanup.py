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
    chat = await client.post("/chat", json={"question": "Hola", "session_id": sid})
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
