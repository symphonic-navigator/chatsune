import base64
import os
from datetime import datetime, timezone

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Cookie,
    Depends,
    HTTPException,
    Request,
    Response,
)

from backend.config import settings
from backend.database import get_db, get_redis
from backend.dependencies import get_current_user, require_admin, require_active_session
from backend.ws.event_bus import EventBus, get_event_bus
from backend.modules.user._auth import (
    create_access_token,
    generate_random_password,
    generate_refresh_token,
    generate_session_id,
    hash_h_auth,
    hash_password,
    verify_h_auth,
    verify_password,
)
from backend.modules.user._models import Argon2Params
from backend.modules.user._recovery_key import generate_recovery_key
from backend.modules.user._key_service import DekUnlockError, UserKeyNotFoundError
from backend.modules.user._crypto import pseudo_salt_for_unknown_user
from backend.modules.user._key_service import UserKeyService
from backend.modules.user._audit import AuditRepository
from backend.modules.user._rate_limit import check_login_rate_limit, check_recovery_rate_limit, get_client_ip
from backend.modules.user._recovery_key import InvalidRecoveryKeyError
from backend.modules.user._refresh import RefreshTokenStore
from backend.modules.user._repository import UserRepository
from shared.dtos.mcp import McpGatewayConfigDto
from backend.modules.tools import invalidate_mcp_registries
from backend.modules.tools._namespace import normalise_namespace, validate_namespace
from shared.dtos.auth import (
    Argon2ParamsDto,
    ChangePasswordRequestDto,
    ChangePasswordRequestV2Dto,
    CreateUserRequestDto,
    CreateUserResponseDto,
    DeclineRecoveryRequestDto,
    DeleteAccountRequestDto,
    DeleteAccountResponseDto,
    KdfParamsRequestDto,
    KdfParamsResponseDto,
    LoginLegacyRequestDto,
    LoginLegacyResponseDto,
    LoginRequestDto,
    LoginRequestV2Dto,
    RecoverDekRequestDto,
    RecoveryRequiredResponseDto,
    ResetPasswordResponseDto,
    SetupRequestDto,
    SetupRequestV2Dto,
    SetupResponseDto,
    TokenResponseDto,
    UpdateAboutMeDto,
    UpdateDisplayNameDto,
    UpdateUserRequestDto,
    UserDto,
    AuditLogEntryDto,
    Role,
)
from shared.dtos.deletion import DeletionReportDto
from shared.events.auth import (
    UserCreatedEvent,
    UserDeactivatedEvent,
    UserDeletedEvent,
    UserPasswordResetEvent,
    UserUpdatedEvent,
    UserProfileUpdatedEvent,
)
from shared.events.user_keys import UserKeyProvisionedEvent, UserKeyRecoveredEvent, UserKeyRecoveryDeclinedEvent
from shared.events.audit import AuditLoggedEvent
from shared.topics import Topics

router = APIRouter(prefix="/api")


def _user_repo() -> UserRepository:
    return UserRepository(get_db())


def _audit_repo() -> AuditRepository:
    return AuditRepository(get_db())


def _refresh_store() -> RefreshTokenStore:
    return RefreshTokenStore(get_redis())


def _key_service() -> UserKeyService:
    return UserKeyService(db=get_db(), redis=get_redis())


def _set_refresh_cookie(response: Response, token: str) -> None:
    kwargs: dict = dict(
        key="refresh_token",
        value=token,
        httponly=True,
        secure=True,
        samesite="strict",
        max_age=settings.jwt_refresh_token_expire_days * 86400,
    )
    if settings.cookie_domain:
        kwargs["domain"] = settings.cookie_domain
    response.set_cookie(**kwargs)


def _clear_refresh_cookie(response: Response) -> None:
    kwargs: dict = dict(
        key="refresh_token", httponly=True, secure=True, samesite="strict"
    )
    if settings.cookie_domain:
        kwargs["domain"] = settings.cookie_domain
    response.delete_cookie(**kwargs)


def _schedule_premium_provider_auto_tests(
    background_tasks: BackgroundTasks, user_id: str,
) -> None:
    from backend.modules.providers._probe import (
        auto_test_untested_provider_accounts,
    )

    background_tasks.add_task(auto_test_untested_provider_accounts, user_id)


# --- Auth Status ---


@router.get("/auth/status")
async def auth_status():
    repo = _user_repo()
    master_admin = await repo.find_by_role("master_admin")
    return {"is_setup_complete": master_admin is not None}


# --- Setup ---


