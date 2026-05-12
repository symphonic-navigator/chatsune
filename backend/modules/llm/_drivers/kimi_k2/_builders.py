"""Request-body builders for Kimi K2.5 / K2.6.

Wire support: Ollama Cloud (``ollama_http``) and Novita (``novita_http``).
Logic: delegate to the existing adapter ``build_request_body`` helpers.
The base builders already handle the three reasoning kinds correctly
(per ``_ollama_http.build_request_body`` and ``_novita_http.build_request_body``
docstrings); the driver's capability spec determines which branch runs.
"""
from __future__ import annotations

from typing import Any

from shared.dtos.inference import CompletionRequest


def build_request_for_ollama_cloud(
    *, slug: str, request: CompletionRequest,
) -> dict[str, Any]:
    raise NotImplementedError("filled in Task 3")


def build_request_for_novita(
    *, slug: str, request: CompletionRequest,
) -> dict[str, Any]:
    raise NotImplementedError("filled in Task 3")
