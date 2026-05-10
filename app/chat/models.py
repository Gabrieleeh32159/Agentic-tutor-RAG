from __future__ import annotations

import uuid
from typing import Literal, TypedDict

from pydantic import BaseModel, Field

from app.search.models import SearchResult


class ChatRequest(BaseModel):
    question: str = Field(min_length=1)
    subject: str | None = None
    level: Literal["introductory", "intermediate", "advanced"] | None = None


class ChatSourceDocument(BaseModel):
    id: uuid.UUID
    title: str
    score: float


class AgentState(TypedDict, total=False):
    question: str
    subject: str | None
    level: str | None
    documents: list[SearchResult]
    generation: str
    is_relevant: bool
    retry_count: int