@router.post("/auth/setup")
async def setup(
    body: SetupRequestV2Dto,
    response: Response,
    event_bus: EventBus = Depends(get_event_bus),
):
    # PIN check is the first line of defence — fail fast before any DB access.
    if body.pin != settings.master_admin_pin:
        raise HTTPException(status_code=401, detail="invalid_pin")

    users_repo = _user_repo()
    svc = _key_service()
    audit = _audit_repo()

    existing = await users_repo.find_by_role("master_admin")
    if existing is not None:
        raise HTTPException(status_code=409, detail="master_admin_exists")

    # Create the user document without a password_hash_version first, then
    # upgrade it so the field is set to 1 (H_auth scheme) in one atomic write.
    password_hash = hash_h_auth(body.h_auth)
    doc = await users_repo.create(
        username=body.username,
        email=body.email,
        display_name=body.display_name,
        password_hash=password_hash,
        role="master_admin",
        must_change_password=False,
    )
    user_id = str(doc["_id"])
    await users_repo.set_password_hash_and_version(user_id, password_hash=password_hash, version=1)

    # Generate a fresh per-user kdf_salt and provision the DEK.
    kdf_salt = os.urandom(32)
    h_kek_bytes = base64.urlsafe_b64decode(body.h_kek)
    await svc.provision_for_new_user(
        user_id=user_id,
        h_kek=h_kek_bytes,
        recovery_key=body.recovery_key,
        kdf_salt=kdf_salt,
    )

    # Unlock the freshly provisioned DEK and open an immediate session.
    dek = await svc.unlock_with_password(user_id=user_id, h_kek=h_kek_bytes)
    session_id = generate_session_id()
    access_token = create_access_token(
        user_id=user_id, role="master_admin", session_id=session_id
    )
    refresh_token = generate_refresh_token()
    store = _refresh_store()
    await store.store(refresh_token, user_id=user_id, session_id=session_id)
    await svc.store_session_dek(
        session_id=session_id,
        dek=dek,
        ttl_seconds=settings.jwt_access_token_expire_minutes * 60,
    )
    _set_refresh_cookie(response, refresh_token)

    await audit.log(
        actor_id=user_id,
        action="user.created",
        resource_type="user",
        resource_id=user_id,
        detail={"role": "master_admin", "method": "setup"},
    )

    await event_bus.publish(
        Topics.USER_CREATED,
        UserCreatedEvent(
            user_id=user_id,
            username=doc["username"],
            role="master_admin",
            timestamp=doc["created_at"],
        ),
    )
    await event_bus.publish(
        Topics.AUDIT_LOGGED,
        AuditLoggedEvent(
            actor_id=user_id,
            action="user.created",
            resource_type="user",
            resource_id=user_id,
            detail={"role": "master_admin", "method": "setup"},
        ),
    )
    await event_bus.publish(
        Topics.USER_KEY_PROVISIONED,
        UserKeyProvisionedEvent(user_id=user_id, reason="signup"),
        target_user_ids=[user_id],
    )

    # Recovery key is NOT echoed — the client generated it and already holds it.
    return {
        "access_token": access_token,
        "expires_in": settings.jwt_access_token_expire_minutes * 60,
    }


# --- Auth ---


@router.post("/auth/login")
async def login(
    body: LoginRequestV2Dto,
    response: Response,
    request: Request,
    background_tasks: BackgroundTasks,
):
    client_ip = get_client_ip(request)
    if not await check_login_rate_limit(client_ip):
        raise HTTPException(status_code=429, detail="Too many login attempts. Try again later.")

    repo = _user_repo()
    svc = _key_service()
    user = await repo.find_by_username_case_insensitive(body.username)

    # Reject unknown users and legacy users (password_hash_version != 1).
    if user is None or user.get("password_hash_version") != 1:
        raise HTTPException(status_code=401, detail="invalid_credentials")

    if not user["is_active"]:
        raise HTTPException(status_code=403, detail="Account is deactivated")

    if not verify_h_auth(body.h_auth, user["password_hash"]):
        raise HTTPException(status_code=401, detail="invalid_credentials")

    keys_doc = await svc.get_keys_doc(user["_id"])
    if keys_doc is None:
        raise HTTPException(status_code=500, detail="dek_integrity_error")

    if keys_doc.dek_recovery_required:
        return RecoveryRequiredResponseDto()

    h_kek_bytes = base64.urlsafe_b64decode(body.h_kek)
    try:
        dek = await svc.unlock_with_password(user_id=user["_id"], h_kek=h_kek_bytes)
    except DekUnlockError:
        raise HTTPException(status_code=500, detail="dek_integrity_error")

    session_id = generate_session_id()
    access_token = create_access_token(
        user_id=user["_id"],
        role=user["role"],
        session_id=session_id,
        must_change_password=user["must_change_password"],
    )
    refresh_token = generate_refresh_token()
    store = _refresh_store()
    await store.store(refresh_token, user_id=user["_id"], session_id=session_id)

    await svc.store_session_dek(
        session_id=session_id,
        dek=dek,
        ttl_seconds=settings.jwt_access_token_expire_minutes * 60,
    )

    _set_refresh_cookie(response, refresh_token)
    _schedule_premium_provider_auto_tests(background_tasks, user["_id"])

    return TokenResponseDto(
        access_token=access_token,
        expires_in=settings.jwt_access_token_expire_minutes * 60,
    )


@router.post("/auth/kdf-params", response_model=KdfParamsResponseDto)
async def kdf_params(body: KdfParamsRequestDto) -> KdfParamsResponseDto:
    """Return the KDF salt and parameters needed before the client can derive keys.

    For unknown or legacy users a deterministic pseudo-salt is returned so that
    the response is indistinguishable from a real user's response, defeating
    user-enumeration probes.
    """
    repo = _user_repo()
    user = await repo.find_by_username_case_insensitive(body.username)

    if user is not None:
        key_svc = _key_service()
        keys_doc = await key_svc.get_keys_doc(str(user["_id"]))
        if keys_doc is not None:
            return KdfParamsResponseDto(
                kdf_salt=base64.urlsafe_b64encode(keys_doc.kdf_salt).decode(),
                kdf_params=Argon2ParamsDto(**keys_doc.kdf_params.model_dump()),
                password_hash_version=user.get("password_hash_version"),
            )
        # Legacy user (pre-migration): exists in the users collection but has no
        # user_keys document yet. Return a pseudo-salt so the client cannot tell
        # the difference from a ghost user.
        salt = pseudo_salt_for_unknown_user(body.username, settings.kdf_pepper_bytes)
        return KdfParamsResponseDto(
            kdf_salt=base64.urlsafe_b64encode(salt).decode(),
            kdf_params=Argon2ParamsDto(memory_kib=65536, iterations=3, parallelism=4),
            password_hash_version=None,
        )

    # Unknown user: deterministic pseudo-salt, indistinguishable from a legacy user.
    salt = pseudo_salt_for_unknown_user(body.username, settings.kdf_pepper_bytes)
    return KdfParamsResponseDto(
        kdf_salt=base64.urlsafe_b64encode(salt).decode(),
        kdf_params=Argon2ParamsDto(memory_kib=65536, iterations=3, parallelism=4),
        password_hash_version=None,
    )


