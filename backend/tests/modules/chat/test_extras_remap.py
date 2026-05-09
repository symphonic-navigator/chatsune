"""Tests for spec §6.5 model-switch extras remap.

Pure logic — no DB, no FastAPI, no adapters.
"""
from shared.dtos.chat import ChatSessionExtras
from shared.dtos.llm import (
    ReasoningCapability,
    ReasoningEffortSpec,
    ToolCapability,
)

from backend.modules.chat._extras_remap import remap_extras_for_capability


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
