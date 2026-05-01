from __future__ import annotations

import uuid
from typing import Literal

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    question: str = Field(min_length=1)
    subject: str | None = None
    level: Literal["introductory", "intermediate", "advanced"] | None = None


class ChatSourceDocument(BaseModel):
    id: uuid.UUID
    title: str
    score: float
