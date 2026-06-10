from __future__ import annotations

import uuid

import httpx
import pytest


async def _create_session(client: httpx.AsyncClient) -> str:
    response = await client.post("/sessions")
    assert response.status_code == 201
    return response.json()["id"]


async def _upload_md(client: httpx.AsyncClient, sid: str, name: str, text: str) -> None:
    response = await client.post(
        f"/sessions/{sid}/documents",
        files={"file": (name, text.encode(), "text/markdown")},
    )
    assert response.status_code == 202
    assert response.json()["status"] == "ready"


@pytest.fixture
async def seeded_session(client: httpx.AsyncClient) -> tuple[httpx.AsyncClient, str]:
    sid = await _create_session(client)
    await _upload_md(
        client, sid, "derivatives.md",
        "A derivative measures how a function changes as its input changes.",
    )
    await _upload_md(
        client, sid, "cells.md",
        "Eukaryotic cells contain membrane-bound organelles.",
    )
    return client, sid


async def test_search_returns_results(
    seeded_session: tuple[httpx.AsyncClient, str],
) -> None:
    client, sid = seeded_session
    response = await client.get(
        "/search", params={"q": "calculus derivatives", "session_id": sid}
    )
    assert response.status_code == 200

    data = response.json()
    assert len(data) > 0
    result = data[0]
    assert "document_id" in result
    assert "filename" in result
    assert "score" in result
    assert "chunks" in result
    assert len(result["chunks"]) > 0
    chunk = result["chunks"][0]
    assert "chunk_id" in chunk
    assert "chunk_text" in chunk
    assert "score" in chunk


async def test_search_is_session_scoped(
    seeded_session: tuple[httpx.AsyncClient, str],
) -> None:
    client, _ = seeded_session
    other_sid = await _create_session(client)
    response = await client.get(
        "/search", params={"q": "derivatives", "session_id": other_sid}
    )
    assert response.status_code == 200
    assert response.json() == []


async def test_search_respects_limit(
    seeded_session: tuple[httpx.AsyncClient, str],
) -> None:
    client, sid = seeded_session
    response = await client.get(
        "/search", params={"q": "science", "session_id": sid, "limit": 1}
    )
    assert response.status_code == 200
    assert len(response.json()) <= 1


async def test_search_requires_session_id(
    seeded_session: tuple[httpx.AsyncClient, str],
) -> None:
    client, _ = seeded_session
    response = await client.get("/search", params={"q": "math"})
    assert response.status_code == 422


async def test_search_missing_query(
    seeded_session: tuple[httpx.AsyncClient, str],
) -> None:
    client, sid = seeded_session
    response = await client.get("/search", params={"session_id": sid})
    assert response.status_code == 422


async def test_search_limit_too_high(
    seeded_session: tuple[httpx.AsyncClient, str],
) -> None:
    client, sid = seeded_session
    response = await client.get(
        "/search", params={"q": "math", "session_id": sid, "limit": 50}
    )
    assert response.status_code == 422


async def test_search_results_have_score(
    seeded_session: tuple[httpx.AsyncClient, str],
) -> None:
    client, sid = seeded_session
    response = await client.get(
        "/search", params={"q": "derivative", "session_id": sid}
    )
    assert response.status_code == 200
    for result in response.json():
        assert isinstance(result["score"], float)
        assert 0 <= result["score"] <= 1


async def test_search_unknown_session_returns_empty(
    seeded_session: tuple[httpx.AsyncClient, str],
) -> None:
    """Searching a non-existent session id is not an error - just no results."""
    client, _ = seeded_session
    response = await client.get(
        "/search", params={"q": "derivative", "session_id": str(uuid.uuid4())}
    )
    assert response.status_code == 200
    assert response.json() == []