@router.post("/auth/login-legacy", response_model=LoginLegacyResponseDto)
async def login_legacy(
    body: LoginLegacyRequestDto,
    response: Response,
    event_bus: EventBus = Depends(get_event_bus),
):
    """One-time migration endpoint for pre-key-infrastructure users.

    Accepts the legacy plaintext password, provisions key material for the
    user, upgrades their password hash to the H_auth scheme, and returns an
    immediate session alongside the recovery key.  The recovery key is
    returned exactly once — it is never stored in plaintext.

    Returns 409 if the user has already been migrated (password_hash_version == 1).
    """
    users_repo = _user_repo()
    svc = _key_service()
    user = await users_repo.find_by_username_case_insensitive(body.username)

    if user is None:
        raise HTTPException(status_code=401, detail="invalid_credentials")

    if user.get("password_hash_version") == 1:
        raise HTTPException(status_code=409, detail="already_migrated")

    if not verify_password(body.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="invalid_credentials")

    user_id = str(user["_id"])

    # Upgrade password hash: replace the bcrypt-over-raw-password with
    # bcrypt-over-H_auth, and bump the version to 1.
    new_hash = hash_h_auth(body.h_auth)
    await users_repo.set_password_hash_and_version(user_id, password_hash=new_hash, version=1)

    # Provision key material for the migrated user.
    recovery_key = generate_recovery_key()
    kdf_salt = pseudo_salt_for_unknown_user(body.username, settings.kdf_pepper_bytes)
    h_kek_bytes = base64.urlsafe_b64decode(body.h_kek)
    await svc.provision_for_new_user(
        user_id=user_id,
        h_kek=h_kek_bytes,
        recovery_key=recovery_key,
        kdf_salt=kdf_salt,
        kdf_params=Argon2Params(),
    )

    # Unlock the DEK we just provisioned and open an immediate session.
    dek = await svc.unlock_with_password(user_id=user_id, h_kek=h_kek_bytes)
    session_id = generate_session_id()
    access_token = create_access_token(
        user_id=user_id,
        role=user["role"],
        session_id=session_id,
        must_change_password=user.get("must_change_password", False),
    )
    refresh_token = generate_refresh_token()
    store = _refresh_store()
    await store.store(refresh_token, user_id=user_id, session_id=session_id)
    await svc.store_session_dek(
        session_id=session_id,
        dek=dek,
        ttl_seconds=settings.jwt_access_token_expire_minutes * 60,
    )

    _set_refresh_cookie(response, refresh_token)

    audit = _audit_repo()
    await audit.log(
        actor_id=user_id,
        action="user.migrated_to_key_infrastructure",
        resource_type="user",
        resource_id=user_id,
    )

    await event_bus.publish(
        Topics.USER_KEY_PROVISIONED,
        UserKeyProvisionedEvent(user_id=user_id, reason="migration"),
        target_user_ids=[user_id],
    )

    return LoginLegacyResponseDto(
        access_token=access_token,
        refresh_token=None,
        expires_in=settings.jwt_access_token_expire_minutes * 60,
        recovery_key=recovery_key,
    )


@router.post("/auth/recover-dek")
async def recover_dek(
    body: RecoverDekRequestDto,
    response: Response,
    event_bus: EventBus = Depends(get_event_bus),
):
    redis = get_redis()
    await check_recovery_rate_limit(body.username, redis)

    users_repo = _user_repo()
    svc = _key_service()
    user = await users_repo.find_by_username_case_insensitive(body.username)
    if user is None or user.get("password_hash_version") != 1:
        raise HTTPException(status_code=401, detail="invalid_credentials")
    if not verify_h_auth(body.h_auth, user["password_hash"]):
        raise HTTPException(status_code=401, detail="invalid_credentials")

    user_id = str(user["_id"])
    new_h_kek_bytes = base64.urlsafe_b64decode(body.h_kek)
    try:
        dek = await svc.unlock_with_recovery_and_rewrap(
            user_id=user_id,
            recovery_key=body.recovery_key,
            new_h_kek=new_h_kek_bytes,
        )
    except (DekUnlockError, InvalidRecoveryKeyError, UserKeyNotFoundError):
        raise HTTPException(status_code=401, detail="invalid_recovery_key")

    session_id = generate_session_id()
    access_token = create_access_token(
        user_id=user_id,
        role=user["role"],
        session_id=session_id,
    )
    refresh_token = generate_refresh_token()
    store = _refresh_store()
    await store.store(refresh_token, user_id=user_id, session_id=session_id)
    await svc.store_session_dek(
        session_id=session_id,
        dek=dek,
        ttl_seconds=settings.jwt_access_token_expire_minutes * 60,
    )
    _set_refresh_cookie(response, refresh_token)

    await event_bus.publish(
        Topics.USER_KEY_RECOVERED,
        UserKeyRecoveredEvent(user_id=user_id),
        target_user_ids=[user_id],
    )
    return {
        "access_token": access_token,
        "expires_in": settings.jwt_access_token_expire_minutes * 60,
    }


