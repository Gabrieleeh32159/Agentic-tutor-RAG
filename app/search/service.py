from __future__ import annotations

from sqlalchemy import Row, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.documents.models import Document
from app.search.models import SearchResult
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

    distance = Document.embedding.cosine_distance(query_embedding)
    score = (1 - distance).label("score")

    stmt = select(Document, score)

    if subject:
        stmt = stmt.where(Document.subject == subject)
    if level:
        stmt = stmt.where(Document.level == level)

    stmt = stmt.order_by(distance).limit(limit)

    result = await session.execute(stmt)
    rows: list[Row[tuple[Document, float]]] = result.all()

    return [
        SearchResult(
            id=row.id,
            title=row.title,
            subject=row.subject,
            level=row.level,
            created_at=row.created_at,
            score=round(row_score, 4),
        )
        for row, row_score in rows
    ]
