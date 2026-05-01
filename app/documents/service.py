from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.documents.models import Document, DocumentCreate
from app.shared.embeddings import get_embedding_provider


async def create_document(
    session: AsyncSession, data: DocumentCreate
) -> Document:
    provider = get_embedding_provider()
    embedding = await provider.embed(data.content)
    document = Document(
        title=data.title,
        content=data.content,
        subject=data.subject,
        level=data.level,
        embedding=embedding,
    )
    session.add(document)
    await session.commit()
    await session.refresh(document)
    return document


async def bulk_create_documents(
    session: AsyncSession, items: list[DocumentCreate]
) -> list[Document]:
    provider = get_embedding_provider()
    texts = [item.content for item in items]
    embeddings = await provider.embed_batch(texts)

    documents = []
    for item, embedding in zip(items, embeddings):
        doc = Document(
            title=item.title,
            content=item.content,
            subject=item.subject,
            level=item.level,
            embedding=embedding,
        )
        session.add(doc)
        documents.append(doc)

    await session.commit()
    for doc in documents:
        await session.refresh(doc)
    return documents
