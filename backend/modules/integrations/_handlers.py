"""REST endpoints for the integrations module."""

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from backend.dependencies import require_active_session
from backend.modules.integrations._registry import get_all, get as get_definition
from backend.modules.integrations._repository import IntegrationRepository
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
        )
        for d in defs.values()
    ]


@router.get("/configs")
async def list_user_configs(
    user: dict = Depends(require_active_session),
) -> list[UserIntegrationConfigDto]:
    """Return all integration configs for the current user."""
    repo = _repo()
    docs = await repo.get_user_configs(user["_id"])
    return [UserIntegrationConfigDto(**d) for d in docs]


class _UpsertBody(BaseModel):
    enabled: bool
    config: dict = {}


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
    doc = await repo.upsert_config(user["_id"], integration_id, body.enabled, body.config)

    event_bus = get_event_bus()
    await event_bus.publish(
        Topics.INTEGRATION_CONFIG_UPDATED,
        IntegrationConfigUpdatedEvent(
            integration_id=integration_id,
            enabled=body.enabled,
            correlation_id=f"int-config-{integration_id}",
            timestamp=datetime.now(timezone.utc),
        ),
        scope=f"user:{user['_id']}",
        target_user_ids=[user["_id"]],
        correlation_id=f"int-config-{integration_id}",
    )

    return UserIntegrationConfigDto(**doc)
