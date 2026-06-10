from __future__ import annotations

import uuid

from sqlmodel import SQLModel


class SearchChunk(SQLModel):
    chunk_id: uuid.UUID
    chunk_text: str
    score: float


class SearchResult(SQLModel):
    document_id: uuid.UUID
    filename: str
    score: float
    chunks: list[SearchChunk]
