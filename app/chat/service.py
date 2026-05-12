from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Annotated, Any

import httpx
from langchain_core.callbacks import adispatch_custom_event
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool
from langgraph.graph import END, StateGraph
from langgraph.prebuilt import InjectedState, ToolNode, tools_condition
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.chat.models import (
    AgentState,
    ChatMessage,
    ChatSession,
    NodeName,
)
from app.search.models import SearchResult
from app.shared.llm import get_chat_model

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = (
    "You are an educational AI study assistant. "
    "When a student asks anything, use the search_documents tool to find "
    "relevant information from the knowledge base, "
    "then answer citing sources by their title. Never answer from your own knowledge."
    "Be concise, accurate, and helpful. Always answer in Markdown format."
)

GRADER_PROMPT = ("Be concise, accurate, and helpful."
    "You are a relevance grader. Given a student question and retrieved documents, "
    "determine if the documents contain information that could help answer the question. "
    "Be lenient: if the documents are even partially related to the topic or could "
    "provide useful context, respond 'yes'. Only respond 'no' if the documents are "
    "completely unrelated to the question. "
    "Respond with exactly 'yes' or 'no'."
)

REWRITE_PROMPT = (
    "You are a query rewriter. Given a student question that did not return relevant "
    "results, rewrite the question to improve retrieval. Keep the same intent but use "
    "different keywords or phrasing. Return only the rewritten question, nothing else."
)

CONTEXT_LIMIT = 5
MAX_RETRIES = 2
NOT_FOUND_MESSAGE = (
    "No relevant documents were found in the knowledge base for this query."
)

# ---------------------------------------------------------------------------
# Session / message persistence
# ---------------------------------------------------------------------------


async def create_session(
    session: AsyncSession,
    *,
    subject: str | None = None,
    level: str | None = None,
) -> ChatSession:
    chat_session = ChatSession(subject=subject, level=level)
    session.add(chat_session)
    await session.commit()
    await session.refresh(chat_session)
    return chat_session


async def get_session_by_id(
    session: AsyncSession,
    session_id: uuid.UUID,
) -> ChatSession | None:
    return await session.get(ChatSession, session_id)


async def update_session_title(
    session: AsyncSession,
    chat_session: ChatSession,
    title: str,
) -> None:
    chat_session.title = title[:120]
    chat_session.updated_at = datetime.now(timezone.utc)
    session.add(chat_session)
    await session.commit()


async def list_sessions(session: AsyncSession) -> list[ChatSession]:
    result = await session.execute(
        select(ChatSession).order_by(ChatSession.created_at.desc())
    )
    return list(result.scalars().all())


async def delete_session(session: AsyncSession, session_id: uuid.UUID) -> bool:
    chat_session = await session.get(ChatSession, session_id)
    if chat_session is None:
        return False
    await session.delete(chat_session)
    await session.commit()
    return True


async def load_session_messages(
    session: AsyncSession,
    session_id: uuid.UUID,
) -> list[BaseMessage]:
    result = await session.execute(
        select(ChatMessage)
        .where(ChatMessage.session_id == session_id)
        .order_by(ChatMessage.created_at)
    )
    rows = result.scalars().all()
    messages: list[BaseMessage] = []
    for row in rows:
        if row.role == "human":
            messages.append(HumanMessage(content=row.content))
        elif row.role == "ai":
            tc = json.loads(row.tool_calls) if row.tool_calls else []
            messages.append(AIMessage(content=row.content, tool_calls=tc))
        elif row.role == "tool":
            messages.append(
                ToolMessage(content=row.content, tool_call_id=row.tool_call_id or "")
            )
        elif row.role == "system":
            messages.append(SystemMessage(content=row.content))
    return messages


async def save_messages(
    session: AsyncSession,
    session_id: uuid.UUID,
    messages: list[BaseMessage],
) -> None:
    for msg in messages:
        role = msg.type  # "human", "ai", "tool", "system"
        # Normalize chunk types (e.g. "AIMessageChunk" -> "ai")
        if role.endswith("Chunk"):
            role = {"AIMessageChunk": "ai", "HumanMessageChunk": "human", "SystemMessageChunk": "system"}.get(role, role)
        content = msg.content if isinstance(msg.content, str) else json.dumps(msg.content)
        tool_calls_json: str | None = None
        tool_call_id: str | None = None

        if isinstance(msg, AIMessage) and msg.tool_calls:
            tool_calls_json = json.dumps(msg.tool_calls)
        if isinstance(msg, ToolMessage):
            tool_call_id = msg.tool_call_id

        row = ChatMessage(
            session_id=session_id,
            role=role,
            content=content,
            tool_calls=tool_calls_json,
            tool_call_id=tool_call_id,
        )
        session.add(row)
    await session.commit()


