# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

"Ask your PDFs": a session-scoped document-chat app. A FastAPI backend ingests uploaded files (pdf/docx/xlsx/txt/md/images) asynchronously, indexes chunks with OpenAI embeddings in pgvector, and answers questions through a self-correcting LangGraph agent streamed over SSE — with guardrails, rate limiting, and optional Langfuse tracing. A Next.js frontend lives in `web/`. The approved design (including carry-over items) is `docs/superpowers/specs/2026-06-10-ask-your-pdfs-design.md`; `NOTES.md` holds the author's design rationale.

## Commands

```bash
uv sync                                     # install deps (incl. dev group)
cp .env.example .env                         # then set OPENAI_API_KEY (ANTHROPIC_API_KEY optional)
docker compose up -d                         # start Postgres 16 + pgvector on :5432

uv run fastapi dev app/main.py               # run API on :8000 (tables auto-create on startup)
uv run python scripts/reset_db.py            # DESTRUCTIVE: drop + recreate all tables (also drops legacy chat_sessions)
uv run streamlit run scripts/streamlit_app.py  # internal dev tool (streamlit is in the dev group, not the Docker image)

uv run pytest                                # all tests (needs Postgres running)
uv run pytest tests/test_chat.py             # single file
uv run pytest tests/test_chat.py::test_name  # single test
uv run ruff check .                           # lint
uv run ruff format .                          # format

cd web && npm install                        # frontend deps
npm run dev                                  # Next.js on :3000 (NEXT_PUBLIC_API_URL defaults to :8000)
npm run build                                # production build
npm run lint                                 # eslint
npx tsc --noEmit                             # type check (no package.json script)
```

**Tests require a live Postgres** at `DATABASE_URL`. Each test **drops and recreates all tables** (`conftest.py::_init_db`). Settings come from `.env` — **if `.env` points at a remote database (e.g. the Neon production DB used for deploy), running pytest wipes it.** Keep `.env` on the local docker-compose Postgres and set the remote URL only in the deploy environment (or ad hoc when running `reset_db.py` for a cutover). `pytest.ini_options` sets `asyncio_mode = "auto"`, so `async def test_*` needs no decorator.

## Architecture

### Feature-module layout
Code is organized by feature under `app/`, each module roughly `models.py` (SQLModel tables + Pydantic schemas together), `router.py` (thin), `service.py` (the real work):

