from datetime import datetime

from pydantic import BaseModel, Field


class PersonaDocument(BaseModel):
    """Internal MongoDB document model for personas. Never expose outside persona module."""

    id: str = Field(alias="_id")
    user_id: str
    name: str
    tagline: str
    model_unique_id: str | None = None
    system_prompt: str
    temperature: float
    reasoning_enabled: bool
    soft_cot_enabled: bool = False
    vision_fallback_model: str | None = None
    nsfw: bool
    use_memory: bool = True
    colour_scheme: str
    display_order: int
    monogram: str
    pinned: bool
    profile_image: str | None
    profile_crop: dict | None = None
    mcp_config: dict | None = None
    # voice_config keys:
    #   auto_read: bool — auto-play assistant messages through active TTS
    #   roleplay_mode: bool — split dialogue vs narrator (feature not yet active)
    # Legacy keys (dialogue_voice, narrator_voice) are ignored at read time;
    # voice selection now lives in integration_configs[tts_integration_id].voice_id.
    voice_config: dict | None = None
    integration_configs: dict[str, dict] = Field(default_factory=dict)
    # Persona-scoped allowlist of integrations the persona has opted into.
    # Stored as a loose dict ({"enabled_integration_ids": [...]}), parsed
    # into ``PersonaIntegrationConfigDto`` at the DTO boundary.
    integrations_config: dict | None = None
    created_at: datetime
    updated_at: datetime
    # Most recent chat-session creation or resume. Drives sidebar LRU
    # ordering. None when the persona has never been chatted with — in
    # that case sort falls back to created_at descending.
    last_used_at: datetime | None = None
    # Mindspace: optional default project for new chats started from a
    # neutral trigger point (sidebar pin click, persona overview, etc.).
    # ``None`` means "no default" — chats land in the global / no-project
    # bucket. Pre-Mindspace personas lack the field entirely and read
    # back as ``None``.
    default_project_id: str | None = None

    model_config = {"populate_by_name": True}