@router.post("/auth/decline-recovery")
async def decline_recovery(
    body: DeclineRecoveryRequestDto,
    event_bus: EventBus = Depends(get_event_bus),
):
    users_repo = _user_repo()
    user = await users_repo.find_by_username_case_insensitive(body.username)
    if user is None:
        return {"status": "acknowledged"}
    user_id = str(user["_id"])
    await users_repo.set_active(user_id, value=False)
    await event_bus.publish(
        Topics.USER_KEY_RECOVERY_DECLINED,
        UserKeyRecoveryDeclinedEvent(user_id=user_id),
        target_user_ids=[user_id],
    )
    return {"status": "acknowledged"}


@router.post("/auth/refresh")
async def refresh(
    response: Response,
    background_tasks: BackgroundTasks,
    refresh_token: str | None = Cookie(default=None),
):
    if not refresh_token:
        raise HTTPException(status_code=401, detail="No refresh token")

    store = _refresh_store()
    data = await store.consume(refresh_token)
    if data is None:
        raise HTTPException(status_code=401, detail="Invalid refresh token")

    repo = _user_repo()
    user = await repo.find_by_id(data["user_id"])
    if not user or not user["is_active"]:
        raise HTTPException(status_code=401, detail="User not found or inactive")

    session_id = data["session_id"]
    access_token = create_access_token(
        user_id=user["_id"],
        role=user["role"],
        session_id=session_id,
        must_change_password=user["must_change_password"],
    )
    new_refresh_token = generate_refresh_token()
    await store.store(
        new_refresh_token, user_id=user["_id"], session_id=session_id
    )

    _set_refresh_cookie(response, new_refresh_token)
    _schedule_premium_provider_auto_tests(background_tasks, user["_id"])

    return TokenResponseDto(
        access_token=access_token,
        expires_in=settings.jwt_access_token_expire_minutes * 60,
    )


@router.post("/auth/logout")
async def logout(
    response: Response,
    user: dict = Depends(get_current_user),
    refresh_token: str | None = Cookie(default=None),
):
    if refresh_token:
        store = _refresh_store()
        await store.consume(refresh_token)
    _clear_refresh_cookie(response)
    return {"status": "ok"}


@router.post("/auth/change-password")
async def change_password(
    body: ChangePasswordRequestV2Dto,
    user: dict = Depends(get_current_user),
    event_bus: EventBus = Depends(get_event_bus),
):
    users_repo = _user_repo()
    svc = _key_service()

    doc = await users_repo.find_by_id(user["sub"])
    if not doc:
        raise HTTPException(status_code=404, detail="User not found")

    # Verify old H_auth against the stored bcrypt hash.
    if not verify_h_auth(body.h_auth_old, doc["password_hash"]):
        raise HTTPException(status_code=401, detail="invalid_credentials")

    h_kek_old = base64.urlsafe_b64decode(body.h_kek_old)
    h_kek_new = base64.urlsafe_b64decode(body.h_kek_new)

    # Rewrap the DEK under the new H_kek — this also verifies the old H_kek is correct.
    try:
        await svc.rewrap_password(
            user_id=str(doc["_id"]), h_kek_old=h_kek_old, h_kek_new=h_kek_new
        )
    except DekUnlockError:
        raise HTTPException(status_code=401, detail="invalid_credentials")

    # Persist the new H_auth bcrypt hash at version 1.
    new_password_hash = hash_h_auth(body.h_auth_new)
    await users_repo.set_password_hash_and_version(
        str(doc["_id"]), password_hash=new_password_hash, version=1
    )

    # If the admin-reset flow set must_change_password, clear it now.
    await users_repo.clear_must_change_password(str(doc["_id"]))

    audit = _audit_repo()
    await audit.log(
        actor_id=doc["_id"],
        action="user.password_changed",
        resource_type="user",
        resource_id=doc["_id"],
    )

    await event_bus.publish(
        Topics.AUDIT_LOGGED,
        AuditLoggedEvent(
            actor_id=doc["_id"],
            action="user.password_changed",
            resource_type="user",
            resource_id=doc["_id"],
        ),
    )

    return {"status": "ok"}


# --- Account self-deletion ---


