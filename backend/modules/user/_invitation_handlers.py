"""HTTP handlers for invitation tokens.

Three endpoints:
- POST /api/admin/invitations         (admin-only, generate fresh token)
- POST /api/invitations/{t}/validate  (public, check status)         [Task 5]
- POST /api/invitations/{t}/register  (public, atomic register)       [Task 6]
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pymongo.errors import DuplicateKeyError, OperationFailure

from backend.database import get_client, get_db, get_redis
from backend.dependencies import require_admin
from backend.modules.user._audit import AuditRepository
from backend.modules.user._handlers import _provision_new_user
from backend.modules.user._invitation_repository import InvitationRepository
from backend.modules.user._key_service import UserKeyService
from backend.modules.user._repository import UserRepository
from backend.ws.event_bus import EventBus, get_event_bus
from shared.dtos.invitation import (
    CreateInvitationResponseDto,
    RegisterViaInvitationRequestDto,
    RegisterViaInvitationResponseDto,
    ValidateInvitationResponseDto,
)
from shared.events.auth import InvitationCreatedEvent, InvitationUsedEvent
from shared.events.audit import AuditLoggedEvent
from shared.topics import Topics

_log = logging.getLogger(__name__)

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


@router.post(
    "/invitations/{token}/validate",
    status_code=200,
    response_model=ValidateInvitationResponseDto,
)
async def validate_invitation(token: str) -> ValidateInvitationResponseDto:
    """Public: tells the frontend whether to render the registration form.

    Always returns HTTP 200. Reason lives in body to prevent enumeration
    via response codes.
    """
    repo = _invitation_repo()
    doc = await repo.find_by_token(token)
    if doc is None:
        return ValidateInvitationResponseDto(valid=False, reason="not_found")
    if doc["used"]:
        return ValidateInvitationResponseDto(valid=False, reason="used")
    if doc["expires_at"] < datetime.now(timezone.utc):
        return ValidateInvitationResponseDto(valid=False, reason="expired")
    return ValidateInvitationResponseDto(valid=True, reason=None)


@router.post(
    "/invitations/{token}/register",
    status_code=200,
    response_model=RegisterViaInvitationResponseDto,
)
async def register_via_invitation(
    token: str,
    body: RegisterViaInvitationRequestDto,
    event_bus: EventBus = Depends(get_event_bus),
) -> RegisterViaInvitationResponseDto:
    """Atomically validate-and-consume the token, create the user, provision keys.

    Returns 410 if the token is consumed/expired/unknown. Returns 409 on
    username/email collision (and rolls back the token mark so it stays
    usable). Returns 200 with the new ``user_id`` on success — there is
    NO auto-login; the user navigates to /login themselves.

    The token mark-used and the user/key provisioning all run inside a
    single MongoDB transaction so that any failure during user creation
    leaves the token unused and re-usable. Audit and event publication
    happen *after* the transaction commits — they are best-effort
    observability and must not roll back a successful registration.
    """
    db = get_db()
    repo = InvitationRepository(db)
    users_repo = UserRepository(db)
    svc = UserKeyService(db=db, redis=get_redis())

    client = get_client()
    user_id: str | None = None
    token_id: str | None = None

    # Retry loop for TransientTransactionError (e.g. WriteConflict when two
    # registrations race for the same token). On retry the second attempt
    # will see ``used: True`` from the winner's commit and short-circuit
    # to 410 — exactly the desired loser-gets-Gone behaviour.
    max_retries = 3
    for attempt in range(max_retries):
        try:
            async with await client.start_session() as session:
                async with session.start_transaction():
                    # Atomic validate-and-consume. Returns None for
                    # used/expired/unknown. The placeholder used_by_user_id
                    # is patched below once we know the real id — kept
                    # inside the same transaction so an outside reader
                    # never observes the placeholder value.
                    marked = await repo.mark_used_atomic(
                        token,
                        used_by_user_id="pending",
                        session=session,
                    )
                    if marked is None:
                        raise HTTPException(
                            status_code=410, detail="invitation_invalid",
                        )

                    try:
                        user_doc, _dek = await _provision_new_user(
                            users_repo=users_repo,
                            svc=svc,
                            username=body.username,
                            email=body.email,
                            display_name=body.display_name,
                            h_auth=body.h_auth,
                            h_kek=body.h_kek,
                            recovery_key=body.recovery_key,
                            role="user",
                            must_change_password=False,
                            session=session,
                        )
                    except DuplicateKeyError:
                        # Aborts the transaction — the mark-used write is
                        # rolled back and the token remains usable. Surface
                        # as 409 to the client.
                        raise HTTPException(
                            status_code=409,
                            detail="username_or_email_taken",
                        )

                    user_id = str(user_doc["_id"])
                    token_id = str(marked["_id"])

                    # Patch the token doc with the real user id, still in-tx.
                    await db["invitation_tokens"].update_one(
                        {"_id": marked["_id"]},
                        {"$set": {"used_by_user_id": user_id}},
                        session=session,
                    )
            break  # success — leave the retry loop
        except OperationFailure as exc:
            # MongoDB tags retriable transaction failures with the
            # ``TransientTransactionError`` label. Anything else is fatal.
            if "TransientTransactionError" in (exc.details or {}).get(
                "errorLabels", []
            ) and attempt < max_retries - 1:
                _log.info(
                    "invitation.register.transient_retry token=%s attempt=%d",
                    token, attempt + 1,
                )
                continue
            raise

    # Outside the transaction — best-effort audit and event publication.
    audit = AuditRepository(db)
    try:
        await audit.log(
            actor_id=user_id,
            action="user.invitation_used",
            resource_type="invitation",
            resource_id=token_id,
            detail={},
        )
    except Exception:
        _log.warning(
            "invitation.register.audit_failed user_id=%s token_id=%s",
            user_id, token_id, exc_info=True,
        )

    await event_bus.publish(
        Topics.INVITATION_USED,
        InvitationUsedEvent(token_id=token_id, used_by_user_id=user_id),
    )
    await event_bus.publish(
        Topics.AUDIT_LOGGED,
        AuditLoggedEvent(
            actor_id=user_id,
            action="user.invitation_used",
            resource_type="invitation",
            resource_id=token_id,
            detail={},
        ),
    )

    return RegisterViaInvitationResponseDto(success=True, user_id=user_id)
