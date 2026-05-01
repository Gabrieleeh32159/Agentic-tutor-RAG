from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Literal

from pgvector.sqlalchemy import Vector
from sqlalchemy import Column, DateTime, String, Text
from sqlmodel import Field, SQLModel


class Document(SQLModel, table=True):
    __tablename__ = "documents"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    title: str = Field(sa_column=Column(Text, nullable=False))
    content: str = Field(sa_column=Column(Text, nullable=False))
    subject: str = Field(max_length=50)
    level: Literal["introductory", "intermediate", "advanced"] = Field(
        sa_column=Column(String(20), nullable=False),
    )
    embedding: list[float] | None = Field(
        default=None,
        sa_column=Column(Vector(1536)),
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )


class DocumentCreate(SQLModel):
    title: str = Field(min_length=1)
    content: str = Field(min_length=1)
    subject: str = Field(min_length=1, max_length=50)
    level: Literal["introductory", "intermediate", "advanced"]


class DocumentResponse(SQLModel):
    id: uuid.UUID
    title: str
    subject: str
    level: str
    created_at: datetime