@router.delete("/users/me")
async def delete_my_account(
    body: DeleteAccountRequestDto,
    response: Response,
    user: dict = Depends(get_current_user),
    event_bus: EventBus = Depends(get_event_bus),
) -> DeleteAccountResponseDto:
    """Authenticated self-delete (right-to-be-forgotten).

    Purges every trace of the user across all modules, writes a final
    audit-log entry as an external attestation, revokes all sessions,
    and redirects the now-logged-out client to a public confirmation
    page via a short-lived Redis slug.

    Master admin accounts cannot self-delete — the role must be
    transferred first.
    """
    import logging as _logging  # local to keep the existing imports undisturbed
    _logger = _logging.getLogger(__name__)

    repo = _user_repo()
    user_id = user["sub"]
    doc = await repo.find_by_id(user_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="User not found")

    # Master admin is the site owner. Cascading their deletion would
    # orphan the installation. They must transfer the role first.
    if doc.get("role") == Role.MASTER_ADMIN:
        _logger.info(
            "user.self_delete.master_admin_blocked user_id=%s", user_id,
        )
        raise HTTPException(
            status_code=403,
            detail=(
                "Master admin accounts cannot self-delete. "
                "Transfer the role first."
            ),
        )

    # Case-sensitive confirmation. Small friction deliberate.
    if body.confirm_username != doc["username"]:
        _logger.info(
            "user.self_delete.confirm_mismatch user_id=%s", user_id,
        )
        raise HTTPException(
            status_code=400, detail="Confirmation username does not match.",
        )

    redis = get_redis()
    # Import inside the handler to avoid a top-level import cycle: the
    # cascade module imports from other modules that themselves import
    # user-module primitives at module load time.
    from backend.modules.user import DeletionReportStore, cascade_delete_user

    _logger.info("user.self_delete.start user_id=%s", user_id)
    success, report = await cascade_delete_user(user_id, redis)

    # Audit attestation AFTER the cascade. The cascade itself deletes
    # every audit row tied to this user, so writing the attestation now
    # leaves exactly one surviving record — the account's self-delete
    # receipt — which is the desired behaviour.
    audit = _audit_repo()
    try:
        await audit.log(
            actor_id=user_id,
            action="user.self_deleted",
            resource_type="user",
            resource_id=user_id,
            detail={
                "warnings": report.total_warnings,
                "success": success,
            },
        )
    except Exception:
        # Audit failure must not hide the cascade outcome from the user.
        _logger.warning(
            "user.self_delete.audit_failed user_id=%s", user_id,
            exc_info=True,
        )

    # Store the report behind a random slug so the logged-out user can
    # still view their receipt on the public confirmation page.
    slug = await DeletionReportStore(redis).store(report)

    # Broadcast USER_DELETED to admins. The fan-out rule in event_bus
    # restricts delivery to admin/master_admin roles only — no
    # target_user_ids, since the deleted user has no live sessions.
    await event_bus.publish(
        Topics.USER_DELETED,
        UserDeletedEvent(
            user_id=user_id,
            username=report.target_name,
            timestamp=datetime.now(timezone.utc),
        ),
    )

    # Invalidate the refresh cookie. Access tokens already-issued will
    # stop being accepted because subsequent lookups against the users
    # collection will find no row.
    _clear_refresh_cookie(response)

    _logger.info(
        "user.self_delete.done user_id=%s success=%s warnings=%d slug_len=%d",
        user_id, success, report.total_warnings, len(slug),
    )
    return DeleteAccountResponseDto(slug=slug, success=success)


@router.get("/auth/deletion-report/{slug}")
async def get_deletion_report(slug: str) -> DeletionReportDto:
    """Public fetch for a short-lived deletion report.

    Deliberately unauthenticated: by the time a user reads their
    receipt they are already logged out. The slug itself is the
    capability — 24 bytes of ``secrets.token_urlsafe`` entropy + a
    15-minute Redis TTL.
    """
    # Defensive length check — a malformed slug can never match anyway,
    # but rejecting obviously-bogus input early avoids pointless Redis
    # round-trips and keeps logs clean.
    if not slug or len(slug) > 128:
        raise HTTPException(status_code=400, detail="Invalid slug.")

    from backend.modules.user import DeletionReportStore

    report = await DeletionReportStore(get_redis()).fetch(slug)
    if report is None:
        raise HTTPException(
            status_code=410,
            detail=(
                "Deletion report has expired or is unknown. "
                "Reports are kept for 15 minutes."
            ),
        )
    return report


# --- User Profile ---


@router.get("/users/me/about-me")
async def get_about_me(user: dict = Depends(get_current_user)):
    repo = _user_repo()
    about_me = await repo.get_about_me(user["sub"])
    return {"about_me": about_me}


@router.patch("/users/me/about-me")
async def update_about_me(
    body: UpdateAboutMeDto,
    user: dict = Depends(get_current_user),
):
    repo = _user_repo()
    await repo.update_about_me(user["sub"], body.about_me)
    return {"about_me": body.about_me}


@router.get("/users/me")
async def get_me(user: dict = Depends(get_current_user)):
    repo = _user_repo()
    doc = await repo.find_by_id(user["sub"])
    if doc is None:
        raise HTTPException(status_code=404, detail="User not found")
    return UserRepository.to_dto(doc)


@router.patch("/users/me/profile")
async def update_my_profile(
    body: UpdateDisplayNameDto,
    user: dict = Depends(get_current_user),
    event_bus: EventBus = Depends(get_event_bus),
):
    repo = _user_repo()
    doc = await repo.update(user["sub"], {"display_name": body.display_name})
    if doc is None:
        raise HTTPException(status_code=404, detail="User not found")

    await event_bus.publish(
        Topics.USER_PROFILE_UPDATED,
        UserProfileUpdatedEvent(
            user_id=user["sub"],
            display_name=doc["display_name"],
            timestamp=doc["updated_at"],
        ),
        target_user_ids=[user["sub"]],
    )

    return UserRepository.to_dto(doc)


# --- User Management ---


@router.post("/admin/users", status_code=201)
async def create_user(
    body: CreateUserRequestDto,
    user: dict = Depends(require_admin),
    event_bus: EventBus = Depends(get_event_bus),
):
    # Only master_admin can create admins
    if body.role == Role.ADMIN and user["role"] != Role.MASTER_ADMIN:
        raise HTTPException(
            status_code=403, detail="Only master admin can create admin users"
        )
    if body.role == Role.MASTER_ADMIN:
        raise HTTPException(
            status_code=403, detail="Cannot create another master admin"
        )
    if body.role not in (Role.ADMIN, Role.USER):
        raise HTTPException(status_code=400, detail="Invalid role")

    repo = _user_repo()
    password = generate_random_password()
    password_hash = hash_password(password)

    try:
        doc = await repo.create(
            username=body.username,
            email=body.email,
            display_name=body.display_name or "Unnamed User",
            password_hash=password_hash,
            role=body.role,
            must_change_password=True,
        )
    except Exception:
        raise HTTPException(
            status_code=409, detail="Username or email already exists"
        )

    audit = _audit_repo()
    await audit.log(
        actor_id=user["sub"],
        action="user.created",
        resource_type="user",
        resource_id=doc["_id"],
        detail={"role": body.role},
    )

    await event_bus.publish(
        Topics.USER_CREATED,
        UserCreatedEvent(user_id=doc["_id"], username=doc["username"], role=body.role, timestamp=doc["created_at"]),
    )
    await event_bus.publish(
        Topics.AUDIT_LOGGED,
        AuditLoggedEvent(actor_id=user["sub"], action="user.created", resource_type="user", resource_id=doc["_id"], detail={"role": body.role}),
    )

    return CreateUserResponseDto(
        user=UserRepository.to_dto(doc),
        generated_password=password,
    )


