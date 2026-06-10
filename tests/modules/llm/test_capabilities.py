from backend.modules.llm._capabilities import (
    resolve_capabilities,
    ResolvedCapabilities,
    CapabilityHint,
    DEFAULT_CAPABILITIES,
)
from shared.dtos.llm import ReasoningCapability, ToolCapability


class _StubAdapter:
    def __init__(self, hint=None):
        self._hint = hint

    def capability_hint(self, model_id):
        return self._hint


def test_yaml_match_returns_first_class():
    """Use a YAML entry that still has effort buckets (GPT-5) — Claude
    entries dropped effort per INS-037."""
    res = resolve_capabilities(
        adapter_type="openrouter_http",
        model_id="openai/gpt-5",
        adapter=_StubAdapter(),
    )
    assert isinstance(res, ResolvedCapabilities)
    assert res.first_class_support is True
    assert res.reasoning.kind == "optional"
    assert res.reasoning.effort.default_bucket == "medium"
    assert res.tools.supported is True


def test_yaml_match_anthropic_has_no_effort_per_INS037():
    """Claude entries deliberately omit effort buckets — see INS-037.
    Anthropic-via-router uses on/off only so cache_control survives."""
    res = resolve_capabilities(
        adapter_type="openrouter_http",
        model_id="anthropic/claude-opus-4.7",
        adapter=_StubAdapter(),
    )
    assert res.first_class_support is True
    assert res.reasoning.kind == "optional"
    assert res.reasoning.effort is None


def test_adapter_hint_used_when_no_yaml_match():
    hint = CapabilityHint(
        reasoning=ReasoningCapability(kind="always_on"),
        tools=ToolCapability(supported=True),
        first_class_support=True,
    )
    res = resolve_capabilities(
        adapter_type="someadapter",
        model_id="some-unknown-model",
        adapter=_StubAdapter(hint=hint),
    )
    assert res.reasoning.kind == "always_on"
    assert res.first_class_support is True


def test_universal_fallback_when_nothing_matches():
    res = resolve_capabilities(
        adapter_type="someadapter",
        model_id="some-unknown-model",
        adapter=_StubAdapter(),
    )
    assert res.reasoning.kind == "optional"
    assert res.reasoning.effort is None
    assert res.tools.supported is True
    assert res.tools.exclusive_with_reasoning is False
    assert res.first_class_support is False


def test_wildcard_pattern_matches():
    res = resolve_capabilities(
        adapter_type="openrouter_http",
        model_id="anthropic/claude-opus-4.7:beta",
        adapter=_StubAdapter(),
    )
    assert res.first_class_support is True


def test_default_capabilities_constant_is_optional_no_effort():
    assert DEFAULT_CAPABILITIES.reasoning.kind == "optional"
    assert DEFAULT_CAPABILITIES.reasoning.effort is None
    assert DEFAULT_CAPABILITIES.tools.supported is True
    assert DEFAULT_CAPABILITIES.tools.exclusive_with_reasoning is False


def test_grok_4_3_xai_http_has_effort_buckets():
    """xAI native adapter exposes the three-way effort picker for grok-4.3 — off-path is handled inside the adapter, not as a fourth bucket."""
    res = resolve_capabilities(
        adapter_type="xai_http",
        model_id="grok-4.3",
        adapter=_StubAdapter(),
    )
    assert res.first_class_support is True
    assert res.reasoning.kind == "optional"
    assert res.reasoning.effort is not None
    assert res.reasoning.effort.buckets == ["low", "medium", "high"]
    assert res.reasoning.effort.default_bucket == "low"
    assert res.tools.supported is True


def test_grok_4_3_via_openrouter_has_no_effort_buckets():
    """Cross-adapter scope: effort buckets only via xai_http.

    grok-4.3 served through OpenRouter has no specific YAML rule and falls
    through to the adapter heuristic / universal fallback, which carries
    no effort spec.
    """
    res = resolve_capabilities(
        adapter_type="openrouter_http",
        model_id="grok-4.3",
        adapter=_StubAdapter(),
    )
    assert res.reasoning.effort is None


