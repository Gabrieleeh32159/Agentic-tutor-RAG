from __future__ import annotations

import logging
from typing import Any

from app.shared.config import get_settings

logger = logging.getLogger(__name__)

# Module-level cache: None means "not yet constructed"; the handler instance
# once built with valid keys; stays None forever when keys are absent.
_handler: Any | None = None


def _enabled() -> bool:
    settings = get_settings()
    return bool(settings.LANGFUSE_PUBLIC_KEY and settings.LANGFUSE_SECRET_KEY)


def get_langfuse_handler() -> Any | None:
    """Return a LangChain CallbackHandler for Langfuse, or None when keys are unset.

    Returning None keeps every call site a strict no-op (tests remain key-free).

    SDK adaptation note (langfuse 4.x):
      - Import path is ``langfuse.langchain.CallbackHandler`` — same as the v3
        plan's ``from langfuse.langchain import CallbackHandler``.
      - Constructor accepts ``public_key`` directly (no env-var-only path), so
        we pass the settings values explicitly.  The global Langfuse client
        (``LangfuseResourceManager._instances``) is a singleton keyed by
        public_key; calling this function multiple times is idempotent.
    """
    global _handler
    if not _enabled():
        return None
    if _handler is None:
        settings = get_settings()
        # v4: pass keys explicitly so the SDK does NOT log "client disabled"
        # warnings.  host is passed via the LANGFUSE_HOST env var convention;
        # the Langfuse() constructor also reads LANGFUSE_HOST directly.
        import os

        from langfuse.langchain import CallbackHandler

        os.environ.setdefault("LANGFUSE_HOST", settings.LANGFUSE_HOST)
        _handler = CallbackHandler(public_key=settings.LANGFUSE_PUBLIC_KEY)
    return _handler


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