@router.get("/admin/users")
async def list_users(
    skip: int = 0,
    limit: int = 50,
    user: dict = Depends(require_admin),
):
    repo = _user_repo()
    users = await repo.list_users(skip=skip, limit=limit)
    total = await repo.count()
    return {
        "users": [UserRepository.to_dto(u) for u in users],
        "total": total,
        "skip": skip,
        "limit": limit,
    }


@router.get("/admin/users/{user_id}")
async def get_user(
    user_id: str,
    user: dict = Depends(require_admin),
):
    repo = _user_repo()
    doc = await repo.find_by_id(user_id)
    if not doc:
        raise HTTPException(status_code=404, detail="User not found")
    return UserRepository.to_dto(doc)


@router.patch("/admin/users/{user_id}")
async def update_user(
    user_id: str,
    body: UpdateUserRequestDto,
    user: dict = Depends(require_admin),
    event_bus: EventBus = Depends(get_event_bus),
):
    repo = _user_repo()
    target = await repo.find_by_id(user_id)
    if not target:
        raise HTTPException(status_code=404, detail="User not found")

    # Permission checks
    if target["role"] == "master_admin":
        raise HTTPException(
            status_code=403, detail="Cannot modify master admin"
        )
    if target["role"] == "admin" and user["role"] != "master_admin":
        raise HTTPException(
            status_code=403, detail="Only master admin can modify admin users"
        )
    if body.is_active is False and user_id == user["sub"]:
        raise HTTPException(
            status_code=403, detail="Cannot deactivate yourself"
        )
    if body.role is not None:
        if user["role"] != "master_admin":
            raise HTTPException(
                status_code=403, detail="Only master admin can change roles"
            )
        if body.role == "master_admin":
            raise HTTPException(
                status_code=403, detail="Cannot assign master admin role"
            )
        if body.role not in ("admin", "user"):
            raise HTTPException(status_code=400, detail="Invalid role")

    fields = body.model_dump(exclude_none=True)
    if not fields:
        raise HTTPException(status_code=400, detail="No fields to update")

    updated = await repo.update(user_id, fields)

    audit = _audit_repo()
    await audit.log(
        actor_id=user["sub"],
        action="user.updated",
        resource_type="user",
        resource_id=user_id,
        detail={"changes": fields},
    )

    await event_bus.publish(
        Topics.USER_UPDATED,
        UserUpdatedEvent(user_id=user_id, changes=fields, timestamp=updated["updated_at"]),
        target_user_ids=[user_id],
    )
    await event_bus.publish(
        Topics.AUDIT_LOGGED,
        AuditLoggedEvent(actor_id=user["sub"], action="user.updated", resource_type="user", resource_id=user_id, detail={"changes": fields}),
    )

    return UserRepository.to_dto(updated)


@router.delete("/admin/users/{user_id}")
async def delete_user(
    user_id: str,
    user: dict = Depends(require_admin),
    event_bus: EventBus = Depends(get_event_bus),
):
    repo = _user_repo()
    target = await repo.find_by_id(user_id)
    if not target:
        raise HTTPException(status_code=404, detail="User not found")

    if target["role"] == "master_admin":
        raise HTTPException(
            status_code=403, detail="Cannot deactivate master admin"
        )
    if target["role"] == "admin" and user["role"] != "master_admin":
        raise HTTPException(
            status_code=403, detail="Only master admin can deactivate admin users"
        )
    if user_id == user["sub"]:
        raise HTTPException(
            status_code=403, detail="Cannot deactivate yourself"
        )

    await repo.update(user_id, {"is_active": False})

    audit = _audit_repo()
    await audit.log(
        actor_id=user["sub"],
        action="user.deactivated",
        resource_type="user",
        resource_id=user_id,
    )

    await event_bus.publish(
        Topics.USER_DEACTIVATED,
        UserDeactivatedEvent(user_id=user_id, timestamp=datetime.now(timezone.utc)),
        target_user_ids=[user_id],
    )
    await event_bus.publish(
        Topics.AUDIT_LOGGED,
        AuditLoggedEvent(actor_id=user["sub"], action="user.deactivated", resource_type="user", resource_id=user_id),
    )

    return {"status": "ok"}


