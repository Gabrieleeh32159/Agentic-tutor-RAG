from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy import update

from app.sessions.models import Session
from app.shared.database import get_session_factory


async def _backdate_session(session_id: str, *, days: int = 0, hours: int = 0) -> None:
    """Set last_activity_at into the past, directly in the DB."""
    factory = get_session_factory()
    async with factory() as db:
        await db.execute(
            update(Session)
            .where(Session.id == uuid.UUID(session_id))
            .values(
                last_activity_at=datetime.now(UTC) - timedelta(days=days, hours=hours)
            )
        )
        await db.commit()


async def test_create_session(client: httpx.AsyncClient) -> None:
    response = await client.post("/sessions")
    assert response.status_code == 201
    data = response.json()
    uuid.UUID(data["id"])
    assert data["title"] is None
    assert "created_at" in data
    assert "last_activity_at" in data


async def test_get_session(client: httpx.AsyncClient) -> None:
    created = (await client.post("/sessions")).json()
    response = await client.get(f"/sessions/{created['id']}")
    assert response.status_code == 200
    assert response.json()["id"] == created["id"]


async def test_get_unknown_session_returns_404_envelope(
    client: httpx.AsyncClient,
) -> None:
    response = await client.get(f"/sessions/{uuid.uuid4()}")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "SESSION_NOT_FOUND"


async def test_get_expired_session_returns_410(client: httpx.AsyncClient) -> None:
    created = (await client.post("/sessions")).json()
    await _backdate_session(created["id"], days=2)

    response = await client.get(f"/sessions/{created['id']}")
    assert response.status_code == 410
    assert response.json()["error"]["code"] == "SESSION_EXPIRED"


async def test_get_session_touches_activity(client: httpx.AsyncClient) -> None:
    created = (await client.post("/sessions")).json()
    await _backdate_session(created["id"], hours=1)

    after = (await client.get(f"/sessions/{created['id']}")).json()

    touched = datetime.fromisoformat(after["last_activity_at"])
    # Normalize to tz-aware in case the serialized string lacks an offset
    if touched.tzinfo is None:
        touched = touched.replace(tzinfo=UTC)
    assert touched > datetime.now(UTC) - timedelta(minutes=5)


async def test_delete_session(client: httpx.AsyncClient) -> None:
    created = (await client.post("/sessions")).json()
    response = await client.delete(f"/sessions/{created['id']}")
    assert response.status_code == 204

    response = await client.get(f"/sessions/{created['id']}")
    assert response.status_code == 404


async def test_delete_unknown_session_returns_404(client: httpx.AsyncClient) -> None:
    response = await client.delete(f"/sessions/{uuid.uuid4()}")
    assert response.status_code == 404
