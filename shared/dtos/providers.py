"""Shared DTOs for the Premium Provider Accounts module."""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field


class Capability(str, Enum):
    LLM = "llm"
    TTS = "tts"
    STT = "stt"
    WEBSEARCH = "websearch"
    TTI = "tti"
    ITI = "iti"


CAPABILITY_META: dict[Capability, dict[str, str]] = {
    Capability.LLM: {
        "label": "Text",
        "tooltip": "Provides chat models you can pick for any persona.",
    },
    Capability.TTS: {
        "label": "TTS",
        "tooltip": "Synthesises persona replies into speech for voice chats.",
    },
    Capability.STT: {
        "label": "STT",
        "tooltip": "Transcribes your voice input into text for the chat.",
    },
    Capability.WEBSEARCH: {
        "label": "Web search",
        "tooltip": "Provides web search during chats, regardless of which model you use.",
    },
    Capability.TTI: {
        "label": "Text to Image",
        "tooltip": "Creates images from a text prompt during chats.",
    },
    Capability.ITI: {
        "label": "Image to Image",
        "tooltip": "Edits or transforms an uploaded image based on a prompt.",
    },
}


class PremiumProviderDefinitionDto(BaseModel):
    """Static catalogue entry — sent to frontend at /api/providers/catalogue."""
    id: str
    display_name: str
    icon: str
    base_url: str
    capabilities: list[Capability]
    config_fields: list[dict[str, Any]]
    linked_integrations: list[str] = Field(default_factory=list)


class PremiumProviderAccountDto(BaseModel):
    """User-owned account — secrets redacted."""
    provider_id: str
    config: dict[str, Any]
    last_test_status: str | None
    last_test_error: str | None
    last_test_at: datetime | None


class PremiumProviderUpsertRequest(BaseModel):
    """Request body for POST/PUT /api/providers/{provider_id}."""
    config: dict[str, Any]


class PremiumProviderTestResultDto(BaseModel):
    """Response for the /test endpoint."""
    status: Literal["ok", "error"]
    error: str | None
