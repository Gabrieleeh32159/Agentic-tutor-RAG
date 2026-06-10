from __future__ import annotations

import json
import uuid

import httpx
import pytest


@pytest.fixture
async def seeded_chat_client(client: httpx.AsyncClient) -> httpx.AsyncClient:
    """Seed DB with documents, then return the client for chat tests."""
    docs = [
        {
            "title": "Introduction to Derivatives",
            "content": "A derivative measures how a function changes as its input changes.",
            "subject": "math",
            "level": "introductory",
        },
        {
            "title": "Cell Structure",
            "content": "Eukaryotic cells contain membrane-bound organelles.",
            "subject": "biology",
            "level": "introductory",
        },
    ]
    response = await client.post("/documents/bulk", json=docs)
    assert response.status_code == 201
    return client


def _parse_sse(body: str) -> list[str]:
    """Extract data lines from an SSE response body."""
    return [line for line in body.split("\n") if line.startswith("data: ")]


def _collect_tokens(lines: list[str]) -> str:
    tokens: list[str] = []
    for line in lines:
        data = line.removeprefix("data: ")
        if data == "[DONE]":
            break
        parsed = json.loads(data)
        if "token" in parsed:
            tokens.append(parsed["token"])
    return "".join(tokens)


# ---------------------------------------------------------------------------
# Academic questions (tool calling path)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_returns_streaming_response(
    seeded_chat_client: httpx.AsyncClient,
) -> None:
    response = await seeded_chat_client.post(
        "/chat",
        json={"question": "What is a derivative?"},
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")


@pytest.mark.asyncio
async def test_chat_stream_contains_session_id(
    seeded_chat_client: httpx.AsyncClient,
) -> None:
    response = await seeded_chat_client.post(
        "/chat",
        json={"question": "What is a derivative?"},
    )
    lines = _parse_sse(response.text)
    first = json.loads(lines[0].removeprefix("data: "))
    assert "session_id" in first


@pytest.mark.asyncio
async def test_chat_stream_contains_sources(
    seeded_chat_client: httpx.AsyncClient,
) -> None:
    response = await seeded_chat_client.post(
        "/chat",
        json={"question": "What is a derivative?"},
    )
    lines = _parse_sse(response.text)
    sources_lines = [ln for ln in lines if '"sources"' in ln]
    assert len(sources_lines) > 0
    parsed = json.loads(sources_lines[0].removeprefix("data: "))
    assert "sources" in parsed
    assert isinstance(parsed["sources"], list)
    assert len(parsed["sources"]) > 0
    assert "document_id" in parsed["sources"][0]
    assert "title" in parsed["sources"][0]
    assert "score" in parsed["sources"][0]


@pytest.mark.asyncio
async def test_chat_stream_contains_tokens(
    seeded_chat_client: httpx.AsyncClient,
) -> None:
    response = await seeded_chat_client.post(
        "/chat",
        json={"question": "What is a derivative?"},
    )
    lines = _parse_sse(response.text)
    token_lines = [ln for ln in lines if '"token"' in ln]
    assert len(token_lines) > 0
    assert lines[-1] == "data: [DONE]"


@pytest.mark.asyncio
async def test_chat_stream_ends_with_done(
    seeded_chat_client: httpx.AsyncClient,
) -> None:
    response = await seeded_chat_client.post(
        "/chat",
        json={"question": "What is a derivative?"},
    )
    lines = _parse_sse(response.text)
    assert lines[-1] == "data: [DONE]"


@pytest.mark.asyncio
async def test_chat_stream_full_answer(
    seeded_chat_client: httpx.AsyncClient,
) -> None:
    response = await seeded_chat_client.post(
        "/chat",
        json={"question": "What is a derivative?"},
    )
    lines = _parse_sse(response.text)
    full_answer = _collect_tokens(lines)
    assert full_answer == "This is a test answer."


@pytest.mark.asyncio
async def test_chat_with_subject_filter(
    seeded_chat_client: httpx.AsyncClient,
) -> None:
    response = await seeded_chat_client.post(
        "/chat",
        json={"question": "Tell me about cells", "subject": "biology"},
    )
    assert response.status_code == 200
    lines = _parse_sse(response.text)
    sources_line = next(ln for ln in lines if '"sources"' in ln)
    parsed = json.loads(sources_line.removeprefix("data: "))
    for src in parsed["sources"]:
        assert src["title"] == "Cell Structure"


# ---------------------------------------------------------------------------
# Casual questions (no tool calling)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_casual_no_search(client: httpx.AsyncClient) -> None:
    """A casual greeting should get a direct response with no sources."""
    response = await client.post("/chat", json={"question": "Hola"})
    assert response.status_code == 200
    lines = _parse_sse(response.text)
    sources_lines = [ln for ln in lines if '"sources"' in ln]
    assert len(sources_lines) == 0
    full_answer = _collect_tokens(lines)
    assert len(full_answer) > 0
    assert lines[-1] == "data: [DONE]"


# ---------------------------------------------------------------------------
# Session management
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_creates_session(
    seeded_chat_client: httpx.AsyncClient,
) -> None:
    """First message should create a session and return session_id."""
    response = await seeded_chat_client.post(
        "/chat",
        json={"question": "What is a derivative?"},
    )
    lines = _parse_sse(response.text)
    first = json.loads(lines[0].removeprefix("data: "))
    session_id = first["session_id"]
    # Verify it's a valid UUID
    uuid.UUID(session_id)


@pytest.mark.asyncio
async def test_chat_continues_session(
    seeded_chat_client: httpx.AsyncClient,
) -> None:
    """Sending a second message to the same session should preserve context."""
    # First message
    r1 = await seeded_chat_client.post(
        "/chat",
        json={"question": "What is a derivative?"},
    )
    lines1 = _parse_sse(r1.text)
    session_id = json.loads(lines1[0].removeprefix("data: "))["session_id"]

    # Second message to the same session
    r2 = await seeded_chat_client.post(
        "/chat",
        json={"question": "Explain more", "session_id": session_id},
    )
    assert r2.status_code == 200
    lines2 = _parse_sse(r2.text)
    sid2 = json.loads(lines2[0].removeprefix("data: "))["session_id"]
    assert sid2 == session_id


@pytest.mark.asyncio
async def test_chat_session_messages(
    seeded_chat_client: httpx.AsyncClient,
) -> None:
    """GET /chat/sessions/{id}/messages should return persisted messages."""
    r = await seeded_chat_client.post(
        "/chat",
        json={"question": "What is a derivative?"},
    )
    lines = _parse_sse(r.text)
    session_id = json.loads(lines[0].removeprefix("data: "))["session_id"]

    # Fetch messages
    r2 = await seeded_chat_client.get(f"/chat/sessions/{session_id}/messages")
    assert r2.status_code == 200
    messages = r2.json()
    assert len(messages) >= 2, f"Expected at least 2 messages (human + ai), got {len(messages)}: {messages}"
    roles = [m["role"] for m in messages]
    assert roles[0] == "human"
    assert "ai" in roles, f"No 'ai' message found in roles: {roles}"
    # Verify the human message content
    assert messages[0]["content"] == "What is a derivative?"
    # Verify at least one ai message has non-empty content
    ai_messages = [m for m in messages if m["role"] == "ai" and m["content"]]
    assert len(ai_messages) >= 1, f"No ai message with content found: {messages}"


@pytest.mark.asyncio
async def test_chat_casual_messages_persisted(
    client: httpx.AsyncClient,
) -> None:
    """A casual (no-tool) conversation should also persist messages."""
    r = await client.post("/chat", json={"question": "Hola"})
    assert r.status_code == 200
    lines = _parse_sse(r.text)
    session_id = json.loads(lines[0].removeprefix("data: "))["session_id"]

    r2 = await client.get(f"/chat/sessions/{session_id}/messages")
    assert r2.status_code == 200
    messages = r2.json()
    assert len(messages) >= 2, f"Expected at least 2 messages, got {len(messages)}: {messages}"
    assert messages[0]["role"] == "human"
    assert messages[0]["content"] == "Hola"
    ai_messages = [m for m in messages if m["role"] == "ai"]
    assert len(ai_messages) >= 1
    assert len(ai_messages[0]["content"]) > 0


@pytest.mark.asyncio
async def test_chat_list_sessions(
    seeded_chat_client: httpx.AsyncClient,
) -> None:
    """GET /chat/sessions should return created sessions."""
    await seeded_chat_client.post(
        "/chat",
        json={"question": "What is a derivative?"},
    )
    r = await seeded_chat_client.get("/chat/sessions")
    assert r.status_code == 200
    sessions = r.json()
    assert len(sessions) >= 1
    assert "id" in sessions[0]
    assert "title" in sessions[0]


@pytest.mark.asyncio
async def test_chat_delete_session(
    seeded_chat_client: httpx.AsyncClient,
) -> None:
    """DELETE /chat/sessions/{id} should remove session and messages."""
    r = await seeded_chat_client.post(
        "/chat",
        json={"question": "What is a derivative?"},
    )
    lines = _parse_sse(r.text)
    session_id = json.loads(lines[0].removeprefix("data: "))["session_id"]

    # Delete
    r2 = await seeded_chat_client.delete(f"/chat/sessions/{session_id}")
    assert r2.status_code == 204

    # Verify it's gone
    r3 = await seeded_chat_client.get(f"/chat/sessions/{session_id}/messages")
    assert r3.status_code == 404


@pytest.mark.asyncio
async def test_chat_invalid_session_id(client: httpx.AsyncClient) -> None:
    """Using a non-existent session_id should return 404."""
    fake_id = str(uuid.uuid4())
    response = await client.post(
        "/chat",
        json={"question": "Hello", "session_id": fake_id},
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_chat_tool_messages_persisted(
    seeded_chat_client: httpx.AsyncClient,
) -> None:
    """After an academic question (tool calling), tool messages must be saved."""
    r = await seeded_chat_client.post(
        "/chat",
        json={"question": "What is a derivative?"},
    )
    assert r.status_code == 200
    lines = _parse_sse(r.text)
    session_id = json.loads(lines[0].removeprefix("data: "))["session_id"]

    r2 = await seeded_chat_client.get(f"/chat/sessions/{session_id}/messages")
    messages = r2.json()
    roles = [m["role"] for m in messages]
    # Must have: human → ai (tool_calls) → tool → ai (answer)
    assert "tool" in roles, f"ToolMessages not persisted. Roles: {roles}"
    # The ai message with tool_calls should have non-empty tool_calls
    ai_with_tools = [m for m in messages if m["role"] == "ai" and m.get("tool_calls")]
    assert len(ai_with_tools) >= 1, f"No AI message with tool_calls found: {messages}"


@pytest.mark.asyncio
async def test_chat_multiturn_with_tools(
    seeded_chat_client: httpx.AsyncClient,
) -> None:
    """A follow-up after a tool-calling turn must work (history is valid)."""
    # First turn: academic question triggers tools
    r1 = await seeded_chat_client.post(
        "/chat",
        json={"question": "What is a derivative?"},
    )
    assert r1.status_code == 200
    lines1 = _parse_sse(r1.text)
    session_id = json.loads(lines1[0].removeprefix("data: "))["session_id"]

    # Second turn: casual follow-up on same session
    r2 = await seeded_chat_client.post(
        "/chat",
        json={"question": "Thanks!", "session_id": session_id},
    )
    assert r2.status_code == 200
    lines2 = _parse_sse(r2.text)
    # Should NOT contain an error
    error_lines = [ln for ln in lines2 if '"error"' in ln]
    assert len(error_lines) == 0, f"Got errors: {error_lines}"
    # Should end with [DONE]
    assert lines2[-1] == "data: [DONE]"


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_missing_question(client: httpx.AsyncClient) -> None:
    response = await client.post("/chat", json={})
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_chat_empty_question(client: httpx.AsyncClient) -> None:
    response = await client.post("/chat", json={"question": ""})
    assert response.status_code == 422
