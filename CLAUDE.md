# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A FastAPI async service for educational-content Retrieval-Augmented Generation (a take-home challenge). It ingests documents, indexes them with OpenAI embeddings in pgvector, and answers student questions via an agentic RAG loop with streaming. Steps 1–3 of the challenge are implemented (ingestion, semantic search, RAG chat); Step 4 (flashcard generation) is **not** implemented.

## Commands

```bash
uv sync                                    # install deps (incl. dev group)
cp .env.example .env                        # then set OPENAI_API_KEY (ANTHROPIC_API_KEY optional)
docker compose up -d                        # start Postgres 16 + pgvector on :5432

uv run fastapi dev app/main.py              # run API on :8000 (tables auto-create on startup)
uv run python scripts/reset_db.py            # DESTRUCTIVE: drop + recreate all tables (schema cutover)
uv run streamlit run scripts/streamlit_app.py  # chat UI that visualises the agent flow
uv run python scripts/chat.py               # CLI chat client

uv run pytest                               # run all tests (needs Postgres running)
uv run pytest tests/test_chat.py            # single file
uv run pytest tests/test_chat.py::test_name # single test
uv run ruff check .                          # lint
uv run ruff format .                         # format
```

**Tests require a live Postgres** (the same `DATABASE_URL` as dev). Each test drops and recreates all tables (`conftest.py::_init_db`), so don't point tests at a database with data you care about. `pytest.ini_options` sets `asyncio_mode = "auto"`, so `async def test_*` needs no decorator.

## Architecture

### Feature-module layout
Code is organized by feature under `app/`, each module self-contained with the same shape:
- `models.py` — SQLModel DB tables **and** Pydantic request/response schemas together
- `router.py` — FastAPI `APIRouter` (thin; delegates to service)
- `service.py` — business logic (where the real work lives)

Modules: `documents/` (ingest), `search/` (semantic search), `chat/` (agentic RAG). `app/shared/` holds cross-cutting infra: `config.py` (pydantic-settings), `database.py`, `embeddings.py`, `llm.py`. Routers are wired in `app/main.py`, which also imports every model module so SQLModel registers all tables; `lifespan` runs `SQLModel.metadata.create_all` on startup — **there are no migrations**, schema changes happen by editing models.

### Data model: documents are chunked, embeddings live on chunks
`create_document` splits `content` with a `RecursiveCharacterTextSplitter` (chunk_size 300, overlap 50) into `DocumentChunk` rows. **The text that gets embedded is enriched** (`_build_enriched_text`: title + subject + level + chunk), not the raw chunk. Embeddings are `Vector(1536)` columns (`text-embedding-3-small`). `Document.chunk_count` records how many chunks a doc produced.

### Search: chunk-level retrieval, document-level results
`search/service.py` embeds the query, ranks `DocumentChunk` rows by cosine distance, **over-fetches `limit * 3`** chunks, then groups them back by document. Each `SearchResult` carries the document's best chunk score plus all its matched chunks. Score = `1 - cosine_distance`. There is **no ANN/IVFFlat index** on the vector column — search is exact.

### Chat: a self-correcting LangGraph agent
`chat/service.py` builds a LangGraph `StateGraph` with two nodes — `agent` (LLM) and `tools` — looping `agent → tools → agent` via `tools_condition` until the model stops calling tools. State is `AgentState` (`messages` with the `add_messages` reducer, plus `subject`/`level` filters). Node names come from the `NodeName` enum.

The single tool is `search_documents` (`chat/tools.py`), which implements an **agentic RAG retry loop** (constants in `chat/prompts.py`):
1. Call the `/search` endpoint, get results.
2. **Grade relevance** by top score: `≥ HIGH_RELEVANCE_THRESHOLD` → relevant; `< LOW_RELEVANCE_THRESHOLD` → not; in between → ask an LLM grader (`GRADER_PROMPT`).
3. If not relevant and retries remain (`MAX_RETRIES`), **rewrite the query** (`REWRITE_PROMPT`) and retry. Otherwise return `NOT_FOUND_MESSAGE`.

Key detail: the tool calls `/search` over HTTP **in-process** via an httpx `ASGITransport` client (built in the router, passed into `build_graph`), rather than calling the search service directly. `subject`/`level` are injected from graph state via `InjectedState`.

### Streaming + persistence (`chat/router.py`)
`POST /chat` returns an SSE stream (`text/event-stream`). It drives `graph.astream_events(version="v2")` and emits:
- `session_id` first, then agent tokens (events tagged `agent_llm`),
- step events (`retrieve` / `grade_documents` / `rewrite_query`) surfaced from `adispatch_custom_event` calls inside the tool, plus `sources`,
- `[DONE]` last.

Conversation is persisted: `ChatSession` + `ChatMessage` tables. Each turn reloads history (`load_session_messages` reconstructs LangChain `Human/AI/Tool/System` messages from rows) and prepends `SYSTEM_PROMPT`. Messages are saved **before** the final `[DONE]` yield, using a fresh DB session from `get_session_factory()`, because the client may disconnect and cancel the generator after the last write.

### Provider abstractions (swap-friendly)
- `shared/llm.py::get_chat_model()` returns a LangChain `BaseChatModel`: OpenAI primary, and if `ANTHROPIC_API_KEY` is set, wraps it with `.with_fallbacks([ChatAnthropic(...)])`. Cached in a module global.
- `shared/embeddings.py` defines an `EmbeddingProvider` ABC with an `OpenAIEmbeddingProvider` impl, behind `get_embedding_provider()`. To add a provider, implement the ABC — callers don't change.

### How tests fake the AI layer
`conftest.py` provides autouse fixtures that swap the real providers for deterministic fakes — **no network/API keys needed for tests**:
- `FakeEmbeddingProvider` hashes text to a stable normalized vector.
- `FakeChatModel` is a full `BaseChatModel` that inspects message content to decide behavior: returns `"yes"` for grader prompts, a canned rewrite for rewriter prompts, and triggers tool calls only when the user message contains an academic keyword (`_ACADEMIC_KEYWORDS`). It supports `bind_tools` and word-by-word `_stream`, so the LangGraph + SSE path runs end-to-end against it.

## Conventions
- `from __future__ import annotations` at the top of every module; modern typing (`X | None`, `list[...]`).
- Async everywhere — DB (asyncpg/SQLAlchemy async), embeddings, LLM calls.
- Ruff lint selects `E,W,F,I,B,C4,UP`; line length (`E501`) is ignored.
- `NOTES.md` (in Spanish) records the author's design rationale and is the anchor for the interview — worth reading before changing retrieval/prompt behavior.
