"""Driver Protocol — per-model-family request/response handling.

A Driver matches a model family by slug-basename pattern, returns the
capability spec for the model on a given adapter, and provides the
request-body builder and response-chunk parser appropriate for the
(adapter_type, slug) combination.

See devdocs/specs/driver-layer.md for the architecture.
"""
from __future__ import annotations

from typing import Any, ClassVar, Protocol, runtime_checkable

from backend.modules.llm._adapters._events import ProviderStreamEvent
from backend.modules.llm._capabilities import ResolvedCapabilities
from shared.dtos.inference import CompletionRequest


@runtime_checkable
class Driver(Protocol):
    """Per-model-family driver. See spec for semantics."""

    PATTERNS: ClassVar[list[str]]
    """fnmatch patterns matched against the slug basename
    (slug.rsplit('/', 1)[-1]). Multiple patterns supported so naming-
    convention drift across routers does not multiply driver classes."""

    SUPPORTED_ADAPTERS: ClassVar[frozenset[str]]
    """Set of adapter_types this driver claims for capability resolution
    and (where applicable) wire handling.

    ``match_driver`` only returns the driver class when both the slug
    basename matches one of ``PATTERNS`` AND the adapter_type is in
    this set. Listings on non-supported adapters therefore fall through
    cleanly to the YAML lookup, the adapter heuristic, or the universal
    default — they never reach the driver's ``capability_spec`` and so
    cannot trigger the driver's defensive ``NotImplementedError``.

    The driver-internal ``NotImplementedError`` guards in
    ``capability_spec`` / ``build_request`` / ``parse_chunk`` remain in
    place as defence-in-depth and are intentionally loud at inference
    time if anything ever bypasses ``match_driver``."""

    def capability_spec(
        self,
        *,
        adapter_type: str,
        slug: str,
    ) -> ResolvedCapabilities:
        """Return the capability spec for this (adapter, slug).

        For Plan 1 the driver returns its full spec without merging
        provider metadata. Plan 5 introduces None-overridable fields
        (context_length, pricing) and the merge step.
        """
        ...

    def build_request(
        self,
        *,
        adapter_type: str,
        slug: str,
        request: CompletionRequest,
    ) -> dict[str, Any]:
        """Construct the wire-level request body for this (adapter, slug).

        Returns a dict matching the adapter's transport expectations.
        For openrouter_http this is the OpenAI-compat JSON body shape.
        """
        ...

    def parse_chunk(
        self,
        *,
        adapter_type: str,
        slug: str,
        chunk: dict[str, Any],
    ) -> list[ProviderStreamEvent]:
        """Translate a single decoded chunk into zero or more events.

        For Plan 1 (OR only) chunks are post-SSE-decoded JSON dicts.
        Later plans extend to NDJSON (Ollama Cloud) and additional
        stream-key extraction (delta.reasoning_content, message.thinking).
        """
        ...
