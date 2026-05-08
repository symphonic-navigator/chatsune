from typing import Literal

from pydantic import BaseModel


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
    reasoning_enabled: bool = False
    supports_reasoning: bool = False  # model capability — adapter uses this to decide whether to send think param
    cache_hint: str | None = None     # provider-specific cache locality hint (e.g. session UUID for x-grok-conv-id)
    # Anthropic prompt-cache TTL — only honoured by the OpenRouter and
    # nano-gpt adapters when the model is a Claude family member.
    # Other adapters and non-Anthropic routes ignore the field. Default
    # ``"off"`` keeps existing call-sites and tests behaviourally
    # unchanged. See devdocs/specs/2026-05-08-claude-router-cache-breakpoints-design.md.
    anthropic_cache_ttl: Literal["off", "5m", "1h"] = "off"
