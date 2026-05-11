from __future__ import annotations

import logging
from typing import Any

import httpx
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import END, StateGraph

from app.chat.models import AgentState
from app.search.models import SearchChunk, SearchResult
from app.shared.llm import get_chat_model

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    "You are an educational AI study assistant. "
    "Answer the student's question using ONLY the provided context documents. "
    "Cite sources by their title when you use information from them. "
    "If the context does not contain enough information to answer, say so clearly. "
    "Be concise, accurate, and helpful."
)

GRADER_PROMPT = (
    "You are a relevance grader. Given a student question and retrieved documents, "
    "determine if the documents contain information relevant to answering the question. "
    "Respond with exactly 'yes' or 'no'."
)

CONTEXT_LIMIT = 5
MAX_RETRIES = 2

REWRITE_PROMPT = (
    "You are a query rewriter. Given a student question that did not return relevant results, "
    "rewrite the question to improve retrieval. Keep the same intent but use different keywords "
    "or phrasing. Return only the rewritten question, nothing else."
)

NOT_FOUND_MESSAGE = (
    "I'm sorry, I couldn't find relevant information in our knowledge base "
    "to answer your question. Please try rephrasing or asking about a different topic."
)


def _build_context_block(state: AgentState) -> str:
    parts: list[str] = []
    idx = 1
    for doc in state.get("documents", []):
        for chunk in doc.chunks:
            parts.append(f"[{idx}] Title: {doc.title}\n{chunk.chunk_text}")
            idx += 1
    return "\n\n".join(parts)


def _make_retrieve_node(http_client: httpx.AsyncClient):
    async def retrieve(state: AgentState) -> dict[str, Any]:
        params: dict[str, str | int] = {
            "q": state["question"],
            "limit": CONTEXT_LIMIT,
        }
        if state.get("subject"):
            params["subject"] = state["subject"]
        if state.get("level"):
            params["level"] = state["level"]

        response = await http_client.get("/search", params=params)
        response.raise_for_status()

        results = [SearchResult.model_validate(item) for item in response.json()]
        return {"documents": results}

    return retrieve


def _make_grade_node(llm: BaseChatModel):
    async def grade_documents(state: AgentState) -> dict[str, Any]:
        documents = state.get("documents", [])
        if not documents:
            return {"is_relevant": False}

        context = _build_context_block(state)
        messages = [
            SystemMessage(content=GRADER_PROMPT),
            HumanMessage(
                content=(
                    f"Question: {state['question']}\n\n"
                    f"Documents:\n{context}"
                )
            ),
        ]
        response = await llm.ainvoke(messages)
        answer = response.content.strip().lower()
        return {"is_relevant": answer.startswith("yes")}

    return grade_documents


def _make_generate_node(llm: BaseChatModel):
    tagged_llm = llm.with_config(tags=["generator"])

    async def generate(state: AgentState) -> dict[str, Any]:
        context = _build_context_block(state)
        messages = [
            SystemMessage(content=SYSTEM_PROMPT),
            HumanMessage(
                content=(
                    f"Context documents:\n{context}\n\n"
                    f"Student question: {state['question']}"
                )
            ),
        ]
        full_response = ""
        async for chunk in tagged_llm.astream(messages):
            full_response += chunk.content if hasattr(chunk, "content") else str(chunk)
        return {"generation": full_response}

    return generate


def _make_rewrite_node(llm: BaseChatModel):
    async def rewrite_query(state: AgentState) -> dict[str, Any]:
        messages = [
            SystemMessage(content=REWRITE_PROMPT),
            HumanMessage(content=state["question"]),
        ]
        response = await llm.ainvoke(messages)
        new_question = response.content.strip()
        retry_count = state.get("retry_count", 0) + 1
        return {"question": new_question, "retry_count": retry_count}

    return rewrite_query


async def not_found(state: AgentState) -> dict[str, Any]:
    return {"generation": NOT_FOUND_MESSAGE}


def _route_after_grading(state: AgentState) -> str:
    if state.get("is_relevant"):
        return "generate"
    if state.get("retry_count", 0) < MAX_RETRIES:
        return "rewrite_query"
    return "not_found"


def build_graph(
    http_client: httpx.AsyncClient,
    llm: BaseChatModel | None = None,
) -> StateGraph:
    if llm is None:
        llm = get_chat_model()

    workflow = StateGraph(AgentState)

    workflow.add_node("retrieve", _make_retrieve_node(http_client))
    workflow.add_node("grade_documents", _make_grade_node(llm))
    workflow.add_node("rewrite_query", _make_rewrite_node(llm))
    workflow.add_node("generate", _make_generate_node(llm))
    workflow.add_node("not_found", not_found)

    workflow.set_entry_point("retrieve")
    workflow.add_edge("retrieve", "grade_documents")
    workflow.add_conditional_edges(
        "grade_documents",
        _route_after_grading,
        {"generate": "generate", "rewrite_query": "rewrite_query", "not_found": "not_found"},
    )
    workflow.add_edge("rewrite_query", "retrieve")
    workflow.add_edge("generate", END)
    workflow.add_edge("not_found", END)

    return workflow.compile()
