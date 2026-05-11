from __future__ import annotations

import logging

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_openai import ChatOpenAI

from app.shared.config import get_settings

logger = logging.getLogger(__name__)


_chat_model: BaseChatModel | None = None


def get_chat_model() -> BaseChatModel:
    """Return a LangChain-compatible chat model with optional fallback."""
    global _chat_model
    if _chat_model is None:
        settings = get_settings()
        primary = ChatOpenAI(
            model=settings.CHAT_MODEL,
            api_key=settings.OPENAI_API_KEY,
            streaming=True,
        )
        if settings.ANTHROPIC_API_KEY:
            from langchain_anthropic import ChatAnthropic

            secondary = ChatAnthropic(
                model="claude-haiku-4-5-20251001",
                api_key=settings.ANTHROPIC_API_KEY,
            )
            _chat_model = primary.with_fallbacks([secondary])
        else:
            _chat_model = primary
    return _chat_model