@router.post("/admin/users/{user_id}/reset-password")
async def reset_password(
    user_id: str,
    user: dict = Depends(require_admin),
    event_bus: EventBus = Depends(get_event_bus),
):
    repo = _user_repo()
    target = await repo.find_by_id(user_id)
    if not target:
        raise HTTPException(status_code=404, detail="User not found")

    if target["role"] == "master_admin":
        raise HTTPException(
            status_code=403, detail="Cannot reset master admin password"
        )
    if target["role"] == "admin" and user["role"] != "master_admin":
        raise HTTPException(
            status_code=403, detail="Only master admin can reset admin passwords"
        )

    password = generate_random_password()
    password_hash = hash_password(password)
    updated = await repo.update(
        user_id, {"password_hash": password_hash, "must_change_password": True}
    )

    audit = _audit_repo()
    await audit.log(
        actor_id=user["sub"],
        action="user.password_reset",
        resource_type="user",
        resource_id=user_id,
    )

    await event_bus.publish(
        Topics.USER_PASSWORD_RESET,
        UserPasswordResetEvent(user_id=user_id, timestamp=datetime.now(timezone.utc)),
        target_user_ids=[user_id],
    )
    await event_bus.publish(
        Topics.AUDIT_LOGGED,
        AuditLoggedEvent(actor_id=user["sub"], action="user.password_reset", resource_type="user", resource_id=user_id),
    )

    return ResetPasswordResponseDto(
        user=UserRepository.to_dto(updated),
        generated_password=password,
    )


# --- Audit Log ---


@router.get("/admin/audit-log")
async def get_audit_log(
    skip: int = 0,
    limit: int = 50,
    action: str | None = None,
    resource_type: str | None = None,
    resource_id: str | None = None,
    actor_id: str | None = None,
    user: dict = Depends(require_admin),
):
    audit = _audit_repo()

    # Non-master admins can only see their own entries
    effective_actor_id = actor_id
    if user["role"] != "master_admin":
        effective_actor_id = user["sub"]

    entries = await audit.list_entries(
        skip=skip,
        limit=limit,
        actor_id=effective_actor_id,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
    )

    return {
        "entries": [AuditRepository.to_dto(e) for e in entries],
        "skip": skip,
        "limit": limit,
    }


# ── MCP Gateways ─────────────────────────────────────────────────────


from pydantic import BaseModel as _BaseModel


class CreateMcpGatewayRequest(_BaseModel):
    name: str
    url: str
    api_key: str | None = None
    enabled: bool = True
    server_configs: dict = {}
    tool_overrides: list = []


class UpdateMcpGatewayRequest(_BaseModel):
    name: str | None = None
    url: str | None = None
    api_key: str | None = None
    enabled: bool | None = None
    disabled_tools: list[str] | None = None
    server_configs: dict | None = None
    tool_overrides: list | None = None


def _invalidate_user_mcp(user_id: str) -> None:
    """Clear cached MCP registries for all connections of a user."""
    from backend.ws.manager import get_manager
    cids = get_manager().connection_ids_for_user(user_id)
    if cids:
        invalidate_mcp_registries(cids)


@router.get("/user/mcp/gateways")
async def list_mcp_gateways(user: dict = Depends(require_active_session)):
    repo = _user_repo()
    gateways = await repo.get_mcp_gateways(user["sub"])
    return [McpGatewayConfigDto(**gw) for gw in gateways]


@router.post("/user/mcp/gateways", status_code=201)
async def create_mcp_gateway(
    body: CreateMcpGatewayRequest,
    user: dict = Depends(require_active_session),
):
    from uuid import uuid4
    repo = _user_repo()
    existing = await repo.get_mcp_gateways(user["sub"])
    existing_namespaces = {normalise_namespace(gw["name"]) for gw in existing}

    err = validate_namespace(body.name, existing_namespaces)
    if err:
        raise HTTPException(status_code=422, detail=err)

    gateway = {
        "id": str(uuid4()),
        "name": body.name,
        "url": body.url,
        "api_key": body.api_key,
        "enabled": body.enabled,
        "disabled_tools": [],
        "server_configs": body.server_configs,
        "tool_overrides": body.tool_overrides,
    }
    await repo.add_mcp_gateway(user["sub"], gateway)
    _invalidate_user_mcp(user["sub"])
    return McpGatewayConfigDto(**gateway)


@router.patch("/user/mcp/gateways/{gateway_id}")
async def update_mcp_gateway(
    gateway_id: str,
    body: UpdateMcpGatewayRequest,
    user: dict = Depends(require_active_session),
):
    repo = _user_repo()
    updates = body.model_dump(exclude_unset=True)
    if not updates:
        raise HTTPException(status_code=422, detail="No fields to update")

    if "name" in updates:
        existing = await repo.get_mcp_gateways(user["sub"])
        existing_namespaces = {
            normalise_namespace(gw["name"])
            for gw in existing
            if gw["id"] != gateway_id
        }
        err = validate_namespace(updates["name"], existing_namespaces)
        if err:
            raise HTTPException(status_code=422, detail=err)

    success = await repo.update_mcp_gateway(user["sub"], gateway_id, updates)
    if not success:
        raise HTTPException(status_code=404, detail="Gateway not found")
    _invalidate_user_mcp(user["sub"])

    gateways = await repo.get_mcp_gateways(user["sub"])
    gw = next((g for g in gateways if g["id"] == gateway_id), None)
    if not gw:
        raise HTTPException(status_code=404, detail="Gateway not found")
    return McpGatewayConfigDto(**gw)


@router.delete("/user/mcp/gateways/{gateway_id}", status_code=204)
async def delete_mcp_gateway(
    gateway_id: str,
    user: dict = Depends(require_active_session),
):
    repo = _user_repo()
    success = await repo.delete_mcp_gateway(user["sub"], gateway_id)
    if not success:
        raise HTTPException(status_code=404, detail="Gateway not found")
    _invalidate_user_mcp(user["sub"])


# ── Admin MCP Gateways ───────────────────────────────────────────────


async def _get_admin_mcp_settings(db) -> dict:
    """Read the admin MCP settings document."""
    doc = await db["admin_settings"].find_one({"_id": "mcp"})
    return doc or {"_id": "mcp", "gateways": []}


