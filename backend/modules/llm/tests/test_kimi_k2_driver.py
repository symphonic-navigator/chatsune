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


# --- builder helpers -------------------------------------------------------


from shared.dtos.chat import ChatSessionExtras  # noqa: E402
from shared.dtos.inference import (  # noqa: E402
    CompletionMessage,
    CompletionRequest,
    ContentPart,
    ToolDefinition,
)
from shared.dtos.llm import ReasoningCapability, ToolCapability  # noqa: E402


def _make_request(
    *,
    slug: str,
    kind: str = "optional",
    default_on: bool = True,
    reasoning_mode: str = "on",
    tools_enabled: bool = False,
    tools: list[ToolDefinition] | None = None,
) -> CompletionRequest:
    """Build a CompletionRequest for builder tests.

    The ``kind`` argument lets a test simulate the capability spec the
    resolver would have attached for a given (adapter, slug). For Kimi
    tests we pass:
      - kind='optional' for Ollama K2.5/K2.6
      - kind='no_reasoning' for Novita K2.5
      - kind='always_on' for Novita K2.6
    """
    return CompletionRequest(
        model=slug,
        messages=[
            CompletionMessage(
                role="user",
                content=[ContentPart(type="text", text="Hello")],
            )
        ],
        tools=tools,
        reasoning=ReasoningCapability(
            kind=kind, effort=None, default_on=default_on,
        ),
        tools_capability=ToolCapability(supported=True),
        extras=ChatSessionExtras(
            tools_enabled=tools_enabled,
            reasoning_mode=reasoning_mode,
            reasoning_effort=None,
        ),
    )


# --- build_request: Ollama Cloud -------------------------------------------


def test_build_request_ollama_reasoning_on_writes_think_true() -> None:
    """Optional kind + reasoning_mode='on' -> body['think'] is True.
    The base ``_ollama_http.build_request_body`` already handles this
    when ``reasoning.kind == 'optional'`` — the driver just delegates."""
    driver = KimiK2Driver()
    body = driver.build_request(
        adapter_type="ollama_http",
        slug=_OLLAMA_K25,
        request=_make_request(slug=_OLLAMA_K25, kind="optional", reasoning_mode="on"),
    )
    assert body["think"] is True


def test_build_request_ollama_reasoning_off_writes_think_false() -> None:
    driver = KimiK2Driver()
    body = driver.build_request(
        adapter_type="ollama_http",
        slug=_OLLAMA_K25,
        request=_make_request(slug=_OLLAMA_K25, kind="optional", reasoning_mode="off"),
    )
    assert body["think"] is False


def test_build_request_ollama_k26_reasoning_on_writes_think_true() -> None:
    """K2.6 on Ollama Cloud uses the same wire shape as K2.5."""
    driver = KimiK2Driver()
    body = driver.build_request(
        adapter_type="ollama_http",
        slug=_OLLAMA_K26,
        request=_make_request(slug=_OLLAMA_K26, kind="optional", reasoning_mode="on"),
    )
    assert body["think"] is True


def test_build_request_ollama_includes_tools_when_enabled() -> None:
    driver = KimiK2Driver()
    tools = [
        ToolDefinition(
            name="get_time",
            description="Return the current time",
            parameters={"type": "object", "properties": {}},
        )
    ]
    body = driver.build_request(
        adapter_type="ollama_http",
        slug=_OLLAMA_K25,
        request=_make_request(
            slug=_OLLAMA_K25, kind="optional",
            tools_enabled=True, tools=tools,
        ),
    )
    assert "tools" in body
    assert body["tools"][0]["function"]["name"] == "get_time"


def test_build_request_ollama_omits_tools_when_disabled() -> None:
    driver = KimiK2Driver()
    tools = [
        ToolDefinition(
            name="get_time",
            description="Return the current time",
            parameters={"type": "object", "properties": {}},
        )
    ]
    body = driver.build_request(
        adapter_type="ollama_http",
        slug=_OLLAMA_K25,
        request=_make_request(
            slug=_OLLAMA_K25, kind="optional",
            tools_enabled=False, tools=tools,
        ),
    )
    assert "tools" not in body


# --- build_request: Novita -------------------------------------------------


def test_build_request_novita_k25_omits_reasoning_block() -> None:
    """K2.5 on Novita is no_reasoning — the base Novita builder only adds
    a ``reasoning`` block when kind=='optional', so this should already
    be absent. The driver delegates unchanged.
    """
    driver = KimiK2Driver()
    body = driver.build_request(
        adapter_type="novita_http",
        slug=_NOVITA_K25,
        request=_make_request(
            slug=_NOVITA_K25, kind="no_reasoning", default_on=False,
            reasoning_mode="off",
        ),
    )
    assert "reasoning" not in body
    assert "enable_thinking" not in body


def test_build_request_novita_k26_omits_reasoning_block() -> None:
    """K2.6 on Novita is always_on — the base Novita builder omits the
    reasoning block (only set for kind=='optional'). The provider
    ignores the toggle anyway."""
    driver = KimiK2Driver()
    body = driver.build_request(
        adapter_type="novita_http",
        slug=_NOVITA_K26,
        request=_make_request(
            slug=_NOVITA_K26, kind="always_on", default_on=True,
            reasoning_mode="on",
        ),
    )
    assert "reasoning" not in body
    assert "enable_thinking" not in body


def test_build_request_novita_inherits_message_translation() -> None:
    driver = KimiK2Driver()
    body = driver.build_request(
        adapter_type="novita_http",
        slug=_NOVITA_K25,
        request=_make_request(slug=_NOVITA_K25, kind="no_reasoning"),
    )
    assert len(body["messages"]) == 1
    assert body["messages"][0]["role"] == "user"
    assert body["messages"][0]["content"] == "Hello"


def test_build_request_novita_includes_tools_when_enabled() -> None:
    driver = KimiK2Driver()
    tools = [
        ToolDefinition(
            name="get_time",
            description="Return the current time",
            parameters={"type": "object", "properties": {}},
        )
    ]
    body = driver.build_request(
        adapter_type="novita_http",
        slug=_NOVITA_K26,
        request=_make_request(
            slug=_NOVITA_K26, kind="always_on",
            tools_enabled=True, tools=tools,
        ),
    )
    assert "tools" in body
    assert body["tools"][0]["function"]["name"] == "get_time"


# --- build_request: unsupported adapters -----------------------------------


@pytest.mark.parametrize(
    "adapter_type",
    ["openrouter_http", "nano_gpt_http", "gmi_http"],
)
def test_build_request_unsupported_adapter_raises(adapter_type: str) -> None:
    driver = KimiK2Driver()
    with pytest.raises(NotImplementedError, match="adapter_type"):
        driver.build_request(
            adapter_type=adapter_type,
            slug=_OLLAMA_K25,
            request=_make_request(slug=_OLLAMA_K25, kind="optional"),
        )
