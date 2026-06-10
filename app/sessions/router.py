from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.sessions import service
from app.sessions.models import SessionResponse
from app.shared.database import get_session

router = APIRouter(prefix="/sessions", tags=["sessions"])


@router.post("", response_model=SessionResponse, status_code=status.HTTP_201_CREATED)
async def create_session(db: AsyncSession = Depends(get_session)) -> SessionResponse:
    session = await service.create_session(db)
    return SessionResponse.model_validate(session, from_attributes=True)


@router.get("/{session_id}", response_model=SessionResponse)
async def get_session_detail(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_session),
) -> SessionResponse:
    session = await service.get_active_session(db, session_id)
    await service.touch_session(db, session)
    return SessionResponse.model_validate(session, from_attributes=True)


@router.delete("/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_session(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_session),
) -> None:
    await service.delete_session(db, session_id)
