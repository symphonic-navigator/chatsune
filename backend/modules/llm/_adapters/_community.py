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
        homelab_id = (connection.config.get("homelab_id") or "").strip()
        api_key = (connection.config.get("api_key") or "").strip()
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

        return [
            _model_meta_to_dto(connection, m)
            for m in raw_models
            if m.get("slug") in allowlist and m.get("context_length")
        ]

    def stream_completion(
        self,
        connection: ResolvedConnection,
        request: CompletionRequest,
    ) -> AsyncIterator[ProviderStreamEvent]:
        raise NotImplementedError  # Task 4

    @classmethod
    def router(cls) -> APIRouter | None:
        return None  # Task 5 mounts this
