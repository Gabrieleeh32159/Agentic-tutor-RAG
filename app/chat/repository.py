from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.chat.models import ChatMessage, ChatSession


async def create_session(
    session: AsyncSession,
    *,
    subject: str | None = None,
    level: str | None = None,
) -> ChatSession:
    chat_session = ChatSession(subject=subject, level=level)
    session.add(chat_session)
    await session.commit()
    await session.refresh(chat_session)
    return chat_session


async def get_session_by_id(
    session: AsyncSession,
    session_id: uuid.UUID,
) -> ChatSession | None:
    return await session.get(ChatSession, session_id)


async def update_session_title(
    session: AsyncSession,
    chat_session: ChatSession,
    title: str,
) -> None:
    chat_session.title = title[:120]
    chat_session.updated_at = datetime.now(timezone.utc)
    session.add(chat_session)
    await session.commit()


async def list_sessions(session: AsyncSession) -> list[ChatSession]:
    result = await session.execute(
        select(ChatSession).order_by(ChatSession.created_at.desc())
    )
    return list(result.scalars().all())


async def delete_session(session: AsyncSession, session_id: uuid.UUID) -> bool:
    chat_session = await session.get(ChatSession, session_id)
    if chat_session is None:
        return False
    await session.delete(chat_session)
    await session.commit()
    return True


async def load_session_messages(
    session: AsyncSession,
    session_id: uuid.UUID,
) -> list[BaseMessage]:
    result = await session.execute(
        select(ChatMessage)
        .where(ChatMessage.session_id == session_id)
        .order_by(ChatMessage.created_at)
    )
    rows = result.scalars().all()
    messages: list[BaseMessage] = []
    for row in rows:
        if row.role == "human":
            messages.append(HumanMessage(content=row.content))
        elif row.role == "ai":
            tc = json.loads(row.tool_calls) if row.tool_calls else []
            messages.append(AIMessage(content=row.content, tool_calls=tc))
        elif row.role == "tool":
            messages.append(
                ToolMessage(content=row.content, tool_call_id=row.tool_call_id or "")
            )
        elif row.role == "system":
            messages.append(SystemMessage(content=row.content))
    return messages


async def save_messages(
    session: AsyncSession,
    session_id: uuid.UUID,
    messages: list[BaseMessage],
) -> None:
    for msg in messages:
        if isinstance(msg, HumanMessage):
            role = "human"
        elif isinstance(msg, ToolMessage):
            role = "tool"
        elif isinstance(msg, AIMessage):
            role = "ai"
        elif isinstance(msg, SystemMessage):
            role = "system"
        else:
            role = msg.type
        content = msg.content if isinstance(msg.content, str) else json.dumps(msg.content)
        tool_calls_json: str | None = None
        tool_call_id: str | None = None

        if isinstance(msg, AIMessage) and msg.tool_calls:
            tool_calls_json = json.dumps(msg.tool_calls)
        if isinstance(msg, ToolMessage):
            tool_call_id = msg.tool_call_id

        row = ChatMessage(
            session_id=session_id,
            role=role,
            content=content,
            tool_calls=tool_calls_json,
            tool_call_id=tool_call_id,
        )
        session.add(row)
    await session.commit()


async def get_session_messages(
    session: AsyncSession,
    session_id: uuid.UUID,
) -> list[ChatMessage]:
    result = await session.execute(
        select(ChatMessage)
        .where(ChatMessage.session_id == session_id)
        .order_by(ChatMessage.created_at)
    )
    return list(result.scalars().all())
