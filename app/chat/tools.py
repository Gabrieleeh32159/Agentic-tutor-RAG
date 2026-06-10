from __future__ import annotations

from typing import Annotated

import httpx
from langchain_core.callbacks import adispatch_custom_event
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool
from langgraph.prebuilt import InjectedState

from app.chat.prompts import (
    CONTEXT_LIMIT,
    GRADER_PROMPT,
    HIGH_RELEVANCE_THRESHOLD,
    LOW_RELEVANCE_THRESHOLD,
    MAX_RETRIES,
    NOT_FOUND_MESSAGE,
    REWRITE_PROMPT,
)
from app.search.models import SearchResult


def _format_results(results: list[SearchResult]) -> str:
    """Format search results into a text block for the LLM."""
    parts: list[str] = []
    idx = 1
    for doc in results:
        for chunk in doc.chunks:
            parts.append(f"[{idx}] File: {doc.filename}\n{chunk.chunk_text}")
            idx += 1
    return "\n\n".join(parts) if parts else "No results found."


def make_search_tool(
    http_client: httpx.AsyncClient,
    llm: BaseChatModel,
):
    @tool
    async def search_documents(
        query: str,
        session_id: Annotated[str, InjectedState("session_id")],
        config: RunnableConfig | None = None,
    ) -> str:
        """Search the user's uploaded documents for content relevant to their question. Use this tool whenever the user asks about the content of their documents or any factual/knowledge question."""
        current_query = query

        for attempt in range(MAX_RETRIES + 1):
            # --- 1. Search ---
            params: dict[str, str | int] = {
                "q": current_query,
                "limit": CONTEXT_LIMIT,
                "session_id": session_id,
            }

            response = await http_client.get("/search", params=params)
            response.raise_for_status()
            results = [SearchResult.model_validate(item) for item in response.json()]

            sources = [
                {
                    "document_id": str(doc.document_id),
                    "filename": doc.filename,
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
                            f"Question: {current_query}\n\nDocuments:\n{context_block}"
                        )
                    ),
                ]
                grade_response = await llm.ainvoke(grade_messages)
                answer = grade_response.content.strip().lower()
                is_relevant = answer.startswith("yes")

            await adispatch_custom_event(
                "grade_result",
                {
                    "is_relevant": is_relevant,
                    "attempt": attempt,
                    "query": current_query,
                },
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
