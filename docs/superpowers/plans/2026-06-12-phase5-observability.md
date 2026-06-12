# Phase 5: Langfuse Observability — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every chat turn produces a full Langfuse trace (agent → tool → grader → rewrite → answer) tied to the session, annotated with request id, retrieved document ids, retry count, the grounding verdict (as a score), and a `guardrail_degraded` tag when moderation failed open. Vision-OCR calls are traced per page. With no Langfuse keys configured, everything is a strict no-op — zero behavior change, tests stay key-free.

**Architecture:** `app/shared/observability.py` exposes `get_langfuse_handler() -> CallbackHandler | None` (None when `LANGFUSE_PUBLIC_KEY`/`LANGFUSE_SECRET_KEY` are unset) plus a `score_trace(...)` helper that no-ops without keys. The chat router passes the handler + Langfuse metadata through the existing `graph.astream_events(config=...)`; the vision module passes it per `ainvoke`. The grounding verdict and grade results become trace scores; `moderation_flagged` is NOT a trace tag (flagged requests are blocked with 400 before any LLM runs, so there is no trace to tag — documented decision).

**SDK CAUTION (for the implementer):** the `langfuse` SDK API changed significantly between v2 (`from langfuse.callback import CallbackHandler`, constructor takes keys) and v3 (`from langfuse.langchain import CallbackHandler`, configuration via env vars / global client, trace attributes via `metadata={"langfuse_session_id": ...}`, scores via `langfuse.get_client().create_score(...)`, trace id via `handler.last_trace_id`). The code below is written against **v3**. After `uv sync`, VERIFY every Langfuse call against the installed package (read `.venv/lib/python*/site-packages/langfuse/`) and adapt signatures as needed — disclose any adaptation. The REQUIREMENTS are fixed; the exact SDK incantation is yours to confirm.

**This is plan 5 of 7.** Current state: 115 tests green ~7s; local Postgres; all AI faked in tests. `check_input` already returns `InputCheckResult(moderation_degraded=...)` — the router currently discards it with a bare `await` and a Phase-5 comment; this phase captures it.

---

### Task 1: Observability module + chat/vision wiring (single task, one commit)

**Files:**
- Create: `app/shared/observability.py`, `tests/test_observability.py`
- Modify: `pyproject.toml`, `app/shared/config.py`, `app/chat/router.py`, `app/ingestion/vision.py`, `render.yaml`

- [ ] **Step 1: Dep + config.** Add `"langfuse>=3.0.0"` to `pyproject.toml` dependencies; `uv sync`. In `app/shared/config.py` add:

```python
    LANGFUSE_PUBLIC_KEY: str = ""
    LANGFUSE_SECRET_KEY: str = ""
    LANGFUSE_HOST: str = "https://cloud.langfuse.com"
```

- [ ] **Step 2: Write the failing tests.** Create `tests/test_observability.py`:

```python
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
    import app.shared.observability as obs

    settings = get_settings()
    monkeypatch.setattr(settings, "LANGFUSE_PUBLIC_KEY", "pk-test")
    monkeypatch.setattr(settings, "LANGFUSE_SECRET_KEY", "sk-test")
    monkeypatch.setattr(obs, "_handler", None)  # reset the cache
    handler = get_langfuse_handler()
    assert handler is not None
    monkeypatch.setattr(obs, "_handler", None)


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
```

(Adapt the cache-reset attribute name to whatever the implementation uses. If constructing a v3 CallbackHandler requires env vars rather than constructor args, set them via monkeypatch.setenv and reset the langfuse global client too — verify against the SDK.)

- [ ] **Step 3: Run to verify failure.** ImportError on `app.shared.observability`.

- [ ] **Step 4: Implement `app/shared/observability.py`** (v3-flavored; VERIFY against installed SDK):

```python
from __future__ import annotations

import logging
from typing import Any

from app.shared.config import get_settings

logger = logging.getLogger(__name__)

_handler: Any | None = None
_configured: bool | None = None


def _enabled() -> bool:
    settings = get_settings()
    return bool(settings.LANGFUSE_PUBLIC_KEY and settings.LANGFUSE_SECRET_KEY)


def get_langfuse_handler() -> Any | None:
    """LangChain callback handler for Langfuse, or None when keys are unset.

    Returning None keeps every call site a strict no-op (and tests key-free).
    """
    global _handler, _configured
    if not _enabled():
        return None
    if _handler is None:
        import os

        settings = get_settings()
        # v3 reads configuration from env / the global client
        os.environ.setdefault("LANGFUSE_PUBLIC_KEY", settings.LANGFUSE_PUBLIC_KEY)
        os.environ.setdefault("LANGFUSE_SECRET_KEY", settings.LANGFUSE_SECRET_KEY)
        os.environ.setdefault("LANGFUSE_HOST", settings.LANGFUSE_HOST)
        from langfuse.langchain import CallbackHandler

        _handler = CallbackHandler()
    return _handler


def score_trace(handler: Any | None, *, name: str, value: float) -> None:
    """Attach a score to the handler's last trace. No-op when disabled/unknown."""
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
```