async def _save_admin_mcp_settings(db, gateways: list[dict]) -> None:
    """Upsert the admin MCP settings document."""
    await db["admin_settings"].update_one(
        {"_id": "mcp"},
        {"$set": {"gateways": gateways}},
        upsert=True,
    )


@router.get("/admin/mcp/gateways")
async def list_admin_mcp_gateways(user: dict = Depends(require_admin)):
    db = get_db()
    settings = await _get_admin_mcp_settings(db)
    return [McpGatewayConfigDto(**gw) for gw in settings.get("gateways", [])]


@router.post("/admin/mcp/gateways", status_code=201)
async def create_admin_mcp_gateway(
    body: CreateMcpGatewayRequest,
    user: dict = Depends(require_admin),
):
    from uuid import uuid4
    db = get_db()
    settings = await _get_admin_mcp_settings(db)
    existing = settings.get("gateways", [])
    existing_namespaces = {normalise_namespace(gw["name"]) for gw in existing}

    err = validate_namespace(body.name, existing_namespaces)
    if err:
        raise HTTPException(status_code=422, detail=err)

    gateway = {
        "id": str(uuid4()),
        "name": body.name,
        "url": body.url,
        "api_key": body.api_key,
        "enabled": body.enabled,
        "disabled_tools": [],
        "server_configs": body.server_configs,
        "tool_overrides": body.tool_overrides,
    }
    existing.append(gateway)
    await _save_admin_mcp_settings(db, existing)
    invalidate_mcp_registries()  # admin change affects all users
    return McpGatewayConfigDto(**gateway)


@router.patch("/admin/mcp/gateways/{gateway_id}")
async def update_admin_mcp_gateway(
    gateway_id: str,
    body: UpdateMcpGatewayRequest,
    user: dict = Depends(require_admin),
):
    db = get_db()
    settings = await _get_admin_mcp_settings(db)
    gateways = settings.get("gateways", [])

    target = next((gw for gw in gateways if gw["id"] == gateway_id), None)
    if not target:
        raise HTTPException(status_code=404, detail="Gateway not found")

    updates = body.model_dump(exclude_unset=True)
    if "name" in updates:
        existing_namespaces = {
            normalise_namespace(gw["name"])
            for gw in gateways
            if gw["id"] != gateway_id
        }
        err = validate_namespace(updates["name"], existing_namespaces)
        if err:
            raise HTTPException(status_code=422, detail=err)

    target.update(updates)
    await _save_admin_mcp_settings(db, gateways)
    invalidate_mcp_registries()  # admin change affects all users
    return McpGatewayConfigDto(**target)


@router.delete("/admin/mcp/gateways/{gateway_id}", status_code=204)
async def delete_admin_mcp_gateway(
    gateway_id: str,
    user: dict = Depends(require_admin),
):
    db = get_db()
    settings = await _get_admin_mcp_settings(db)
    gateways = settings.get("gateways", [])
    original_len = len(gateways)
    gateways = [gw for gw in gateways if gw["id"] != gateway_id]
    if len(gateways) == original_len:
        raise HTTPException(status_code=404, detail="Gateway not found")
    await _save_admin_mcp_settings(db, gateways)
    invalidate_mcp_registries()  # admin change affects all users


# ── MCP Gateway Proxy ────────────────────────────────────────────────
# Admin and user-remote gateways may be reachable only from the backend
# (e.g. Docker-internal hostnames). These endpoints proxy tools/list and
# tools/call so the frontend can explore and test them.


class _McpProxyCallRequest(_BaseModel):
    tool_name: str
    arguments: dict = {}


async def _resolve_gateway(
    gateway_id: str, user: dict,
) -> McpGatewayConfigDto:
    """Look up a gateway by ID across admin and user-remote tiers."""
    db = get_db()
    # Check admin gateways
    admin_doc = await db["admin_settings"].find_one({"_id": "mcp"})
    if admin_doc:
        for gw in admin_doc.get("gateways", []):
            if gw["id"] == gateway_id:
                return McpGatewayConfigDto(**gw)
    # Check user gateways
    repo = UserRepository(db)
    user_gateways = await repo.get_mcp_gateways(user["sub"])
    for gw in user_gateways:
        if gw["id"] == gateway_id:
            return McpGatewayConfigDto(**gw)
    raise HTTPException(status_code=404, detail="Gateway not found")


@router.get("/mcp/gateways/{gateway_id}/tools")
async def proxy_mcp_tools_list(
    gateway_id: str,
    user: dict = Depends(require_active_session),
):
    """Proxy tools/list to a backend-reachable MCP gateway."""
    from backend.modules.tools._mcp_executor import McpExecutor

    gw = await _resolve_gateway(gateway_id, user)
    executor = McpExecutor()
    mcp_url = gw.url.rstrip("/") + "/mcp"
    tools = await executor.discover_tools(url=mcp_url, api_key=gw.api_key)
    return {"tools": tools}


@router.post("/mcp/gateways/{gateway_id}/call")
async def proxy_mcp_tool_call(
    gateway_id: str,
    body: _McpProxyCallRequest,
    user: dict = Depends(require_active_session),
):
    """Proxy tools/call to a backend-reachable MCP gateway."""
    import json as _json

    from backend.modules.tools._mcp_executor import McpExecutor

    gw = await _resolve_gateway(gateway_id, user)
    executor = McpExecutor()
    mcp_url = gw.url.rstrip("/") + "/mcp"
    result_json = await executor.call_tool(
        url=mcp_url, api_key=gw.api_key,
        tool_name=body.tool_name, arguments=body.arguments,
    )
    return _json.loads(result_json)
