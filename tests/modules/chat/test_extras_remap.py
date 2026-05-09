"""Tests for spec §6.5 model-switch extras remap.

Pure logic — no DB, no FastAPI, no adapters.
"""
from shared.dtos.chat import ChatSessionExtras
from shared.dtos.llm import (
    ReasoningCapability,
    ReasoningEffortSpec,
    ToolCapability,
)

from backend.modules.chat._extras_remap import (
    default_extras_for_capability,
    remap_extras_for_capability,
)


def _cap(kind, effort_buckets=None, tool_supported=True, mutex=False):
    effort = (
        ReasoningEffortSpec(
            buckets=effort_buckets,
            default_bucket=effort_buckets[len(effort_buckets) // 2],
        )
        if effort_buckets else None
    )
    return (
        ReasoningCapability(kind=kind, effort=effort),
        ToolCapability(supported=tool_supported, exclusive_with_reasoning=mutex),
    )


def test_remap_preserves_tools_when_supported():
    old = ChatSessionExtras(
        tools_enabled=True, reasoning_mode="on", reasoning_effort="high",
    )
    new_r, new_t = _cap("optional", ["low", "medium", "high"])
    out = remap_extras_for_capability(old, new_r, new_t)
    assert out.tools_enabled is True
    assert out.reasoning_mode == "on"
    assert out.reasoning_effort == "high"


def test_remap_drops_tools_when_unsupported():
    old = ChatSessionExtras(
        tools_enabled=True, reasoning_mode="off", reasoning_effort=None,
    )
    new_r, new_t = _cap("optional", tool_supported=False)
    out = remap_extras_for_capability(old, new_r, new_t)
    assert out.tools_enabled is False


def test_remap_forces_reasoning_on_for_always_on():
    old = ChatSessionExtras(
        tools_enabled=True, reasoning_mode="off", reasoning_effort=None,
    )
    new_r, new_t = _cap("always_on")
    out = remap_extras_for_capability(old, new_r, new_t)
    assert out.reasoning_mode == "on"


def test_remap_forces_reasoning_off_for_no_reasoning():
    old = ChatSessionExtras(
        tools_enabled=True, reasoning_mode="on", reasoning_effort="medium",
    )
    new_r, new_t = _cap("no_reasoning")
    out = remap_extras_for_capability(old, new_r, new_t)
    assert out.reasoning_mode == "off"
    assert out.reasoning_effort is None


def test_remap_resets_effort_when_bucket_not_in_new_capability():
    old = ChatSessionExtras(
        tools_enabled=False, reasoning_mode="on", reasoning_effort="minimal",
    )
    new_r, new_t = _cap("optional", ["low", "medium", "high"])  # no "minimal"
    out = remap_extras_for_capability(old, new_r, new_t)
    assert out.reasoning_effort == "medium"  # default_bucket of new spec


def test_remap_tools_win_when_mutex_violated():
    old = ChatSessionExtras(
        tools_enabled=True, reasoning_mode="on", reasoning_effort="medium",
    )
    new_r, new_t = _cap("optional", ["low", "medium", "high"], mutex=True)
    out = remap_extras_for_capability(old, new_r, new_t)
    assert out.tools_enabled is True
    assert out.reasoning_mode == "off"  # tools win on conflict


# ---------------------------------------------------------------------------
# default_extras_for_capability — spec §4.5
# ---------------------------------------------------------------------------


def test_defaults_optional_no_mutex_both_on():
    r = ReasoningCapability(
        kind="optional",
        effort=ReasoningEffortSpec(
            buckets=["low", "medium", "high"], default_bucket="medium",
        ),
    )
    t = ToolCapability(supported=True)
    e = default_extras_for_capability(r, t)
    assert e.tools_enabled is True
    assert e.reasoning_mode == "on"
    assert e.reasoning_effort == "medium"


def test_defaults_optional_with_mutex_tools_on_reasoning_off():
    r = ReasoningCapability(kind="optional")
    t = ToolCapability(supported=True, exclusive_with_reasoning=True)
    e = default_extras_for_capability(r, t)
    assert e.tools_enabled is True
    assert e.reasoning_mode == "off"
    assert e.reasoning_effort is None


def test_defaults_always_on_no_mutex():
    r = ReasoningCapability(kind="always_on")
    t = ToolCapability(supported=True)
    e = default_extras_for_capability(r, t)
    assert e.reasoning_mode == "on"
    assert e.tools_enabled is True


def test_defaults_always_on_with_mutex_tools_off():
    r = ReasoningCapability(
        kind="always_on",
        effort=ReasoningEffortSpec(
            buckets=["low", "high"], default_bucket="high",
        ),
    )
    t = ToolCapability(supported=True, exclusive_with_reasoning=True)
    e = default_extras_for_capability(r, t)
    assert e.reasoning_mode == "on"
    # mutex forces tools off so reasoning can stay on for always_on models
    assert e.tools_enabled is False
    assert e.reasoning_effort == "high"


def test_defaults_no_reasoning_tools_on_when_supported():
    r = ReasoningCapability(kind="no_reasoning")
    t = ToolCapability(supported=True)
    e = default_extras_for_capability(r, t)
    assert e.reasoning_mode == "off"
    assert e.tools_enabled is True
    assert e.reasoning_effort is None


def test_defaults_no_reasoning_tools_off_when_unsupported():
    r = ReasoningCapability(kind="no_reasoning")
    t = ToolCapability(supported=False)
    e = default_extras_for_capability(r, t)
    assert e.tools_enabled is False
    assert e.reasoning_mode == "off"


def test_defaults_optional_no_effort_spec_returns_none():
    r = ReasoningCapability(kind="optional")  # no effort spec
    t = ToolCapability(supported=False)
    e = default_extras_for_capability(r, t)
    assert e.reasoning_mode == "on"
    assert e.reasoning_effort is None
    assert e.tools_enabled is False
