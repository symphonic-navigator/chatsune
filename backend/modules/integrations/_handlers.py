"""REST endpoints for the integrations module."""

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from backend.dependencies import require_active_session
from backend.modules.integrations._registry import get_all, get as get_definition
from backend.modules.integrations._repository import IntegrationRepository
from backend.modules.integrations._voice_adapters import (
    get_adapter,
    VoiceAdapterError,
)
# Deferred at call site to break the __init__ → _handlers → __init__ circular import.
from backend.database import get_db
from backend.ws.event_bus import get_event_bus
from shared.dtos.integrations import IntegrationDefinitionDto, IntegrationConfigFieldDto, UserIntegrationConfigDto
from shared.events.integrations import IntegrationConfigUpdatedEvent
from shared.topics import Topics

_log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/integrations", tags=["integrations"])


def _repo() -> IntegrationRepository:
    return IntegrationRepository(get_db())


@router.get("/definitions")
async def list_definitions(
    _user: dict = Depends(require_active_session),
) -> list[IntegrationDefinitionDto]:
    """Return all available integration definitions."""
    defs = get_all()
    return [
        IntegrationDefinitionDto(
            id=d.id,
            display_name=d.display_name,
            description=d.description,
            icon=d.icon,
            execution_mode=d.execution_mode,
            config_fields=[IntegrationConfigFieldDto(**f) for f in d.config_fields],
            has_tools=len(d.tool_definitions) > 0,
            has_response_tags=bool(d.response_tag_prefix),
            has_prompt_extension=bool(d.system_prompt_template),
            capabilities=[c.value for c in d.capabilities],
            persona_config_fields=[IntegrationConfigFieldDto(**f) for f in d.persona_config_fields],
            hydrate_secrets=d.hydrate_secrets,
        )
        for d in defs.values()
    ]


@router.get("/configs")
async def list_user_configs(
    user: dict = Depends(require_active_session),
) -> list[UserIntegrationConfigDto]:
    """Return all integration configs for the current user."""
    repo = _repo()
    docs = await repo.get_user_configs(user["sub"])
    return [UserIntegrationConfigDto(**d) for d in docs]


class _UpsertBody(BaseModel):
    enabled: bool
    config: dict = {}


class _VoiceTtsBody(BaseModel):
    text: str
    voice_id: str


@router.put("/configs/{integration_id}")
async def upsert_config(
    integration_id: str,
    body: _UpsertBody,
    user: dict = Depends(require_active_session),
) -> UserIntegrationConfigDto:
    """Create or update a user's integration config."""
    definition = get_definition(integration_id)
    if definition is None:
        raise HTTPException(status_code=404, detail=f"Unknown integration: {integration_id}")

    repo = _repo()
    doc = await repo.upsert_config(user["sub"], integration_id, body.enabled, body.config)

    event_bus = get_event_bus()
    await event_bus.publish(
        Topics.INTEGRATION_CONFIG_UPDATED,
        IntegrationConfigUpdatedEvent(
            integration_id=integration_id,
            enabled=body.enabled,
            correlation_id=f"int-config-{integration_id}",
            timestamp=datetime.now(timezone.utc),
        ),
        scope=f"user:{user['sub']}",
        target_user_ids=[user["sub"]],
        correlation_id=f"int-config-{integration_id}",
    )

    has_secret_fields = any(f.get("secret") for f in (definition.config_fields if definition else []))
    if body.enabled and has_secret_fields:
        from backend.modules.integrations import emit_integration_secrets_for_user
        await emit_integration_secrets_for_user(
            user_id=user["sub"], db=get_db(), event_bus=event_bus,
        )
    elif not body.enabled and has_secret_fields:
        from backend.modules.integrations import emit_integration_secrets_cleared
        await emit_integration_secrets_cleared(
            user_id=user["sub"],
            integration_id=integration_id,
            event_bus=event_bus,
        )

    return UserIntegrationConfigDto(**doc)


async def load_api_key_for(user_id: str, integration_id: str) -> str | None:
    """Return the decrypted API key for (user, integration), or None if the
    integration is not configured or not enabled for this user."""
    repo = _repo()
    pairs = await repo.list_enabled_with_secrets(user_id)
    for iid, secrets in pairs:
        if iid == integration_id:
            key = secrets.get("api_key")
            if key is not None:
                # Diagnostic — debugging xAI auth rejection. Logs only a short
                # prefix + length, never the full key. Remove once the xAI
                # auth flow is confirmed stable.
                masked = f"{key[:4]}…{key[-2:]}" if len(key) > 8 else "(short)"
                _log.info(
                    "voice.load_api_key integration=%s len=%d prefix/suffix=%s",
                    integration_id, len(key), masked,
                )
            return key
    return None


def _voice_error_response(exc: VoiceAdapterError) -> JSONResponse:
    code = type(exc).__name__.removesuffix("Error").removeprefix("Voice").lower() or "error"
    return JSONResponse(
        status_code=exc.http_status,
        content={"error_code": f"voice_{code}", "message": exc.user_message},
    )


@router.get("/{integration_id}/voice/voices")
async def voice_list_voices(
    integration_id: str,
    user: dict = Depends(require_active_session),
):
    api_key = await load_api_key_for(user["sub"], integration_id)
    if api_key is None:
        raise HTTPException(status_code=404, detail="Integration not enabled")
    adapter = get_adapter(integration_id)
    if adapter is None:
        raise HTTPException(status_code=400, detail="Integration is not backend-proxied")
    try:
        voices = await adapter.list_voices(api_key)
    except VoiceAdapterError as e:
        return _voice_error_response(e)
    return {"voices": [v.model_dump() for v in voices]}


@router.post("/{integration_id}/voice/stt")
async def voice_stt(
    integration_id: str,
    audio: UploadFile = File(...),
    language: str | None = Form(None),
    user: dict = Depends(require_active_session),
):
    api_key = await load_api_key_for(user["sub"], integration_id)
    if api_key is None:
        raise HTTPException(status_code=404, detail="Integration not enabled")
    adapter = get_adapter(integration_id)
    if adapter is None:
        raise HTTPException(status_code=400, detail="Integration is not backend-proxied")
    audio_bytes = await audio.read()
    content_type = audio.content_type or "audio/wav"
    try:
        text = await adapter.transcribe(
            audio=audio_bytes, content_type=content_type,
            api_key=api_key, language=language,
        )
    except VoiceAdapterError as e:
        return _voice_error_response(e)
    return {"text": text}


@router.post("/{integration_id}/voice/tts")
async def voice_tts(
    integration_id: str,
    body: _VoiceTtsBody,
    user: dict = Depends(require_active_session),
):
    api_key = await load_api_key_for(user["sub"], integration_id)
    if api_key is None:
        raise HTTPException(status_code=404, detail="Integration not enabled")
    adapter = get_adapter(integration_id)
    if adapter is None:
        raise HTTPException(status_code=400, detail="Integration is not backend-proxied")
    try:
        audio_bytes, content_type = await adapter.synthesise(
            text=body.text, voice_id=body.voice_id, api_key=api_key,
        )
    except VoiceAdapterError as e:
        return _voice_error_response(e)
    return Response(content=audio_bytes, media_type=content_type)
