from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.chat.models import ChatRequest
from app.chat.service import retrieve_context, stream_chat_response
from app.shared.database import get_session
from app.shared.llm import LLMUnavailableError, get_llm_provider

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/chat", tags=["chat"])


@router.post("")
async def chat(
    body: ChatRequest,
    session: AsyncSession = Depends(get_session),
) -> StreamingResponse:
    sources, context_docs = await retrieve_context(
        session=session,
        question=body.question,
        subject=body.subject,
        level=body.level,
    )

    llm = get_llm_provider()

    async def event_stream():
        # First, emit the source document IDs as a JSON event
        sources_payload = json.dumps(
            {"sources": [{"id": str(s.id), "title": s.title, "score": s.score} for s in sources]}
        )
        yield f"data: {sources_payload}\n\n"

        # Then stream the LLM answer token by token
        try:
            async for token in stream_chat_response(llm, body.question, context_docs):
                yield f"data: {json.dumps({'token': token})}\n\n"
            
            yield "data: [DONE]\n\n"
        except LLMUnavailableError:
            yield f"data: {json.dumps({'error': 'All LLM providers are unavailable'})}\n\n"
        except Exception as exc:
            logger.exception("LLM streaming failed")
            yield f"data: {json.dumps({'error': str(exc)})}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
    )
