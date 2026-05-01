from __future__ import annotations

from abc import ABC, abstractmethod

from openai import AsyncOpenAI

from app.shared.config import get_settings


class EmbeddingProvider(ABC):
    @abstractmethod
    async def embed(self, text: str) -> list[float]: ...

    @abstractmethod
    async def embed_batch(self, texts: list[str]) -> list[list[float]]: ...


class OpenAIEmbeddingProvider(EmbeddingProvider):
    def __init__(self) -> None:
        settings = get_settings()
        self._client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
        self._model = settings.EMBEDDING_MODEL

    async def embed(self, text: str) -> list[float]:
        response = await self._client.embeddings.create(
            model=self._model,
            input=text,
        )
        return response.data[0].embedding

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        response = await self._client.embeddings.create(
            model=self._model,
            input=texts,
        )
        return [item.embedding for item in response.data]


_provider: EmbeddingProvider | None = None


def get_embedding_provider() -> EmbeddingProvider:
    global _provider
    if _provider is None:
        _provider = OpenAIEmbeddingProvider()
    return _provider
