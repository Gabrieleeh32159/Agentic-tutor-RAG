from __future__ import annotations

from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.documents.models import Document, DocumentChunk
from app.search.models import SearchChunk, SearchResult
from app.shared.embeddings import get_embedding_provider


async def search_documents(
    session: AsyncSession,
    query: str,
    limit: int = 5,
    subject: str | None = None,
    level: str | None = None,
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
            Document.title,
            Document.subject,
            Document.level,
            score_expr,
        )
        .join(Document, DocumentChunk.document_id == Document.id)
    )

    if subject:
        stmt = stmt.where(Document.subject == subject)
    if level:
        stmt = stmt.where(Document.level == level)

    stmt = stmt.order_by(distance).limit(limit * 3)

    result = await session.execute(stmt)
    rows = result.all()

    # Group by document
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
                "title": row.title,
                "subject": row.subject,
                "level": row.level,
                "score": chunk_score,
            }

    # Sort documents by best score, take top `limit`
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
