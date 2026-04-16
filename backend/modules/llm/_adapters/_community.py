"""Consumer-side adapter for Community Provisioning (CSP/1).

This adapter is strictly engine-agnostic — no branching on engine
type is allowed anywhere in this file. If you feel the urge to do
so, the right answer is to extend CSP, not to leak engine identity
into the backend.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator

from fastapi import APIRouter

from backend.modules.llm._adapters._base import BaseAdapter
from backend.modules.llm._adapters._events import ProviderStreamEvent
from backend.modules.llm._adapters._types import (
    AdapterTemplate,
    ConfigFieldHint,
    ResolvedConnection,
)
from backend.modules.llm._csp._registry import get_sidecar_registry
from shared.dtos.inference import CompletionRequest
from shared.dtos.llm import ModelMetaDto

_log = logging.getLogger(__name__)


def _homelab_service():
    """Factory — deferred so monkeypatching in tests works and to avoid
    an import-time cycle with the LLM module's public API.
    """
    from backend.database import get_db
    from backend.modules.llm._homelabs import HomelabService
    from backend.ws.event_bus import get_event_bus

    return HomelabService(get_db(), get_event_bus())


def _frame_to_event(frame):
    """Translate a CSP frame into the adapter-layer ProviderStreamEvent.

    Engine-agnostic by construction — the CSP protocol abstracts all engines
    uniformly. If you find yourself wanting to branch on engine type here,
    extend CSP instead.
    """
    from backend.modules.llm._adapters._events import (
        ContentDelta,
        StreamAborted,
        StreamDone,
        StreamError,
        ThinkingDelta,
        ToolCallEvent,
    )
    from backend.modules.llm._csp._frames import (
        ErrFrame,
        StreamEndFrame,
        StreamFrame,
    )

    if isinstance(frame, StreamFrame):
        delta = frame.delta
        if delta.content:
            return ContentDelta(delta=delta.content)
        if delta.reasoning:
            return ThinkingDelta(delta=delta.reasoning)
        if delta.tool_calls:
            # CSP carries tool-calls as a list of dicts. Surface only the first
            # fragment here — chat orchestration receives one ToolCallEvent
            # per call, matching the ollama_http adapter's behaviour.
            tc = delta.tool_calls[0] if delta.tool_calls else {}
            return ToolCallEvent(
                id=str(tc.get("id") or ""),
                name=str(tc.get("name") or ""),
                arguments=str(tc.get("arguments") or "{}"),
            )
        return None
    if isinstance(frame, StreamEndFrame):
        if frame.finish_reason == "cancelled":
            return StreamAborted(reason="cancelled")
        if frame.finish_reason == "error":
            return StreamError(
                error_code="provider_unavailable",
                message="Engine returned an error; see host logs.",
            )
        usage = frame.usage or {}
        # Usage keys in CSP are engine-agnostic (prompt_tokens / completion_tokens).
        return StreamDone(
            input_tokens=usage.get("prompt_tokens"),
            output_tokens=usage.get("completion_tokens"),
        )
    if isinstance(frame, ErrFrame):
        # Normalise CSP err-codes to the StreamError vocabulary consumers expect.
        mapped = {
            "model_not_found": "model_not_found",
            "model_oom": "provider_unavailable",
            "engine_unavailable": "provider_unavailable",
            "engine_error": "provider_unavailable",
            "invalid_request": "provider_unavailable",
            "rate_limited": "provider_unavailable",
            "cancelled": "provider_unavailable",
            "internal": "provider_unavailable",
        }.get(frame.code, "provider_unavailable")
        # Preserve the raw CSP code by surfacing it back as the StreamError
        # error_code when it's already in the consumer vocabulary; otherwise
        # fall back to the mapped value. This keeps model_not_found
        # observable end-to-end.
        return StreamError(
            error_code=frame.code if frame.code == "model_not_found" else mapped,
            message=frame.message,
        )
    return None


# Capabilities are a string set shared by all CSP engines — this mapping is
# intentionally engine-agnostic and lives alongside the adapter to keep the
# translation close to the frame definition.
def _model_meta_to_dto(
    connection: ResolvedConnection, raw: dict,
) -> ModelMetaDto:
    caps = set(raw.get("capabilities") or [])
    raw_params = raw.get("parameter_count")
    return ModelMetaDto(
        connection_id=connection.id,
        connection_slug=connection.slug,
        connection_display_name=connection.display_name,
        model_id=raw["slug"],
        display_name=raw.get("display_name") or raw["slug"],
        context_window=int(raw["context_length"]),
        supports_reasoning="reasoning" in caps or "thinking" in caps,
        supports_vision="vision" in caps,
        supports_tool_calls="tools" in caps or "tool_calling" in caps,
        parameter_count=None,
        raw_parameter_count=(
            int(raw_params) if isinstance(raw_params, int) else None
        ),
        quantisation_level=raw.get("quantisation"),
    )


class CommunityAdapter(BaseAdapter):
    adapter_type = "community"
    display_name = "Community"
    view_id = "community"
    secret_fields = frozenset({"api_key"})

    @classmethod
    def templates(cls) -> list[AdapterTemplate]:
        return [
            AdapterTemplate(
                id="homelab_via_community",
                display_name="Homelab via Community",
                slug_prefix="community",
                config_defaults={"homelab_id": "", "api_key": ""},
                required_config_fields=("homelab_id", "api_key"),
            ),
        ]

    @classmethod
    def config_schema(cls) -> list[ConfigFieldHint]:
        return [
            ConfigFieldHint(
                name="homelab_id",
                type="string",
                label="Homelab-ID",
                required=True,
                min=11,
                max=11,
                placeholder="Xk7bQ2eJn9m",
            ),
            ConfigFieldHint(
                name="api_key",
                type="secret",
                label="API-Key",
                required=True,
            ),
        ]

    async def fetch_models(
        self, connection: ResolvedConnection,
    ) -> list[ModelMetaDto]:
        _log.warning(
            "community.fetch_models.enter connection_id=%s slug=%s",
            connection.id, connection.slug,
        )
        homelab_id = (connection.config.get("homelab_id") or "").strip()
        api_key = (connection.config.get("api_key") or "").strip()
        _log.warning(
            "community.fetch_models.config homelab_id=%r api_key_set=%s",
            homelab_id, bool(api_key),
        )
        if not homelab_id or not api_key:
            return []

        sidecar = get_sidecar_registry().get(homelab_id)
        if sidecar is None:
            _log.info(
                "community.fetch_models.offline connection_id=%s homelab_id=%s",
                connection.id, homelab_id,
            )
            return []

        svc = _homelab_service()
        key_doc = await svc.validate_consumer_access_key(
            homelab_id=homelab_id, api_key_plaintext=api_key,
        )
        if key_doc is None:
            _log.info(
                "community.fetch_models.key_rejected connection_id=%s homelab_id=%s",
                connection.id, homelab_id,
            )
            return []
        allowlist = set(key_doc.get("allowed_model_slugs", []))

        try:
            raw_models = await sidecar.rpc_list_models()
        except Exception as exc:  # noqa: BLE001 — degrade gracefully on RPC failure
            _log.warning(
                "community.fetch_models.rpc_failed connection_id=%s homelab_id=%s err=%s",
                connection.id, homelab_id, exc,
            )
            return []

        raw_slugs = [m.get("slug") for m in raw_models]
        kept = [
            m for m in raw_models
            if m.get("slug") in allowlist and m.get("context_length")
        ]
        dropped_no_ctx = [
            m.get("slug") for m in raw_models
            if m.get("slug") in allowlist and not m.get("context_length")
        ]
        _log.warning(
            "community.fetch_models.result connection_id=%s homelab_id=%s "
            "sidecar_reported=%d allowlist=%d kept=%d "
            "sidecar_slugs=%r allowlist_slugs=%r dropped_no_ctx=%r",
            connection.id, homelab_id,
            len(raw_models), len(allowlist), len(kept),
            raw_slugs, sorted(allowlist), dropped_no_ctx,
        )
        return [_model_meta_to_dto(connection, m) for m in kept]

    async def stream_completion(  # type: ignore[override]
        self,
        connection: ResolvedConnection,
        request: CompletionRequest,
    ) -> AsyncIterator[ProviderStreamEvent]:
        from backend.modules.llm._adapters._events import (
            StreamError,
            StreamRefused,
        )

        homelab_id = (connection.config.get("homelab_id") or "").strip()
        api_key = (connection.config.get("api_key") or "").strip()
        # ``request.model`` is the raw model slug; the connection-slug prefix
        # is stripped one layer up by ``stream_completion`` in the LLM public
        # API (see backend/modules/llm/__init__.py::parse_model_unique_id).
        model_slug = (request.model or "").strip()

        if not homelab_id or not api_key or not model_slug:
            yield StreamRefused(reason="incomplete_configuration")
            return

        svc = _homelab_service()
        key_doc = await svc.validate_consumer_access(
            homelab_id=homelab_id,
            api_key_plaintext=api_key,
            model_slug=model_slug,
        )
        if key_doc is None:
            yield StreamRefused(reason="api_key_invalid_or_model_not_allowed")
            return

        sidecar = get_sidecar_registry().get(homelab_id)
        if sidecar is None:
            yield StreamError(
                error_code="provider_unavailable",
                message="Homelab is offline.",
            )
            return

        body = self._to_generate_chat_body(model_slug, request)
        try:
            async for frame in sidecar.rpc_generate_chat(body):
                ev = _frame_to_event(frame)
                if ev is not None:
                    yield ev
        except Exception as exc:  # noqa: BLE001 — surface as terminal error
            _log.exception(
                "community.stream_completion.failed connection_id=%s homelab_id=%s",
                connection.id, homelab_id,
            )
            yield StreamError(error_code="provider_unavailable", message=str(exc))

    @staticmethod
    def _to_generate_chat_body(
        model_slug: str, request: CompletionRequest,
    ) -> dict:
        # Translate the internal CompletionMessage shape into the CSP
        # generate_chat body. Engine-specific quirks must be handled on the
        # sidecar — this code MUST NOT branch on engine type.
        messages: list[dict] = []
        for msg in request.messages:
            text_parts = [p.text for p in msg.content if p.type == "text" and p.text]
            images = [p.data for p in msg.content if p.type == "image" and p.data]
            item: dict = {
                "role": msg.role,
                "content": "".join(text_parts) if text_parts else "",
            }
            if images:
                item["images"] = images
            if msg.tool_calls:
                item["tool_calls"] = [
                    {"id": tc.id, "name": tc.name, "arguments": tc.arguments}
                    for tc in msg.tool_calls
                ]
            if msg.tool_call_id is not None:
                item["tool_call_id"] = msg.tool_call_id
            messages.append(item)

        tools_payload: list[dict] | None = None
        if request.tools:
            tools_payload = [
                {
                    "type": t.type,
                    "name": t.name,
                    "description": t.description,
                    "parameters": t.parameters,
                }
                for t in request.tools
            ]

        params: dict = {}
        if request.temperature is not None:
            params["temperature"] = request.temperature

        body: dict = {
            "model_slug": model_slug,
            "messages": messages,
            "parameters": params,
            "options": {
                "reasoning": bool(request.reasoning_enabled and request.supports_reasoning),
            },
        }
        if tools_payload is not None:
            body["tools"] = tools_payload
        return body

    @classmethod
    def router(cls) -> APIRouter | None:
        return _build_adapter_router()


# ----- adapter sub-router -----


def _build_adapter_router() -> APIRouter:
    from time import monotonic

    from fastapi import Depends

    from backend.modules.llm._resolver import resolve_connection_for_user

    router = APIRouter()

    @router.post("/test")
    async def test_connection(
        c: ResolvedConnection = Depends(resolve_connection_for_user),
    ) -> dict:
        homelab_id = (c.config.get("homelab_id") or "").strip()
        api_key = (c.config.get("api_key") or "").strip()
        if not homelab_id or not api_key:
            return {
                "valid": False,
                "error": "Homelab-ID or API-Key is missing.",
                "latency_ms": 0,
                "model_count": 0,
                "total_models_on_homelab": 0,
            }

        sidecar = get_sidecar_registry().get(homelab_id)
        if sidecar is None:
            return {
                "valid": False,
                "error": "Homelab is offline.",
                "latency_ms": 0,
                "model_count": 0,
                "total_models_on_homelab": 0,
            }

        svc = _homelab_service()
        key_doc = await svc.validate_consumer_access_key(
            homelab_id=homelab_id, api_key_plaintext=api_key,
        )
        if key_doc is None:
            return {
                "valid": False,
                "error": "API-Key is invalid or revoked.",
                "latency_ms": 0,
                "model_count": 0,
                "total_models_on_homelab": 0,
            }

        t0 = monotonic()
        try:
            models = await sidecar.rpc_list_models()
        except Exception as exc:  # noqa: BLE001 — surfaced to the frontend
            return {
                "valid": False,
                "error": f"Sidecar error: {exc}",
                "latency_ms": int((monotonic() - t0) * 1000),
                "model_count": 0,
                "total_models_on_homelab": 0,
            }
        latency_ms = int((monotonic() - t0) * 1000)
        allow = set(key_doc.get("allowed_model_slugs", []))
        visible = [m for m in models if m.get("slug") in allow]
        return {
            "valid": True,
            "latency_ms": latency_ms,
            "model_count": len(visible),
            "total_models_on_homelab": len(models),
            "error": None,
        }

    @router.get("/diagnostics")
    async def diagnostics(
        c: ResolvedConnection = Depends(resolve_connection_for_user),
    ) -> dict:
        homelab_id = (c.config.get("homelab_id") or "").strip()
        sidecar = get_sidecar_registry().get(homelab_id) if homelab_id else None
        if sidecar is None:
            return {"online": False}
        return {
            "online": True,
            "sidecar_version": sidecar.sidecar_version,
            "engine": sidecar.engine_info,
            "capabilities": sorted(sidecar.capabilities),
            "max_concurrent": sidecar.max_concurrent,
            "display_name": sidecar.display_name,
        }

    return router
