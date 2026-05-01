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
                    print(f"     ID:    {src['id']}")
                    print(f"     Score: {score_pct:.1f}%")
                print(f"  {'─' * 50}\n")
                print("  💬 Answer:\n")
                sources_printed = True

            elif "token" in parsed:
                sys.stdout.write(parsed["token"])
                sys.stdout.flush()

            elif "error" in parsed:
                print(f"\n  ❌ Error: {parsed['error']}")
                sys.exit(1)

    print(f"{'─' * 60}")


if __name__ == "__main__":
    main()
