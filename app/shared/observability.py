from __future__ import annotations

import logging
from typing import Any

from app.shared.config import get_settings

logger = logging.getLogger(__name__)

# Set to True once the process-wide Langfuse singleton has been registered.
# The heavy client is shared; individual handlers are created per-call so
# that last_trace_id stays per-request (chat and OCR would otherwise race).
_client_registered = False


def _enabled() -> bool:
    settings = get_settings()
    return bool(settings.LANGFUSE_PUBLIC_KEY and settings.LANGFUSE_SECRET_KEY)


def get_langfuse_handler() -> Any | None:
    """LangChain callback handler for Langfuse, or None when keys are unset.

    A fresh handler per call keeps ``last_trace_id`` per-request (chat and
    background OCR would otherwise race on a shared handler). The heavy
    Langfuse client behind it is a process-wide singleton, registered once
    via ``Langfuse(public_key=..., secret_key=..., host=...)`` so that
    ``get_client(public_key=pk)`` resolves it rather than returning a
    disabled no-op.
    """
    global _client_registered
    if not _enabled():
        return None
    settings = get_settings()
    if not _client_registered:
        from langfuse import Langfuse

        Langfuse(
            public_key=settings.LANGFUSE_PUBLIC_KEY,
            secret_key=settings.LANGFUSE_SECRET_KEY,
            host=settings.LANGFUSE_HOST,
        )
        _client_registered = True
    from langfuse.langchain import CallbackHandler

    return CallbackHandler(public_key=settings.LANGFUSE_PUBLIC_KEY)


def score_trace(handler: Any | None, *, name: str, value: float) -> None:
    """Attach a numeric score to the handler's last trace. No-op when disabled.

    SDK adaptation note (langfuse 4.x):
      - ``handler.last_trace_id`` is set by ``LangchainCallbackHandler`` after
        the root run completes (same attribute name as planned).
      - ``get_client().create_score(trace_id=..., name=..., value=...)`` is the
        correct v4 call — ``get_client()`` returns the default singleton client.
    """
    if handler is None:
        return
    trace_id = getattr(handler, "last_trace_id", None)
    if not trace_id:
        return
    try:
        from langfuse import get_client

        get_client().create_score(trace_id=trace_id, name=name, value=value)
    except Exception:
        logger.warning("Failed to record Langfuse score %s", name, exc_info=True)
