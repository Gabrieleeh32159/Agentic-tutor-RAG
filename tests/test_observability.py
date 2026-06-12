from __future__ import annotations

import httpx
import pytest

from app.shared.config import get_settings
from app.shared.observability import get_langfuse_handler, score_trace


def test_handler_is_none_without_keys() -> None:
    settings = get_settings()
    assert settings.LANGFUSE_PUBLIC_KEY == ""
    assert get_langfuse_handler() is None


def test_handler_built_with_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    from langfuse._client.resource_manager import LangfuseResourceManager

    import app.shared.observability as obs

    settings = get_settings()
    monkeypatch.setattr(settings, "LANGFUSE_PUBLIC_KEY", "pk-lf-test")
    monkeypatch.setattr(settings, "LANGFUSE_SECRET_KEY", "sk-lf-test")
    # Reset the module-level cache so get_langfuse_handler() creates a new one
    monkeypatch.setattr(obs, "_handler", None)
    handler = get_langfuse_handler()
    assert handler is not None
    # Cleanup: reset cache and tear down the Langfuse singleton so it doesn't
    # interfere with subsequent tests (v4 SDK uses a class-level _instances dict).
    monkeypatch.setattr(obs, "_handler", None)
    with LangfuseResourceManager._lock:
        for instance in LangfuseResourceManager._instances.values():
            instance.shutdown()
        LangfuseResourceManager._instances.clear()


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
