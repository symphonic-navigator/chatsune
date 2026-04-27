"""HTTP handlers for invitation tokens.

Three endpoints (this task adds the first):
- POST /api/admin/invitations         (admin-only, generate fresh token)
- POST /api/invitations/{t}/validate  (public, check status)         [Task 5]
- POST /api/invitations/{t}/register  (public, atomic register)       [Task 6]
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from backend.database import get_db
from backend.dependencies import require_admin
from backend.modules.user._audit import AuditRepository
from backend.modules.user._invitation_repository import InvitationRepository
from backend.ws.event_bus import EventBus, get_event_bus
from shared.dtos.invitation import CreateInvitationResponseDto
from shared.events.auth import InvitationCreatedEvent
from shared.events.audit import AuditLoggedEvent
from shared.topics import Topics

router = APIRouter(prefix="/api")


def _invitation_repo() -> InvitationRepository:
    return InvitationRepository(get_db())


def _audit_repo() -> AuditRepository:
    return AuditRepository(get_db())


@router.post(
    "/admin/invitations",
    status_code=201,
    response_model=CreateInvitationResponseDto,
)
async def create_invitation(
    user: dict = Depends(require_admin),
    event_bus: EventBus = Depends(get_event_bus),
) -> CreateInvitationResponseDto:
    repo = _invitation_repo()
    doc = await repo.create(created_by=user["sub"], ttl_hours=24)

    audit = _audit_repo()
    await audit.log(
        actor_id=user["sub"],
        action="user.invitation_created",
        resource_type="invitation",
        resource_id=str(doc["_id"]),
        detail={},
    )
    await event_bus.publish(
        Topics.INVITATION_CREATED,
        InvitationCreatedEvent(
            token_id=str(doc["_id"]),
            actor_id=user["sub"],
            expires_at=doc["expires_at"],
        ),
    )
    await event_bus.publish(
        Topics.AUDIT_LOGGED,
        AuditLoggedEvent(
            actor_id=user["sub"],
            action="user.invitation_created",
            resource_type="invitation",
            resource_id=str(doc["_id"]),
            detail={},
        ),
    )

    return CreateInvitationResponseDto(token=doc["token"], expires_at=doc["expires_at"])
