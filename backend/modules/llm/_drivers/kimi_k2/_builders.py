"""Request-body builders for Kimi K2.5 / K2.6.

Wire support: Ollama Cloud (``ollama_http``) and Novita (``novita_http``).

Both builders delegate to the existing adapter ``build_request_body``
helpers and return the result unchanged. The base builders already
produce the correct wire shape for the three reasoning kinds we surface:

- ``optional`` (Ollama K2.5, K2.6) → ``_ollama_http`` writes
  ``think: true/false`` based on ``extras.reasoning_mode``.
- ``no_reasoning`` (Novita K2.5) → ``_novita_http`` omits the
  ``reasoning`` block (only set when kind == ``optional``).
- ``always_on`` (Novita K2.6) → ``_novita_http`` omits the ``reasoning``
  block. The provider ignores the toggle anyway (probe 2026-05-12), so
  there is no working signal to send.

If Kimi later sprouts a working effort knob, slip the override into the
relevant builder rather than mutating the adapter.
"""
from __future__ import annotations

from typing import Any

from shared.dtos.inference import CompletionRequest


def build_request_for_ollama_cloud(
    *, slug: str, request: CompletionRequest,
) -> dict[str, Any]:
    """Build the Ollama Cloud request body for Kimi K2.5 / K2.6.

    Pure delegation — ``_ollama_http.build_request_body`` handles
    everything correctly when ``request.reasoning.kind == 'optional'``
    (which the driver's capability spec guarantees for this adapter).
    """
    # Local import to avoid a circular dependency at module load time
    # (drivers depend on adapter helpers; the adapter consults drivers
    # at call time).
    from backend.modules.llm._adapters._ollama_http import (
        build_request_body as _ollama_build_request_body,
    )

    return _ollama_build_request_body(request)


def build_request_for_novita(
    *, slug: str, request: CompletionRequest,
) -> dict[str, Any]:
    """Build the Novita request body for Kimi K2.5 / K2.6.

    Pure delegation — ``_novita_http.build_request_body`` omits the
    ``reasoning`` block when ``reasoning.kind`` is ``no_reasoning``
    (K2.5) or ``always_on`` (K2.6), which is exactly what we want for
    Kimi on Novita (the provider ignores the toggle for K2.6 and the
    block is meaningless for K2.5).
    """
    from backend.modules.llm._adapters._novita_http import (
        build_request_body as _novita_build_request_body,
    )

    return _novita_build_request_body(request)
