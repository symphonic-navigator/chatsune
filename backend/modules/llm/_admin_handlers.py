"""Admin endpoints for the server's local Ollama instance.

Reads the URL from the ``OLLAMA_LOCAL_BASE_URL`` env var. All routes are
admin-guarded via ``require_admin``. Includes pull/cancel/delete/list
routes backed by ``OllamaModelOps`` for managing local models.
"""

from __future__ import annotations

import os
from typing import Any, Callable

import httpx
from fastapi import APIRouter, Depends, HTTPException

from backend.dependencies import require_admin
from backend.modules.llm._ollama_model_ops import OllamaModelOps
from backend.modules.llm._pull_registry import get_pull_registry

_PROBE_TIMEOUT = httpx.Timeout(10.0)
_ADMIN_SCOPE = "admin-local"


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

    ``http_transport`` / ``event_bus_factory`` are injection points for tests.
    ``event_bus_factory`` defaults to ``None``; when not provided the bus is
    resolved lazily at request time via ``backend.ws.event_bus.get_event_bus``.
    The lazy import avoids pulling the WebSocket subsystem at module-import
    time, which matters for minimal test setups.
    """
    router = APIRouter()

    def _resolve_bus():
        if event_bus_factory is not None:
            return event_bus_factory()
        # Lazy import: backend.ws.event_bus may not import cleanly at module
        # import time in some contexts (e.g. minimal test setups).
        from backend.ws.event_bus import get_event_bus
        return get_event_bus()

    def _ops() -> OllamaModelOps:
        return OllamaModelOps(
            base_url=_local_base_url(),
            api_key=None,
            scope=_ADMIN_SCOPE,
            event_bus=_resolve_bus(),
            registry=get_pull_registry(),
            http_transport=http_transport,
        )

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

    @router.post("/ollama-local/pull")
    async def pull(
        body: dict, _user: dict = Depends(require_admin),
    ) -> dict:
        slug = (body.get("slug") or "").strip()
        if not slug:
            raise HTTPException(400, "slug is required")
        pull_id = await _ops().start_pull(slug=slug)
        return {"pull_id": pull_id}

    @router.post("/ollama-local/pull/{pull_id}/cancel", status_code=204)
    async def cancel_pull(
        pull_id: str, _user: dict = Depends(require_admin),
    ) -> None:
        ok = get_pull_registry().cancel(_ADMIN_SCOPE, pull_id)
        if not ok:
            raise HTTPException(404, "pull not found")

    @router.delete("/ollama-local/models/{name:path}", status_code=204)
    async def delete_model(
        name: str, _user: dict = Depends(require_admin),
    ) -> None:
        try:
            await _ops().delete(name)
        except httpx.HTTPStatusError as exc:
            raise HTTPException(
                502, f"Ollama returned {exc.response.status_code}",
            ) from exc
        except httpx.ConnectError as exc:
            raise HTTPException(503, "Cannot reach Ollama") from exc

    @router.get("/ollama-local/pulls")
    async def list_pulls(_user: dict = Depends(require_admin)) -> dict:
        handles = get_pull_registry().list(_ADMIN_SCOPE)
        return {
            "pulls": [
                {
                    "pull_id": h.pull_id,
                    "slug": h.slug,
                    "status": h.last_status,
                    "started_at": h.started_at.isoformat(),
                }
                for h in handles
            ]
        }

    return router
