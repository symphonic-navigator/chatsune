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
from shared.dtos.inference import CompletionRequest
from shared.dtos.llm import ModelMetaDto

_log = logging.getLogger(__name__)


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
        raise NotImplementedError  # Task 3

    def stream_completion(
        self,
        connection: ResolvedConnection,
        request: CompletionRequest,
    ) -> AsyncIterator[ProviderStreamEvent]:
        raise NotImplementedError  # Task 4

    @classmethod
    def router(cls) -> APIRouter | None:
        return None  # Task 5 mounts this
