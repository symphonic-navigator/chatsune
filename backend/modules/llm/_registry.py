"""Adapter registry — maps adapter_type string to adapter class.

``ADAPTER_REGISTRY`` is the *user-createable* registry: the set of
``adapter_type`` values a user may pick when creating a Connection.

``get_adapter_class`` additionally resolves Premium-only adapter types
(currently ``xai_http``) that are reachable via the Premium Provider
resolver but must not be selectable as a regular user Connection —
see :mod:`backend.modules.llm._resolver`.
"""

from backend.modules.llm._adapters._base import BaseAdapter
from backend.modules.llm._adapters._community import CommunityAdapter
from backend.modules.llm._adapters._mistral_http import MistralHttpAdapter
from backend.modules.llm._adapters._nano_gpt_http import NanoGptHttpAdapter
from backend.modules.llm._adapters._ollama_http import OllamaHttpAdapter
from backend.modules.llm._adapters._xai_http import XaiHttpAdapter

ADAPTER_REGISTRY: dict[str, type[BaseAdapter]] = {
    "ollama_http": OllamaHttpAdapter,
    "community": CommunityAdapter,
    "nano_gpt_http": NanoGptHttpAdapter,
}

# Premium-only adapter types — not user-createable, but instantiable by the
# Premium Provider resolver. Keeping them out of ``ADAPTER_REGISTRY`` prevents
# users from creating a stray ``xai_http`` Connection that would bypass the
# Premium Provider credential flow. See commit 37688d9 and INS-* (Premium
# Provider Accounts).
_PREMIUM_ONLY_ADAPTERS: dict[str, type[BaseAdapter]] = {
    "xai_http": XaiHttpAdapter,
    "mistral_http": MistralHttpAdapter,
}


def get_adapter_class(adapter_type: str) -> type[BaseAdapter] | None:
    """Return the adapter class for ``adapter_type`` or ``None``.

    Consults the user-facing ``ADAPTER_REGISTRY`` first, then the
    premium-only map. Use this at any call site that instantiates an
    adapter from a :class:`ResolvedConnection` — including Premium-
    synthesised connections.
    """
    cls = ADAPTER_REGISTRY.get(adapter_type)
    if cls is not None:
        return cls
    return _PREMIUM_ONLY_ADAPTERS.get(adapter_type)
