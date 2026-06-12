from __future__ import annotations

import httpx


async def test_rate_limit_returns_envelope_429(client: httpx.AsyncClient) -> None:
    """With the limiter enabled and a tiny default limit, requests get a 429 envelope."""
    from app.shared.rate_limit import limiter

    limiter.enabled = True
    try:
        # default limit is high; hammer /health until we trip it or hit a sane bound
        last = None
        for _ in range(70):
            last = await client.get("/health")
            if last.status_code == 429:
                break
        assert last is not None and last.status_code == 429
        body = last.json()
        assert body["error"]["code"] == "RATE_LIMITED"
        assert "request_id" in body["error"]
    finally:
        limiter.enabled = False
        limiter.reset()


async def test_rate_limit_disabled_in_tests_by_default(
    client: httpx.AsyncClient,
) -> None:
    for _ in range(70):
        response = await client.get("/health")
    assert response.status_code == 200
