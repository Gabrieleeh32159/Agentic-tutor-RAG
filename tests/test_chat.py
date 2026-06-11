from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy import update

from app.ingestion.service import wait_for_ingestion
from app.sessions.models import Session
from app.shared.database import get_session_factory

MD_DERIVATIVES = b"A derivative measures how a function changes as its input changes."
MD_CELLS = b"Eukaryotic cells contain membrane-bound organelles."


async def _create_session(client: httpx.AsyncClient) -> str:
    response = await client.post("/sessions")
    assert response.status_code == 201
    return response.json()["id"]


@pytest.fixture
async def chat_session(client: httpx.AsyncClient) -> tuple[httpx.AsyncClient, str]:
    """A session seeded with two ready documents."""
    sid = await _create_session(client)
    for name, content in [("derivatives.md", MD_DERIVATIVES), ("cells.md", MD_CELLS)]:
        response = await client.post(
            f"/sessions/{sid}/documents",
            files={"file": (name, content, "text/markdown")},
        )
        assert response.status_code == 202
    await wait_for_ingestion()
    return client, sid


def _parse_sse(body: str) -> list[str]:
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


async def test_chat_returns_streaming_response(
    chat_session: tuple[httpx.AsyncClient, str],
) -> None:
    client, sid = chat_session
    response = await client.post(
        "/chat", json={"question": "What is a derivative?", "session_id": sid}
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")


async def test_chat_stream_contains_session_id(
    chat_session: tuple[httpx.AsyncClient, str],
) -> None:
    client, sid = chat_session
    response = await client.post(
        "/chat", json={"question": "What is a derivative?", "session_id": sid}
    )
    lines = _parse_sse(response.text)
    first = json.loads(lines[0].removeprefix("data: "))
    assert first["session_id"] == sid


async def test_chat_stream_contains_sources_with_filename(
    chat_session: tuple[httpx.AsyncClient, str],
) -> None:
    client, sid = chat_session
    response = await client.post(
        "/chat", json={"question": "What is a derivative?", "session_id": sid}
    )
    lines = _parse_sse(response.text)
    sources_lines = [ln for ln in lines if '"sources"' in ln]
    assert len(sources_lines) > 0
    parsed = json.loads(sources_lines[0].removeprefix("data: "))
    assert len(parsed["sources"]) > 0
    src = parsed["sources"][0]
    assert "document_id" in src
    assert "filename" in src
    assert "score" in src


async def test_chat_stream_full_answer_and_done(
    chat_session: tuple[httpx.AsyncClient, str],
) -> None:
    client, sid = chat_session
    response = await client.post(
        "/chat", json={"question": "What is a derivative?", "session_id": sid}
    )
    lines = _parse_sse(response.text)
    assert _collect_tokens(lines) == "This is a test answer."
    assert lines[-1] == "data: [DONE]"


async def test_chat_only_searches_own_session(
    chat_session: tuple[httpx.AsyncClient, str],
) -> None:
    """A fresh session with no documents must not see the seeded docs."""
    client, _ = chat_session
    empty_sid = await _create_session(client)
    response = await client.post(
        "/chat", json={"question": "What is a derivative?", "session_id": empty_sid}
    )
    assert response.status_code == 200
    lines = _parse_sse(response.text)
    sources_lines = [ln for ln in lines if '"sources"' in ln]
    for line in sources_lines:
        parsed = json.loads(line.removeprefix("data: "))
        assert parsed["sources"] == []


# ---------------------------------------------------------------------------
# Casual questions (no tool calling)
# ---------------------------------------------------------------------------


async def test_chat_casual_no_search(client: httpx.AsyncClient) -> None:
    sid = await _create_session(client)
    response = await client.post("/chat", json={"question": "Hola", "session_id": sid})
    assert response.status_code == 200
    lines = _parse_sse(response.text)
    assert [ln for ln in lines if '"sources"' in ln] == []
    assert len(_collect_tokens(lines)) > 0
    assert lines[-1] == "data: [DONE]"


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------


async def test_chat_messages_persisted(
    chat_session: tuple[httpx.AsyncClient, str],
) -> None:
    client, sid = chat_session
    await client.post(
        "/chat", json={"question": "What is a derivative?", "session_id": sid}
    )

    response = await client.get(f"/sessions/{sid}/messages")
    assert response.status_code == 200
    messages = response.json()
    assert len(messages) >= 2
    assert messages[0]["role"] == "human"
    assert messages[0]["content"] == "What is a derivative?"
    ai_messages = [m for m in messages if m["role"] == "ai" and m["content"]]
    assert len(ai_messages) >= 1


async def test_chat_tool_messages_persisted(
    chat_session: tuple[httpx.AsyncClient, str],
) -> None:
    client, sid = chat_session
    await client.post(
        "/chat", json={"question": "What is a derivative?", "session_id": sid}
    )

    messages = (await client.get(f"/sessions/{sid}/messages")).json()
    roles = [m["role"] for m in messages]
    assert "tool" in roles, f"ToolMessages not persisted. Roles: {roles}"
    ai_with_tools = [m for m in messages if m["role"] == "ai" and m.get("tool_calls")]
    assert len(ai_with_tools) >= 1


async def test_chat_multiturn_with_tools(
    chat_session: tuple[httpx.AsyncClient, str],
) -> None:
    client, sid = chat_session
    r1 = await client.post(
        "/chat", json={"question": "What is a derivative?", "session_id": sid}
    )
    assert r1.status_code == 200

    r2 = await client.post("/chat", json={"question": "Thanks!", "session_id": sid})
    assert r2.status_code == 200
    lines = _parse_sse(r2.text)
    assert [ln for ln in lines if '"error"' in ln] == []
    assert lines[-1] == "data: [DONE]"


async def test_chat_sets_session_title(
    chat_session: tuple[httpx.AsyncClient, str],
) -> None:
    client, sid = chat_session
    await client.post(
        "/chat", json={"question": "What is a derivative?", "session_id": sid}
    )
    detail = (await client.get(f"/sessions/{sid}")).json()
    assert detail["title"] == "What is a derivative?"


# ---------------------------------------------------------------------------
# Validation & session binding
# ---------------------------------------------------------------------------


async def test_chat_requires_session_id(client: httpx.AsyncClient) -> None:
    response = await client.post("/chat", json={"question": "Hello"})
    assert response.status_code == 422


async def test_chat_unknown_session_returns_404(client: httpx.AsyncClient) -> None:
    response = await client.post(
        "/chat", json={"question": "Hello", "session_id": str(uuid.uuid4())}
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "SESSION_NOT_FOUND"


async def test_chat_missing_question(client: httpx.AsyncClient) -> None:
    sid = await _create_session(client)
    response = await client.post("/chat", json={"session_id": sid})
    assert response.status_code == 422


async def test_chat_empty_question(client: httpx.AsyncClient) -> None:
    sid = await _create_session(client)
    response = await client.post("/chat", json={"question": "", "session_id": sid})
    assert response.status_code == 422


async def test_messages_endpoint_unknown_session(client: httpx.AsyncClient) -> None:
    response = await client.get(f"/sessions/{uuid.uuid4()}/messages")
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Expired session
# ---------------------------------------------------------------------------


async def _backdate_session(session_id: str, *, days: int = 0, hours: int = 0) -> None:
    """Set last_activity_at into the past, directly in the DB."""
    factory = get_session_factory()
    async with factory() as db:
        await db.execute(
            update(Session)
            .where(Session.id == uuid.UUID(session_id))
            .values(
                last_activity_at=datetime.now(UTC) - timedelta(days=days, hours=hours)
            )
        )
        await db.commit()


async def test_chat_expired_session_returns_410(client: httpx.AsyncClient) -> None:
    sid = await _create_session(client)
    await _backdate_session(sid, days=2)
    response = await client.post("/chat", json={"question": "Hello", "session_id": sid})
    assert response.status_code == 410
    assert response.json()["error"]["code"] == "SESSION_EXPIRED"
