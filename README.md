# Ask your PDFs — Agentic RAG

Upload PDFs, scans, Word docs, spreadsheets, or images and chat with them. Documents are parsed locally (with a vision-LLM OCR fallback for scanned pages), chunked, and indexed with OpenAI embeddings in **pgvector**. Questions are answered by a **self-correcting LangGraph agent** that retrieves, grades the relevance of what it finds, and rewrites the query to retry when results are weak — then streams a cited Markdown/LaTeX answer over SSE, finished with a **grounding verdict** that says whether the answer is actually supported by your documents. Two apps in one repo: a FastAPI backend and a Next.js frontend (`web/`).

This started as a take-home RAG exercise and grew into a portfolio piece for retrieval, agent loops, and production-minded async FastAPI.

## Highlights

- **Session-scoped workspaces, no auth** — every visitor gets an isolated session; documents, chunks, and chat history cascade-delete when a background sweeper expires sessions after 24h of inactivity. Expired sessions return a distinct `410 SESSION_EXPIRED`.
- **Async multi-format ingestion** — `.pdf` `.docx` `.xlsx` `.txt` `.md` `.png` `.jpg` `.jpeg` `.webp` via a parser registry. Uploads return `202` immediately; clients poll a status contract (`status` / `stage` / `progress` / `error_code`). Scanned pages and images fall back to **vision-LLM OCR** (page-at-a-time rasterization, bounded memory). Interrupted jobs are reconciled to a visible `failed/interrupted` state on restart.
- **Agentic RAG loop** — the LangGraph agent decides *whether* to search, grades results (cheap score thresholds first, LLM grader only for the ambiguous band), and rewrites + retries before giving up. Every step streams to the client as an SSE event.
- **Guardrails** — pre-stream injection scan + OpenAI moderation gate (clean `400 GUARDRAIL_BLOCKED`), retrieved text framed as untrusted data inside `<retrieved-content>` tags, and a post-stream LLM grounding judge that annotates each answer `grounded` / `ungrounded` / `unverified` without ever blocking the stream.
- **Senior-grade error handling** — a typed error taxonomy mapped to a structured `{"error": {code, message, request_id}}` envelope, request-id logging middleware, mid-stream SSE error events, and a 120s stream timeout.
- **Rate limiting** — slowapi keyed by IP: 10/hour uploads, 20/min chat, 60/min default.
- **Langfuse tracing** — full traces (agent → tool → grader → grounding score) when keys are set; a strict no-op without them.
- **119 tests, no API keys needed** — deterministic fakes for chat, embeddings, vision OCR, and moderation exercise the full LangGraph + SSE path end to end.
- **Scroll-animated landing page** — a Framer Motion walkthrough of the pipeline (upload → parse/OCR → chunks → embeddings → agent loop → streamed answer) in a paper-and-ink visual style.

## Architecture

```
 web/ (Next.js, Vercel)                  app/ (FastAPI, Render)
 ┌──────────────────────┐   REST + SSE  ┌─────────────────────────────────┐
 │ landing  /            │◄────────────►│ sessions/   workspaces + TTL    │
 │ chat     /chat        │              │ documents/  upload → 202        │
 │ lib/api.ts  lib/sse.ts│              │ ingestion/  parse→OCR→embed     │──► OpenAI
 └──────────────────────┘              │ search/     cosine over chunks  │    (vision OCR,
                                        │ chat/       LangGraph agent ────┼──► embeddings,
                                        │ guardrails/ inject·mod·ground  │    chat + optional
                                        │ shared/     errors·limits·obs  │    Anthropic fallback)
                                        └───────────┬─────────────────────┘
                                                    ▼                ╲
                                        Postgres 16 + pgvector        ╲ Langfuse (optional)
                                        sessions → documents → chunks (CASCADE)
```

## Quickstart

**Backend** (Python 3.13+, [uv](https://docs.astral.sh/uv/), Docker):

```bash
uv sync                          # install deps
cp .env.example .env             # set OPENAI_API_KEY (ANTHROPIC_API_KEY optional fallback)
docker compose up -d             # Postgres 16 + pgvector on :5432
uv run fastapi dev app/main.py   # API on :8000 (tables auto-create on startup)
```

**Frontend**:

```bash
cd web
npm install
npm run dev                      # http://localhost:3000 (talks to :8000 by default)
```

Set `NEXT_PUBLIC_API_URL` if the API runs elsewhere. A Streamlit dev tool that visualises the agent flow is also available: `uv run streamlit run scripts/streamlit_app.py`.

## API

| Method & path | Description |
|---|---|
| `POST /sessions` | Create a workspace session (`201`). |
| `GET /sessions/{id}` | Session detail incl. its documents (touches activity). |
| `DELETE /sessions/{id}` | Delete a session and everything in it. |
| `GET /sessions/{id}/messages` | Full chat history for a session. |
| `POST /sessions/{id}/documents` | Multipart upload; validates, returns `202`, processes in the background. |
| `GET /sessions/{id}/documents` | List documents with ingestion status (poll this). |
| `DELETE /sessions/{id}/documents/{doc_id}` | Remove a document and its chunks. |
| `GET /search` | Semantic search: `q` and `session_id` required, `limit` 1–20. |
| `POST /chat` | `{question, session_id}` → SSE stream: `session_id`, tokens, step events (`retrieve` / `grade_documents` / `rewrite_query`), `sources`, `grounding` verdict, `[DONE]`. |
| `GET /health` | Liveness probe. |

Interactive docs at `http://localhost:8000/docs`. Errors use a structured envelope: `{"error": {"code", "message", "request_id"}}`.

## Limits & guardrails

| Limit | Value |
|---|---|
| Max upload size | 10 MB |
| Max PDF pages | 50 |
| Vision-OCR pages per document | 20 |
| Documents per session | 20 |
| Chunks per document | 500 |
| Excel | 10 sheets, 2,000 rows/sheet |
| Question length | 4,000 chars |
| Session TTL | 24h of inactivity |
| Rate limits | 10/hour uploads · 20/min chat · 60/min default (per IP) |
| Chat stream timeout | 120 s |

Guardrail policy: moderation outages **fail open** (logged, traced as degraded); parse/OCR errors **fail closed** (document marked `failed`, never silently empty); the grounding judge **annotates, never blocks**.

## Tests

```bash
uv run pytest        # 119 tests — needs a live Postgres (docker compose up -d)
uv run ruff check .  # lint
```

Tests swap in deterministic fakes for every AI surface (chat model, embeddings, vision OCR, moderation, grounding judge), so **no API keys are needed**. Each test drops and recreates all tables — point `DATABASE_URL` at a throwaway local database, never at production.

## More docs

- **[docs/DEPLOY.md](docs/DEPLOY.md)** — Render + Vercel + Langfuse deployment runbook.
- **[CLAUDE.md](CLAUDE.md)** — a deeper architecture tour.
- **[NOTES.md](NOTES.md)** — design rationale and trade-offs (latest section in Spanish).
