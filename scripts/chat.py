"""Interactive chat script that pretty-prints sources and streams the LLM answer."""

from __future__ import annotations

import json
import sys

import httpx

BASE_URL = "http://localhost:8000"


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: uv run python scripts/chat.py 'your question' [subject] [level]")
        sys.exit(1)

    question = sys.argv[1]
    subject = sys.argv[2] if len(sys.argv) > 2 else None
    level = sys.argv[3] if len(sys.argv) > 3 else None

    payload: dict[str, str] = {"question": question}
    if subject:
        payload["subject"] = subject
    if level:
        payload["level"] = level

    print(f"\n{'─' * 60}")
    print(f"  Question: {question}")
    if subject:
        print(f"  Subject:  {subject}")
    if level:
        print(f"  Level:    {level}")
    print(f"{'─' * 60}\n")

    with httpx.stream(
        "POST",
        f"{BASE_URL}/chat",
        json=payload,
        timeout=60.0,
    ) as response:
        if response.status_code != 200:
            print(f"Error: HTTP {response.status_code}")
            print(response.read().decode())
            sys.exit(1)

        sources_printed = False

        for line in response.iter_lines():
            if not line.startswith("data: "):
                continue

            data = line.removeprefix("data: ")

            if data == "[DONE]":
                print("\n")
                break

            parsed = json.loads(data)

            if "sources" in parsed and not sources_printed:
                sources = parsed["sources"]
                print("  📚 Source Documents:")
                print(f"  {'─' * 50}")
                for i, src in enumerate(sources, 1):
                    score_pct = src["score"] * 100
                    print(f"  {i}. {src['title']}")
                    print(f"     ID:    {src['document_id']}")
                    print(f"     Score: {score_pct:.1f}%")
                    chunks = src.get("chunks", [])
                    for j, chunk in enumerate(chunks, 1):
                        preview = chunk["chunk_text"][:120].replace("\n", " ")
                        print(f"     Chunk {j} (score {chunk['score']:.4f}): {preview}...")
                print(f"  {'─' * 50}\n")
                sources_printed = True

            elif "step" in parsed:
                step = parsed["step"]
                detail = parsed.get("detail", "")
                if step == "retrieve":
                    print(f"  🔍 [{step}] {detail}")
                elif step == "grade_documents":
                    is_relevant = parsed.get("is_relevant", False)
                    icon = "✅" if is_relevant else "❌"
                    print(f"  {icon} [{step}] {detail}")
                elif step == "generate":
                    print(f"  🤖 [{step}] {detail}\n")
                    print("  💬 Answer:\n")
                elif step == "rewrite_query":
                    retry = parsed.get("retry", 0)
                    new_q = parsed.get("new_question", "")
                    print(f"  🔄 [{step}] Attempt {retry}: \"{new_q}\"")
                    sources_printed = False
                elif step == "not_found":
                    print(f"  ⚠️  [{step}] {detail}\n")

            elif "token" in parsed:
                sys.stdout.write(parsed["token"])
                sys.stdout.flush()

            elif "error" in parsed:
                print(f"\n  ❌ Error: {parsed['error']}")
                sys.exit(1)

    print(f"{'─' * 60}")


if __name__ == "__main__":
    main()
