"""REST endpoints for the integrations module."""

import logging
from datetime import datetime, timezone
from typing import Awaitable, Callable, TypeVar

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from backend._retry import execute_with_retry
from backend.dependencies import require_active_session
from backend.modules.integrations._registry import get_all, get as get_definition
from backend.modules.integrations._repository import IntegrationRepository
from backend.modules.integrations._voice_adapters import (
    get_adapter,
    VoiceAdapterError,
    VoiceRateLimitError,
    VoiceUnavailableError,
)
# Deferred at call site to break the __init__ → _handlers → __init__ circular import.
from backend.database import get_db
from backend.ws.event_bus import get_event_bus
from shared.dtos.integrations import (
    IntegrationCapability,
    IntegrationDefinitionDto,
    IntegrationConfigFieldDto,
    UserIntegrationConfigDto,
)
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
            linked_premium_provider=d.linked_premium_provider,
            assignable=d.assignable,
        )
        for d in defs.values()
    ]


@router.get("/configs")
async def list_user_configs(
    user: dict = Depends(require_active_session),
) -> list[UserIntegrationConfigDto]:
    """Return all integration configs for the current user.

    Each returned DTO carries ``effective_enabled`` — the authoritative
    "is this integration usable" flag derived from
    :func:`effective_enabled_map`. For integrations linked to a Premium
    Provider Account (``xai_voice``, ``mistral_voice``), there is usually
    no ``user_integration_configs`` document, yet the integration is
    effectively enabled as soon as the Premium account exists. We emit a
    synthetic DTO for those cases so the frontend store has an entry
    keyed by the integration id (otherwise voice-provider dropdowns and
    engine-readiness checks, which look up ``configs[integration_id]``,
    find nothing and treat the integration as disabled).
    """
    # Local import to avoid circular: backend.modules.integrations
    # imports from _handlers at module init.
    from backend.modules.integrations import effective_enabled_map

    repo = _repo()
    docs = await repo.get_user_configs(user["sub"])
    effective_map = await effective_enabled_map(user["sub"])

    result: list[UserIntegrationConfigDto] = []
    seen: set[str] = set()
    for d in docs:
        iid = d["integration_id"]
        seen.add(iid)
        result.append(
            UserIntegrationConfigDto(
                **d,
                effective_enabled=effective_map.get(iid, False),
            )
        )
    # Synthetic entries for integrations that are effectively enabled but
    # have no stored config document (the common case for linked premium
    # integrations — there is no UI to create a config row, so the doc
    # never exists even though the integration is usable).
    for iid, on in effective_map.items():
        if on and iid not in seen:
            result.append(
                UserIntegrationConfigDto(
                    integration_id=iid,
                    enabled=False,
                    config={},
                    effective_enabled=True,
                )
            )
    return result


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

    # Derive effective_enabled from the authoritative map, not doc["enabled"] —
    # for linked integrations the stored flag is meaningless; effective state
    # depends on the Premium Provider Account's presence.
    from backend.modules.integrations import is_effective_enabled
    effective = await is_effective_enabled(user["sub"], integration_id)
    return UserIntegrationConfigDto(**doc, effective_enabled=effective)


async def load_api_key_for(user_id: str, integration_id: str) -> str | None:
    """Return the decrypted API key for (user, integration), or None if the
    integration is not configured or not enabled for this user.

    For integrations linked to a Premium Provider Account (e.g. ``xai_voice``
    → ``xai``), the key is resolved against the user's Premium Provider
    store. Otherwise we fall back to the legacy per-integration secret
    store.
    """
    definition = get_definition(integration_id)
    if definition is not None and definition.linked_premium_provider:
        from backend.modules.providers import PremiumProviderService
        from backend.modules.providers._repository import (
            PremiumProviderAccountRepository,
        )
        svc = PremiumProviderService(PremiumProviderAccountRepository(get_db()))
        return await svc.get_decrypted_secret(
            user_id, definition.linked_premium_provider, "api_key",
        )
    repo = _repo()
    pairs = await repo.list_enabled_with_secrets(user_id)
    for iid, secrets in pairs:
        if iid == integration_id:
            return secrets.get("api_key")
    return None


def _voice_error_response(exc: VoiceAdapterError) -> JSONResponse:
    code = type(exc).__name__.removesuffix("Error").removeprefix("Voice").lower() or "error"
    return JSONResponse(
        status_code=exc.http_status,
        content={"error_code": f"voice_{code}", "message": exc.user_message},
    )


# Voice retry policy lives in :mod:`backend._retry` and is shared with
# the LLM adapters: 4 retries with exponential back-off (1s, 2s, 4s, 8s
# ±25 % jitter, capped at 16 s) on rate-limit (429) and upstream-
# unavailable (5xx) errors. Auth, bad-request, and unexpected-status
# errors still bubble up on the first try — they are not transient.
_VOICE_TRANSIENT_ERRORS: tuple[type[VoiceAdapterError], ...] = (
    VoiceRateLimitError,
    VoiceUnavailableError,
)


