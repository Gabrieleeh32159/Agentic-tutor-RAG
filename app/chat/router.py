from __future__ import annotations

import json
import logging

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from httpx import ASGITransport

from app.chat.models import ChatRequest, NodeName
from app.chat.service import build_graph

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/chat", tags=["chat"])


@router.post("")
async def chat(
    body: ChatRequest,
    request: Request,
) -> StreamingResponse:
    initial_state = {
        "question": body.question,
        "subject": body.subject,
        "level": body.level,
    }

    async def event_stream():
        transport = ASGITransport(app=request.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://internal") as http_client:
            graph = build_graph(http_client)

            try:
                sources_emitted = False
                async for event in graph.astream_events(initial_state, version="v2"):
                    kind = event["event"]

                    # Emit sources after retrieval completes
                    if (
                        kind == "on_chain_end"
                        and event.get("name") == NodeName.RETRIEVE
                        and not sources_emitted
                    ):
                        documents = event["data"]["output"].get("documents", [])
                        sources = [
                            {
                                "document_id": str(doc.document_id),
                                "title": doc.title,
                                "score": doc.score,
                                "chunks": [
                                    {
                                        "chunk_id": str(c.chunk_id),
                                        "chunk_text": c.chunk_text,
                                        "score": c.score,
                                    }
                                    for c in doc.chunks
                                ],
                            }
                            for doc in documents
                        ]
                        yield f"data: {json.dumps({'step': NodeName.RETRIEVE, 'detail': f'Found {len(documents)} relevant documents'})}\n\n"
                        yield f"data: {json.dumps({'sources': sources})}\n\n"
                        sources_emitted = True

                    # Emit grading decision
                    if kind == "on_chain_end" and event.get("name") == NodeName.GRADE_DOCUMENTS:
                        output = event["data"]["output"]
                        is_relevant = output.get("is_relevant", False)
                        yield f"data: {json.dumps({'step': NodeName.GRADE_DOCUMENTS, 'is_relevant': is_relevant, 'detail': 'Documents are relevant' if is_relevant else 'Documents are not relevant'})}\n\n"

                    # Emit query rewrite
                    if kind == "on_chain_end" and event.get("name") == NodeName.REWRITE_QUERY:
                        output = event["data"]["output"]
                        new_question = output.get("question", "")
                        retry = output.get("retry_count", 0)
                        yield f"data: {json.dumps({'step': NodeName.REWRITE_QUERY, 'retry': retry, 'new_question': new_question, 'detail': f'Rewriting query (attempt {retry}): {new_question}'})}\n\n"
                        sources_emitted = False

                    # Emit generate step start
                    if kind == "on_chain_start" and event.get("name") == NodeName.GENERATE:
                        yield f"data: {json.dumps({'step': NodeName.GENERATE, 'detail': 'Generating answer from context...'})}\n\n"

                    # Stream tokens from the generate node's LLM call
                    if kind == "on_chat_model_stream":
                        tags = event.get("tags", [])
                        if "generator" in tags:
                            chunk = event["data"]["chunk"]
                            token = chunk.content if hasattr(chunk, "content") else str(chunk)
                            if token:
                                yield f"data: {json.dumps({'token': token})}\n\n"

                    # Capture not_found generation
                    if kind == "on_chain_end" and event.get("name") == NodeName.NOT_FOUND:
                        yield f"data: {json.dumps({'step': NodeName.NOT_FOUND, 'detail': 'No relevant information found'})}\n\n"
                        message = event["data"]["output"].get("generation", "")
                        if message:
                            yield f"data: {json.dumps({'token': message})}\n\n"

                yield "data: [DONE]\n\n"
            except Exception as exc:
                logger.exception("Chat streaming failed")
                yield f"data: {json.dumps({'error': str(exc)})}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
    )
