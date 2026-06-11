from __future__ import annotations

import uuid

import httpx
import pytest

from app.ingestion.service import wait_for_ingestion

MD_CONTENT = b"# Calculus Notes\n\nA derivative measures how a function changes as its input changes."


async def _create_session(client: httpx.AsyncClient) -> str:
    response = await client.post("/sessions")
    assert response.status_code == 201
    return response.json()["id"]


def _upload(name: str, content: bytes, mime: str) -> dict:
    return {"file": (name, content, mime)}


async def _await_ready(client: httpx.AsyncClient, sid: str, doc_id: str) -> dict:
    """Wait for background ingestion then fetch the document by id."""
    await wait_for_ingestion()
    docs = (await client.get(f"/sessions/{sid}/documents")).json()
    return next(d for d in docs if d["id"] == doc_id)


async def test_upload_markdown_document(client: httpx.AsyncClient) -> None:
    sid = await _create_session(client)
    response = await client.post(
        f"/sessions/{sid}/documents",
        files=_upload("notes.md", MD_CONTENT, "text/markdown"),
    )
    assert response.status_code == 202

    data = response.json()
    assert data["filename"] == "notes.md"
    assert data["mime_type"] == "text/markdown"
    assert data["size_bytes"] == len(MD_CONTENT)
    assert data["status"] == "pending"  # async: background task processes it

    final = await _await_ready(client, sid, data["id"])
    assert final["status"] == "ready"
    assert final["chunk_count"] >= 1
    assert final["error_code"] is None


async def test_upload_txt_document(client: httpx.AsyncClient) -> None:
    sid = await _create_session(client)
    response = await client.post(
        f"/sessions/{sid}/documents",
        files=_upload("plain.txt", b"Cells contain organelles.", "text/plain"),
    )
    assert response.status_code == 202
    assert response.json()["status"] == "pending"

    final = await _await_ready(client, sid, response.json()["id"])
    assert final["status"] == "ready"


async def test_upload_unsupported_type_returns_415(client: httpx.AsyncClient) -> None:
    sid = await _create_session(client)
    response = await client.post(
        f"/sessions/{sid}/documents",
        files=_upload("malware.exe", b"MZ...", "application/octet-stream"),
    )
    assert response.status_code == 415
    assert response.json()["error"]["code"] == "UNSUPPORTED_FILE_TYPE"


async def test_upload_oversized_file_returns_413(client: httpx.AsyncClient) -> None:
    sid = await _create_session(client)
    big = b"x" * (10 * 1024 * 1024 + 1)
    response = await client.post(
        f"/sessions/{sid}/documents",
        files=_upload("big.txt", big, "text/plain"),
    )
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "FILE_TOO_LARGE"


async def test_upload_invalid_utf8_fails_async(client: httpx.AsyncClient) -> None:
    """Invalid UTF-8 text files now fail asynchronously (parse_failed, not 422)."""
    sid = await _create_session(client)
    response = await client.post(
        f"/sessions/{sid}/documents",
        files=_upload("binary.txt", b"\xff\xfe\x00\x01", "text/plain"),
    )
    assert response.status_code == 202
    doc = response.json()
    final = await _await_ready(client, sid, doc["id"])
    assert final["status"] == "failed"
    assert final["error_code"] == "parse_failed"


