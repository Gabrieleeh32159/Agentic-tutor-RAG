from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Request, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.documents.models import DocumentResponse
from app.documents.service import (
    count_documents,
    create_pending_document,
    delete_document,
    list_documents,
)
from app.ingestion.registry import SUPPORTED_TYPES, sniff_matches_extension
from app.ingestion.service import ingestion_queue_full, schedule_processing
from app.sessions.service import get_active_session, touch_session
from app.shared.config import get_settings
from app.shared.database import get_session
from app.shared.errors import (
    FileTooLargeError,
    IngestionBusyError,
    SessionLimitExceededError,
    UnsupportedFileTypeError,
)
from app.shared.rate_limit import limiter

router = APIRouter(prefix="/sessions/{session_id}/documents", tags=["documents"])


def _extension(filename: str) -> str:
    dot = filename.rfind(".")
    return filename[dot:].lower() if dot != -1 else ""


@router.post("", response_model=DocumentResponse, status_code=status.HTTP_202_ACCEPTED)
@limiter.limit("10/hour")
async def upload_document(
    session_id: uuid.UUID,
    request: Request,
    file: UploadFile,
    db: AsyncSession = Depends(get_session),
) -> DocumentResponse:
    session = await get_active_session(db, session_id)
    settings = get_settings()

    # Validation order: session → doc-count cap → extension → bounded read → size → sniff
    if await count_documents(db, session_id) >= settings.MAX_DOCS_PER_SESSION:
        raise SessionLimitExceededError(
            f"This session already has {settings.MAX_DOCS_PER_SESSION} documents"
        )

    if ingestion_queue_full():
        raise IngestionBusyError(
            "The server is processing too many documents right now. Try again shortly."
        )

    filename = file.filename or "upload"
    ext = _extension(filename)
    if ext not in SUPPORTED_TYPES:
        supported = ", ".join(sorted(SUPPORTED_TYPES))
        raise UnsupportedFileTypeError(
            f"Unsupported file type '{ext or filename}'. Supported: {supported}"
        )

    data = await file.read(settings.MAX_UPLOAD_BYTES + 1)
    if len(data) > settings.MAX_UPLOAD_BYTES:
        limit_mb = settings.MAX_UPLOAD_BYTES // (1024 * 1024)
        raise FileTooLargeError(f"File exceeds the {limit_mb} MB limit")

    if not sniff_matches_extension(data, ext):
        raise UnsupportedFileTypeError(
            f"File content does not match the '{ext}' extension"
        )

    document = await create_pending_document(
        db,
        session_id=session_id,
        filename=filename,
        mime_type=SUPPORTED_TYPES[ext],
        size_bytes=len(data),
    )
    await touch_session(db, session)
    schedule_processing(document.id, data, ext)
    return DocumentResponse.model_validate(document, from_attributes=True)


@router.get("", response_model=list[DocumentResponse])
async def get_documents(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_session),
) -> list[DocumentResponse]:
    await get_active_session(db, session_id)
    documents = await list_documents(db, session_id)
    return [DocumentResponse.model_validate(d, from_attributes=True) for d in documents]


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_document(
    session_id: uuid.UUID,
    document_id: uuid.UUID,
    db: AsyncSession = Depends(get_session),
) -> None:
    await get_active_session(db, session_id)
    await delete_document(db, session_id, document_id)
