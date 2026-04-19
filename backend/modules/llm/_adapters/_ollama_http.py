"""Ollama HTTP adapter — unified for local, cloud, and custom instances."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from collections.abc import AsyncIterator
from uuid import uuid4

import httpx
from fastapi import APIRouter, Depends, HTTPException

from datetime import UTC, datetime

from backend.config import settings
from backend.modules.llm._adapters._base import BaseAdapter
from backend.modules.llm._adapters._events import (
    ContentDelta,
    ProviderStreamEvent,
    StreamAborted,
    StreamDone,
    StreamError,
    StreamRefused,
    StreamSlow,
    ThinkingDelta,
    ToolCallEvent,
)
from backend.modules.llm._adapters._types import (
    AdapterTemplate,
    ConfigFieldHint,
    ResolvedConnection,
)
from shared.dtos.inference import CompletionMessage, CompletionRequest
from shared.dtos.llm import ModelMetaDto

_log = logging.getLogger(__name__)

_TIMEOUT = httpx.Timeout(connect=15.0, read=300.0, write=15.0, pool=15.0)
_PROBE_TIMEOUT = httpx.Timeout(10.0)
_REFUSAL_REASONS: frozenset[str] = frozenset({"content_filter", "refusal"})

# Opt-in payload tracing for cache-miss debugging. Enable via
# LLM_TRACE_PAYLOADS=1 in the environment; keep off in production.
_TRACE_PAYLOADS = os.environ.get("LLM_TRACE_PAYLOADS") == "1"

GUTTER_SLOW_SECONDS: float = 30.0
GUTTER_ABORT_SECONDS: float = float(os.environ.get("LLM_STREAM_ABORT_SECONDS", "120"))


# ----- helpers (moved from _ollama_base.py) -----

def _is_refusal_reason(reason: str | None) -> bool:
    if not reason:
        return False
    return reason.lower() in _REFUSAL_REASONS


def _parse_parameter_size(value: str) -> int | None:
    value = value.strip().upper()
    suffixes = {"T": 10**12, "B": 10**9, "M": 10**6, "K": 10**3}
    for suffix, mul in suffixes.items():
        if value.endswith(suffix):
            try:
                return int(float(value[:-1]) * mul)
            except (ValueError, TypeError):
                return None
    try:
        return int(value)
    except (ValueError, TypeError):
        return None


def _format_parameter_count(value: int | None) -> str | None:
    if not value:
        return None
    if value >= 10**12:
        n = value / 10**12
        return f"{int(n)}T" if n == int(n) else f"{n:.1f}T"
    if value >= 10**9:
        n = value / 10**9
        return f"{int(n)}B" if n == int(n) else f"{n:.1f}B"
    if value >= 10**6:
        n = value / 10**6
        return f"{int(n)}M" if n == int(n) else f"{n:.1f}M"
    return None


def _build_display_name(model_name: str) -> str:
    colon = model_name.find(":")
    if colon >= 0:
        name_part = model_name[:colon]
        tag = model_name[colon + 1:]
    else:
        name_part = model_name
        tag = None
    title = " ".join(w.capitalize() for w in name_part.split("-"))
    if not tag or tag.lower() == "latest":
        return title
    return f"{title} ({tag.upper()})"


def _translate_message(msg: CompletionMessage) -> dict:
    text_parts = [p.text for p in msg.content if p.type == "text" and p.text]
    images = [p.data for p in msg.content if p.type == "image" and p.data]
    result: dict = {
        "role": msg.role,
        "content": "".join(text_parts) if text_parts else "",
    }
    if images:
        result["images"] = images
    if msg.tool_calls:
        result["tool_calls"] = [
            {"function": {"name": tc.name, "arguments": json.loads(tc.arguments)}}
            for tc in msg.tool_calls
        ]
    return result


def _build_chat_payload(request: CompletionRequest) -> dict:
    messages = [_translate_message(m) for m in request.messages]
    payload: dict = {"model": request.model, "messages": messages, "stream": True}
    if request.supports_reasoning:
        payload["think"] = request.reasoning_enabled
    if request.temperature is not None:
        payload["options"] = {"temperature": request.temperature}
    if request.tools:
        payload["tools"] = [
            {
                "type": t.type,
                "function": {
                    "name": t.name,
                    "description": t.description,
                    "parameters": t.parameters,
                },
            }
            for t in request.tools
        ]
    return payload


def _auth_headers(api_key: str | None) -> dict:
    if not api_key:
        return {}
    return {"Authorization": f"Bearer {api_key}"}


def _map_to_dto(
    connection_id: str, connection_display_name: str, connection_slug: str,
    model_name: str, detail: dict,
) -> ModelMetaDto:
    capabilities = detail.get("capabilities", [])
    model_info = detail.get("model_info", {})
    details = detail.get("details", {})
    context_window = 0
    for key, value in model_info.items():
        if key.endswith(".context_length") and isinstance(value, int):
            context_window = value
            break
    raw_params = None
    param_str = details.get("parameter_size")
    if param_str is not None:
        raw_params = _parse_parameter_size(param_str)
    if raw_params is None:
        raw_params = model_info.get("general.parameter_count")
        if raw_params is not None and not isinstance(raw_params, int):
            try:
                raw_params = int(raw_params)
            except (ValueError, TypeError):
                raw_params = None
    return ModelMetaDto(
        connection_id=connection_id,
        connection_display_name=connection_display_name,
        connection_slug=connection_slug,
        model_id=model_name,
        display_name=_build_display_name(model_name),
        context_window=context_window,
        supports_reasoning="thinking" in capabilities,
        supports_vision="vision" in capabilities,
        supports_tool_calls="tools" in capabilities,
        parameter_count=_format_parameter_count(raw_params),
        raw_parameter_count=raw_params,
        quantisation_level=details.get("quantization_level"),
    )


def _filter_unusable(metas: list[ModelMetaDto]) -> list[ModelMetaDto]:
    # Models without a context length are under-specified and cannot be used — drop them.
    return [m for m in metas if m.context_window > 0]


# ----- adapter -----

class OllamaHttpAdapter(BaseAdapter):
    adapter_type = "ollama_http"
    display_name = "Ollama"
    view_id = "ollama_http"
    secret_fields = frozenset({"api_key"})

    @classmethod
    def templates(cls) -> list[AdapterTemplate]:
        return [
            AdapterTemplate(
                id="ollama_local",
                display_name="Ollama Local",
                slug_prefix="ollama-local",
                config_defaults={
                    "url": "http://localhost:11434",
                    "api_key": "",
                    "max_parallel": 1,
                },
            ),
            AdapterTemplate(
                id="ollama_cloud",
                display_name="Ollama Cloud",
                slug_prefix="ollama-cloud",
                config_defaults={
                    "url": "https://ollama.com",
                    "api_key": "",
                    "max_parallel": 3,
                },
                # Cloud requires authentication — surface this to the UI so
                # the save button stays disabled until a key is entered.
                required_config_fields=("api_key",),
            ),
            AdapterTemplate(
                id="custom",
                display_name="Custom",
                slug_prefix="ollama",
                config_defaults={"url": "", "api_key": "", "max_parallel": 1},
            ),
        ]

    @classmethod
    def config_schema(cls) -> list[ConfigFieldHint]:
        return [
            ConfigFieldHint(name="url", type="url", label="URL",
                            placeholder="http://localhost:11434"),
            ConfigFieldHint(name="api_key", type="secret", label="API Key",
                            required=False),
            ConfigFieldHint(name="max_parallel", type="integer",
                            label="Max parallel inferences",
                            min=1, max=32),
        ]

    @classmethod
    def router(cls) -> APIRouter:
        # Defined below to keep handler functions close to the adapter.
        return _build_adapter_router()

    async def fetch_models(
        self, c: ResolvedConnection,
    ) -> list[ModelMetaDto]:
        url = c.config["url"].rstrip("/")
        api_key = c.config.get("api_key") or None
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            tags_resp = await client.get(
                f"{url}/api/tags", headers=_auth_headers(api_key),
            )
            tags_resp.raise_for_status()
            tag_entries = tags_resp.json().get("models", [])

            sem = asyncio.Semaphore(5)

            async def _fetch_one(name: str) -> tuple[str, dict | None]:
                async with sem:
                    try:
                        show_resp = await client.post(
                            f"{url}/api/show",
                            json={"model": name},
                            headers=_auth_headers(api_key),
                        )
                        show_resp.raise_for_status()
                        return name, show_resp.json()
                    except Exception:
                        _log.warning("Failed detail fetch for model '%s'", name)
                        return name, None

            results = await asyncio.gather(
                *(_fetch_one(e["name"]) for e in tag_entries),
            )
        metas = [
            _map_to_dto(c.id, c.display_name, c.slug, name, detail)
            for name, detail in results if detail is not None
        ]
        return _filter_unusable(metas)

    async def stream_completion(
        self, c: ResolvedConnection, request: CompletionRequest,
    ) -> AsyncIterator[ProviderStreamEvent]:
        url = c.config["url"].rstrip("/")
        api_key = c.config.get("api_key") or None
        payload = _build_chat_payload(request)
        if _TRACE_PAYLOADS:
            _log.info(
                "LLM_TRACE path=direct url=%s payload=%s",
                url, json.dumps(payload, default=str, sort_keys=True),
            )
        seen_done = False
        pending_next: asyncio.Task | None = None
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            try:
                async with client.stream(
                    "POST", f"{url}/api/chat",
                    json=payload, headers=_auth_headers(api_key),
                ) as resp:
                    if resp.status_code in (401, 403):
                        yield StreamError(error_code="invalid_api_key", message="Invalid API key")
                        return
                    if resp.status_code != 200:
                        body = await resp.aread()
                        detail = body.decode("utf-8", errors="replace")[:500]
                        _log.error("Upstream %d for model %s: %s",
                                   resp.status_code, payload.get("model"), detail)
                        yield StreamError(
                            error_code="provider_unavailable",
                            message=f"Upstream returned {resp.status_code}: {detail}",
                        )
                        return

                    stream_iter = resp.aiter_lines().__aiter__()
                    line_start = time.monotonic()
                    slow_fired = False
                    while True:
                        elapsed = time.monotonic() - line_start
                        budget = (
                            GUTTER_ABORT_SECONDS - elapsed if slow_fired
                            else GUTTER_SLOW_SECONDS - elapsed
                        )
                        if budget <= 0:
                            if not slow_fired:
                                _log.info(
                                    "ollama_base.gutter_slow model=%s idle=%.1fs",
                                    payload.get("model"), elapsed,
                                )
                                yield StreamSlow()
                                slow_fired = True
                                continue
                            _log.warning(
                                "ollama_base.gutter_abort model=%s idle=%.1fs",
                                payload.get("model"), elapsed,
                            )
                            if pending_next is not None:
                                pending_next.cancel()
                            yield StreamAborted(reason="gutter_timeout")
                            return
                        if pending_next is None:
                            pending_next = asyncio.ensure_future(stream_iter.__anext__())
                        done, _ = await asyncio.wait({pending_next}, timeout=budget)
                        if not done:
                            continue
                        task = done.pop()
                        pending_next = None
                        try:
                            line = task.result()
                        except StopAsyncIteration:
                            break
                        line_start = time.monotonic()
                        slow_fired = False
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            chunk = json.loads(line)
                        except json.JSONDecodeError:
                            _log.warning("Skipping malformed NDJSON: %s", line)
                            continue
                        if settings.inference_logging:
                            msg = chunk.get("message") or {}
                            tcs = msg.get("tool_calls") or []
                            _log.info(
                                "ollama_base.chunk model=%s done=%s done_reason=%s "
                                "content_chars=%d thinking_chars=%d tool_calls=%d",
                                payload.get("model"),
                                bool(chunk.get("done")),
                                chunk.get("done_reason"),
                                len(msg.get("content") or ""),
                                len(msg.get("thinking") or ""),
                                len(tcs),
                            )
                            if tcs:
                                for _tc in tcs:
                                    _fn = _tc.get("function") or {}
                                    _log.info(
                                        "ollama_base.chunk.tool_call model=%s name=%s "
                                        "args_chars=%d",
                                        payload.get("model"),
                                        _fn.get("name"),
                                        len(json.dumps(_fn.get("arguments") or {})),
                                    )
                        if chunk.get("done"):
                            seen_done = True
                            done_reason = chunk.get("done_reason")
                            if done_reason and done_reason not in ("stop", "length"):
                                _log.info(
                                    "ollama_base.done_reason model=%s reason=%s",
                                    payload.get("model"), done_reason,
                                )
                            if _is_refusal_reason(done_reason):
                                msg = chunk.get("message", {})
                                yield StreamRefused(
                                    reason=done_reason,
                                    refusal_text=msg.get("refusal") or None,
                                )
                                return
                            yield StreamDone(
                                input_tokens=chunk.get("prompt_eval_count"),
                                output_tokens=chunk.get("eval_count"),
                            )
                            break
                        message = chunk.get("message", {})
                        thinking = message.get("thinking", "")
                        if thinking:
                            yield ThinkingDelta(delta=thinking)
                        content = message.get("content", "")
                        if content:
                            yield ContentDelta(delta=content)
                        for tc in message.get("tool_calls", []):
                            fn = tc.get("function", {})
                            yield ToolCallEvent(
                                id=f"call_{uuid4().hex[:12]}",
                                name=fn.get("name", ""),
                                arguments=json.dumps(fn.get("arguments", {})),
                            )
            except asyncio.CancelledError:
                if pending_next is not None and not pending_next.done():
                    pending_next.cancel()
                _log.warning("Stream cancelled mid-flight (model=%s)",
                             payload.get("model"))
                raise
            except httpx.ConnectError:
                yield StreamError(error_code="provider_unavailable", message="Connection failed")
                return
        if not seen_done:
            yield StreamDone()


# ----- adapter sub-router (test + diagnostics) -----

def _build_adapter_router() -> APIRouter:
    from backend.database import get_db, get_redis
    from backend.modules.llm._connections import ConnectionRepository
    from backend.modules.llm._metadata import refresh_connection_models
    from backend.modules.llm._ollama_model_ops import OllamaModelOps
    from backend.modules.llm._pull_registry import get_pull_registry
    from backend.modules.llm._registry import ADAPTER_REGISTRY
    from backend.modules.llm._resolver import resolve_connection_for_user
    from backend.ws.event_bus import EventBus, get_event_bus
    from shared.events.llm import LlmConnectionModelsRefreshedEvent, LlmConnectionUpdatedEvent
    from shared.topics import Topics

    router = APIRouter()

    def _repo() -> ConnectionRepository:
        return ConnectionRepository(get_db())

    @router.post("/test")
    async def test_connection(
        c: ResolvedConnection = Depends(resolve_connection_for_user),
        event_bus: EventBus = Depends(get_event_bus),
        repo: ConnectionRepository = Depends(_repo),
    ) -> dict:
        url = c.config["url"].rstrip("/")
        api_key = c.config.get("api_key") or None
        valid = False
        error: str | None = None
        try:
            async with httpx.AsyncClient(timeout=_PROBE_TIMEOUT) as client:
                resp = await client.get(f"{url}/api/tags",
                                        headers=_auth_headers(api_key))
                if resp.status_code in (401, 403):
                    error = "Invalid API key"
                else:
                    resp.raise_for_status()
                    valid = True
        except Exception as exc:
            error = str(exc)

        updated = await repo.update_test_status(
            c.user_id,
            c.id,
            status="valid" if valid else "failed",
            error=error,
        )
        if updated is not None:
            await event_bus.publish(
                Topics.LLM_CONNECTION_UPDATED,
                LlmConnectionUpdatedEvent(
                    connection=ConnectionRepository.to_dto(updated),
                    timestamp=datetime.now(UTC),
                ),
            )
        return {"valid": valid, "error": error}

    @router.get("/diagnostics")
    async def diagnostics(
        c: ResolvedConnection = Depends(resolve_connection_for_user),
    ) -> dict:
        url = c.config["url"].rstrip("/")
        api_key = c.config.get("api_key") or None
        async with httpx.AsyncClient(timeout=_PROBE_TIMEOUT) as client:
            try:
                ps_resp, tags_resp = await asyncio.gather(
                    client.get(f"{url}/api/ps", headers=_auth_headers(api_key)),
                    client.get(f"{url}/api/tags", headers=_auth_headers(api_key)),
                )
                ps_resp.raise_for_status()
                tags_resp.raise_for_status()
                return {"ps": ps_resp.json(), "tags": tags_resp.json()}
            except httpx.ConnectError as exc:
                raise HTTPException(status_code=503, detail="Cannot connect") from exc
            except httpx.HTTPStatusError as exc:
                raise HTTPException(
                    status_code=502,
                    detail=f"Upstream returned {exc.response.status_code}",
                ) from exc

    def _make_on_models_changed(c: ResolvedConnection, event_bus: EventBus):
        """Build a callback that refreshes LLM metadata cache for ``c`` and
        emits ``LLM_CONNECTION_MODELS_REFRESHED`` on success or failure. Used as the
        ``on_models_changed`` hook for post-pull and post-delete operations.
        """
        adapter_cls = ADAPTER_REGISTRY[c.adapter_type]
        redis = get_redis()

        async def _cb() -> None:
            error_msg: str | None = None
            try:
                await refresh_connection_models(c, adapter_cls, redis)
            except Exception as exc:  # noqa: BLE001 — surface to frontend via event
                error_msg = str(exc)
            await event_bus.publish(
                Topics.LLM_CONNECTION_MODELS_REFRESHED,
                LlmConnectionModelsRefreshedEvent(
                    connection_id=c.id,
                    success=error_msg is None,
                    error=error_msg,
                    timestamp=datetime.now(UTC),
                ),
                target_user_ids=[c.user_id],
            )

        return _cb

    def _ops_for(c: ResolvedConnection, event_bus: EventBus) -> OllamaModelOps:
        return OllamaModelOps(
            base_url=c.config["url"].rstrip("/"),
            api_key=c.config.get("api_key") or None,
            scope=f"connection:{c.id}",
            event_bus=event_bus,
            registry=get_pull_registry(),
            target_user_ids=[c.user_id],
            on_models_changed=_make_on_models_changed(c, event_bus),
        )

    @router.post("/pull")
    async def pull(
        body: dict,
        c: ResolvedConnection = Depends(resolve_connection_for_user),
        event_bus: EventBus = Depends(get_event_bus),
    ) -> dict:
        slug = (body.get("slug") or "").strip()
        if not slug:
            raise HTTPException(400, "slug is required")
        ops = _ops_for(c, event_bus)
        pull_id = await ops.start_pull(slug=slug)
        return {"pull_id": pull_id}

    @router.post("/pull/{pull_id}/cancel", status_code=204)
    async def cancel_pull(
        pull_id: str,
        c: ResolvedConnection = Depends(resolve_connection_for_user),
    ) -> None:
        ok = get_pull_registry().cancel(f"connection:{c.id}", pull_id)
        if not ok:
            raise HTTPException(404, "pull not found")

    @router.delete("/models/{name:path}", status_code=204)
    async def delete_model(
        name: str,
        c: ResolvedConnection = Depends(resolve_connection_for_user),
        event_bus: EventBus = Depends(get_event_bus),
    ) -> None:
        ops = _ops_for(c, event_bus)
        try:
            await ops.delete(name)
        except httpx.HTTPStatusError as exc:
            raise HTTPException(
                502, f"Ollama returned {exc.response.status_code}",
            ) from exc
        except httpx.ConnectError as exc:
            raise HTTPException(503, "Cannot reach Ollama") from exc

    @router.get("/pulls")
    async def list_pulls(
        c: ResolvedConnection = Depends(resolve_connection_for_user),
    ) -> dict:
        handles = get_pull_registry().list(f"connection:{c.id}")
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
