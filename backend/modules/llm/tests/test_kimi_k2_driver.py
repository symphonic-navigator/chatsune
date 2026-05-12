"""Tests for KimiK2Driver — capability spec, request body, chunk parsing.

Mirrors the structure of test_mimo_v25_driver.py. Kimi K2 is a
two-adapter (Ollama Cloud + Novita) integration with per-(adapter, slug)
reasoning capability differences:

- Ollama Cloud (k2.5, k2.6): optional reasoning, ``think: true/false``
- Novita k2.5: no_reasoning (provider returns empty reasoning_content)
- Novita k2.6: always_on (provider ignores reasoning toggle)

See devdocs/research/kimi-k2-wire-shapes.md for the wire-shape probes
that motivate this matrix.
"""
from __future__ import annotations

import pytest

from backend.modules.llm._drivers import match_driver
from backend.modules.llm._drivers.kimi_k2 import KimiK2Driver


_OLLAMA_K25 = "kimi-k2.5"
_OLLAMA_K26 = "kimi-k2.6"
_NOVITA_K25 = "moonshotai/kimi-k2.5"
_NOVITA_K26 = "moonshotai/kimi-k2.6"


# --- match_driver ----------------------------------------------------------


def test_match_driver_ollama_k25() -> None:
    assert match_driver(_OLLAMA_K25) is KimiK2Driver


def test_match_driver_ollama_k26() -> None:
    assert match_driver(_OLLAMA_K26) is KimiK2Driver


def test_match_driver_novita_k25_with_publisher_prefix() -> None:
    assert match_driver(_NOVITA_K25) is KimiK2Driver


def test_match_driver_novita_k26_with_publisher_prefix() -> None:
    assert match_driver(_NOVITA_K26) is KimiK2Driver


def test_match_driver_does_not_match_older_kimi() -> None:
    """K2.4 and earlier are not first-class — the driver targets K2.5+."""
    assert match_driver("kimi-k2.4") is None
    assert match_driver("moonshotai/kimi-k2") is None


def test_match_driver_does_not_match_unrelated_moonshot_model() -> None:
    assert match_driver("moonshotai/kimi-vl") is None