- `sessions/` — workspace CRUD, activity touching, TTL expiry (`service.py`), and the cleanup sweeper (`cleanup.py`).
- `documents/` — upload validation + Document/DocumentChunk tables; the router returns 202 and delegates processing to `ingestion/`.
- `ingestion/` — parser registry and the async pipeline (no router; it's invoked by `documents/router.py`).
- `search/` — session-scoped semantic search.
- `chat/` — LangGraph agent, SSE streaming, message persistence (`repository.py`), prompts/constants (`prompts.py`).
- `guardrails/` — `input_check.py` (injection regex + moderation gate), `moderation.py` (OpenAI client), `grounding.py` (post-stream judge).
- `shared/` — `config.py` (pydantic-settings; all limits live here), `database.py`, `embeddings.py`, `llm.py`, `errors.py`, `logging.py`, `rate_limit.py`, `observability.py`.

`app/main.py` wires routers, the slowapi limiter + ASGI middleware, `RequestIDMiddleware`, CORS (`FRONTEND_ORIGIN` + localhost:3000), and the `AppError` handlers. It imports every model module so SQLModel registers all tables; `lifespan` runs `create_all`, marks orphaned pending/processing documents as `failed/interrupted` (startup reconciliation), and starts the cleanup loop. **There are no migrations** — schema changes mean editing models and running `scripts/reset_db.py` (data is disposable by design).

### Session-workspace model
Everything hangs off `sessions`: `documents` and `chat_messages` FK to it with `ON DELETE CASCADE`, `document_chunks` cascade from documents. No auth — the client keeps its session id in localStorage. `get_active_session` raises `SessionNotFoundError` (404) or `SessionExpiredError` (410, distinct so clients know to mint a new session); mutating/reading endpoints call `touch_session` to bump `last_activity_at`. `app/sessions/cleanup.py::cleanup_loop` runs every `CLEANUP_INTERVAL_MINUTES` (15): bulk-deletes sessions idle past `SESSION_TTL_HOURS` (24) and reaps documents stuck in pending/processing longer than `STALE_PROCESSING_MINUTES` (60). A session auto-titles from the first chat question.

### Async ingestion pipeline (`app/ingestion/`)
Upload validation order in `documents/router.py`: session → doc-count cap (20) → queue cap → extension in `SUPPORTED_TYPES` → bounded read (10 MB + 1) → size → puremagic signature sniff (`sniff_matches_extension` — a plausibility gate, not validation). Then a `pending` Document row is inserted, `schedule_processing` fires a detached `asyncio.create_task` (held in a module-level `_tasks` set against GC), and the endpoint returns **202**.

`service.py::process_document` runs **parse → ocr → chunk → embed → save**, opening its own DB session and committing every stage transition so polling (`GET /sessions/{id}/documents`) sees `status/stage/progress` move. The status contract: `status` pending/processing/ready/failed, `stage` parsing/ocr/embedding/saving, `progress` 0–100, lowercase `error_code`/`error_message` on failure. Concurrency is bounded by a lazily-initialised semaphore (`MAX_CONCURRENT_INGESTIONS = 2`; lazy so it binds to the running loop under pytest) and a queue cap (`MAX_QUEUED_INGESTIONS = 10` → `503 INGESTION_BUSY`). CPU-bound parsing/rasterization is offloaded via `asyncio.to_thread`.

`registry.py` maps extension → parser; each parser returns `ParsedDocument(blocks, page_count, needs_ocr_pages)`. Adding a format = adding a parser module + registry entry. OCR: `vision.py` rasterizes one PDF page at a time (pypdfium2, bounded memory) and sends it to `get_vision_model()` (gpt-4o-mini); the prompt contract demands `NO_TEXT` for blank pages and `clean_transcription` also filters refusals ("I'm sorry…") so neither enters the index. Images skip rasterization — the upload *is* the image. Capped at `MAX_OCR_PAGES_PER_DOC` (20). Chunking: `RecursiveCharacterTextSplitter` (300/50); xlsx rows become **atomic** markdown-table blocks (30 rows, header repeated, max 10 sheets / 2,000 rows per sheet) that pass through unsplit. The **embedded text is enriched** (`build_enriched_text`: filename + page/sheet + chunk), not the raw chunk. File bytes are parse-and-discard — only chunks + metadata persist.

### Search: chunk-level retrieval, document-level results
`search/service.py` embeds the query, ranks `DocumentChunk` rows by cosine distance **within the session and only over `READY` documents**, over-fetches `limit * 3` chunks, then groups by document (best chunk score + all matched chunks). Score = `1 - cosine_distance`. No ANN index — search is exact.

### Chat: a self-correcting LangGraph agent
`chat/service.py` builds a two-node graph — `agent` (LLM) and `tools` — looping via `tools_condition`. State is `AgentState` (`messages` + `session_id`, injected into the tool via `InjectedState`). The single tool `search_documents` (`chat/tools.py`) implements the retry loop (constants in `chat/prompts.py`): search → grade by top score (`≥ 0.75` relevant, `< 0.25` not, in between → LLM grader) → if weak and retries remain (`MAX_RETRIES = 2`), rewrite the query and retry; else return `NOT_FOUND_MESSAGE`. Successful results are returned wrapped in `<retrieved-content>` tags. The tool calls `/search` over HTTP **in-process** via an httpx `ASGITransport` client built in the router.

`POST /chat` (`chat/router.py`) gates input first (see guardrails), then streams SSE in this order: `{"session_id"}` → token events (chat-model stream events tagged `agent_llm`) interleaved with step events (`retrieve` / `grade_documents` / `rewrite_query`, surfaced from `adispatch_custom_event` inside the tool) and `{"sources"}` → `{"grounding": {"verdict"}}` → `data: [DONE]`. The stream loop is wrapped in `asyncio.timeout(CHAT_STREAM_TIMEOUT_SECONDS = 120)`; failures emit a structured `{"error": {code: STREAM_TIMEOUT | STREAM_FAILED}}` SSE event and still fall through to grounding/persist/[DONE]. Messages are persisted **before** the final `[DONE]` yield with a fresh DB session (the client may disconnect and cancel the generator after the last write); the grounding verdict is stored on the last AI row. History is reloaded each turn from `chat_messages` (`load_session_messages`) with `SYSTEM_PROMPT` prepended — the full history, there is no window.

### Guardrails (`app/guardrails/`)
- **Input gate** (router-level, pre-stream, blocking): `check_input` runs a conservative English-only injection regex scan (fail-closed) and OpenAI moderation (`omni-moderation-latest`); hits raise `GuardrailBlockedError` → clean `400 GUARDRAIL_BLOCKED` before any SSE. Moderation outages **fail open** (logged, `moderation_degraded` flows into the Langfuse tags).
- **Untrusted content framing**: tool output is wrapped in `<retrieved-content>` and `SYSTEM_PROMPT` instructs the model that content inside those tags is data, never instructions.
- **Grounding** (post-stream, annotating, never blocking): `check_grounding` LLM-judges the final answer against this turn's retrieved chunks (last attempt only, capped at 6,000 chars) → `grounded`/`ungrounded`/`unverified` (`unverified` when no retrieval happened or the judge fails). Emitted as an SSE event before `[DONE]`, persisted on the AI message, scored in Langfuse.

### Shared infra
- `errors.py`: `AppError(code, status_code)` subclasses (`SESSION_NOT_FOUND` 404, `SESSION_EXPIRED` 410, `UNSUPPORTED_FILE_TYPE` 415, `FILE_TOO_LARGE` 413, `PAGE_LIMIT_EXCEEDED` 413, `PARSE_FAILED` 422, `SESSION_DOCUMENT_LIMIT` 409, `GUARDRAIL_BLOCKED` 400, `INGESTION_BUSY` 503, …) rendered as `{"error": {"code", "message", "request_id"}}`.
- `logging.py`: `RequestIDMiddleware` is **pure ASGI** (BaseHTTPMiddleware breaks SSE); request id flows via contextvar into every log line and the `X-Request-ID` response header.
- `rate_limit.py`: slowapi in-memory keyed by client IP, default `60/minute`; route decorators add `10/hour` (upload) and `20/minute` (chat). Exact on the single Render process; resets on restart. **Any SSE endpoint must carry a `@limiter.limit` decorator** — slowapi's ASGI middleware corrupts undecorated streaming responses.
- `observability.py`: `get_langfuse_handler()` returns `None` when `LANGFUSE_PUBLIC_KEY/SECRET_KEY` are unset → full no-op (tests stay key-free). Fresh handler per call (keeps `last_trace_id` per-request), process-wide client singleton, `score_trace` for grounding/retrieval-attempt scores.
- `llm.py`: `get_chat_model()` — ChatOpenAI (streaming) with optional Anthropic `.with_fallbacks`; `get_vision_model()` for OCR. All clients (incl. `embeddings.py`'s `OpenAIEmbeddingProvider`) set explicit timeouts + SDK `max_retries` — **deliberately no tenacity** (would stack with SDK retries). `embeddings.py` keeps the `EmbeddingProvider` ABC behind `get_embedding_provider()`.

### How tests fake the AI layer
119 tests, **no network/API keys needed**. `tests/conftest.py` autouse fixtures:
- `FakeEmbeddingProvider` — hashes text to a stable normalized vector.
- `FakeChatModel` — full `BaseChatModel` that branches on message content: "grounding judge" → `yes`, "relevance grader" → `yes`, "query rewriter" → canned rewrite, post-ToolMessage → canned answer, tool calls only for academic keywords; `TRIGGER_STREAM_FAILURE` in the question simulates a mid-stream provider crash. Supports `bind_tools` + word-by-word `_stream`, so LangGraph + SSE run end to end.
- `mock_vision` — canned OCR transcription + fake rasterizer (yields `FAKE_VISION_TEXT` for assertions).
- `mock_moderation` — passes everything; tests override per-case.
- `mock_judge_model` — the grounding judge uses the fake model.
- `_disable_rate_limiting` and `_reset_ingestion_semaphore` (fresh semaphore per test event loop).

Real parsers run against tiny committed fixtures in `tests/fixtures/` (regenerate with `scripts/make_fixtures.py`). Async-ingestion tests await `wait_for_ingestion()` instead of sleeping.

### Frontend (`web/`)
Next.js App Router + TypeScript + Tailwind v4 + Motion. `app/page.tsx` is the scroll-animated landing; `app/chat/page.tsx` is the app (`components/chat/*`: UploadZone, DocumentList, ChatPanel, AgentStepsTimeline, SourcesPanel, GroundingBadge, StampedNotice for guardrail/rate-limit refusals, ServerWakingNotice for Render cold starts). **All backend contact goes through `lib/`** — components never fetch directly: `lib/api.ts` (typed REST client, `NEXT_PUBLIC_API_URL`), `lib/sse.ts` (hand-rolled SSE line parser over fetch + ReadableStream), `lib/session.ts` (localStorage id; 404/410 → new session), `lib/types.ts` (the `ChatEvent` discriminated union mirroring the SSE protocol — the contract's single source of truth). Error codes are a dual namespace by design: UPPERCASE envelope codes (`SESSION_EXPIRED`, `RATE_LIMITED`) vs lowercase document-row codes (`parse_failed`, `interrupted`). The paper-and-ink design system (palette, offset shadows, grain, typography tokens) lives in `app/globals.css`. `web/CLAUDE.md` points at the bundled Next.js docs — read those before assuming Next.js conventions.

## Conventions
- `from __future__ import annotations` at the top of every module; modern typing (`X | None`, `list[...]`).
- Async everywhere — DB (asyncpg/SQLAlchemy async), embeddings, LLM calls; sync CPU-bound work goes through `asyncio.to_thread`.
- Timestamps are timezone-aware: `datetime.now(UTC)`, `DateTime(timezone=True)` columns.
- Ruff selects `E,W,F,I,B,C4,UP`, ignores `E501`; `fastapi.Depends`/`fastapi.Query` are exempted from B008 via `extend-immutable-calls`.
- No migrations: edit models, then `uv run python scripts/reset_db.py` (destructive).
- Design rationale lives in `NOTES.md` (the interview anchor; latest section in Spanish) and `docs/superpowers/specs/` — read before changing retrieval, prompts, or guardrail behavior.
