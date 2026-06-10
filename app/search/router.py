from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.search.models import SearchResult
from app.search.service import search_documents
from app.shared.database import get_session

router = APIRouter(prefix="/search", tags=["search"])


@router.get("", response_model=list[SearchResult])
async def search(
    q: str = Query(..., min_length=1),
    session_id: uuid.UUID = Query(...),
    limit: int = Query(5, ge=1, le=20),
    session: AsyncSession = Depends(get_session),
) -> list[SearchResult]:
    return await search_documents(
        session=session,
        query=q,
        session_id=session_id,
        limit=limit,
    )
