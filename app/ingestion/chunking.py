from __future__ import annotations

import logging

from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.ingestion.base import Chunk, ParsedBlock

logger = logging.getLogger(__name__)

_splitter = RecursiveCharacterTextSplitter(
    separators=["\n\n", "\n", r"(?<=\. )"],
    is_separator_regex=True,
    chunk_size=300,
    chunk_overlap=50,
)


def chunk_blocks(
    blocks: list[ParsedBlock], max_chunks: int | None = None
) -> list[Chunk]:
    """Split parsed blocks into embeddable chunks, preserving source location.

    Atomic blocks (pre-chunked, e.g. xlsx markdown tables) pass through unsplit.
    """
    chunks: list[Chunk] = []
    for block in blocks:
        if block.is_atomic:
            chunks.append(
                Chunk(
                    text=block.text,
                    page_number=block.page_number,
                    sheet_name=block.sheet_name,
                )
            )
            continue
        for piece in _splitter.split_text(block.text):
            chunks.append(
                Chunk(
                    text=piece,
                    page_number=block.page_number,
                    sheet_name=block.sheet_name,
                )
            )
    if max_chunks is not None and len(chunks) > max_chunks:
        logger.warning(
            "Document produced %d chunks; truncating to %d", len(chunks), max_chunks
        )
        chunks = chunks[:max_chunks]
    return chunks


def build_enriched_text(
    filename: str,
    chunk: str,
    page_number: int | None = None,
    sheet_name: str | None = None,
) -> str:
    """Text that actually gets embedded: file context + chunk content."""
    location = ""
    if page_number is not None:
        location = f" | Page: {page_number}"
    elif sheet_name is not None:
        location = f" | Sheet: {sheet_name}"
    return f"File: {filename}{location}\nContent: {chunk}"
