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
    "You are a friendly and helpful educational AI study assistant for uDocz. "
    "You love helping students learn and always respond in a warm, encouraging tone.\n\n"
    "## Conversation\n"
    "- For greetings, casual chat, follow-up questions, or clarifications, "
    "respond naturally and warmly WITHOUT using the search tool.\n"
    "- When continuing a conversation, consider the previous context.\n\n"
    "## Academic questions\n"
    "- Use the search_documents tool ONLY for academic, factual, or knowledge-based questions.\n"
    "- Base your answer on the retrieved documents. Cite sources inline using [Title] format, "
    "e.g. 'According to [Calculus I], derivatives measure rates of change.'\n"
    "- If no relevant documents are found, say so honestly.\n\n"
    "## Format\n"
    "- ALWAYS respond in well-structured Markdown.\n"
    "- Use headers (##, ###), bold, bullet points, and numbered lists to organize content.\n"
    "- For math equations, ALWAYS use LaTeX wrapped in dollar signs: "
    "inline math with $...$ and block math with $$...$$.\n"
    "  Example: 'The derivative is $f'(x) = 2x$' or a block:\n"
    "  $$\\frac{dy}{dx} = f'(g(x)) \\cdot g'(x)$$\n"
    "- Never write raw LaTeX without dollar sign delimiters."
)

GRADER_PROMPT = (
    "You are a relevance grader. Given a student question and retrieved documents, "
    "determine if the documents contain information relevant to the question. "
    "Be lenient: if the documents are even partially related or provide useful context, "
    "respond 'yes'. Only respond 'no' if the documents are completely unrelated. "
    "Respond with exactly 'yes' or 'no'."
)

REWRITE_PROMPT = (
    "You are a query rewriter for an educational search engine. "
    "The original query did not return relevant results. "
    "Rewrite it using synonyms, broader/narrower terms, or academic phrasing "
    "to improve retrieval. Keep the same intent. "
    "Return only the rewritten question, nothing else."
)

CONTEXT_LIMIT = 5
MAX_RETRIES = 2
HIGH_RELEVANCE_THRESHOLD = 0.75
LOW_RELEVANCE_THRESHOLD = 0.25
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
        if isinstance(msg, HumanMessage):
            role = "human"
        elif isinstance(msg, ToolMessage):
            role = "tool"
        elif isinstance(msg, AIMessage):
            role = "ai"
        elif isinstance(msg, SystemMessage):
            role = "system"
        else:
            role = msg.type
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
            elif results[0].score >= HIGH_RELEVANCE_THRESHOLD:
                is_relevant = True
            elif results[0].score < LOW_RELEVANCE_THRESHOLD:
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
                    HumanMessage(
                        content=f"Original query: {query}\nFailed query: {current_query}"
                        if query != current_query
                        else current_query
                    ),
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
