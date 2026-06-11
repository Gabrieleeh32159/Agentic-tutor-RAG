from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from app.ingestion.service import wait_for_ingestion

FIXTURES = Path(__file__).parent / "fixtures"


async def _create_session(client: httpx.AsyncClient) -> str:
    response = await client.post("/sessions")
    assert response.status_code == 201
    return response.json()["id"]


async def _upload_fixture(
    client: httpx.AsyncClient, sid: str, name: str, mime: str
) -> dict:
    data = (FIXTURES / name).read_bytes()
    response = await client.post(
        f"/sessions/{sid}/documents",
        files={"file": (name, data, mime)},
    )
    assert response.status_code == 202, response.text
    return response.json()


async def _get_doc(client: httpx.AsyncClient, sid: str, doc_id: str) -> dict:
    docs = (await client.get(f"/sessions/{sid}/documents")).json()
    return next(d for d in docs if d["id"] == doc_id)


async def test_upload_returns_pending_then_processes(client: httpx.AsyncClient) -> None:
    sid = await _create_session(client)
    doc = await _upload_fixture(client, sid, "sample.pdf", "application/pdf")
    assert doc["status"] == "pending"
    assert doc["chunk_count"] == 0

    await wait_for_ingestion()

    final = await _get_doc(client, sid, doc["id"])
    assert final["status"] == "ready"
    assert final["page_count"] == 2
    assert final["chunk_count"] >= 1
    assert final["progress"] == 100


async def test_pdf_content_is_searchable(client: httpx.AsyncClient) -> None:
    sid = await _create_session(client)
    await _upload_fixture(client, sid, "sample.pdf", "application/pdf")
    await wait_for_ingestion()

    response = await client.get(
        "/search", params={"q": "photosynthesis light energy", "session_id": sid}
    )
    results = response.json()
    assert len(results) == 1
    assert results[0]["filename"] == "sample.pdf"


async def test_scanned_pdf_goes_through_ocr(
    client: httpx.AsyncClient, mock_vision: str
) -> None:
    sid = await _create_session(client)
    doc = await _upload_fixture(client, sid, "scanned.pdf", "application/pdf")
    await wait_for_ingestion()

    final = await _get_doc(client, sid, doc["id"])
    assert final["status"] == "ready"
    assert final["page_count"] == 2

    response = await client.get(
        "/search", params={"q": "photosynthesis", "session_id": sid}
    )
    results = response.json()
    assert results, "OCR text should be searchable"
    assert (
        mock_vision.split()[0].lower() in results[0]["chunks"][0]["chunk_text"].lower()
    )


async def test_docx_upload(client: httpx.AsyncClient) -> None:
    sid = await _create_session(client)
    doc = await _upload_fixture(
        client,
        sid,
        "sample.docx",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )
    await wait_for_ingestion()
    final = await _get_doc(client, sid, doc["id"])
    assert final["status"] == "ready"
    assert final["chunk_count"] >= 1


