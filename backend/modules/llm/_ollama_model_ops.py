"""Helper for Ollama model management operations (pull, cancel, delete).

Encapsulates the streaming /api/pull loop, progress-event throttling,
error mapping, and delete. Used by both the per-connection adapter
sub-router and the admin ollama-local handlers.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import UTC, datetime
from typing import Any, Awaitable, Callable

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

_log = logging.getLogger(__name__)
_TIMEOUT = httpx.Timeout(60.0, read=None)  # no read timeout for long streams
_DEFAULT_THROTTLE_S = 0.2  # 5 Hz


class OllamaStreamError(Exception):
    """Raised when Ollama reports an error inside the stream body.

    Ollama responds with HTTP 200 OK even for errors like a missing
    manifest, surfacing the failure only as ``{"error": "..."}`` on the
    stream. We raise this so the pull loop can translate it into a
    proper FAILED event.
    """


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
    if isinstance(exc, OllamaStreamError):
        message = str(exc)
        lower = message.lower()
        if (
            "not found" in lower
            or "does not exist" in lower
            or "manifest" in lower
        ):
            return "model_not_found", message
        return "pull_stream_error", message
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
        target_user_ids: list[str],
        http_transport: httpx.AsyncBaseTransport | None = None,
        progress_throttle_seconds: float = _DEFAULT_THROTTLE_S,
        on_models_changed: Callable[[], Awaitable[None]] | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._scope = scope
        self._bus = event_bus
        self._registry = registry
        self._target_user_ids = target_user_ids
        self._transport = http_transport
        self._throttle = progress_throttle_seconds
        self._on_models_changed = on_models_changed

    async def _notify_models_changed(self) -> None:
        """Best-effort post-operation hook. Logs and swallows failures —
        the underlying pull/delete already succeeded, so a refresh error
        must not be reported as an operational failure to the user."""
        if self._on_models_changed is None:
            return
        try:
            await self._on_models_changed()
        except Exception as exc:  # noqa: BLE001 — best-effort refresh, must not fail the pull/delete
            _log.warning(
                "on_models_changed hook failed for scope=%s: %s",
                self._scope, exc,
            )

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
            target_user_ids=self._target_user_ids,
        )

        completed_published = False
        last_emit = 0.0
        last_state: dict[str, Any] | None = None
        last_emitted_state: dict[str, Any] | None = None

        try:
            async with httpx.AsyncClient(
                timeout=_TIMEOUT, transport=self._transport,
            ) as client:
                async with client.stream(
                    "POST",
                    f"{self._base_url}/api/pull",
                    headers=_auth_headers(self._api_key),
                    json={"model": slug, "stream": True},
                ) as resp:
                    resp.raise_for_status()
                    async for line in resp.aiter_lines():
                        line = line.strip()
                        if not line:
                            continue
                        obj = json.loads(line)
                        if "error" in obj:
                            # Ollama surfaces pull failures in-stream with
                            # HTTP 200 OK; raise so the FAILED branch fires.
                            raise OllamaStreamError(str(obj["error"]))
                        status = obj.get("status", "")
                        self._registry.update_status(pull_id, status)
                        last_state = obj
                        now = time.monotonic()
                        if now - last_emit >= self._throttle:
                            await self._emit_progress(pull_id, obj)
                            last_emitted_state = obj
                            last_emit = now

            # Stream finished cleanly. Shield the finalisation from a late
            # cancel landing in the window between stream-end and COMPLETED,
            # so the user doesn't see CANCELLED for a pull that actually
            # succeeded.
            await asyncio.shield(
                self._finalise_success(
                    pull_id, slug, last_state, last_emitted_state,
                )
            )
            completed_published = True

        except asyncio.CancelledError:
            if not completed_published:
                # Real cancel during the pull — tell listeners. Shield so a
                # second cancel can't swallow the CANCELLED event; the inner
                # try/except absorbs a cancel that fires during the shield
                # itself.
                try:
                    await asyncio.shield(
                        self._bus.publish(
                            Topics.LLM_MODEL_PULL_CANCELLED,
                            ModelPullCancelledEvent(
                                pull_id=pull_id,
                                scope=self._scope,
                                slug=slug,
                                timestamp=datetime.now(UTC),
                            ),
                            correlation_id=pull_id,
                            target_user_ids=self._target_user_ids,
                        )
                    )
                except asyncio.CancelledError:
                    pass
            raise
        except Exception as exc:
            code, message = map_ollama_error(exc)
            # Intentionally do NOT re-raise here — the failure is surfaced
            # via the FAILED event on the bus, not via task exception state.
            # Keeping the task "successful" from asyncio's POV avoids
            # spurious "Task exception was never retrieved" warnings for
            # fire-and-forget pull tasks.
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
                target_user_ids=self._target_user_ids,
            )

    async def _finalise_success(
        self,
        pull_id: str,
        slug: str,
        last_state: dict[str, Any] | None,
        last_emitted_state: dict[str, Any] | None,
    ) -> None:
        # Flush final state only if it hasn't already been emitted as the
        # last throttled update. Compare by identity — same dict object
        # means no change since the last throttled emit, so emitting it
        # again would be a duplicate progress event for the same state.
        if last_state is not None and last_state is not last_emitted_state:
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
            target_user_ids=self._target_user_ids,
        )
        await self._notify_models_changed()

    async def _emit_progress(self, pull_id: str, obj: dict[str, Any]) -> None:
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
            target_user_ids=self._target_user_ids,
        )

    async def delete(self, name: str) -> None:
        async with httpx.AsyncClient(
            timeout=_TIMEOUT, transport=self._transport,
        ) as client:
            resp = await client.request(
                "DELETE",
                f"{self._base_url}/api/delete",
                headers=_auth_headers(self._api_key),
                json={"model": name},
            )
            resp.raise_for_status()
        await self._bus.publish(
            Topics.LLM_MODEL_DELETED,
            ModelDeletedEvent(
                scope=self._scope,
                name=name,
                timestamp=datetime.now(UTC),
            ),
            target_user_ids=self._target_user_ids,
        )
        await self._notify_models_changed()
