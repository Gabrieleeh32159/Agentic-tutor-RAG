"""Drop and recreate all tables. DESTRUCTIVE - wipes all data.

Used for the schema cutover on environments where tables already exist
(create_all never alters existing tables). Run once per environment:

    uv run python scripts/reset_db.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

# Make ``app`` importable when the script is run from any directory.
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlmodel import SQLModel

from app.chat.models import ChatMessage  # noqa: F401
from app.documents.models import Document, DocumentChunk  # noqa: F401
from app.sessions.models import Session  # noqa: F401
from app.shared.config import get_settings
from app.shared.database import close_engine, get_engine, init_engine


async def main() -> None:
    settings = get_settings()
    init_engine(settings.DATABASE_URL)
    async with get_engine().begin() as conn:
        # Legacy tables (chat_sessions, the old chat_messages FK) are no longer
        # in metadata, so drop_all alone can't remove them on an old database.
        await conn.exec_driver_sql(
            "DROP TABLE IF EXISTS chat_messages, chat_sessions CASCADE"
        )
        await conn.run_sync(SQLModel.metadata.drop_all)
        await conn.run_sync(SQLModel.metadata.create_all)
    await close_engine()
    print("Database schema reset.")


if __name__ == "__main__":
    asyncio.run(main())