def _voice_is_retriable(exc: BaseException) -> bool:
    return isinstance(exc, _VOICE_TRANSIENT_ERRORS)


T = TypeVar("T")


async def _with_transient_retry(
    operation: str,
    integration_id: str,
    fn: Callable[[], Awaitable[T]],
) -> T:
    """Execute ``fn`` with exponential back-off on transient voice errors.

    Retries on :class:`VoiceRateLimitError` (HTTP 429) and
    :class:`VoiceUnavailableError` (HTTP 5xx). Auth, bad-request, and
    unexpected-status errors bubble up on the first try.

    The helper lives in the handler layer (not the adapters) so every
    adapter — xAI, Mistral, and any future one — benefits uniformly
    without each implementation having to remember to retry. After all
    retries are exhausted the original exception bubbles up unchanged
    (the proxy route then maps it to the right HTTP status).
    """
    return await execute_with_retry(
        fn,
        is_retriable=_voice_is_retriable,
        operation_name=f"voice.{operation}",
        logger=_log,
        correlation_id=integration_id,
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
        voices = await _with_transient_retry(
            "list_voices", integration_id,
            lambda: adapter.list_voices(api_key),
        )
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
    # Read the upload eagerly so we have immutable bytes to pass on retry.
    # The UploadFile's underlying SpooledTemporaryFile would be at EOF on a
    # second read without an explicit seek, which we avoid by staying in
    # the local ``audio_bytes`` buffer for both attempts.
    audio_bytes = await audio.read()
    content_type = audio.content_type or "audio/wav"
    try:
        text = await _with_transient_retry(
            "transcribe", integration_id,
            lambda: adapter.transcribe(
                audio=audio_bytes, content_type=content_type,
                api_key=api_key, language=language,
            ),
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
        audio_bytes, content_type = await _with_transient_retry(
            "synthesise", integration_id,
            lambda: adapter.synthesise(
                text=body.text, voice_id=body.voice_id, api_key=api_key,
            ),
        )
    except VoiceAdapterError as e:
        return _voice_error_response(e)
    return Response(content=audio_bytes, media_type=content_type)


def _require_cloning_support(integration_id: str) -> None:
    """Return None if the integration declares TTS_VOICE_CLONING, else raise 400.

    We check the declared capability rather than probing the adapter; the
    adapter's default ``clone_voice`` / ``delete_voice`` raise
    ``NotImplementedError`` which we also map to 400 below as a safety net.
    """
    definition = get_definition(integration_id)
    if definition is None:
        raise HTTPException(status_code=404, detail=f"Unknown integration: {integration_id}")
    if IntegrationCapability.TTS_VOICE_CLONING not in definition.capabilities:
        raise HTTPException(
            status_code=400,
            detail="Integration does not support voice cloning",
        )


@router.post("/{integration_id}/voice/clone")
async def voice_clone(
    integration_id: str,
    audio: UploadFile = File(...),
    name: str = Form(...),
    user: dict = Depends(require_active_session),
):
    _require_cloning_support(integration_id)
    api_key = await load_api_key_for(user["sub"], integration_id)
    if api_key is None:
        raise HTTPException(status_code=400, detail="Integration not enabled or no API key configured")
    adapter = get_adapter(integration_id)
    if adapter is None:
        raise HTTPException(status_code=400, detail="Integration is not backend-proxied")
    # Same reasoning as voice_stt: read once, retry from the buffer.
    audio_bytes = await audio.read()
    content_type = audio.content_type or "audio/wav"
    try:
        voice = await _with_transient_retry(
            "clone_voice", integration_id,
            lambda: adapter.clone_voice(
                audio=audio_bytes, content_type=content_type,
                name=name, api_key=api_key,
            ),
        )
    except NotImplementedError:
        raise HTTPException(status_code=400, detail="Adapter does not support voice cloning")
    except VoiceAdapterError as e:
        return _voice_error_response(e)
    return voice.model_dump()


@router.delete("/{integration_id}/voice/voices/{voice_id}", status_code=204)
async def voice_delete(
    integration_id: str,
    voice_id: str,
    user: dict = Depends(require_active_session),
):
    _require_cloning_support(integration_id)
    api_key = await load_api_key_for(user["sub"], integration_id)
    if api_key is None:
        raise HTTPException(status_code=400, detail="Integration not enabled or no API key configured")
    adapter = get_adapter(integration_id)
    if adapter is None:
        raise HTTPException(status_code=400, detail="Integration is not backend-proxied")
    try:
        await _with_transient_retry(
            "delete_voice", integration_id,
            lambda: adapter.delete_voice(voice_id=voice_id, api_key=api_key),
        )
    except NotImplementedError:
        raise HTTPException(status_code=400, detail="Adapter does not support voice cloning")
    except VoiceAdapterError as e:
        return _voice_error_response(e)
    return Response(status_code=204)
