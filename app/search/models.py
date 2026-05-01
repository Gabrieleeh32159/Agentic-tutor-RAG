from __future__ import annotations

import uuid
from datetime import datetime

from sqlmodel import SQLModel


class SearchResult(SQLModel):
    id: uuid.UUID
    title: str
    subject: str
    level: str
    created_at: datetime
    score: float
