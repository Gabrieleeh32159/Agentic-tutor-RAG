from __future__ import annotations

from langchain_text_splitters import RecursiveCharacterTextSplitter
from sqlalchemy.ext.asyncio import AsyncSession

from app.documents.models import Document, DocumentChunk, DocumentCreate
from app.shared.embeddings import get_embedding_provider

_splitter = RecursiveCharacterTextSplitter(
    separators=["\n\n", "\n", r"(?<=\. )"], 
    is_separator_regex=True,
    chunk_size=300,
    chunk_overlap=50
)


def _build_enriched_text(
    title: str, subject: str, level: str, chunk: str
) -> str:
    return (
        f"Title: {title}\n"
        f"Subject: {subject} | Level: {level}\n"
        f"Content: {chunk}"
    )


async def create_document(
    session: AsyncSession, data: DocumentCreate
) -> Document:
    provider = get_embedding_provider()

    chunks = _splitter.split_text(data.content)
    enriched_texts = [
        _build_enriched_text(data.title, data.subject, data.level, chunk)
        for chunk in chunks
    ]
    embeddings = await provider.embed_batch(enriched_texts)

    document = Document(
        title=data.title,
        content=data.content,
        subject=data.subject,
        level=data.level,
        chunk_count=len(chunks),
    )
    session.add(document)
    await session.flush()

    chunk_models = [
        DocumentChunk(
            document_id=document.id,
            chunk_text=chunk,
            embedding=embedding,
        )
        for chunk, embedding in zip(chunks, embeddings)
    ]
    session.add_all(chunk_models)

    await session.commit()
    await session.refresh(document)
    return document


async def bulk_create_documents(
    session: AsyncSession, items: list[DocumentCreate]
) -> list[Document]:
    if not items:
        return []

    provider = get_embedding_provider()

    all_chunks: list[tuple[int, str]] = []  # (doc_index, chunk_text)
    all_enriched: list[str] = []
    chunk_counts: list[int] = []
    for i, item in enumerate(items):
        chunks = _splitter.split_text(item.content)
        chunk_counts.append(len(chunks))
        for chunk in chunks:
            all_chunks.append((i, chunk))
            all_enriched.append(
                _build_enriched_text(item.title, item.subject, item.level, chunk)
            )

    embeddings = await provider.embed_batch(all_enriched) if all_enriched else []

    documents: list[Document] = []
    for item, count in zip(items, chunk_counts):
        doc = Document(
            title=item.title,
            content=item.content,
            subject=item.subject,
            level=item.level,
            chunk_count=count,
        )
        session.add(doc)
        documents.append(doc)
    await session.flush()

    chunk_models: list[DocumentChunk] = []
    for (doc_idx, chunk_text), embedding in zip(all_chunks, embeddings):
        chunk_models.append(
            DocumentChunk(
                document_id=documents[doc_idx].id,
                chunk_text=chunk_text,
                embedding=embedding,
            )
        )
    session.add_all(chunk_models)

    await session.commit()
    for doc in documents:
        await session.refresh(doc)

    return documents
