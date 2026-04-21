"""Static registry of Premium Providers."""
import logging

from backend.modules.providers._models import PremiumProviderDefinition
from shared.dtos.providers import Capability

_log = logging.getLogger(__name__)
_registry: dict[str, PremiumProviderDefinition] = {}


def register(defn: PremiumProviderDefinition) -> None:
    if defn.id in _registry:
        raise ValueError(f"Provider '{defn.id}' already registered")
    _registry[defn.id] = defn
    _log.info("Registered premium provider: %s", defn.id)


def get(provider_id: str) -> PremiumProviderDefinition | None:
    return _registry.get(provider_id)


def get_all() -> dict[str, PremiumProviderDefinition]:
    return dict(_registry)


def _api_key_field(label: str) -> dict:
    return {
        "key": "api_key",
        "label": label,
        "field_type": "password",
        "secret": True,
        "required": True,
        "description": "Encrypted at rest, never leaves the backend.",
    }


def _register_builtins() -> None:
    register(PremiumProviderDefinition(
        id="xai",
        display_name="xAI",
        icon="xai",
        base_url="https://api.x.ai/v1",
        capabilities=[
            Capability.LLM, Capability.TTS, Capability.STT,
            Capability.TTI, Capability.ITI,
        ],
        config_fields=[_api_key_field("xAI API Key")],
        probe_url="https://api.x.ai/v1/models",
        probe_method="GET",
        linked_integrations=["xai_voice"],
    ))

    register(PremiumProviderDefinition(
        id="mistral",
        display_name="Mistral",
        icon="mistral",
        base_url="https://api.mistral.ai/v1",
        capabilities=[Capability.LLM, Capability.TTS, Capability.STT],
        config_fields=[_api_key_field("Mistral API Key")],
        probe_url="https://api.mistral.ai/v1/models",
        probe_method="GET",
        linked_integrations=["mistral_voice"],
    ))

    register(PremiumProviderDefinition(
        id="ollama_cloud",
        display_name="Ollama Cloud",
        icon="ollama",
        base_url="https://ollama.com",
        capabilities=[Capability.LLM, Capability.WEBSEARCH],
        config_fields=[_api_key_field("Ollama Cloud API Key")],
        probe_url="https://ollama.com/api/me",
        probe_method="POST",
        linked_integrations=[],
    ))


_register_builtins()
