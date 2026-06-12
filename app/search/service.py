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
