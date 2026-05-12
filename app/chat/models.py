from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import StrEnum
from typing import Annotated, Literal

from langgraph.graph import add_messages
from pydantic import BaseModel, Field
from sqlalchemy import Column, DateTime, ForeignKey, Index, String, Text
from sqlmodel import Field as SQLField
from sqlmodel import SQLModel

from app.search.models import SearchResult  # noqa: F401

from typing import TypedDict


# ---------------------------------------------------------------------------
# Enum for graph node names
# ---------------------------------------------------------------------------


class NodeName(StrEnum):
    AGENT = "agent"
    TOOLS = "tools"


# ---------------------------------------------------------------------------
# DB tables
# ---------------------------------------------------------------------------


class ChatSession(SQLModel, table=True):
    __tablename__ = "chat_sessions"

    id: uuid.UUID = SQLField(default_factory=uuid.uuid4, primary_key=True)
    title: str | None = SQLField(default=None, sa_column=Column(Text, nullable=True))
    subject: str | None = SQLField(default=None, max_length=50)
    level: str | None = SQLField(
        default=None,
        sa_column=Column(String(20), nullable=True),
    )
    created_at: datetime = SQLField(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    updated_at: datetime = SQLField(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )


class ChatMessage(SQLModel, table=True):
    __tablename__ = "chat_messages"
    __table_args__ = (
        Index("ix_chat_messages_session_created", "session_id", "created_at"),
    )

    id: uuid.UUID = SQLField(default_factory=uuid.uuid4, primary_key=True)
    session_id: uuid.UUID = SQLField(
        sa_column=Column(
            ForeignKey("chat_sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
    )
    role: str = SQLField(sa_column=Column(String(10), nullable=False))
    content: str = SQLField(sa_column=Column(Text, nullable=False, server_default=""))
    tool_calls: str | None = SQLField(default=None, sa_column=Column(Text, nullable=True))
    tool_call_id: str | None = SQLField(
        default=None, sa_column=Column(String(64), nullable=True)
    )
    created_at: datetime = SQLField(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )


# ---------------------------------------------------------------------------
# API request / response schemas
# ---------------------------------------------------------------------------


class ChatRequest(BaseModel):
    question: str = Field(min_length=1)
    session_id: uuid.UUID | None = None
    subject: str | None = None
    level: Literal["introductory", "intermediate", "advanced"] | None = None


class ChatSessionResponse(BaseModel):
    id: uuid.UUID
    title: str | None
    subject: str | None
    level: str | None
    created_at: datetime
    updated_at: datetime


class ChatMessageResponse(BaseModel):
    id: uuid.UUID
    role: str
    content: str
    tool_calls: str | None = None
    tool_call_id: str | None = None
    created_at: datetime


# ---------------------------------------------------------------------------
# LangGraph agent state
# ---------------------------------------------------------------------------


class AgentState(TypedDict, total=False):
    """Agent state with messages (add_messages reducer) and optional filters."""

    messages: Annotated[list, add_messages]
    subject: str | None
    level: str | None
