"""Spec §6.5 model-switch mapping for ChatSessionExtras and §4.5 defaults.

Pure logic: given the existing extras and the capability of the new
model, compute the remapped extras. Preserve where possible, force
where the new capability demands it, and let tools win on a mutex
conflict (Chris's rule from §6.5).

Also exposes :func:`default_extras_for_capability` — the capability-driven
initial defaults used both for fresh chat sessions and as a fallback when
a legacy session document carries no ``extras`` field at all.

Used both by the PATCH ``/sessions/{id}/extras`` endpoint (validation
shape mirrors the remap rules) and by the model-switch wiring (Task 24).
"""
from shared.dtos.chat import ChatSessionExtras
from shared.dtos.llm import ReasoningCapability, ToolCapability


def remap_extras_for_capability(
    old: ChatSessionExtras,
    reasoning: ReasoningCapability,
    tools: ToolCapability,
) -> ChatSessionExtras:
    """Apply spec §6.5 mapping when the model on a chat session changes.

    - Tools: preserved if the new model supports them; else forced ``False``.
    - Reasoning mode: forced ``"on"`` for ``always_on`` models, forced
      ``"off"`` for ``no_reasoning`` models, otherwise preserved.
    - Reasoning effort: preserved if the bucket exists in the new model's
      effort spec; otherwise reset to ``default_bucket``; otherwise
      ``None`` (model has no effort selector or reasoning ends up off).
    - Mutex: if the resulting state would have both tools and reasoning
      on against a mutex-only model, tools win and reasoning is forced
      off (per Chris's §6.5 rule).
    """
    # Tools: preserve if new model supports; else False
    tools_enabled = old.tools_enabled if tools.supported else False

    # Reasoning mode
    if reasoning.kind == "always_on":
        mode = "on"
    elif reasoning.kind == "no_reasoning":
        mode = "off"
    else:
        mode = old.reasoning_mode

    # Effort: preserve if bucket exists in new spec; else default; else None
    if reasoning.effort and old.reasoning_effort in reasoning.effort.buckets:
        effort = old.reasoning_effort
    elif reasoning.effort:
        effort = reasoning.effort.default_bucket
    else:
        effort = None

    # No effort when reasoning is off
    if mode == "off":
        effort = None

    # Mutex: tools win
    if tools.exclusive_with_reasoning and tools_enabled and mode == "on":
        mode = "off"
        effort = None

    return ChatSessionExtras(
        tools_enabled=tools_enabled,
        reasoning_mode=mode,
        reasoning_effort=effort,
    )


def default_extras_for_capability(
    reasoning: ReasoningCapability,
    tools: ToolCapability,
) -> ChatSessionExtras:
    """Spec §4.5 — initial defaults for a fresh chat session given the model's capability.

    Rules:
      - ``no_reasoning``  → reasoning off; tools follow ``tools.supported``.
      - ``always_on``     → reasoning on (effort = default bucket if present);
        tools on iff supported AND the capability has no tools/reasoning mutex.
      - ``optional``      → if a mutex applies, default to tools-on /
        reasoning-off (tools win the conflict, mirroring §6.5). Without a
        mutex: both on (reasoning at default bucket if present).

    Effort always falls back to ``None`` when reasoning is off or the
    capability does not declare an effort spec.
    """
    has_mutex = tools.exclusive_with_reasoning
    tools_supported = tools.supported
    kind = reasoning.kind

    if kind == "no_reasoning":
        return ChatSessionExtras(
            tools_enabled=tools_supported,
            reasoning_mode="off",
            reasoning_effort=None,
        )

    if kind == "always_on":
        effort = reasoning.effort.default_bucket if reasoning.effort else None
        return ChatSessionExtras(
            tools_enabled=tools_supported and not has_mutex,
            reasoning_mode="on",
            reasoning_effort=effort,
        )

    # optional
    if has_mutex:
        return ChatSessionExtras(
            tools_enabled=tools_supported,
            reasoning_mode="off",
            reasoning_effort=None,
        )

    effort = reasoning.effort.default_bucket if reasoning.effort else None
    return ChatSessionExtras(
        tools_enabled=tools_supported,
        reasoning_mode="on",
        reasoning_effort=effort,
    )
