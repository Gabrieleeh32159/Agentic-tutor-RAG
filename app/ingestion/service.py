from __future__ import annotations

import asyncio
import logging
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.documents.models import Document, DocumentChunk, DocumentStatus
from app.ingestion import vision
from app.ingestion.base import ParsedBlock, ParsedDocument
from app.ingestion.chunking import build_enriched_text, chunk_blocks
from app.ingestion.registry import SUPPORTED_TYPES, get_parser
from app.shared.config import get_settings
from app.shared.database import get_session_factory
from app.shared.embeddings import get_embedding_provider
from app.shared.errors import AppError, ParseFailedError

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}

logger = logging.getLogger(__name__)

# Strong references to in-flight tasks (asyncio only keeps weak ones).
_tasks: set[asyncio.Task] = set()

# Bound concurrency: max 2 concurrent parse/OCR operations on this process.
# pypdf/pypdfium2 are sync CPU-bound; the semaphore limits event-loop starvation
# and peak memory on a single 512 MB container that also serves SSE streams.
MAX_CONCURRENT_INGESTIONS = 2

# Lazy-initialised so it binds to the running event loop, not the import-time
# loop (which can differ under pytest's per-test loop isolation).
_ingestion_semaphore: asyncio.Semaphore | None = None


def _get_semaphore() -> asyncio.Semaphore:
    global _ingestion_semaphore
    if _ingestion_semaphore is None:
        _ingestion_semaphore = asyncio.Semaphore(MAX_CONCURRENT_INGESTIONS)
    return _ingestion_semaphore


# Cap on the total number of documents allowed in the queue (pending + in-flight).
# Each queued task pins its data bytes (≤10 MB) in memory; without a cap a burst
# of uploads can exhaust the 512 MB container.
MAX_QUEUED_INGESTIONS = 10


def ingestion_queue_full() -> bool:
    """Return True when the in-flight task set is at or above the queue cap."""
    return len(_tasks) >= MAX_QUEUED_INGESTIONS


def schedule_processing(document_id: uuid.UUID, data: bytes, extension: str) -> None:
    """Fire-and-forget background processing; the upload endpoint returns 202."""
    task = asyncio.create_task(process_document(document_id, data, extension))
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)


async def wait_for_ingestion() -> None:
    """Test helper: wait until every scheduled ingestion task has finished."""
    while _tasks:
        await asyncio.gather(*list(_tasks), return_exceptions=True)


async def process_document(document_id: uuid.UUID, data: bytes, extension: str) -> None:
    """Parse -> OCR -> chunk -> embed -> save, updating status/stage/progress.

    Opens its own DB session (the request session is gone by the time this runs).
    Every stage transition commits so the polling endpoint sees progress.
    CPU-bound parsing and rasterization are offloaded to a thread pool via
    asyncio.to_thread; the semaphore bounds peak concurrency to 2.
    """
    async with _get_semaphore():
        factory = get_session_factory()
        async with factory() as db:
            document = await db.get(Document, document_id)
            if document is None:  # deleted before processing started
                return
            try:
                settings = get_settings()

                # --- parse ---
                await _set_stage(db, document, "parsing", progress=5)
                parser = get_parser(extension)
                if parser is None:  # defensive; router already validated
                    raise ParseFailedError(f"No parser for {extension}")
                # Offload CPU-bound sync parsing to a thread so the event loop
                # stays responsive. Module-attribute access ensures the
                # monkeypatch in tests bites correctly.
                parsed: ParsedDocument = await asyncio.to_thread(
                    parser.parse, data, document.filename
                )

                # --- ocr ---
                if parsed.needs_ocr_pages:
                    await _set_stage(db, document, "ocr", progress=10)
                    ocr_pages = parsed.needs_ocr_pages[: settings.MAX_OCR_PAGES_PER_DOC]
                    skipped = len(parsed.needs_ocr_pages) - len(ocr_pages)
                    if skipped:
                        logger.warning(
                            "Document %s: skipping OCR for %d pages beyond the cap",
                            document.id,
                            skipped,
                        )
                    for n, page_number in enumerate(ocr_pages, start=1):
                        if extension in IMAGE_EXTENSIONS:
                            # The upload IS the image; pass its real MIME type
                            # so the vision LLM gets the correct data URL scheme.
                            image_bytes = data
                            image_mime = SUPPORTED_TYPES.get(extension, "image/png")
                        else:
                            # Rasterize the scanned PDF page to PNG (CPU-bound).
                            image_bytes = await asyncio.to_thread(
                                vision.rasterize_pdf_page, data, page_number - 1
                            )
                            image_mime = "image/png"
                        text = vision.clean_transcription(
                            await vision.extract_text_from_image(
                                image_bytes, mime=image_mime
                            )
                        )
                        if text:
                            # OCR output joins the regular blocks with its page number
                            parsed.blocks.append(
                                ParsedBlock(text=text, page_number=page_number)
                            )
                        progress = 10 + int(40 * n / len(ocr_pages))
                        await _set_stage(db, document, "ocr", progress=progress)

                # --- chunk ---
                chunks = chunk_blocks(
                    parsed.blocks, max_chunks=settings.MAX_CHUNKS_PER_DOC
                )
                if not chunks:
                    raise ParseFailedError(
                        "No text could be extracted from the document"
                    )

                # --- embed ---
                await _set_stage(db, document, "embedding", progress=60)
                enriched = [
                    build_enriched_text(
                        document.filename, c.text, c.page_number, c.sheet_name
                    )
                    for c in chunks
                ]
                embeddings = await get_embedding_provider().embed_batch(enriched)

                # --- save ---
                await _set_stage(db, document, "saving", progress=90)
                db.add_all(
                    [
                        DocumentChunk(
                            document_id=document.id,
                            chunk_index=i,
                            page_number=chunk.page_number,
                            chunk_text=chunk.text,
                            embedding=embedding,
                        )
                        for i, (chunk, embedding) in enumerate(
                            zip(chunks, embeddings, strict=True)
                        )
                    ]
                )
                document.page_count = parsed.page_count
                document.chunk_count = len(chunks)
                document.status = DocumentStatus.READY
                document.stage = None
                document.progress = 100
                db.add(document)
                await db.commit()
            except Exception as exc:
                logger.exception("Failed to process document %s", document_id)
                await db.rollback()
                if isinstance(exc, AppError):
                    document.error_code = exc.code.lower()
                    document.error_message = exc.message
                else:
                    document.error_code = "processing_failed"
                    document.error_message = "Failed to process the document."
                document.status = DocumentStatus.FAILED
                document.stage = None
                document.progress = 0
                try:
                    db.add(document)
                    await db.commit()
                except Exception:
                    logger.exception(
                        "Could not persist FAILED status for document %s", document_id
                    )


async def _set_stage(
    db: AsyncSession, document: Document, stage: str, progress: int
) -> None:
    document.status = DocumentStatus.PROCESSING
    document.stage = stage
    document.progress = progress
    db.add(document)
    await db.commit()
