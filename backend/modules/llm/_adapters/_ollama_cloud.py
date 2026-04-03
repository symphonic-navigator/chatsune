import logging

import httpx

from backend.modules.llm._adapters._base import BaseAdapter
from shared.dtos.llm import ModelMetaDto

_log = logging.getLogger(__name__)

_TIMEOUT = 15.0


def _format_parameter_count(value: int | None) -> str | None:
    """Convert raw parameter count to human-readable form (e.g. 675B, 7.5B, 405M)."""
    if not value:
        return None
    if value >= 1_000_000_000_000:
        n = value / 1_000_000_000_000
        return f"{n:g}T"
    if value >= 1_000_000_000:
        n = value / 1_000_000_000
        return f"{n:g}B"
    if value >= 1_000_000:
        n = value / 1_000_000
        return f"{n:g}M"
    return None


def _build_display_name(model_name: str) -> str:
    """Convert 'mistral-large-3:675b' to 'Mistral Large 3 (675B)'."""
    colon_idx = model_name.find(":")
    if colon_idx >= 0:
        name_part = model_name[:colon_idx]
        tag = model_name[colon_idx + 1:]
    else:
        name_part = model_name
        tag = None

    title = " ".join(word.capitalize() for word in name_part.split("-"))

    if not tag or tag.lower() == "latest":
        return title
    return f"{title} ({tag.upper()})"


class OllamaCloudAdapter(BaseAdapter):
    """Ollama Cloud inference adapter."""

    async def validate_key(self, api_key: str) -> bool:
        """Validate key via GET /api/me. Returns True on 200, False on 401/403."""
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.get(
                f"{self.base_url}/api/me",
                headers={"Authorization": f"Bearer {api_key}"},
            )
        return resp.status_code == 200

    async def fetch_models(self) -> list[ModelMetaDto]:
        """Fetch model list from /api/tags, then details from /api/show per model."""
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            tags_resp = await client.get(f"{self.base_url}/api/tags")
            tags_resp.raise_for_status()
            tag_entries = tags_resp.json().get("models", [])

            models: list[ModelMetaDto] = []
            for entry in tag_entries:
                name = entry["name"]
                try:
                    show_resp = await client.post(
                        f"{self.base_url}/api/show",
                        json={"model": name},
                    )
                    show_resp.raise_for_status()
                    detail = show_resp.json()
                except Exception:
                    _log.warning("Failed to fetch details for model '%s'; skipping.", name)
                    continue

                models.append(self._map_to_dto(name, detail))

        return models

    def _map_to_dto(self, model_name: str, detail: dict) -> ModelMetaDto:
        capabilities = detail.get("capabilities", [])
        model_info = detail.get("model_info", {})
        details = detail.get("details", {})

        # Extract context window from model_info (key ends with .context_length)
        context_window = 0
        for key, value in model_info.items():
            if key.endswith(".context_length") and isinstance(value, int):
                context_window = value
                break

        # Extract parameter count — prefer details.parameter_size, fall back to model_info
        raw_params = None
        param_str = details.get("parameter_size")
        if param_str is not None:
            try:
                raw_params = int(param_str)
            except (ValueError, TypeError):
                pass
        if raw_params is None:
            raw_params = model_info.get("general.parameter_count")

        return ModelMetaDto(
            provider_id="ollama_cloud",
            model_id=model_name,
            display_name=_build_display_name(model_name),
            context_window=context_window,
            supports_reasoning="thinking" in capabilities,
            supports_vision="vision" in capabilities,
            supports_tool_calls="tools" in capabilities,
            parameter_count=_format_parameter_count(raw_params),
            quantisation_level=details.get("quantization_level"),
        )
