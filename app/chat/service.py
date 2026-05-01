from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession

from app.chat.models import ChatSourceDocument
from app.search.service import search_documents
from app.shared.llm import LLMProvider

SYSTEM_PROMPT = (
    "You are an educational AI study assistant. "
    "Answer the student's question using ONLY the provided context documents. "
    "Cite sources by their title when you use information from them. "
    "If the context does not contain enough information to answer, say so clearly. "
    "Be concise, accurate, and helpful."
)

CONTEXT_LIMIT = 3


def _build_user_prompt(question: str, context_docs: list[dict[str, str]]) -> str:
    context_parts = []
    for i, doc in enumerate(context_docs, 1):
        context_parts.append(
            f"[{i}] Title: {doc['title']}\n{doc['content']}"
        )
    context_block = "\n\n".join(context_parts)
    return (
        f"Context documents:\n{context_block}\n\n"
        f"Student question: {question}"
    )


async def retrieve_context(
    session: AsyncSession,
    question: str,
    subject: str | None = None,
    level: str | None = None,
) -> tuple[list[ChatSourceDocument], list[dict[str, str]]]:
    results = await search_documents(
        session=session,
        query=question,
        limit=CONTEXT_LIMIT,
        subject=subject,
        level=level,
    )

    sources = [
        ChatSourceDocument(id=r.id, title=r.title, score=r.score)
        for r in results
    ]

    context_docs: list[dict[str, str]] = []
    for r in results:
        from app.documents.models import Document
        from sqlalchemy import select

        stmt = select(Document).where(Document.id == r.id)
        row = await session.execute(stmt)
        doc = row.scalar_one()
        context_docs.append({"title": doc.title, "content": doc.content})

    return sources, context_docs


async def stream_chat_response(
    llm: LLMProvider,
    question: str,
    context_docs: list[dict[str, str]],
) -> AsyncIterator[str]:
    user_prompt = _build_user_prompt(question, context_docs)
    async for token in llm.stream(SYSTEM_PROMPT, user_prompt):
        yield token
