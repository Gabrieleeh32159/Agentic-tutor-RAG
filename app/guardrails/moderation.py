from __future__ import annotations

import logging
from dataclasses import dataclass, field

from openai import AsyncOpenAI

from app.shared.config import get_settings

logger = logging.getLogger(__name__)

_client: AsyncOpenAI | None = None


def _get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        settings = get_settings()
        _client = AsyncOpenAI(
            api_key=settings.OPENAI_API_KEY,
            timeout=10.0,
            max_retries=1,
        )
    return _client


@dataclass
class ModerationResult:
    flagged: bool
    categories: list[str] = field(default_factory=list)
    degraded: bool = False  # True when moderation could not run (fail-open)


async def moderate_text(text: str) -> ModerationResult:
    """OpenAI moderation. Raises on transport errors - the caller decides the
    fail-open policy."""
    response = await _get_client().moderations.create(
        model="omni-moderation-latest",
        input=text,
    )
    result = response.results[0]
    categories = [
        name
        for name, value in result.categories.model_dump().items()
        if value
    ]
    return ModerationResult(flagged=result.flagged, categories=categories)
