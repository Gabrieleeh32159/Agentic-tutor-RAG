# Take-Home Challenge: Educational Content RAG Service

Welcome! This is a practical backend + AI engineering challenge modeled after a real-world problem: building a small, production-ready slice of an educational content retrieval and AI-tutor service.

The challenge is organized in four progressive steps. **You do not have to finish all four** to be considered -- quality over completeness. Leave notes in your `NOTES.md` about anything you skipped and why.

## Context

You are building a backend service that:

1. **Ingests** educational documents (title + content + subject + level).
2. **Indexes** them for semantic search using OpenAI embeddings + pgvector.
3. **Answers** student questions using Retrieval-Augmented Generation (RAG), citing the relevant documents.
4. **Generates** study flashcards from any indexed document using structured LLM output.

This is a simplified version of patterns used in real edtech AI platforms -- semantic content retrieval, multi-provider LLM orchestration, structured outputs for educational artifacts.

## Tech stack (fixed)

- **Python 3.13+** with [uv](https://docs.astral.sh/uv/) as the package manager
- **FastAPI** for the HTTP layer, **async throughout**
- **PostgreSQL 16** with the **pgvector** extension (provided via `docker-compose.yml`)
- **SQLAlchemy (async)** + **SQLModel** for ORM, **asyncpg** as the driver
- **Pydantic v2** for all request/response schemas
- **OpenAI** for embeddings. **OpenAI or Anthropic** for chat (your choice, or both with a fallback)
- **pytest** + **pytest-asyncio** for tests

A `pyproject.toml` scaffold with the core dependencies is already included. You may add more if you need to.

## Steps

### Step 1 -- Ingestion API

Build a `POST /documents` endpoint that:

- Accepts a JSON body with `title`, `content`, `subject`, `level` (use `introductory | intermediate | advanced`).
- Stores the document in PostgreSQL.
- Generates an embedding with OpenAI (`text-embedding-3-small` is fine) from the `content`.
- Stores the embedding in a `pgvector` column.
- Returns the created document's `id` and basic metadata.

A sample dataset is provided at `data/documents.jsonl`. Provide a way to bulk-ingest it (a CLI script or an endpoint -- your call).

### Step 2 -- Semantic Search

Build a `GET /search` endpoint:

- Query params: `q` (required), `limit` (default 5, max 20), optional `subject`, optional `level`.
- Converts `q` to an embedding using the same model as ingestion.
- Returns the top `limit` documents by **cosine similarity**, optionally filtered by `subject` / `level`.
- Response must include the similarity score for each result.

### Step 3 -- AI Study Assistant / RAG

Build a `POST /chat` endpoint:

- Accepts a JSON body with `question` (string) and optional `subject` / `level` filters.
- Retrieves relevant documents using the semantic search from Step 2.
- Answers the student's question grounded in the retrieved context, citing the source documents.
- Calls an LLM (OpenAI **or** Anthropic, candidate's choice).
- Returns a **streaming** response.
- The response must also include the list of document IDs that were retrieved as context.

**Bonus**: support both OpenAI and Anthropic with a fallback mechanism -- if the primary provider errors out, try the secondary.

### Step 4 -- Flashcard Generation (Bonus)

Build a `POST /flashcards/generate` endpoint:

- Accepts a `document_id` (and optional `count`, default 5).
- Loads the document.
- Uses the LLM with **structured output** (function calling, JSON mode, or `pydantic-ai`) to generate `count` flashcards, each with `question`, `answer`, `difficulty` (`easy | medium | hard`).
- Returns the generated flashcards.

Do not persist the flashcards -- just return them. What matters here is the structured-output prompt engineering, not storage.

## What "done" looks like

- The service runs end-to-end from a clean clone: `docker compose up -d` + the run command below, and every endpoint you implemented responds correctly.
- The codebase is ready for a team code review. You decide what that means.
- No hardcoded secrets in the repo.
- `NOTES.md` is filled in (it anchors our sync technical interview).

## Time target

4 to 6 hours for Steps 1-3. Step 4 is explicitly a bonus. There is no hard deadline once you accept the GitHub invitation -- quality is what matters.

## Getting started

```bash
# 1. Install uv if you do not have it
# https://docs.astral.sh/uv/

# 2. Install dependencies
uv sync

# 3. Copy and fill the env file
cp .env.example .env   # at minimum, set OPENAI_API_KEY

# 4. Start Postgres + pgvector
docker compose up -d

# 5. Run the service
uv run fastapi dev app/main.py

# 6. Run the tests
uv run pytest
```

## Submission

When you are ready:

1. Make sure the repo builds and tests pass on a clean clone.
2. Fill in `NOTES.md` with:
   - Your main technical decisions and **why** (provider choice, data model, prompt design, retrieval strategy, etc.).
   - Any trade-offs or things you deliberately left out.
   - What you would do next if you had more time.
3. Push your final commit to the `main` branch of this repo.
4. Reply to the email we sent you, and include a short (~5 min) Loom screencast walking through your solution.

Good luck, and have fun -- this is meant to be a realistic slice of the work, not a gotcha.

We evaluate architecture, AI integration quality, data modeling, and production readiness -- but we care more about thoughtful decisions than feature completeness.