async def test_upload_to_unknown_session_returns_404(client: httpx.AsyncClient) -> None:
    response = await client.post(
        f"/sessions/{uuid.uuid4()}/documents",
        files=_upload("notes.md", MD_CONTENT, "text/markdown"),
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "SESSION_NOT_FOUND"


async def test_list_documents(client: httpx.AsyncClient) -> None:
    sid = await _create_session(client)
    await client.post(
        f"/sessions/{sid}/documents",
        files=_upload("notes.md", MD_CONTENT, "text/markdown"),
    )
    await wait_for_ingestion()
    response = await client.get(f"/sessions/{sid}/documents")
    assert response.status_code == 200
    docs = response.json()
    assert len(docs) == 1
    assert docs[0]["filename"] == "notes.md"


async def test_list_documents_is_session_scoped(client: httpx.AsyncClient) -> None:
    sid_a = await _create_session(client)
    sid_b = await _create_session(client)
    await client.post(
        f"/sessions/{sid_a}/documents",
        files=_upload("notes.md", MD_CONTENT, "text/markdown"),
    )
    await wait_for_ingestion()
    response = await client.get(f"/sessions/{sid_b}/documents")
    assert response.status_code == 200
    assert response.json() == []


async def test_delete_document(client: httpx.AsyncClient) -> None:
    sid = await _create_session(client)
    doc = (
        await client.post(
            f"/sessions/{sid}/documents",
            files=_upload("notes.md", MD_CONTENT, "text/markdown"),
        )
    ).json()
    await wait_for_ingestion()

    response = await client.delete(f"/sessions/{sid}/documents/{doc['id']}")
    assert response.status_code == 204

    docs = (await client.get(f"/sessions/{sid}/documents")).json()
    assert docs == []


async def test_delete_document_wrong_session_returns_404(
    client: httpx.AsyncClient,
) -> None:
    sid_a = await _create_session(client)
    sid_b = await _create_session(client)
    doc = (
        await client.post(
            f"/sessions/{sid_a}/documents",
            files=_upload("notes.md", MD_CONTENT, "text/markdown"),
        )
    ).json()
    await wait_for_ingestion()

    response = await client.delete(f"/sessions/{sid_b}/documents/{doc['id']}")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "DOCUMENT_NOT_FOUND"


async def test_session_detail_includes_documents(client: httpx.AsyncClient) -> None:
    sid = await _create_session(client)
    await client.post(
        f"/sessions/{sid}/documents",
        files=_upload("notes.md", MD_CONTENT, "text/markdown"),
    )
    await wait_for_ingestion()
    response = await client.get(f"/sessions/{sid}")
    assert response.status_code == 200
    data = response.json()
    assert len(data["documents"]) == 1
    assert data["documents"][0]["filename"] == "notes.md"


async def test_upload_empty_file_fails_async(client: httpx.AsyncClient) -> None:
    """Empty/whitespace files now fail asynchronously (parse_failed, not 422)."""
    sid = await _create_session(client)
    response = await client.post(
        f"/sessions/{sid}/documents",
        files=_upload("empty.txt", b"   \n", "text/plain"),
    )
    assert response.status_code == 202
    doc = response.json()
    final = await _await_ready(client, sid, doc["id"])
    assert final["status"] == "failed"
    assert final["error_code"] == "parse_failed"


async def test_processing_failure_marks_document_failed(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    import app.shared.embeddings as embeddings_module
    from app.shared.embeddings import EmbeddingProvider

    class BoomProvider(EmbeddingProvider):
        async def embed(self, text: str) -> list[float]:
            raise RuntimeError("embedding provider down")

        async def embed_batch(self, texts: list[str]) -> list[list[float]]:
            raise RuntimeError("embedding provider down")

    monkeypatch.setattr(embeddings_module, "_provider", BoomProvider())

    sid = await _create_session(client)
    response = await client.post(
        f"/sessions/{sid}/documents",
        files=_upload("notes.md", MD_CONTENT, "text/markdown"),
    )
    assert response.status_code == 202
    doc = response.json()

    await wait_for_ingestion()
    final = await _await_ready(client, sid, doc["id"])
    assert final["status"] == "failed"
    assert final["error_code"] == "processing_failed"
    assert final["error_message"]
    assert final["chunk_count"] == 0


async def test_search_excludes_failed_documents(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    import app.shared.embeddings as embeddings_module
    from app.shared.embeddings import EmbeddingProvider

    sid = await _create_session(client)

    class BoomProvider(EmbeddingProvider):
        async def embed(self, text: str) -> list[float]:
            raise RuntimeError("embedding provider down")

        async def embed_batch(self, texts: list[str]) -> list[list[float]]:
            raise RuntimeError("embedding provider down")

    saved = embeddings_module._provider
    monkeypatch.setattr(embeddings_module, "_provider", BoomProvider())
    await client.post(
        f"/sessions/{sid}/documents",
        files=_upload("broken.md", MD_CONTENT, "text/markdown"),
    )
    await wait_for_ingestion()
    monkeypatch.setattr(embeddings_module, "_provider", saved)

    response = await client.get(
        "/search", params={"q": "derivative", "session_id": sid}
    )
    assert response.status_code == 200
    assert response.json() == []
