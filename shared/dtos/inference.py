from typing import Literal

from pydantic import BaseModel, Field

from shared.dtos.chat import ChatSessionExtras
from shared.dtos.llm import ReasoningCapability, ToolCapability


class ContentPart(BaseModel):
    type: Literal["text", "image"]
    text: str | None = None
    data: str | None = None          # base64-encoded bytes for image parts
    media_type: str | None = None    # e.g. "image/png"


class ToolCallResult(BaseModel):
    id: str
    name: str
    arguments: str                   # JSON-encoded string of tool arguments


class CompletionMessage(BaseModel):
    role: Literal["system", "user", "assistant", "tool"]
    content: list[ContentPart]
    tool_calls: list[ToolCallResult] | None = None
    tool_call_id: str | None = None  # required for role="tool" messages


class ToolDefinition(BaseModel):
    type: Literal["function"] = "function"
    name: str
    description: str
    parameters: dict                 # JSON Schema object describing tool parameters


class CompletionRequest(BaseModel):
    model: str                       # provider-specific model slug
    messages: list[CompletionMessage]
    temperature: float | None = None
    tools: list[ToolDefinition] | None = None
    # Capability + extras model — replaces reasoning_enabled and supports_reasoning.
    # Adapter reads (reasoning, extras) and translates to provider-specific request shapes.
    reasoning: ReasoningCapability
    tools_capability: ToolCapability
    extras: ChatSessionExtras = Field(
        default_factory=lambda: ChatSessionExtras(
            tools_enabled=False, reasoning_mode="off", reasoning_effort=None
        )
    )
    cache_hint: str | None = None     # provider-specific cache locality hint (e.g. session UUID for x-grok-conv-id)
    # Anthropic prompt-cache TTL — only honoured by the OpenRouter and
    # nano-gpt adapters when the model is a Claude family member.
    # Other adapters and non-Anthropic routes ignore the field. Default
    # ``"5m"`` matches the persona-level default; existing call-sites
    # always pass an explicit value resolved from the persona, so this
    # default is only the fallback for ad-hoc callers (e.g. the LLM test
    # harness). See devdocs/specs/2026-05-08-claude-router-cache-breakpoints-design.md.
    anthropic_cache_ttl: Literal["off", "5m", "1h"] = "5m"
    # Position (0-based index into ``messages``) of the first tail message
    # after a compaction. When set, the Anthropic-cache marker strategy
    # places its 2nd marker here instead of at the heuristic block boundary,
    # so the System + Compact-Anchor prefix is held in cache for 1h between
    # turns of an unchanged checkpoint.
    compact_anchor_index: int | None = None
