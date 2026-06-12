from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.chat.models import ChatMessageResponse
from app.chat.repository import get_session_messages
from app.documents.models import DocumentResponse
from app.documents.service import list_documents
from app.sessions import service
from app.sessions.models import SessionDetailResponse, SessionResponse
from app.shared.database import get_session

router = APIRouter(prefix="/sessions", tags=["sessions"])


@router.post("", response_model=SessionResponse, status_code=status.HTTP_201_CREATED)
async def create_session(db: AsyncSession = Depends(get_session)) -> SessionResponse:
    session = await service.create_session(db)
    return SessionResponse.model_validate(session, from_attributes=True)


@router.get("/{session_id}", response_model=SessionDetailResponse)
async def get_session_detail(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_session),
) -> SessionDetailResponse:
    session = await service.get_active_session(db, session_id)
    await service.touch_session(db, session)
    documents = await list_documents(db, session_id)
    return SessionDetailResponse(
        id=session.id,
        title=session.title,
        created_at=session.created_at,
        last_activity_at=session.last_activity_at,
        documents=[
            DocumentResponse.model_validate(d, from_attributes=True) for d in documents
        ],
    )


@router.get("/{session_id}/messages", response_model=list[ChatMessageResponse])
async def get_messages(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_session),
) -> list[ChatMessageResponse]:
    session = await service.get_active_session(db, session_id)
    await service.touch_session(db, session)
    messages = await get_session_messages(db, session_id)
    return [
        ChatMessageResponse(
            id=m.id,
            role=m.role,
            content=m.content,
            tool_calls=m.tool_calls,
            tool_call_id=m.tool_call_id,
            grounded=m.grounded,
            created_at=m.created_at,
        )
        for m in messages
    ]


@router.delete("/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_session(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_session),
) -> None:
    await service.delete_session(db, session_id)
