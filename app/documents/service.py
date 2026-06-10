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
                for i, (chunk, embedding) in enumerate(
                    zip(chunks, embeddings, strict=True)
                )
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