def test_glm_5_ollama_http_is_first_class_optional_reasoning():
    """GLM-5 via Ollama Cloud: reasoning toggleable via think:true/false."""
    res = resolve_capabilities(
        adapter_type="ollama_http",
        model_id="glm-5",
        adapter=_StubAdapter(),
    )
    assert isinstance(res, ResolvedCapabilities)
    assert res.first_class_support is True
    assert res.reasoning.kind == "optional"
    assert res.reasoning.effort is None
    assert res.reasoning.default_on is True
    assert res.tools.supported is True
    assert res.tools.exclusive_with_reasoning is False


def test_glm_5_1_ollama_http_is_first_class_optional_reasoning():
    """GLM-5.1 via Ollama Cloud: same profile as GLM-5."""
    res = resolve_capabilities(
        adapter_type="ollama_http",
        model_id="glm-5.1",
        adapter=_StubAdapter(),
    )
    assert isinstance(res, ResolvedCapabilities)
    assert res.first_class_support is True
    assert res.reasoning.kind == "optional"
    assert res.reasoning.effort is None
    assert res.reasoning.default_on is True
    assert res.tools.supported is True
    assert res.tools.exclusive_with_reasoning is False


def test_glm_5_novita_http_is_first_class_always_on_reasoning():
    """GLM-5 via Novita: reasoning_content cannot be suppressed upstream."""
    res = resolve_capabilities(
        adapter_type="novita_http",
        model_id="zai-org/glm-5",
        adapter=_StubAdapter(),
    )
    assert isinstance(res, ResolvedCapabilities)
    assert res.first_class_support is True
    assert res.reasoning.kind == "always_on"
    assert res.reasoning.effort is None
    assert res.tools.supported is True
    assert res.tools.exclusive_with_reasoning is False


def test_glm_5_1_novita_http_is_first_class_always_on_reasoning():
    """GLM-5.1 via Novita: same profile as GLM-5."""
    res = resolve_capabilities(
        adapter_type="novita_http",
        model_id="zai-org/glm-5.1",
        adapter=_StubAdapter(),
    )
    assert isinstance(res, ResolvedCapabilities)
    assert res.first_class_support is True
    assert res.reasoning.kind == "always_on"
    assert res.reasoning.effort is None
    assert res.tools.supported is True
    assert res.tools.exclusive_with_reasoning is False


def test_fable_nano_gpt_is_first_class_with_effort_buckets():
    """Fable 5 via nano-gpt — effort-based thinking (INS-055). Unlike
    the Sonnet/Opus entries (INS-037, no effort block), Fable carries
    buckets because the enabled flag alone is a silent no-op."""
    res = resolve_capabilities(
        adapter_type="nano_gpt_http",
        model_id="anthropic/claude-fable-5",
        adapter=_StubAdapter(),
    )
    assert res.first_class_support is True
    assert res.reasoning.kind == "optional"
    assert res.reasoning.effort is not None
    assert res.reasoning.effort.buckets == ["low", "medium", "high"]
    assert res.reasoning.effort.default_bucket == "medium"
    assert res.reasoning.default_on is True
    assert res.reasoning.replay_reasoning is True
    assert res.tools.supported is True
    assert res.tools.exclusive_with_reasoning is False


def test_fable_latest_alias_matches_same_entry():
    """The claude-fable-latest alias routes to Fable 5 upstream; the
    wildcard pattern covers it with identical capabilities."""
    res = resolve_capabilities(
        adapter_type="nano_gpt_http",
        model_id="anthropic/claude-fable-latest",
        adapter=_StubAdapter(),
    )
    assert res.first_class_support is True
    assert res.reasoning.effort is not None
    assert res.reasoning.effort.default_bucket == "medium"


def test_fable_via_openrouter_is_not_first_class():
    """Cross-adapter scope: first-class Fable is nano-gpt only (spec §5)."""
    res = resolve_capabilities(
        adapter_type="openrouter_http",
        model_id="anthropic/claude-fable-5",
        adapter=_StubAdapter(),
    )
    assert res.first_class_support is False
