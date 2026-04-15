"""Helper for Ollama model management operations (pull, cancel, delete).

Encapsulates the streaming /api/pull loop, progress-event throttling,
error mapping, and delete. Used by both the per-connection adapter
sub-router and the admin ollama-local handlers.
"""

from __future__ import annotations

import asyncio
import json
import time
from datetime import UTC, datetime
from typing import Any

import httpx

from backend.modules.llm._pull_registry import PullTaskRegistry
from shared.events.llm import (
    ModelDeletedEvent,
    ModelPullCancelledEvent,
    ModelPullCompletedEvent,
    ModelPullFailedEvent,
    ModelPullProgressEvent,
    ModelPullStartedEvent,
)
from shared.topics import Topics

_TIMEOUT = httpx.Timeout(60.0, read=None)  # no read timeout for long streams
_DEFAULT_THROTTLE_S = 0.2  # 5 Hz


def map_ollama_error(exc: BaseException) -> tuple[str, str]:
    """Map an exception from an Ollama call to (error_code, user_message)."""
    if isinstance(exc, httpx.ConnectError):
        return "ollama_unreachable", "Cannot reach the Ollama instance."
    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code
        if status in (401, 403):
            return "ollama_auth_failed", "Ollama rejected the API key."
        if status == 404:
            return "model_not_found", "Ollama does not know this model."
        return "pull_stream_error", f"Ollama returned HTTP {status}."
    if isinstance(exc, (httpx.ReadError, httpx.RemoteProtocolError)):
        return "pull_stream_error", "Ollama stream ended unexpectedly."
    if isinstance(exc, json.JSONDecodeError):
        return "pull_stream_error", "Malformed response from Ollama."
    return "unknown", "An unexpected error occurred."


def _auth_headers(api_key: str | None) -> dict[str, str]:
    return {"Authorization": f"Bearer {api_key}"} if api_key else {}


class OllamaModelOps:
    def __init__(
        self,
        *,
        base_url: str,
        api_key: str | None,
        scope: str,
        event_bus: Any,
        registry: PullTaskRegistry,
        http_transport: httpx.AsyncBaseTransport | None = None,
        progress_throttle_seconds: float = _DEFAULT_THROTTLE_S,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._scope = scope
        self._bus = event_bus
        self._registry = registry
        self._transport = http_transport
        self._throttle = progress_throttle_seconds

    async def start_pull(self, *, slug: str) -> str:
        handle = self._registry.register(
            scope=self._scope,
            slug=slug,
            coro_factory=lambda pid: self._pull_loop(pid, slug),
        )
        return handle.pull_id

    async def _pull_loop(self, pull_id: str, slug: str) -> None:
        await self._bus.publish(
            Topics.LLM_MODEL_PULL_STARTED,
            ModelPullStartedEvent(
                pull_id=pull_id,
                scope=self._scope,
                slug=slug,
                timestamp=datetime.now(UTC),
            ),
            correlation_id=pull_id,
        )
        last_emit = 0.0
        last_state: dict | None = None
        try:
            async with httpx.AsyncClient(
                timeout=_TIMEOUT, transport=self._transport,
            ) as client:
                async with client.stream(
                    "POST",
                    f"{self._base_url}/api/pull",
                    headers=_auth_headers(self._api_key),
                    json={"name": slug, "stream": True},
                ) as resp:
                    resp.raise_for_status()
                    async for line in resp.aiter_lines():
                        line = line.strip()
                        if not line:
                            continue
                        obj = json.loads(line)
                        status = obj.get("status", "")
                        self._registry.update_status(pull_id, status)
                        last_state = obj
                        now = time.monotonic()
                        if now - last_emit >= self._throttle:
                            await self._emit_progress(pull_id, obj)
                            last_emit = now
            if last_state is not None:
                await self._emit_progress(pull_id, last_state)
            await self._bus.publish(
                Topics.LLM_MODEL_PULL_COMPLETED,
                ModelPullCompletedEvent(
                    pull_id=pull_id,
                    scope=self._scope,
                    slug=slug,
                    timestamp=datetime.now(UTC),
                ),
                correlation_id=pull_id,
            )
        except asyncio.CancelledError:
            await self._bus.publish(
                Topics.LLM_MODEL_PULL_CANCELLED,
                ModelPullCancelledEvent(
                    pull_id=pull_id,
                    scope=self._scope,
                    slug=slug,
                    timestamp=datetime.now(UTC),
                ),
                correlation_id=pull_id,
            )
            raise
        except Exception as exc:
            code, message = map_ollama_error(exc)
            await self._bus.publish(
                Topics.LLM_MODEL_PULL_FAILED,
                ModelPullFailedEvent(
                    pull_id=pull_id,
                    scope=self._scope,
                    slug=slug,
                    error_code=code,
                    user_message=message,
                    timestamp=datetime.now(UTC),
                ),
                correlation_id=pull_id,
            )

    async def _emit_progress(self, pull_id: str, obj: dict) -> None:
        await self._bus.publish(
            Topics.LLM_MODEL_PULL_PROGRESS,
            ModelPullProgressEvent(
                pull_id=pull_id,
                scope=self._scope,
                status=obj.get("status", ""),
                digest=obj.get("digest"),
                completed=obj.get("completed"),
                total=obj.get("total"),
                timestamp=datetime.now(UTC),
            ),
            correlation_id=pull_id,
        )

    async def delete(self, name: str) -> None:
        async with httpx.AsyncClient(
            timeout=_TIMEOUT, transport=self._transport,
        ) as client:
            resp = await client.request(
                "DELETE",
                f"{self._base_url}/api/delete",
                headers=_auth_headers(self._api_key),
                json={"name": name},
            )
            resp.raise_for_status()
        await self._bus.publish(
            Topics.LLM_MODEL_DELETED,
            ModelDeletedEvent(
                scope=self._scope,
                name=name,
                timestamp=datetime.now(UTC),
            ),
        )
