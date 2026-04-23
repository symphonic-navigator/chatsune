from unittest.mock import MagicMock

from backend.modules.llm._adapters._community import CommunityAdapter
from backend.modules.llm._adapters._nano_gpt_http import NanoGptHttpAdapter
from backend.modules.llm._adapters._ollama_http import OllamaHttpAdapter
from backend.modules.llm._registry import (
    _PREMIUM_ONLY_ADAPTERS,
    _instantiate_adapter,
    ADAPTER_REGISTRY,
    get_adapter_class,
)


def test_nano_gpt_http_is_premium_only():
    # Nano-GPT is a Premium Provider: users configure a BYOK account through
    # the Premium Provider panel, not as a regular Connection. The adapter
    # class must therefore be gated behind ``_PREMIUM_ONLY_ADAPTERS`` so no
    # user can create a stray Connection with ``adapter_type="nano_gpt_http"``.
    assert "nano_gpt_http" in _PREMIUM_ONLY_ADAPTERS
    assert _PREMIUM_ONLY_ADAPTERS["nano_gpt_http"] is NanoGptHttpAdapter


def test_nano_gpt_http_not_user_configurable():
    assert "nano_gpt_http" not in ADAPTER_REGISTRY


def test_get_adapter_class_returns_nano_gpt_http():
    # Still resolvable by adapter_type string — Premium resolver uses this.
    assert get_adapter_class("nano_gpt_http") is NanoGptHttpAdapter


def test_instantiate_adapter_passes_redis_when_init_accepts_it():
    # NanoGptHttpAdapter declares a ``redis`` keyword on ``__init__``; the
    # metadata-layer helper must pass the Redis client through so the
    # adapter can persist its pair map.
    redis = MagicMock()
    adapter = _instantiate_adapter(NanoGptHttpAdapter, redis)
    assert isinstance(adapter, NanoGptHttpAdapter)
    assert adapter._redis is redis


def test_instantiate_adapter_omits_redis_for_stateless_adapters():
    # Existing adapters (Ollama, Community, xAI, Mistral) take no constructor
    # arguments; the helper must not break them by passing redis.
    redis = MagicMock()
    ollama = _instantiate_adapter(OllamaHttpAdapter, redis)
    community = _instantiate_adapter(CommunityAdapter, redis)
    assert isinstance(ollama, OllamaHttpAdapter)
    assert isinstance(community, CommunityAdapter)
