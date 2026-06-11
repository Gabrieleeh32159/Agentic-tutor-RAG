"""Interactive chat script that pretty-prints sources and streams the LLM answer.

Supports multi-turn conversations via session_id persistence.

Usage:
    uv run python scripts/chat.py 'your question'
    uv run python scripts/chat.py 'your question' <existing-session-id>
"""

from __future__ import annotations

import json
import sys

import httpx

BASE_URL = "http://localhost:8000"


def _create_session() -> str:
    """POST /sessions and return the new session id."""
    resp = httpx.post(f"{BASE_URL}/sessions", timeout=10.0)
    resp.raise_for_status()
    sid = resp.json()["id"]
    print(f"  📝 New session: {sid}")
    return sid


def chat_turn(question: str, session_id: str) -> None:
    """Send one message and stream the response."""
    payload: dict[str, str] = {"question": question, "session_id": session_id}

    print(f"\n{'─' * 60}")
    print(f"  Question: {question}")
    print(f"  Session:  {session_id}")
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

        answer_started = False

        for line in response.iter_lines():
            if not line.startswith("data: "):
                continue

            data = line.removeprefix("data: ")

            if data == "[DONE]":
                print("\n")
                break

            parsed = json.loads(data)

            if "sources" in parsed:
                sources = parsed["sources"]
                print("  📚 Source Documents:")
                print(f"  {'─' * 50}")
                for i, src in enumerate(sources, 1):
                    score_pct = src["score"] * 100
                    print(f"  {i}. {src['filename']}")
                    print(f"     ID:    {src['document_id']}")
                    print(f"     Score: {score_pct:.1f}%")
                    chunks = src.get("chunks", [])
                    for j, chunk in enumerate(chunks, 1):
                        preview = chunk["chunk_text"][:120].replace("\n", " ")
                        print(
                            f"     Chunk {j} (score {chunk['score']:.4f}): {preview}..."
                        )
                print(f"  {'─' * 50}\n")

            elif "step" in parsed:
                step = parsed["step"]
                detail = parsed.get("detail", "")
                if step == "retrieve":
                    print(f"  🔍 [{step}] {detail}")
                elif step == "grade_documents":
                    is_relevant = parsed.get("is_relevant", False)
                    grade_query = parsed.get("query", "")
                    icon = "✅" if is_relevant else "❌"
                    print(
                        f'  {icon} [{step}] Results for "{grade_query}" are {"relevant" if is_relevant else "not relevant"}'
                    )
                elif step == "rewrite_query":
                    retry = parsed.get("retry", 0)
                    new_q = parsed.get("new_question", "")
                    print(f'  🔄 [{step}] Attempt {retry}: "{new_q}"')

            elif "token" in parsed:
                if not answer_started:
                    print("  💬 Answer:\n")
                    answer_started = True
                sys.stdout.write(parsed["token"])
                sys.stdout.flush()

            elif "error" in parsed:
                print(f"\n  ❌ Error: {parsed['error']}")
                sys.exit(1)

    print(f"{'─' * 60}")


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: uv run python scripts/chat.py 'your question' [session-id]")
        print(
            "       After the first message, enter follow-up questions interactively."
        )
        sys.exit(1)

    question = sys.argv[1]
    session_id = sys.argv[2] if len(sys.argv) > 2 else _create_session()

    chat_turn(question, session_id)

    # Interactive follow-up loop
    while True:
        try:
            follow_up = input("\n  Follow-up (or 'q' to quit): ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n  Bye!")
            break
        if not follow_up or follow_up.lower() == "q":
            break
        chat_turn(follow_up, session_id)


if __name__ == "__main__":
    main()
