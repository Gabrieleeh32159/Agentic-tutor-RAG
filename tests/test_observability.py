from __future__ import annotations

import httpx
import pytest

from app.shared.config import get_settings
from app.shared.observability import get_langfuse_handler, score_trace


def test_handler_is_none_without_keys() -> None:
    settings = get_settings()
    assert settings.LANGFUSE_PUBLIC_KEY == ""
    assert get_langfuse_handler() is None


def test_handler_built_with_keys_is_actually_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.shared.observability as obs

    settings = get_settings()
    monkeypatch.setattr(settings, "LANGFUSE_PUBLIC_KEY", "pk-test")
    monkeypatch.setattr(settings, "LANGFUSE_SECRET_KEY", "sk-test")
    monkeypatch.setattr(obs, "_client_registered", False)

    try:
        handler = obs.get_langfuse_handler()
        assert handler is not None
        # _langfuse_client is set by LangchainCallbackHandler.__init__ via get_client()
        client = getattr(handler, "_langfuse_client", None)
        assert client is not None
        # _tracing_enabled lives on the Langfuse client instance
        assert getattr(client, "_tracing_enabled", False) is True
    finally:
        from langfuse._client.resource_manager import LangfuseResourceManager

        with LangfuseResourceManager._lock:
            for instance in list(LangfuseResourceManager._instances.values()):
                try:
                    instance.shutdown()
                except Exception:
                    pass
            LangfuseResourceManager._instances.clear()
        monkeypatch.setattr(obs, "_client_registered", False)


def test_score_trace_noops_without_keys() -> None:
    # Must not raise, must not require network
    score_trace(None, name="grounding", value=1.0)


async def test_chat_unaffected_without_keys(client: httpx.AsyncClient) -> None:
    """The whole streaming path works with observability disabled (no keys)."""
    response = await client.post("/sessions")
    sid = response.json()["id"]
    chat = await client.post("/chat", json={"question": "Hola", "session_id": sid})
    assert chat.status_code == 200
    assert chat.text.rstrip().endswith("data: [DONE]")
