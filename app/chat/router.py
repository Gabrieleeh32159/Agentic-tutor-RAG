from __future__ import annotations

import json
import logging
import uuid

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from httpx import ASGITransport
from langchain_core.messages import AIMessage, HumanMessage
from sqlalchemy.ext.asyncio import AsyncSession

from app.chat.models import (
    ChatMessageResponse,
    ChatRequest,
    ChatSessionResponse,
    NodeName,
)
from app.chat.service import (
    build_graph,
    create_session,
    delete_session,
    get_session_by_id,
    get_session_messages,
    list_sessions,
    load_session_messages,
    save_messages,
    update_session_title,
)
from app.shared.database import get_session, get_session_factory

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/chat", tags=["chat"])


@router.post("")
async def chat(
    body: ChatRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> StreamingResponse:
    # --- Session management ---
    if body.session_id:
        chat_session = await get_session_by_id(session, body.session_id)
        if chat_session is None:
            raise HTTPException(status_code=404, detail="Session not found")
    else:
        chat_session = await create_session(
            session, subject=body.subject, level=body.level
        )

    session_id = chat_session.id

    # --- Load history + build state ---
    history = await load_session_messages(session, session_id)
    user_msg = HumanMessage(content=body.question)
    all_messages = history + [user_msg]

    initial_state = {
        "messages": all_messages,
        "subject": chat_session.subject or body.subject,
        "level": chat_session.level or body.level,
    }

    # --- Auto-title on first message ---
    if chat_session.title is None:
        await update_session_title(session, chat_session, body.question)

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
                async for event in graph.astream_events(initial_state, version="v2"):
                    kind = event["event"]

                    # --- Custom events from search tool ---
                    if kind == "on_custom_event":
                        name = event.get("name", "")

                        if name == "search_results":
                            data = event["data"]
                            sources = data.get("sources", [])
                            query = data.get("query", "")
                            attempt = data.get("attempt", 0)
                            yield f"data: {json.dumps({'step': 'retrieve', 'detail': f'Search attempt {attempt}: found {len(sources)} documents for \"{query}\"'})}\n\n"
                            yield f"data: {json.dumps({'sources': sources})}\n\n"

                        elif name == "grade_result":
                            data = event["data"]
                            is_relevant = data.get("is_relevant", False)
                            grade_query = data.get("query", "")
                            relevance_text = "relevant" if is_relevant else "not relevant"
                            yield f"data: {json.dumps({'step': 'grade_documents', 'is_relevant': is_relevant, 'query': grade_query, 'detail': f'Results for "{grade_query}" are {relevance_text}'})}\n\n"

                        elif name == "query_rewrite":
                            data = event["data"]
                            new_query = data.get("new_query", "")
                            attempt = data.get("attempt", 0)
                            yield f"data: {json.dumps({'step': 'rewrite_query', 'retry': attempt, 'new_question': new_query, 'detail': f'Rewriting query (attempt {attempt}): {new_query}'})}\n\n"

                    # --- Stream tokens from agent LLM ---
                    if kind == "on_chat_model_stream" and "agent_llm" in event.get("tags", []):
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

            except Exception as exc:
                logger.exception("Chat streaming failed")
                yield f"data: {json.dumps({'error': str(exc)})}\n\n"

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


# ---------------------------------------------------------------------------
# Session CRUD endpoints
# ---------------------------------------------------------------------------


@router.get("/sessions", response_model=list[ChatSessionResponse])
async def get_sessions(
    session: AsyncSession = Depends(get_session),
) -> list[ChatSessionResponse]:
    sessions = await list_sessions(session)
    return [
        ChatSessionResponse(
            id=s.id,
            title=s.title,
            subject=s.subject,
            level=s.level,
            created_at=s.created_at,
            updated_at=s.updated_at,
        )
        for s in sessions
    ]


@router.get("/sessions/{session_id}/messages", response_model=list[ChatMessageResponse])
async def get_messages(
    session_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
) -> list[ChatMessageResponse]:
    chat_session = await get_session_by_id(session, session_id)
    if chat_session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    messages = await get_session_messages(session, session_id)
    return [
        ChatMessageResponse(
            id=m.id,
            role=m.role,
            content=m.content,
            tool_calls=m.tool_calls,
            tool_call_id=m.tool_call_id,
            created_at=m.created_at,
        )
        for m in messages
    ]


@router.delete("/sessions/{session_id}", status_code=204)
async def remove_session(
    session_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
) -> None:
    deleted = await delete_session(session, session_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Session not found")
