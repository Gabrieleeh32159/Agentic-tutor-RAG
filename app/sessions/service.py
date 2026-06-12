from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

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
        last = last.replace(tzinfo=UTC)
    return datetime.now(UTC) - last > ttl


async def get_active_session(db: AsyncSession, session_id: uuid.UUID) -> Session:
    """Return the session or raise SessionNotFoundError / SessionExpiredError."""
    session = await db.get(Session, session_id)
    if session is None:
        raise SessionNotFoundError(f"Session {session_id} not found")
    if _is_expired(session):
        raise SessionExpiredError(f"Session {session_id} has expired")
    return session


async def touch_session(db: AsyncSession, session: Session) -> None:
    session.last_activity_at = datetime.now(UTC)
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
