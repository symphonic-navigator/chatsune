"""Admin endpoints for the server's local Ollama instance.

Reads the URL from the ``OLLAMA_LOCAL_BASE_URL`` env var. All routes are
admin-guarded via ``require_admin``. Task 8 will extend this module with
pull/cancel/delete/list routes that use ``OllamaModelOps``.
"""

from __future__ import annotations

import os
from typing import Any, Callable

import httpx
from fastapi import APIRouter, Depends, HTTPException

from backend.dependencies import require_admin

_PROBE_TIMEOUT = httpx.Timeout(10.0)


def _local_base_url() -> str:
    url = os.environ.get("OLLAMA_LOCAL_BASE_URL")
    if not url:
        raise HTTPException(
            status_code=503,
            detail="OLLAMA_LOCAL_BASE_URL is not configured",
        )
    return url.rstrip("/")


def build_admin_router(
    http_transport: httpx.AsyncBaseTransport | None = None,
    event_bus_factory: Callable[[], Any] | None = None,
) -> APIRouter:
    """Build the admin router for ollama-local endpoints.

    ``http_transport`` / ``event_bus_factory`` are injection points for tests
    and for Task 8's pull/cancel/delete routes. ``event_bus_factory`` is
    unused at this stage.
    """
    router = APIRouter()

    async def _get_json(path: str) -> dict:
        url = _local_base_url()
        async with httpx.AsyncClient(
            timeout=_PROBE_TIMEOUT, transport=http_transport,
        ) as client:
            try:
                resp = await client.get(f"{url}{path}")
                resp.raise_for_status()
                return resp.json()
            except httpx.ConnectError as exc:
                raise HTTPException(503, "Cannot reach Ollama") from exc
            except httpx.HTTPStatusError as exc:
                raise HTTPException(
                    502,
                    f"Upstream returned {exc.response.status_code}",
                ) from exc

    @router.get("/ollama-local/ps")
    async def ps(_user: dict = Depends(require_admin)) -> dict:
        return await _get_json("/api/ps")

    @router.get("/ollama-local/tags")
    async def tags(_user: dict = Depends(require_admin)) -> dict:
        return await _get_json("/api/tags")

    return router
