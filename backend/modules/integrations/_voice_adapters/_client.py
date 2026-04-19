"""Shared httpx client for voice adapters.

One client per process with sensible pool limits and timeouts. Adapters
receive the client via DI (passed into their constructor).
"""

import httpx

_client: httpx.AsyncClient | None = None


def init_voice_http_client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(
            timeout=httpx.Timeout(60.0, connect=10.0),
            limits=httpx.Limits(max_connections=50, max_keepalive_connections=10),
        )
    return _client


async def close_voice_http_client() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


def get_voice_http_client() -> httpx.AsyncClient:
    if _client is None:
        raise RuntimeError("Voice HTTP client not initialised")
    return _client
