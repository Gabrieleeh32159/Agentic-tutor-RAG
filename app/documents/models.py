from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import StrEnum

from pgvector.sqlalchemy import Vector
from pydantic import BaseModel
from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text
from sqlmodel import Field, SQLModel


class DocumentStatus(StrEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"


class Document(SQLModel, table=True):
    __tablename__ = "documents"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    session_id: uuid.UUID = Field(
        sa_column=Column(
            ForeignKey("sessions.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
    )
    filename: str = Field(sa_column=Column(Text, nullable=False))
    mime_type: str = Field(sa_column=Column(String(100), nullable=False))
    size_bytes: int = Field(sa_column=Column(Integer, nullable=False))
    page_count: int | None = Field(default=None)
    chunk_count: int = Field(default=0)
    status: str = Field(
        default=DocumentStatus.PENDING,
        sa_column=Column(String(12), nullable=False),
    )
    stage: str | None = Field(default=None, sa_column=Column(String(12), nullable=True))
    progress: int = Field(default=0)
    error_code: str | None = Field(
        default=None, sa_column=Column(String(40), nullable=True)
    )
    error_message: str | None = Field(
        default=None, sa_column=Column(Text, nullable=True)
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )


class DocumentChunk(SQLModel, table=True):
    __tablename__ = "document_chunks"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    document_id: uuid.UUID = Field(
        sa_column=Column(
            ForeignKey("documents.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
    )
    chunk_index: int = Field(default=0)
    page_number: int | None = Field(default=None)
    chunk_text: str = Field(sa_column=Column(Text, nullable=False))
    embedding: list[float] = Field(
        sa_column=Column(Vector(1536), nullable=False),
    )


class DocumentResponse(BaseModel):
    id: uuid.UUID
    filename: str
    mime_type: str
    size_bytes: int
    page_count: int | None
    chunk_count: int
    status: str
    stage: str | None
    progress: int
    error_code: str | None
    error_message: str | None
    created_at: datetime