- [ ] **Step 5: Wire the chat router.** In `app/chat/router.py`:
- Imports: `from app.shared.logging import get_request_id`, `from app.shared.observability import get_langfuse_handler, score_trace`.
- Capture the guardrail signal (replacing the bare await + comment): `guardrail_result = await check_input(body.question)`.
- Inside `event_stream()`, build the config once before the loop:

```python
            handler = get_langfuse_handler()
            run_config: dict = {}
            if handler is not None:
                tags = ["chat"]
                if guardrail_result.moderation_degraded:
                    tags.append("guardrail_degraded")
                run_config = {
                    "callbacks": [handler],
                    "metadata": {
                        "langfuse_session_id": str(session_id),
                        "langfuse_tags": tags,
                        "request_id": get_request_id(),
                    },
                }
```

- Pass it: `graph.astream_events(initial_state, version="v2", config=run_config)` (when `run_config` is `{}` this must be a no-op — verify astream_events accepts an empty dict config; if not, branch on truthiness: `config=run_config or None`).
- Collect document ids alongside the existing chunk collection in the `search_results` branch: maintain `retrieved_doc_ids: list[str]` and `search_attempts: int`, updating both per event (`retrieved_doc_ids[:] = [s["document_id"] for s in sources]`, `search_attempts += 1`).
- After the grounding verdict is computed, record scores + metadata (inside the existing grounding try/except or right after it):

```python
            score_trace(
                handler,
                name="grounding",
                value={"grounded": 1.0, "ungrounded": 0.0, "unverified": 0.5}[verdict],
            )
            if search_attempts:
                score_trace(handler, name="retrieval_attempts", value=float(search_attempts))
```

(Document ids: attach via the run metadata if v3 supports post-hoc update; if not, fold them into the initial metadata as a mutable-after-the-fact field is NOT possible — acceptable fallback: skip per-trace doc ids and rely on the tool spans already containing the search results. Disclose whichever path the SDK allows.)

- [ ] **Step 6: Wire vision.** In `app/ingestion/vision.py::extract_text_from_image`, accept optional metadata and pass the handler:

```python
async def extract_text_from_image(
    image_bytes: bytes,
    mime: str = "image/png",
    *,
    trace_metadata: dict | None = None,
) -> str:
    ...
    handler = get_langfuse_handler()
    config: dict = {}
    if handler is not None:
        config = {
            "callbacks": [handler],
            "metadata": {"langfuse_tags": ["ocr"], **(trace_metadata or {})},
        }
    response = await get_vision_model().ainvoke([message], config=config or None)
```

And in `app/ingestion/service.py`, pass `trace_metadata={"document_id": str(document.id), "page_number": page_number}` at the call site. IMPORTANT: the conftest `mock_vision` fake's signature must be updated to accept the new kwarg (`async def _fake_extract(image_bytes, mime="image/png", *, trace_metadata=None)`).

- [ ] **Step 7: render.yaml.** Add to the service's `envVars`: `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY` (both `sync: false`), `LANGFUSE_HOST` (value `https://cloud.langfuse.com`). Follow the file's existing entry format.

- [ ] **Step 8: Gates.** `uv run pytest -q` ALL green (~119); `uv run ruff check . && uv run ruff format --check .` clean. The key invariant: with no keys set (the test environment), behavior is byte-identical to before — the full suite passing IS that proof.

- [ ] **Step 9: Commit.**

```bash
git add -A
git commit -m "feat: Langfuse observability - traced agent runs + OCR, grounding scores, no-op without keys"
```

---

## Verification (end of Phase 5)

1. `uv run pytest -q` green; lint/format clean.
2. Without keys: API runs identically (suite + a curl smoke).
3. With real Langfuse keys (USER FOLLOW-UP — requires a free cloud.langfuse.com account): set the three env vars, run a chat turn against an uploaded doc, confirm the trace shows agent → tool → grader spans, session id, the grounding score, and an OCR span for a scanned upload. This step can't be verified without user credentials; hand it to the user as a checklist item.

## Out of scope

Frontend (Phase 6); deploy + docs rewrite incl. NOTES.md rationale (Phase 7).
