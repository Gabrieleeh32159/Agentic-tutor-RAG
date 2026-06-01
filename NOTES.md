# Design Notes

Running notes on the technical decisions behind this project — what I chose, why, and what I'd change. This began as a take-home exercise; these notes started as the interview write-up and I keep them as a design log.

## Technical decisions

**Provider abstraction.** I use OpenAI by default for convenience, but the calls go through an abstraction (`EmbeddingProvider` ABC for embeddings, a LangChain `BaseChatModel` for chat) so the application code doesn't depend on the provider. Adding a different provider means extending the abstraction, not touching callers. For chat I also wired an optional Anthropic fallback via LangChain's `.with_fallbacks(...)` — if the primary errors out, the secondary takes over.

**Retrieval `k`.** For this small dataset, returning ~3 documents feels like enough; a very high `k` would introduce noise from documents I don't actually want. With more data I'd raise it to 5, 10, or more. There's no single "perfect" value — it's something to iterate on until results look good.

**Where the context goes in the prompt.** I put the retrieved context in the *user* prompt rather than the system prompt, because it's data that changes between requests, and a fragment could even contain malicious content attempting prompt injection — keeping it out of the system prompt limits its authority. The user prompt lists the relevant documents in order, followed by the student's question:

```
Context documents:
[1] Title: Document 1
Content of document 1

[2] Title: Document 2
Content of document 2

Student question: {question}
```

**Agentic retrieval.** Rather than a single fixed search, the agent decides whether to retrieve at all, grades the relevance of what it gets back, and rewrites the query to retry when results are weak. Grading is cheap by default (score thresholds) and only falls back to an LLM grader for the ambiguous middle band, to keep cost down.

## Trade-offs and things left out

**Chunking.** In a real, larger project I'd chunk the content and embed the chunks (which is what I ended up doing here), store those vectors in a dedicated chunks table, and possibly attach metadata to each chunk before embedding. The current splitter is a reasonable default but not tuned per content type.

**No vector index.** Search is exact (no IVFFlat/HNSW). Fine for ~20 documents; the first thing to add before scaling.

**Cost optimization.** Relevance grading uses score thresholds first and only calls the LLM grader for borderline cases, to avoid an LLM call on every search.

## What I'd do next

- Better evaluation of search quality (e.g. an LLM-graded eval harness over a fixed question set).
- Tune chunking — size, overlap, and per-subject strategies.
- Add an ANN index on the embedding column.
- Hybrid retrieval (keyword + vector) and richer per-chunk metadata.
