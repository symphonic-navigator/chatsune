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


# --- capability_spec -------------------------------------------------------


def test_capability_spec_ollama_k25_optional_reasoning() -> None:
    driver = KimiK2Driver()
    spec = driver.capability_spec(adapter_type="ollama_http", slug=_OLLAMA_K25)
    assert spec.first_class_support is True
    assert spec.reasoning.kind == "optional"
    assert spec.reasoning.default_on is True
    assert spec.reasoning.effort is None
    assert spec.tools.supported is True
    assert spec.tools.exclusive_with_reasoning is False


def test_capability_spec_ollama_k26_optional_reasoning() -> None:
    driver = KimiK2Driver()
    spec = driver.capability_spec(adapter_type="ollama_http", slug=_OLLAMA_K26)
    assert spec.first_class_support is True
    assert spec.reasoning.kind == "optional"
    assert spec.reasoning.default_on is True
    assert spec.reasoning.effort is None
    assert spec.tools.supported is True
    assert spec.tools.exclusive_with_reasoning is False


def test_capability_spec_novita_k25_no_reasoning() -> None:
    """Probe 2026-05-12: K2.5 on Novita never returns reasoning_content.
    Surfaced as ``no_reasoning`` so UI hides the toggle entirely."""
    driver = KimiK2Driver()
    spec = driver.capability_spec(adapter_type="novita_http", slug=_NOVITA_K25)
    assert spec.first_class_support is True
    assert spec.reasoning.kind == "no_reasoning"
    assert spec.reasoning.default_on is False
    assert spec.reasoning.effort is None
    assert spec.tools.supported is True
    assert spec.tools.exclusive_with_reasoning is False


def test_capability_spec_novita_k26_always_on_reasoning() -> None:
    """Probe 2026-05-12: K2.6 on Novita always emits reasoning_content;
    the reasoning toggle is upstream-ignored. Surfaced as ``always_on``
    so UI hides the toggle and shows reasoning by default."""
    driver = KimiK2Driver()
    spec = driver.capability_spec(adapter_type="novita_http", slug=_NOVITA_K26)
    assert spec.first_class_support is True
    assert spec.reasoning.kind == "always_on"
    assert spec.reasoning.default_on is True
    assert spec.reasoning.effort is None
    assert spec.tools.supported is True
    assert spec.tools.exclusive_with_reasoning is False


@pytest.mark.parametrize(
    "adapter_type",
    ["openrouter_http", "nano_gpt_http", "gmi_http"],
)
def test_capability_spec_unsupported_adapters_raise(adapter_type: str) -> None:
    driver = KimiK2Driver()
    with pytest.raises(NotImplementedError, match="adapter_type"):
        driver.capability_spec(adapter_type=adapter_type, slug=_OLLAMA_K25)
