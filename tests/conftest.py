from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import AsyncIterator, Iterator
from typing import Any
from unittest.mock import patch

import httpx
import pytest
from httpx import ASGITransport
from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult
from sqlmodel import SQLModel

import app.shared.embeddings as embeddings_module
from app.chat.models import ChatMessage  # noqa: F401
from app.documents.models import Document, DocumentChunk  # noqa: F401
from app.sessions.models import Session  # noqa: F401
from app.shared.config import get_settings
from app.shared.database import close_engine, get_engine, init_engine
from app.shared.embeddings import EmbeddingProvider

EMBEDDING_DIM = 1536

# Keywords that indicate an academic question requiring tool use
_ACADEMIC_KEYWORDS = [
    "derivative",
    "cell",
    "biology",
    "math",
    "physics",
    "chemistry",
    "history",
    "science",
    "equation",
    "theorem",
    "explain",
    "what is",
    "how does",
    "describe",
    "calculate",
    "define",
]


class FakeEmbeddingProvider(EmbeddingProvider):
    """Deterministic fake: hashes the text to produce a consistent vector."""

    def _fake_vector(self, text: str) -> list[float]:
        h = hashlib.sha256(text.encode()).hexdigest()
        base = [int(c, 16) / 15.0 for c in h]
        vector = (base * (EMBEDDING_DIM // len(base) + 1))[:EMBEDDING_DIM]
        norm = sum(x * x for x in vector) ** 0.5
        return [x / norm for x in vector]

    async def embed(self, text: str) -> list[float]:
        return self._fake_vector(text)

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [self._fake_vector(t) for t in texts]


def _is_academic(text: str) -> bool:
    lower = text.lower()
    return any(kw in lower for kw in _ACADEMIC_KEYWORDS)


class FakeChatModel(BaseChatModel):
    """Deterministic fake chat model that supports tool calling for tests."""

    bound_tools: list[dict] = []

    @property
    def _llm_type(self) -> str:
        return "fake-chat-model"

    def bind_tools(self, tools: Any, **kwargs: Any) -> FakeChatModel:
        from langchain_core.utils.function_calling import convert_to_openai_tool

        bound = []
        for t in tools:
            bound.append(convert_to_openai_tool(t))
        model = FakeChatModel(bound_tools=bound)
        return model

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        # --- Grader prompt ---
        if any(
            isinstance(m.content, str) and "relevance grader" in m.content.lower()
            for m in messages
        ):
            return ChatResult(
                generations=[ChatGeneration(message=AIMessage(content="yes"))]
            )

        # --- Rewriter prompt ---
        if any(
            isinstance(m.content, str) and "query rewriter" in m.content.lower()
            for m in messages
        ):
            return ChatResult(
                generations=[
                    ChatGeneration(
                        message=AIMessage(content="rewritten academic question")
                    )
                ]
            )

        # --- After tool result: generate final answer ---
        if any(isinstance(m, ToolMessage) for m in messages):
            return ChatResult(
                generations=[
                    ChatGeneration(message=AIMessage(content="This is a test answer."))
                ]
            )

        # --- If tools are bound, decide whether to call them ---
        if self.bound_tools:
            # Find the last human message
            last_human = ""
            for m in reversed(messages):
                if (
                    hasattr(m, "content")
                    and isinstance(m.content, str)
                    and m.type == "human"
                ):
                    last_human = m.content
                    break

            if _is_academic(last_human):
                tool_call_id = f"call_{uuid.uuid4().hex[:12]}"
                msg = AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "name": "search_documents",
                            "args": {"query": last_human},
                            "id": tool_call_id,
                            "type": "tool_call",
                        }
                    ],
                )
                return ChatResult(generations=[ChatGeneration(message=msg)])

        # --- Default: casual / direct response ---
        return ChatResult(
            generations=[
                ChatGeneration(
                    message=AIMessage(content="Hello! How can I help you today?")
                )
            ]
        )

    def _stream(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> Iterator[ChatGenerationChunk]:
        result = self._generate(messages, stop, run_manager, **kwargs)
        msg = result.generations[0].message

        # Tool calls: emit as a single chunk with tool_call_chunks AND tool_calls
        if hasattr(msg, "tool_calls") and msg.tool_calls:
            yield ChatGenerationChunk(
                message=AIMessageChunk(
                    content="",
                    tool_calls=msg.tool_calls,
                    tool_call_chunks=[
                        {
                            "name": tc["name"],
                            "args": json.dumps(tc["args"]),
                            "id": tc["id"],
                            "index": i,
                        }
                        for i, tc in enumerate(msg.tool_calls)
                    ],
                )
            )
            return

        # Text response: stream word by word
        text = msg.content
        if not text:
            return
        words = text.split(" ")
        for i, word in enumerate(words):
            token = word if i == len(words) - 1 else word + " "
            yield ChatGenerationChunk(message=AIMessageChunk(content=token))


@pytest.fixture(autouse=True)
def mock_embedding_provider() -> None:
    """Replace the real embedding provider with a fake for all tests."""
    fake = FakeEmbeddingProvider()
    embeddings_module._provider = fake
    yield  # type: ignore[misc]
    embeddings_module._provider = None


@pytest.fixture(autouse=True)
def mock_chat_model():
    """Patch build_graph to use FakeChatModel instead of real OpenAI."""
    from app.chat import service as chat_service

    _original_build = chat_service.build_graph

    def _patched_build(http_client, llm=None):
        return _original_build(http_client, llm=FakeChatModel())

    with patch.object(chat_service, "build_graph", _patched_build):
        yield


@pytest.fixture(autouse=True)
async def _init_db() -> AsyncIterator[None]:
    """Initialize the DB engine and create tables for each test (avoids event-loop mismatch)."""
    settings = get_settings()
    init_engine(settings.DATABASE_URL)
    async with get_engine().begin() as conn:
        await conn.run_sync(SQLModel.metadata.drop_all)
        await conn.run_sync(SQLModel.metadata.create_all)
    yield
    await close_engine()


@pytest.fixture
async def client() -> AsyncIterator[httpx.AsyncClient]:
    """An HTTPX async client wired directly to the FastAPI app (no network)."""
    from app.main import app

    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://testserver"
    ) as c:
        yield c


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


FAKE_VISION_TEXT = "Scanned page about photosynthesis and chlorophyll absorption."


@pytest.fixture(autouse=True)
def mock_vision(monkeypatch: pytest.MonkeyPatch):
    """Replace vision OCR with a canned transcription (no network).

    Yields the canned text so tests can assert against it without importing
    from conftest (tests/ is not a package).
    """
    import app.ingestion.vision as vision_module

    async def _fake_extract(image_bytes: bytes, mime: str = "image/png") -> str:
        return FAKE_VISION_TEXT

    def _fake_rasterize(pdf_bytes: bytes, page_index: int, scale: float = 2.0) -> bytes:
        return b"fake-png"

    monkeypatch.setattr(vision_module, "extract_text_from_image", _fake_extract)
    monkeypatch.setattr(vision_module, "rasterize_pdf_page", _fake_rasterize)
    yield FAKE_VISION_TEXT
