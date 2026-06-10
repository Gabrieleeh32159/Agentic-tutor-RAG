from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.search.models import SearchResult
from app.search.service import search_documents
from app.shared.database import get_session

router = APIRouter(prefix="/search", tags=["search"])


@router.get("", response_model=list[SearchResult])
async def search(
    q: str = Query(..., min_length=1),
    limit: int = Query(5, ge=1, le=20),
    subject: str | None = Query(None),
    level: Literal["introductory", "intermediate", "advanced"] | None = Query(None),
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> list[SearchResult]:
    return await search_documents(
        session=session,
        query=q,
        limit=limit,
        subject=subject,
        level=level,
    )
