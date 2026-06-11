from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.documents.models import Document, DocumentStatus
from app.shared.errors import DocumentNotFoundError


async def count_documents(db: AsyncSession, session_id: uuid.UUID) -> int:
    result = await db.execute(
        select(func.count())
        .select_from(Document)
        .where(Document.session_id == session_id)
    )
    return int(result.scalar_one())


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
