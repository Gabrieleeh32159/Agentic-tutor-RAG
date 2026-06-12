from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated, TypedDict

from langgraph.graph import add_messages
from pydantic import BaseModel, Field
from sqlalchemy import Column, DateTime, ForeignKey, Index, String, Text
from sqlmodel import Field as SQLField
from sqlmodel import SQLModel


class NodeName(StrEnum):
    AGENT = "agent"
    TOOLS = "tools"


# ---------------------------------------------------------------------------
# DB tables
# ---------------------------------------------------------------------------


class ChatMessage(SQLModel, table=True):
    __tablename__ = "chat_messages"
    __table_args__ = (
        Index("ix_chat_messages_session_created", "session_id", "created_at"),
    )

    id: uuid.UUID = SQLField(default_factory=uuid.uuid4, primary_key=True)
    session_id: uuid.UUID = SQLField(
        sa_column=Column(
            ForeignKey("sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
    )
    role: str = SQLField(sa_column=Column(String(10), nullable=False))
    content: str = SQLField(sa_column=Column(Text, nullable=False, server_default=""))
    tool_calls: str | None = SQLField(
        default=None, sa_column=Column(Text, nullable=True)
    )
    tool_call_id: str | None = SQLField(
        default=None, sa_column=Column(String(64), nullable=True)
    )
    grounded: str | None = SQLField(
        default=None, sa_column=Column(String(12), nullable=True)
    )
    created_at: datetime = SQLField(
        default_factory=lambda: datetime.now(UTC),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )


# ---------------------------------------------------------------------------
# API request / response schemas
# ---------------------------------------------------------------------------


class ChatRequest(BaseModel):
    question: str = Field(min_length=1, max_length=4000)
    session_id: uuid.UUID


class ChatMessageResponse(BaseModel):
    id: uuid.UUID
    role: str
    content: str
    tool_calls: str | None = None
    tool_call_id: str | None = None
    grounded: str | None = None
    created_at: datetime


# ---------------------------------------------------------------------------
# LangGraph agent state
# ---------------------------------------------------------------------------


class AgentState(TypedDict, total=False):
    """Agent state: conversation messages plus the session scope for retrieval."""

    messages: Annotated[list, add_messages]
    session_id: str
