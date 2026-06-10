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
