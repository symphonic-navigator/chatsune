"""xAI HTTP adapter — Chat Completions (legacy) for Grok 4.1 Fast."""

from __future__ import annotations

import logging

from backend.modules.llm._adapters._base import BaseAdapter
from backend.modules.llm._adapters._types import (
    AdapterTemplate,
    ConfigFieldHint,
)

_log = logging.getLogger(__name__)


class XaiHttpAdapter(BaseAdapter):
    adapter_type = "xai_http"
    display_name = "xAI / Grok"
    view_id = "xai_http"
    secret_fields = frozenset({"api_key"})

    @classmethod
    def templates(cls) -> list[AdapterTemplate]:
        return [
            AdapterTemplate(
                id="xai_cloud",
                display_name="xAI Cloud",
                slug_prefix="xai",
                config_defaults={
                    "url": "https://api.x.ai/v1",
                    "api_key": "",
                    "max_parallel": 4,
                },
                required_config_fields=("api_key",),
            ),
        ]

    @classmethod
    def config_schema(cls) -> list[ConfigFieldHint]:
        return [
            ConfigFieldHint(
                name="url", type="url", label="URL",
                placeholder="https://api.x.ai/v1",
            ),
            ConfigFieldHint(
                name="api_key", type="secret", label="API Key",
            ),
            ConfigFieldHint(
                name="max_parallel", type="integer",
                label="Max parallel inferences",
                min=1, max=32,
            ),
        ]

    # fetch_models + stream_completion added in later tasks.
