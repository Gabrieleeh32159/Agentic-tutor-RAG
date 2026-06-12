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
    result = await db.execute(delete(Session).where(Session.last_activity_at < cutoff))
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
        .where(Document.status.in_([DocumentStatus.PENDING, DocumentStatus.PROCESSING]))
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
