from __future__ import annotations

import logging

from langchain_core.messages import HumanMessage, SystemMessage

from app.chat.prompts import GROUNDING_PROMPT

logger = logging.getLogger(__name__)

GROUNDED = "grounded"
UNGROUNDED = "ungrounded"
UNVERIFIED = "unverified"

_MAX_EXCERPT_CHARS = 6000


async def check_grounding(llm, answer: str, chunks: list[str]) -> str:
    """LLM-judge the final answer against this turn's retrieved excerpts.

    Annotating only - never blocks the stream. Returns 'unverified' when the
    turn used no retrieval or the judge itself fails (fail-open).
    """
    if not chunks or not answer.strip():
        return UNVERIFIED

    excerpts = "\n\n".join(chunks)[:_MAX_EXCERPT_CHARS]
    messages = [
        SystemMessage(content=GROUNDING_PROMPT),
        HumanMessage(
            content=(
                f"Answer:\n{answer}\n\nRetrieved excerpts:\n"
                f"<retrieved-content>\n{excerpts}\n</retrieved-content>"
            )
        ),
    ]
    try:
        response = await llm.ainvoke(messages)
        verdict = str(response.content).strip().lower()
    except Exception:
        logger.warning("Grounding judge failed; verdict unverified", exc_info=True)
        return UNVERIFIED
    return GROUNDED if verdict.startswith("yes") else UNGROUNDED
