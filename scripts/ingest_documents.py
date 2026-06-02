from __future__ import annotations

import json
import os
from pathlib import Path

import httpx

# Base URL of the running API. Override for a deployed target, e.g.:
#   API_BASE_URL=https://agentic-rag-api.onrender.com uv run python scripts/ingest_documents.py
API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8000").rstrip("/")
API_URL = f"{API_BASE_URL}/documents/bulk"
JSONL_PATH = Path(__file__).resolve().parent.parent / "data" / "documents.jsonl"
BATCH_SIZE = 10


def main() -> None:
    items: list[dict] = []
    with open(JSONL_PATH) as f:
        for line in f:
            items.append(json.loads(line))

    print(f"Loaded {len(items)} documents from {JSONL_PATH.name}")
    print(f"Target: {API_URL}")

    with httpx.Client(timeout=60) as client:
        for i in range(0, len(items), BATCH_SIZE):
            batch = items[i : i + BATCH_SIZE]
            response = client.post(API_URL, json=batch)
            response.raise_for_status()
            docs = response.json()
            total_chunks = sum(d.get("chunk_count", 0) for d in docs)
            print(
                f"  Batch {i // BATCH_SIZE + 1}: ingested {len(docs)} documents ({total_chunks} chunks)"
            )

    print(f"Done. Total documents ingested: {len(items)}")


if __name__ == "__main__":
    main()
