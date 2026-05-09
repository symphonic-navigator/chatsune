from shared.dtos.llm import (
    ReasoningEffortSpec,
    ReasoningCapability,
    ToolCapability,
)


def test_reasoning_effort_spec_requires_default_in_buckets():
    spec = ReasoningEffortSpec(buckets=["low", "medium", "high"], default_bucket="medium")
    assert spec.default_bucket in spec.buckets


def test_reasoning_capability_optional_with_effort():
    cap = ReasoningCapability(
        kind="optional",
        effort=ReasoningEffortSpec(buckets=["low", "medium", "high"], default_bucket="medium"),
        default_on=True,
    )
    assert cap.kind == "optional"
    assert cap.effort.default_bucket == "medium"


def test_reasoning_capability_no_reasoning_omits_effort():
    cap = ReasoningCapability(kind="no_reasoning")
    assert cap.effort is None


def test_tool_capability_default_no_mutex():
    cap = ToolCapability(supported=True)
    assert cap.exclusive_with_reasoning is False


from shared.dtos.llm import ModelMetaDto


def _meta(**overrides):
    base = dict(
        connection_id="c1",
        connection_slug="conn",
        model_id="m1",
        display_name="M1",
        context_window=8000,
        supports_vision=False,
        supports_tool_calls=True,
        reasoning=ReasoningCapability(kind="optional"),
        tools=ToolCapability(supported=True),
    )
    base.update(overrides)
    return ModelMetaDto(**base)


def test_model_meta_supports_reasoning_computed_true_when_optional():
    m = _meta()
    assert m.supports_reasoning is True


def test_model_meta_supports_reasoning_computed_false_when_no_reasoning():
    m = _meta(reasoning=ReasoningCapability(kind="no_reasoning"))
    assert m.supports_reasoning is False


def test_model_meta_first_class_default_false():
    m = _meta()
    assert m.first_class_support is False
