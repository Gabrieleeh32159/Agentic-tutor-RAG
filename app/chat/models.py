from __future__ import annotations

import uuid
from enum import StrEnum
from typing import Literal, TypedDict

from pydantic import BaseModel, Field

from app.search.models import SearchResult


class NodeName(StrEnum):
    RETRIEVE = "retrieve"
    GRADE_DOCUMENTS = "grade_documents"
    REWRITE_QUERY = "rewrite_query"
    GENERATE = "generate"
    NOT_FOUND = "not_found"


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
