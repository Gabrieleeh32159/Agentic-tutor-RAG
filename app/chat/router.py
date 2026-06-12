from __future__ import annotations

import asyncio
import json
import logging

import httpx
from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from httpx import ASGITransport
from langchain_core.messages import HumanMessage, SystemMessage
from sqlalchemy.ext.asyncio import AsyncSession

from app.chat.models import ChatRequest, NodeName
from app.chat.service import (
    SYSTEM_PROMPT,
    build_graph,
    load_session_messages,
    save_messages,
)
from app.sessions.service import get_active_session, touch_session, update_session_title
from app.shared.config import get_settings
from app.shared.database import get_session, get_session_factory
from app.shared.rate_limit import limiter

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/chat", tags=["chat"])


@router.post("")
@limiter.limit("20/minute")
async def chat(
    body: ChatRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> StreamingResponse:
    # --- Session management ---
    chat_session = await get_active_session(session, body.session_id)
    session_id = chat_session.id

    # --- Load history + build state ---
    history = await load_session_messages(session, session_id)
    user_msg = HumanMessage(content=body.question)
    all_messages = [SystemMessage(content=SYSTEM_PROMPT)] + history + [user_msg]

    initial_state = {
        "messages": all_messages,
        "session_id": str(session_id),
    }

    # --- Auto-title on first message ---
    if chat_session.title is None:
        await update_session_title(session, chat_session, body.question)

    await touch_session(session, chat_session)

    async def event_stream():
        transport = ASGITransport(app=request.app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://internal"
        ) as http_client:
            graph = build_graph(http_client)

            # Emit session_id first
            yield f"data: {json.dumps({'session_id': str(session_id)})}\n\n"

            new_messages: list = []

            try:
                async with asyncio.timeout(get_settings().CHAT_STREAM_TIMEOUT_SECONDS):
                    async for event in graph.astream_events(
                        initial_state, version="v2"
                    ):
                        kind = event["event"]

                        # --- Custom events from search tool ---
                        if kind == "on_custom_event":
                            name = event.get("name", "")

                            if name == "search_results":
                                data = event["data"]
                                sources = data.get("sources", [])
                                query = data.get("query", "")
                                attempt = data.get("attempt", 0)
                                yield f"data: {json.dumps({'step': 'retrieve', 'detail': f'Search attempt {attempt}: found {len(sources)} documents for "{query}"'})}\n\n"
                                yield f"data: {json.dumps({'sources': sources})}\n\n"

                            elif name == "grade_result":
                                data = event["data"]
                                is_relevant = data.get("is_relevant", False)
                                grade_query = data.get("query", "")
                                relevance_text = (
                                    "relevant" if is_relevant else "not relevant"
                                )
                                yield f"data: {json.dumps({'step': 'grade_documents', 'is_relevant': is_relevant, 'query': grade_query, 'detail': f'Results for "{grade_query}" are {relevance_text}'})}\n\n"

                            elif name == "query_rewrite":
                                data = event["data"]
                                new_query = data.get("new_query", "")
                                attempt = data.get("attempt", 0)
                                yield f"data: {json.dumps({'step': 'rewrite_query', 'retry': attempt, 'new_question': new_query, 'detail': f'Rewriting query (attempt {attempt}): {new_query}'})}\n\n"

                        # --- Stream tokens from agent LLM ---
                        if kind == "on_chat_model_stream" and "agent_llm" in event.get(
                            "tags", []
                        ):
                            chunk = event["data"]["chunk"]
                            token = (
                                chunk.content
                                if hasattr(chunk, "content")
                                else str(chunk)
                            )
                            if token:
                                yield f"data: {json.dumps({'token': token})}\n\n"

                        # --- Capture messages from agent and tools for persistence ---
                        if kind == "on_chain_end" and event.get("name") in (
                            NodeName.AGENT,
                            NodeName.TOOLS,
                        ):
                            output = event["data"].get("output", {})
                            msgs = output.get("messages", [])
                            new_messages.extend(msgs)

            except TimeoutError:
                logger.exception("Chat stream timed out")
                yield (
                    "data: "
                    + json.dumps(
                        {
                            "error": {
                                "code": "STREAM_TIMEOUT",
                                "message": "The response took too long and was stopped.",
                            }
                        }
                    )
                    + "\n\n"
                )
            except Exception:
                logger.exception("Chat streaming failed")
                yield (
                    "data: "
                    + json.dumps(
                        {
                            "error": {
                                "code": "STREAM_FAILED",
                                "message": "The response could not be completed. Please try again.",
                            }
                        }
                    )
                    + "\n\n"
                )

            # --- Persist new messages BEFORE yielding [DONE] ---
            # (After the last yield, the client may disconnect and cancel the generator)
            try:
                async with get_session_factory()() as db:
                    msgs_to_save = [user_msg] + new_messages
                    await save_messages(db, session_id, msgs_to_save)
            except Exception:
                logger.exception("Failed to save messages")

            yield "data: [DONE]\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
    )
