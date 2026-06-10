from __future__ import annotations

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.documents.models import DocumentCreate, DocumentResponse
from app.documents.service import bulk_create_documents, create_document
from app.shared.database import get_session

router = APIRouter(prefix="/documents", tags=["documents"])


@router.post(
    "",
    response_model=DocumentResponse,
    status_code=status.HTTP_201_CREATED,
)
async def ingest_document(
    data: DocumentCreate,
    session: AsyncSession = Depends(get_session),
) -> DocumentResponse:
    document = await create_document(session, data)
    return DocumentResponse.model_validate(document)


@router.post(
    "/bulk",
    response_model=list[DocumentResponse],
    status_code=status.HTTP_201_CREATED,
)
async def ingest_documents_bulk(
    data: list[DocumentCreate],
    session: AsyncSession = Depends(get_session),
) -> list[DocumentResponse]:
    documents = await bulk_create_documents(session, data)
    return [DocumentResponse.model_validate(doc) for doc in documents]
