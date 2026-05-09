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
