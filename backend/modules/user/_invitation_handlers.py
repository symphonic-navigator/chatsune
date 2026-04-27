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
from pymongo.errors import DuplicateKeyError

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
from shared.events.auth import (
    InvitationCreatedEvent,
    InvitationUsedEvent,
    UserCreatedEvent,
)
from shared.events.audit import AuditLoggedEvent
from shared.events.user_keys import UserKeyProvisionedEvent
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

    # We use ``session.with_transaction(callback)`` rather than a
    # hand-rolled retry loop because it correctly handles BOTH retry
    # semantics defined by the MongoDB driver spec:
    #   * ``TransientTransactionError``      → retry the whole callback
    #   * ``UnknownTransactionCommitResult`` → retry the commit
    # A naive ``async with session.start_transaction()`` plus a
    # try/except on ``OperationFailure`` only covers the first label
    # and silently drops commit-time network blips.
    async with await client.start_session() as session:
        async def _txn(s):
            # Atomic validate-and-consume. Returns None for
            # used/expired/unknown. The placeholder used_by_user_id
            # is patched below once we know the real id — kept
            # inside the same transaction so an outside reader
            # never observes the placeholder value.
            marked = await repo.mark_used_atomic(
                token,
                used_by_user_id="pending",
                session=s,
            )
            if marked is None:
                _log.info("invitation.register.rejected reason=token_invalid")
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
                    session=s,
                )
            except DuplicateKeyError:
                # Aborts the transaction — the mark-used write is
                # rolled back and the token remains usable. Surface
                # as 409 to the client.
                _log.info("invitation.register.rejected reason=user_collision")
                raise HTTPException(
                    status_code=409,
                    detail="username_or_email_taken",
                )

            new_user_id = str(user_doc["_id"])

            # Patch the token doc with the real user id, still in-tx.
            await db["invitation_tokens"].update_one(
                {"_id": marked["_id"]},
                {"$set": {"used_by_user_id": new_user_id}},
                session=s,
            )
            return user_doc, str(marked["_id"])

        user_doc, token_id = await session.with_transaction(_txn)

    user_id = str(user_doc["_id"])
    _log.info(
        "invitation.register.consumed token_id=%s user_id=%s", token_id, user_id,
    )

    # Outside the transaction — best-effort audit and event publication.
    # The transaction has already committed: the user exists and the
    # token is consumed. A Redis hiccup or audit-write failure must
    # NOT translate into a 500 for the client, because they cannot
    # recover (the token is gone). Wrap the entire observability block
    # in one try/except that logs but does not raise.
    try:
        audit = AuditRepository(db)
        await audit.log(
            actor_id=user_id,
            action="user.invitation_used",
            resource_type="invitation",
            resource_id=token_id,
            detail={},
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
        # Mirror the /auth/setup contract: a freshly created user must
        # be visible to admins immediately (USER_CREATED, fan-out, no
        # target_user_ids) and the user themselves must learn that
        # their key material is ready (USER_KEY_PROVISIONED, targeted).
        await event_bus.publish(
            Topics.USER_CREATED,
            UserCreatedEvent(
                user_id=user_id,
                username=user_doc["username"],
                role="user",
                timestamp=user_doc["created_at"],
            ),
        )
        await event_bus.publish(
            Topics.USER_KEY_PROVISIONED,
            UserKeyProvisionedEvent(user_id=user_id, reason="signup"),
            target_user_ids=[user_id],
        )
    except Exception:
        _log.exception(
            "invitation.register.post_commit_failed user_id=%s token_id=%s",
            user_id, token_id,
        )

    return RegisterViaInvitationResponseDto(success=True, user_id=user_id)
