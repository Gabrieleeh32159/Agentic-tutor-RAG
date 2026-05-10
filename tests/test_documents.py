from __future__ import annotations

import httpx
import pytest


SAMPLE_DOC = {
    "title": "Test Document",
    "content": "This is a test document about calculus.",
    "subject": "math",
    "level": "introductory",
}


@pytest.mark.asyncio
async def test_create_document(client: httpx.AsyncClient) -> None:
    response = await client.post("/documents", json=SAMPLE_DOC)
    assert response.status_code == 201

    data = response.json()
    assert data["title"] == SAMPLE_DOC["title"]
    assert data["subject"] == SAMPLE_DOC["subject"]
    assert data["level"] == SAMPLE_DOC["level"]
    assert "id" in data
    assert "created_at" in data
    assert data["chunk_count"] >= 1


@pytest.mark.asyncio
async def test_create_document_invalid_level(client: httpx.AsyncClient) -> None:
    bad_doc = {**SAMPLE_DOC, "level": "beginner"}
    response = await client.post("/documents", json=bad_doc)
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_create_document_missing_title(client: httpx.AsyncClient) -> None:
    bad_doc = {k: v for k, v in SAMPLE_DOC.items() if k != "title"}
    response = await client.post("/documents", json=bad_doc)
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_create_document_empty_content(client: httpx.AsyncClient) -> None:
    bad_doc = {**SAMPLE_DOC, "content": ""}
    response = await client.post("/documents", json=bad_doc)
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_bulk_create_documents(client: httpx.AsyncClient) -> None:
    docs = [
        {
            "title": "Doc 1",
            "content": "Content about biology.",
            "subject": "biology",
            "level": "introductory",
        },
        {
            "title": "Doc 2",
            "content": "Content about physics.",
            "subject": "physics",
            "level": "advanced",
        },
    ]
    response = await client.post("/documents/bulk", json=docs)
    assert response.status_code == 201

    data = response.json()
    assert len(data) == 2
    assert data[0]["title"] == "Doc 1"
    assert data[1]["title"] == "Doc 2"
    assert data[0]["chunk_count"] >= 1
    assert data[1]["chunk_count"] >= 1


@pytest.mark.asyncio
async def test_bulk_create_empty_list(client: httpx.AsyncClient) -> None:
    response = await client.post("/documents/bulk", json=[])
    assert response.status_code == 201
    assert response.json() == []