async def get_session_messages(
    session: AsyncSession,
    session_id: uuid.UUID,
) -> list[ChatMessage]:
    result = await session.execute(
        select(ChatMessage)
        .where(ChatMessage.session_id == session_id)
        .order_by(ChatMessage.created_at)
    )
    return list(result.scalars().all())


# ---------------------------------------------------------------------------
# Search tool with internal quality loop
# ---------------------------------------------------------------------------


def _format_results(results: list[SearchResult]) -> str:
    """Format search results into a text block for the LLM."""
    parts: list[str] = []
    idx = 1
    for doc in results:
        for chunk in doc.chunks:
            parts.append(f"[{idx}] Title: {doc.title}\n{chunk.chunk_text}")
            idx += 1
    return "\n\n".join(parts) if parts else "No results found."


def make_search_tool(
    http_client: httpx.AsyncClient,
    llm: BaseChatModel,
):
    @tool
    async def search_documents(
        query: str,
        subject: Annotated[str | None, InjectedState("subject")] = None,
        level: Annotated[str | None, InjectedState("level")] = None,
        config: RunnableConfig | None = None,
    ) -> str:
        """Search the educational knowledge base for documents relevant to a student's question. Use this tool when the student asks an academic or knowledge-based question that requires looking up information."""
        current_query = query

        for attempt in range(MAX_RETRIES + 1):
            # --- 1. Search ---
            params: dict[str, str | int] = {
                "q": current_query,
                "limit": CONTEXT_LIMIT,
            }
            if subject:
                params["subject"] = subject
            if level:
                params["level"] = level

            response = await http_client.get("/search", params=params)
            response.raise_for_status()
            results = [SearchResult.model_validate(item) for item in response.json()]

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
                for doc in results
            ]

            await adispatch_custom_event(
                "search_results",
                {"sources": sources, "query": current_query, "attempt": attempt},
                config=config,
            )

            # --- 2. Grade relevance ---
            if not results:
                is_relevant = False
            else:
                context_block = _format_results(results)
                grade_messages = [
                    SystemMessage(content=GRADER_PROMPT),
                    HumanMessage(
                        content=(
                            f"Question: {current_query}\n\n"
                            f"Documents:\n{context_block}"
                        )
                    ),
                ]
                grade_response = await llm.ainvoke(grade_messages)
                answer = grade_response.content.strip().lower()
                is_relevant = answer.startswith("yes")

            await adispatch_custom_event(
                "grade_result",
                {"is_relevant": is_relevant, "attempt": attempt, "query": current_query},
                config=config,
            )

            if is_relevant:
                return _format_results(results)

            # --- 3. Rewrite query (if retries remain) ---
            if attempt < MAX_RETRIES:
                rewrite_messages = [
                    SystemMessage(content=REWRITE_PROMPT),
                    HumanMessage(content=current_query),
                ]
                rewrite_response = await llm.ainvoke(rewrite_messages)
                new_query = rewrite_response.content.strip()

                await adispatch_custom_event(
                    "query_rewrite",
                    {
                        "original_query": current_query,
                        "new_query": new_query,
                        "attempt": attempt + 1,
                    },
                    config=config,
                )
                current_query = new_query

        return NOT_FOUND_MESSAGE

    return search_documents


# ---------------------------------------------------------------------------
# Agent graph
# ---------------------------------------------------------------------------


def _make_agent_node(llm_with_tools: BaseChatModel):
    async def agent(state: AgentState, config: RunnableConfig) -> dict[str, Any]:
        messages = state.get("messages", [])
        if not any(isinstance(m, SystemMessage) for m in messages):
            messages = [SystemMessage(content=SYSTEM_PROMPT)] + list(messages)
        tagged_config = {**config, "tags": [*(config.get("tags") or []), "agent_llm"]}
        full_response = None
        async for chunk in llm_with_tools.astream(messages, config=tagged_config):
            if full_response is None:
                full_response = chunk
            else:
                full_response += chunk
        return {"messages": [full_response]}

    return agent


def build_graph(
    http_client: httpx.AsyncClient,
    llm: BaseChatModel | None = None,
):
    if llm is None:
        llm = get_chat_model()

    search_tool = make_search_tool(http_client, llm)
    llm_with_tools = llm.bind_tools([search_tool])

    workflow = StateGraph(AgentState)

    workflow.add_node(NodeName.AGENT, _make_agent_node(llm_with_tools))
    workflow.add_node(NodeName.TOOLS, ToolNode([search_tool]))

    workflow.set_entry_point(NodeName.AGENT)
    workflow.add_conditional_edges(
        NodeName.AGENT,
        tools_condition,
        {NodeName.TOOLS: NodeName.TOOLS, END: END},
    )
    workflow.add_edge(NodeName.TOOLS, NodeName.AGENT)

    return workflow.compile()
