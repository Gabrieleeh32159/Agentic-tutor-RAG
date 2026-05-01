from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator

from anthropic import AsyncAnthropic
from openai import AsyncOpenAI

from app.shared.config import get_settings

logger = logging.getLogger(__name__)


class LLMUnavailableError(Exception):
    """Raised when all LLM providers fail."""


class LLMProvider(ABC):
    @abstractmethod
    async def stream(
        self, system_prompt: str, user_prompt: str
    ) -> AsyncIterator[str]: ...


class OpenAILLMProvider(LLMProvider):
    def __init__(self) -> None:
        settings = get_settings()
        self._client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
        self._model = settings.CHAT_MODEL

    async def stream(
        self, system_prompt: str, user_prompt: str
    ) -> AsyncIterator[str]:
        response = await self._client.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            stream=True,
        )
        async for chunk in response:
            delta = chunk.choices[0].delta.content
            if delta:
                yield delta


class AnthropicLLMProvider(LLMProvider):
    def __init__(self) -> None:
        settings = get_settings()
        self._client = AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)

    async def stream(
        self, system_prompt: str, user_prompt: str
    ) -> AsyncIterator[str]:
        async with self._client.messages.stream(
            model="claude-haiku-4-5-20251001",
            max_tokens=1024,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        ) as stream:
            async for text in stream.text_stream:
                yield text


class FallbackLLMProvider(LLMProvider):
    """Tries the primary provider; falls back to secondary on error."""

    def __init__(
        self, primary: LLMProvider, secondary: LLMProvider
    ) -> None:
        self._primary = primary
        self._secondary = secondary

    async def stream(
        self, system_prompt: str, user_prompt: str
    ) -> AsyncIterator[str]:
        primary_iter = self._primary.stream(system_prompt, user_prompt).__aiter__()
        try:
            first_token = await primary_iter.__anext__()
        except StopAsyncIteration:
            return
        except Exception as exc:
            logger.warning(
                "Primary LLM provider failed (%s), falling back to secondary",
                exc,
            )
            try:
                async for token in self._secondary.stream(system_prompt, user_prompt):
                    yield token
            except Exception as exc2:
                logger.error("Secondary LLM provider also failed (%s)", exc2)
                raise LLMUnavailableError("All LLM providers are unavailable") from exc2
            return

        yield first_token
        async for token in primary_iter:
            yield token


_llm_provider: LLMProvider | None = None


def get_llm_provider() -> LLMProvider:
    global _llm_provider
    if _llm_provider is None:
        settings = get_settings()
        primary = OpenAILLMProvider()
        if settings.ANTHROPIC_API_KEY:
            secondary = AnthropicLLMProvider()
            _llm_provider = FallbackLLMProvider(primary, secondary)
        else:
            _llm_provider = primary
    return _llm_provider
