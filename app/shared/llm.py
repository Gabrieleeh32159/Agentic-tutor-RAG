from __future__ import annotations

import logging

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_openai import ChatOpenAI

from app.shared.config import get_settings

logger = logging.getLogger(__name__)


_chat_model: BaseChatModel | None = None
_vision_model: BaseChatModel | None = None


def get_vision_model() -> BaseChatModel:
    """Multimodal model used for OCR of scanned pages and images."""
    global _vision_model
    if _vision_model is None:
        settings = get_settings()
        _vision_model = ChatOpenAI(
            model=settings.VISION_MODEL,
            api_key=settings.OPENAI_API_KEY,
            temperature=0,
            timeout=90,  # explicit timeout + SDK exponential-backoff retries (see Phase 3 plan: no tenacity stacking)
            max_retries=2,
        )
    return _vision_model


def get_chat_model() -> BaseChatModel:
    """Return a LangChain-compatible chat model with optional fallback."""
    global _chat_model
    if _chat_model is None:
        settings = get_settings()
        primary = ChatOpenAI(
            model=settings.CHAT_MODEL,
            api_key=settings.OPENAI_API_KEY,
            streaming=True,
            timeout=60,  # explicit timeout + SDK exponential-backoff retries (see Phase 3 plan: no tenacity stacking)
            max_retries=2,
        )
        if settings.ANTHROPIC_API_KEY:
            from langchain_anthropic import ChatAnthropic

            secondary = ChatAnthropic(
                model="claude-haiku-4-5-20251001",
                api_key=settings.ANTHROPIC_API_KEY,
                timeout=60,  # explicit timeout + SDK exponential-backoff retries (see Phase 3 plan: no tenacity stacking)
                max_retries=2,
            )
            _chat_model = primary.with_fallbacks([secondary])
        else:
            _chat_model = primary
    return _chat_model
