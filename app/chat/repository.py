from __future__ import annotations

import json
import uuid

from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.chat.models import ChatMessage


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
    grounded: str | None = None,
) -> None:
    rows: list[ChatMessage] = []
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
        content = (
            msg.content if isinstance(msg.content, str) else json.dumps(msg.content)
        )
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
        rows.append(row)
        session.add(row)
    if grounded is not None:
        for row in reversed(rows):
            if row.role == "ai" and row.content:
                row.grounded = grounded
                break
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
