"""Verify the lazy-remap behaviour: if stored extras are inconsistent with
the current model's capability, they are remapped before use AND persisted
+ broadcast back to clients (multi-device sync).

These tests exercise ``remap_extras_for_capability`` from the orchestrator's
point of view — confirming idempotence (no spurious writes when already
consistent) and self-healing semantics (remap kicks in when capability
shifts under a session). The orchestrator wiring is verified end-to-end
by manual testing in Task 25.
"""
from shared.dtos.chat import ChatSessionExtras
from shared.dtos.llm import ReasoningCapability, ReasoningEffortSpec, ToolCapability

from backend.modules.chat._extras_remap import remap_extras_for_capability


def test_extras_unchanged_when_capability_matches():
    extras = ChatSessionExtras(
        tools_enabled=True, reasoning_mode="on", reasoning_effort="medium",
    )
    r = ReasoningCapability(
        kind="optional",
        effort=ReasoningEffortSpec(
            buckets=["low", "medium", "high"], default_bucket="medium",
        ),
    )
    t = ToolCapability(supported=True)
    out = remap_extras_for_capability(extras, r, t)
    assert out == extras  # idempotent when consistent — orchestrator skips persist


def test_extras_remapped_when_capability_changed_to_no_reasoning():
    extras = ChatSessionExtras(
        tools_enabled=True, reasoning_mode="on", reasoning_effort="high",
    )
    r = ReasoningCapability(kind="no_reasoning")
    t = ToolCapability(supported=True)
    out = remap_extras_for_capability(extras, r, t)
    assert out.reasoning_mode == "off"
    assert out.reasoning_effort is None
    assert out.tools_enabled is True


def test_extras_remapped_when_effort_bucket_no_longer_in_spec():
    extras = ChatSessionExtras(
        tools_enabled=False, reasoning_mode="on", reasoning_effort="minimal",
    )
    # New model only supports {low, medium, high} — minimal disappears
    r = ReasoningCapability(
        kind="optional",
        effort=ReasoningEffortSpec(
            buckets=["low", "medium", "high"], default_bucket="medium",
        ),
    )
    t = ToolCapability(supported=True)
    out = remap_extras_for_capability(extras, r, t)
    assert out.reasoning_effort == "medium"  # default bucket of new spec
