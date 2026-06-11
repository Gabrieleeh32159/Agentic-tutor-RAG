from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.documents.models import DocumentResponse
from app.documents.service import (
    create_pending_document,
    delete_document,
    list_documents,
    process_text_document,
)
from app.sessions.service import get_active_session, touch_session
from app.shared.config import get_settings
from app.shared.database import get_session
from app.shared.errors import (
    FileTooLargeError,
    ParseFailedError,
    UnsupportedFileTypeError,
)

router = APIRouter(prefix="/sessions/{session_id}/documents", tags=["documents"])

# Phase 1 supports plain-text formats only; Phase 2 adds the parser registry
# (pdf/docx/xlsx/images) behind the same endpoint.
TEXT_EXTENSIONS = {".txt": "text/plain", ".md": "text/markdown"}


def _extension(filename: str) -> str:
    dot = filename.rfind(".")
    return filename[dot:].lower() if dot != -1 else ""


@router.post("", response_model=DocumentResponse, status_code=status.HTTP_202_ACCEPTED)
async def upload_document(
    session_id: uuid.UUID,
    file: UploadFile,
    db: AsyncSession = Depends(get_session),
) -> DocumentResponse:
    session = await get_active_session(db, session_id)

    filename = file.filename or "upload"
    ext = _extension(filename)
    if ext not in TEXT_EXTENSIONS:
        supported = ", ".join(sorted(TEXT_EXTENSIONS))
        raise UnsupportedFileTypeError(
            f"Unsupported file type '{ext or filename}'. Supported: {supported}"
        )

    settings = get_settings()
    data = await file.read(settings.MAX_UPLOAD_BYTES + 1)
    if len(data) > settings.MAX_UPLOAD_BYTES:
        limit_mb = settings.MAX_UPLOAD_BYTES // (1024 * 1024)
        raise FileTooLargeError(f"File exceeds the {limit_mb} MB limit")

    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ParseFailedError("File is not valid UTF-8 text") from exc

    if not text.strip():
        raise ParseFailedError("File contains no text")

    document = await create_pending_document(
        db,
        session_id=session_id,
        filename=filename,
        mime_type=TEXT_EXTENSIONS[ext],
        size_bytes=len(data),
    )
    # Phase 1 processes inline; Phase 2 moves this into a background task,
    # which is why the endpoint already returns 202 + status fields.
    document = await process_text_document(db, document, text)
    await touch_session(db, session)
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
