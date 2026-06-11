from __future__ import annotations

import httpx
import pytest


@pytest.mark.asyncio
async def test_responses_carry_request_id_header(client: httpx.AsyncClient) -> None:
    response = await client.get("/health")
    assert response.status_code == 200
    request_id = response.headers.get("x-request-id")
    assert request_id is not None
    assert len(request_id) == 12


@pytest.mark.asyncio
async def test_app_error_returns_structured_envelope(client: httpx.AsyncClient) -> None:
    """AppError subclasses must render as {"error": {code, message, request_id}}."""
    from app.main import app
    from app.shared.errors import SessionNotFoundError

    @app.get("/_test/raise-app-error")
    async def _raise() -> None:
        raise SessionNotFoundError("Session abc not found")

    try:
        response = await client.get("/_test/raise-app-error")
    finally:
        app.router.routes = [
            r
            for r in app.router.routes
            if getattr(r, "path", "") != "/_test/raise-app-error"
        ]

    assert response.status_code == 404
    body = response.json()
    assert body["error"]["code"] == "SESSION_NOT_FOUND"
    assert body["error"]["message"] == "Session abc not found"
    assert body["error"]["request_id"] == response.headers["x-request-id"]
