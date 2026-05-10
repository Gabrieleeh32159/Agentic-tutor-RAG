from __future__ import annotations

import httpx
import pytest


@pytest.fixture
async def seeded_client(client: httpx.AsyncClient) -> httpx.AsyncClient:
    """Seed the DB with a few documents for search tests."""
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
        {
            "title": "Eigenvalues",
            "content": "Eigenvalues reveal invariant directions of a linear transformation.",
            "subject": "math",
            "level": "advanced",
        },
    ]
    response = await client.post("/documents/bulk", json=docs)
    assert response.status_code == 201
    return client


@pytest.mark.asyncio
async def test_search_returns_results(seeded_client: httpx.AsyncClient) -> None:
    response = await seeded_client.get("/search", params={"q": "calculus derivatives"})
    assert response.status_code == 200

    data = response.json()
    assert len(data) > 0
    result = data[0]
    assert "document_id" in result
    assert "title" in result
    assert "subject" in result
    assert "level" in result
    assert "score" in result
    assert "chunks" in result
    assert len(result["chunks"]) > 0
    chunk = result["chunks"][0]
    assert "chunk_id" in chunk
    assert "chunk_text" in chunk
    assert "score" in chunk


@pytest.mark.asyncio
async def test_search_respects_limit(seeded_client: httpx.AsyncClient) -> None:
    response = await seeded_client.get(
        "/search", params={"q": "math", "limit": 1}
    )
    assert response.status_code == 200
    assert len(response.json()) <= 1


@pytest.mark.asyncio
async def test_search_filter_by_subject(seeded_client: httpx.AsyncClient) -> None:
    response = await seeded_client.get(
        "/search", params={"q": "cells", "subject": "biology"}
    )
    assert response.status_code == 200

    data = response.json()
    for result in data:
        assert result["subject"] == "biology"


@pytest.mark.asyncio
async def test_search_filter_by_level(seeded_client: httpx.AsyncClient) -> None:
    response = await seeded_client.get(
        "/search", params={"q": "math", "level": "advanced"}
    )
    assert response.status_code == 200

    data = response.json()
    for result in data:
        assert result["level"] == "advanced"


@pytest.mark.asyncio
async def test_search_invalid_level(seeded_client: httpx.AsyncClient) -> None:
    response = await seeded_client.get(
        "/search", params={"q": "math", "level": "beginner"}
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_search_missing_query(seeded_client: httpx.AsyncClient) -> None:
    response = await seeded_client.get("/search")
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_search_limit_too_high(seeded_client: httpx.AsyncClient) -> None:
    response = await seeded_client.get(
        "/search", params={"q": "math", "limit": 50}
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_search_results_have_score(seeded_client: httpx.AsyncClient) -> None:
    response = await seeded_client.get("/search", params={"q": "derivative"})
    assert response.status_code == 200

    data = response.json()
    for result in data:
        assert isinstance(result["score"], float)
        assert 0 <= result["score"] <= 1
