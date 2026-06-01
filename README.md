# Agentic RAG — Educational Study Assistant

A small, production-minded backend that ingests educational documents, indexes them with OpenAI embeddings in **pgvector**, and answers student questions with a **self-correcting agentic RAG** loop over a streaming API. It ships with a Streamlit UI that visualises the agent's retrieve → grade → rewrite reasoning step by step.

This started as a take-home exercise and I've kept extending it as a personal playground for retrieval, LangGraph agents, and async FastAPI patterns.

## What it does

- **Ingests** documents (`title`, `content`, `subject`, `level`), chunks them, and stores per-chunk embeddings in pgvector.
- **Searches** semantically by cosine similarity, with optional `subject` / `level` filters and similarity scores.
- **Answers** questions with an agent that decides *whether* to retrieve, grades the relevance of what it finds, and **rewrites the query and retries** when results are weak — then streams a cited, Markdown/LaTeX-formatted answer.
- **Remembers** conversations: sessions and message history are persisted, so chats are multi-turn.

## Architecture at a glance

```
                ┌──────────────┐   embed (enriched: title+subject+level+chunk)
  POST /documents│  documents   │──────────────────────────────┐
                └──────────────┘                               ▼
                                                        ┌──────────────┐
  GET /search ──────────────────────────────────────►  │   pgvector   │
                                                        │ document_    │
                ┌──────────────┐                        │  chunks      │
  POST /chat ──►│  LangGraph   │  search_documents tool │ (Vector 1536)│
                │    agent     │──(in-process ASGI)────► └──────────────┘
                │ agent⇄tools  │        │  GET /search
                └──────┬───────┘        ▼
                       │         retrieve → grade relevance → rewrite → retry
                       ▼
                  SSE stream: tokens + step events + sources + [DONE]
```

The agentic RAG tool (`app/chat/tools.py`) is the heart of it. On each search it grades the top result: high score → use it, low score → reject, in-between → an LLM grader decides. If results are weak and retries remain, it rewrites the query and tries again before giving up. Every step is surfaced to the client as a server-sent event, which the Streamlit UI renders live.

For a deeper tour of the design (chunking strategy, why search runs over an in-process HTTP call, persistence ordering, provider abstractions), see **[CLAUDE.md](CLAUDE.md)**. Design decisions and trade-offs are in **[NOTES.md](NOTES.md)**.

## Tech stack

- **Python 3.13+** with [uv](https://docs.astral.sh/uv/)
- **FastAPI**, async throughout
- **PostgreSQL 16 + pgvector** for vector storage and cosine search
- **SQLAlchemy (async)** + **SQLModel** + **asyncpg**
- **Pydantic v2** for all schemas
- **LangChain / LangGraph** for the agent; **OpenAI** embeddings + chat, with optional **Anthropic** fallback
- **Streamlit** for the visual chat UI
- **pytest** + **pytest-asyncio**

## Getting started

```bash
# 1. Install uv — https://docs.astral.sh/uv/

# 2. Install dependencies
uv sync

# 3. Configure environment (at minimum set OPENAI_API_KEY)
cp .env.example .env

# 4. Start Postgres + pgvector
docker compose up -d

# 5. Run the API (tables are created automatically on startup)
uv run fastapi dev app/main.py

# 6. Load the sample dataset (20 docs across math, biology, history, programming, science)
uv run python scripts/ingest_documents.py

# 7. Chat with it
uv run streamlit run scripts/streamlit_app.py   # visual UI at http://localhost:8501
#   or
uv run python scripts/chat.py                    # terminal client
```

Set `ANTHROPIC_API_KEY` as well to enable automatic fallback if OpenAI errors out.

## API

| Method & path | Description |
|---|---|
| `POST /documents` | Ingest one document; chunks + embeds it. |
| `POST /documents/bulk` | Ingest a batch (used by the loader script). |
| `GET /search` | Semantic search: `q` (required), `limit` (1–20), optional `subject`, `level`. Returns documents with similarity scores and matched chunks. |
| `POST /chat` | Ask a question; returns an SSE stream of tokens, retrieval/grade/rewrite step events, and the source documents. Pass `session_id` to continue a conversation. |
| `GET /chat/sessions` | List chat sessions. |
| `GET /chat/sessions/{id}/messages` | Full message history for a session. |
| `DELETE /chat/sessions/{id}` | Delete a session and its messages. |
| `GET /health` | Liveness probe. |

Interactive docs at `http://localhost:8000/docs` once the server is running.

## Tests

```bash
uv run pytest            # needs Postgres running
uv run ruff check .      # lint
```

Tests swap in deterministic fake embedding and chat models, so **no API keys are needed to run them** — the full LangGraph + SSE path is exercised end to end. Note that each test drops and recreates all tables, so point tests at a throwaway database.

## Roadmap

Things I want to explore next (see [NOTES.md](NOTES.md) for context):

- Add an ANN index (IVFFlat / HNSW) on the embedding column — search is currently exact.
- Richer chunk metadata and hybrid (keyword + vector) retrieval.
- Flashcard generation from a document using structured LLM output.
- LLM-graded evaluation of retrieval quality.