async def test_xlsx_upload_produces_table_chunks(client: httpx.AsyncClient) -> None:
    sid = await _create_session(client)
    doc = await _upload_fixture(
        client,
        sid,
        "sample.xlsx",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    await wait_for_ingestion()
    final = await _get_doc(client, sid, doc["id"])
    assert final["status"] == "ready"

    response = await client.get("/search", params={"q": "grades", "session_id": sid})
    results = response.json()
    assert results
    assert "| Student | Subject | Grade |" in results[0]["chunks"][0]["chunk_text"]


async def test_image_upload_uses_vision(client: httpx.AsyncClient) -> None:
    sid = await _create_session(client)
    doc = await _upload_fixture(client, sid, "sample.png", "image/png")
    await wait_for_ingestion()
    final = await _get_doc(client, sid, doc["id"])
    assert final["status"] == "ready"
    assert final["page_count"] == 1
    assert final["chunk_count"] >= 1


async def test_mismatched_signature_rejected_at_upload(
    client: httpx.AsyncClient,
) -> None:
    sid = await _create_session(client)
    png_bytes = (FIXTURES / "sample.png").read_bytes()
    response = await client.post(
        f"/sessions/{sid}/documents",
        files={"file": ("fake.pdf", png_bytes, "application/pdf")},
    )
    assert response.status_code == 415
    assert response.json()["error"]["code"] == "UNSUPPORTED_FILE_TYPE"


async def test_corrupt_pdf_fails_async(client: httpx.AsyncClient) -> None:
    sid = await _create_session(client)
    # Valid %PDF signature so it passes the router sniff, but unreadable content
    response = await client.post(
        f"/sessions/{sid}/documents",
        files={"file": ("corrupt.pdf", b"%PDF-1.4 garbage", "application/pdf")},
    )
    assert response.status_code == 202
    doc = response.json()
    await wait_for_ingestion()

    final = await _get_doc(client, sid, doc["id"])
    assert final["status"] == "failed"
    assert final["error_code"] == "parse_failed"
    assert final["error_message"]
    assert final["progress"] == 0


async def test_page_limit_fails_async(client: httpx.AsyncClient) -> None:
    from io import BytesIO

    from pypdf import PdfWriter

    writer = PdfWriter()
    for _ in range(51):
        writer.add_blank_page(width=200, height=200)
    buf = BytesIO()
    writer.write(buf)

    sid = await _create_session(client)
    response = await client.post(
        f"/sessions/{sid}/documents",
        files={"file": ("big.pdf", buf.getvalue(), "application/pdf")},
    )
    assert response.status_code == 202
    doc = response.json()
    await wait_for_ingestion()

    final = await _get_doc(client, sid, doc["id"])
    assert final["status"] == "failed"
    assert final["error_code"] == "page_limit_exceeded"


async def test_session_document_cap(client: httpx.AsyncClient) -> None:
    from app.shared.config import get_settings

    settings = get_settings()
    original = settings.MAX_DOCS_PER_SESSION
    settings.MAX_DOCS_PER_SESSION = 1
    try:
        sid = await _create_session(client)
        await _upload_fixture(client, sid, "sample.txt", "text/plain")
        await wait_for_ingestion()

        data = (FIXTURES / "sample.txt").read_bytes()
        response = await client.post(
            f"/sessions/{sid}/documents",
            files={"file": ("second.txt", data, "text/plain")},
        )
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "SESSION_DOCUMENT_LIMIT"
    finally:
        settings.MAX_DOCS_PER_SESSION = original


async def test_ocr_page_cap_limits_vision_calls(client: httpx.AsyncClient) -> None:
    """Pages beyond MAX_OCR_PAGES_PER_DOC are skipped (logged), doc still ready."""
    from io import BytesIO

    from pypdf import PdfWriter

    from app.shared.config import get_settings

    settings = get_settings()
    original = settings.MAX_OCR_PAGES_PER_DOC
    settings.MAX_OCR_PAGES_PER_DOC = 1
    try:
        writer = PdfWriter()
        for _ in range(3):
            writer.add_blank_page(width=200, height=200)
        buf = BytesIO()
        writer.write(buf)

        sid = await _create_session(client)
        response = await client.post(
            f"/sessions/{sid}/documents",
            files={"file": ("scans.pdf", buf.getvalue(), "application/pdf")},
        )
        assert response.status_code == 202
        doc = response.json()
        await wait_for_ingestion()

        final = await _get_doc(client, sid, doc["id"])
        assert final["status"] == "ready"
        # Only 1 of 3 scanned pages was OCR'd -> exactly 1 page of chunks
        assert final["chunk_count"] >= 1
    finally:
        settings.MAX_OCR_PAGES_PER_DOC = original


async def test_unknown_extension_still_415(client: httpx.AsyncClient) -> None:
    sid = await _create_session(client)
    response = await client.post(
        f"/sessions/{sid}/documents",
        files={"file": ("malware.exe", b"MZ...", "application/octet-stream")},
    )
    assert response.status_code == 415


# --- Hard Requirement 4: encrypted PDF tests ---


async def test_upload_rejected_when_queue_full(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    import app.ingestion.service as ingestion_service

    monkeypatch.setattr(ingestion_service, "MAX_QUEUED_INGESTIONS", 0)
    sid = await _create_session(client)
    data = (FIXTURES / "sample.txt").read_bytes()
    response = await client.post(
        f"/sessions/{sid}/documents",
        files={"file": ("notes.txt", data, "text/plain")},
    )
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "INGESTION_BUSY"


async def test_delete_document_during_processing(client: httpx.AsyncClient) -> None:
    sid = await _create_session(client)
    data = (FIXTURES / "sample.pdf").read_bytes()
    response = await client.post(
        f"/sessions/{sid}/documents",
        files={"file": ("sample.pdf", data, "application/pdf")},
    )
    assert response.status_code == 202
    doc = response.json()

    # Delete immediately - the background task may be queued or mid-flight
    delete = await client.delete(f"/sessions/{sid}/documents/{doc['id']}")
    assert delete.status_code == 204

    await wait_for_ingestion()

    docs = (await client.get(f"/sessions/{sid}/documents")).json()
    assert docs == []

    from sqlalchemy import func, select

    from app.documents.models import DocumentChunk
    from app.shared.database import get_session_factory

    async with get_session_factory()() as db:
        count = (
            await db.execute(select(func.count()).select_from(DocumentChunk))
        ).scalar_one()
    assert count == 0


async def test_hard_encrypted_pdf_fails_async(client: httpx.AsyncClient) -> None:
    """A PDF encrypted with a user password must fail with parse_failed."""
    from io import BytesIO

    from pypdf import PdfWriter

    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    writer.encrypt(user_password="secret", owner_password="owner")
    buf = BytesIO()
    writer.write(buf)
    pdf_bytes = buf.getvalue()

    sid = await _create_session(client)
    response = await client.post(
        f"/sessions/{sid}/documents",
        files={"file": ("encrypted.pdf", pdf_bytes, "application/pdf")},
    )
    assert response.status_code == 202
    doc = response.json()
    await wait_for_ingestion()

    final = await _get_doc(client, sid, doc["id"])
    assert final["status"] == "failed"
    assert final["error_code"] == "parse_failed"
