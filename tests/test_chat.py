from __future__ import annotations

import json

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
async def test_chat_stream_contains_sources(
    seeded_chat_client: httpx.AsyncClient,
) -> None:
    response = await seeded_chat_client.post(
        "/chat",
        json={"question": "What is a derivative?"},
    )
    body = response.text
    lines = [l for l in body.split("\n") if l.startswith("data: ")]

    # First data event should be sources
    first_data = lines[0].removeprefix("data: ")
    parsed = json.loads(first_data)
    assert "sources" in parsed
    assert isinstance(parsed["sources"], list)
    assert len(parsed["sources"]) > 0
    assert "id" in parsed["sources"][0]
    assert "title" in parsed["sources"][0]


@pytest.mark.asyncio
async def test_chat_stream_contains_tokens(
    seeded_chat_client: httpx.AsyncClient,
) -> None:
    response = await seeded_chat_client.post(
        "/chat",
        json={"question": "What is a derivative?"},
    )
    body = response.text
    lines = [l for l in body.split("\n") if l.startswith("data: ")]

    # Should have token events between sources and [DONE]
    token_lines = [l for l in lines if '"token"' in l]
    assert len(token_lines) > 0

    # Last event should be [DONE]
    assert lines[-1] == "data: [DONE]"


@pytest.mark.asyncio
async def test_chat_stream_full_answer(
    seeded_chat_client: httpx.AsyncClient,
) -> None:
    response = await seeded_chat_client.post(
        "/chat",
        json={"question": "What is a derivative?"},
    )
    body = response.text
    lines = [l for l in body.split("\n") if l.startswith("data: ")]

    tokens = []
    for line in lines:
        data = line.removeprefix("data: ")
        if data == "[DONE]":
            break
        parsed = json.loads(data)
        if "token" in parsed:
            tokens.append(parsed["token"])

    full_answer = "".join(tokens)
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
    body = response.text
    lines = [l for l in body.split("\n") if l.startswith("data: ")]
    first_data = json.loads(lines[0].removeprefix("data: "))
    # All sources should be biology
    for src in first_data["sources"]:
        # We only seeded one biology doc, so it should show up
        assert src["title"] == "Cell Structure"


@pytest.mark.asyncio
async def test_chat_missing_question(client: httpx.AsyncClient) -> None:
    response = await client.post("/chat", json={})
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_chat_empty_question(client: httpx.AsyncClient) -> None:
    response = await client.post("/chat", json={"question": ""})
    assert response.status_code == 422
