from datetime import datetime, timezone

from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response

from backend.config import settings
from backend.database import get_db, get_redis
from backend.dependencies import get_current_user, require_admin, require_active_session
from backend.ws.event_bus import EventBus, get_event_bus
from backend.modules.user._auth import (
    create_access_token,
    generate_random_password,
    generate_refresh_token,
    generate_session_id,
    hash_password,
    verify_password,
)
from backend.modules.user._audit import AuditRepository
from backend.modules.user._rate_limit import check_login_rate_limit, get_client_ip
from backend.modules.user._refresh import RefreshTokenStore
from backend.modules.user._repository import UserRepository
from shared.dtos.mcp import McpGatewayConfigDto
from backend.modules.tools import invalidate_mcp_registries
from backend.modules.tools._namespace import normalise_namespace, validate_namespace
from shared.dtos.auth import (
    ChangePasswordRequestDto,
    CreateUserRequestDto,
    CreateUserResponseDto,
    LoginRequestDto,
    ResetPasswordResponseDto,
    SetupRequestDto,
    SetupResponseDto,
    TokenResponseDto,
    UpdateAboutMeDto,
    UpdateDisplayNameDto,
    UpdateUserRequestDto,
    UserDto,
    AuditLogEntryDto,
    Role,
)
from shared.events.auth import (
    UserCreatedEvent,
    UserDeactivatedEvent,
    UserPasswordResetEvent,
    UserUpdatedEvent,
    UserProfileUpdatedEvent,
)
from shared.events.audit import AuditLoggedEvent
from shared.topics import Topics

router = APIRouter(prefix="/api")


def _user_repo() -> UserRepository:
    return UserRepository(get_db())


def _audit_repo() -> AuditRepository:
    return AuditRepository(get_db())


def _refresh_store() -> RefreshTokenStore:
    return RefreshTokenStore(get_redis())


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


# --- Auth Status ---


@router.get("/auth/status")
async def auth_status():
    repo = _user_repo()
    master_admin = await repo.find_by_role("master_admin")
    return {"is_setup_complete": master_admin is not None}


# --- Setup ---


@router.post("/setup", status_code=201)
async def setup(
    body: SetupRequestDto,
    response: Response,
    event_bus: EventBus = Depends(get_event_bus),
):
    repo = _user_repo()
    audit = _audit_repo()

    existing = await repo.find_by_role("master_admin")
    if existing:
        raise HTTPException(status_code=409, detail="Master admin already exists")

    if body.pin != settings.master_admin_pin:
        raise HTTPException(status_code=403, detail="Invalid PIN")

    password_hash = hash_password(body.password)
    doc = await repo.create(
        username=body.username,
        email=body.email,
        display_name=body.username,
        password_hash=password_hash,
        role="master_admin",
        must_change_password=False,
    )

    session_id = generate_session_id()
    access_token = create_access_token(
        user_id=doc["_id"], role="master_admin", session_id=session_id
    )
    refresh_token = generate_refresh_token()
    store = _refresh_store()
    await store.store(refresh_token, user_id=doc["_id"], session_id=session_id)

    _set_refresh_cookie(response, refresh_token)

    await audit.log(
        actor_id=doc["_id"],
        action="user.created",
        resource_type="user",
        resource_id=doc["_id"],
        detail={"role": "master_admin", "method": "setup"},
    )

    await event_bus.publish(
        Topics.USER_CREATED,
        UserCreatedEvent(user_id=doc["_id"], username=doc["username"], role="master_admin", timestamp=doc["created_at"]),
    )
    await event_bus.publish(
        Topics.AUDIT_LOGGED,
        AuditLoggedEvent(actor_id=doc["_id"], action="user.created", resource_type="user", resource_id=doc["_id"], detail={"role": "master_admin", "method": "setup"}),
    )

    return SetupResponseDto(
        user=UserRepository.to_dto(doc),
        access_token=access_token,
        expires_in=settings.jwt_access_token_expire_minutes * 60,
    )


# --- Auth ---


@router.post("/auth/login")
async def login(body: LoginRequestDto, response: Response, request: Request):
    client_ip = get_client_ip(request)
    if not await check_login_rate_limit(client_ip):
        raise HTTPException(status_code=429, detail="Too many login attempts. Try again later.")

    repo = _user_repo()
    user = await repo.find_by_username(body.username)

    if not user:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    if not user["is_active"]:
        raise HTTPException(status_code=403, detail="Account is deactivated")

    if not verify_password(body.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid credentials")

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

    _set_refresh_cookie(response, refresh_token)

    return TokenResponseDto(
        access_token=access_token,
        expires_in=settings.jwt_access_token_expire_minutes * 60,
    )


@router.post("/auth/refresh")
async def refresh(
    response: Response,
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


@router.patch("/auth/password")
async def change_password(
    body: ChangePasswordRequestDto,
    response: Response,
    user: dict = Depends(get_current_user),
    event_bus: EventBus = Depends(get_event_bus),
):
    repo = _user_repo()
    doc = await repo.find_by_id(user["sub"])
    if not doc:
        raise HTTPException(status_code=404, detail="User not found")

    if not verify_password(body.current_password, doc["password_hash"]):
        raise HTTPException(status_code=401, detail="Current password is incorrect")

    new_hash = hash_password(body.new_password)
    await repo.update(
        doc["_id"],
        {"password_hash": new_hash, "must_change_password": False},
    )

    # Issue new token pair without mcp claim
    session_id = generate_session_id()
    access_token = create_access_token(
        user_id=doc["_id"],
        role=doc["role"],
        session_id=session_id,
        must_change_password=False,
    )
    refresh_token_new = generate_refresh_token()
    store = _refresh_store()
    await store.store(
        refresh_token_new, user_id=doc["_id"], session_id=session_id
    )

    _set_refresh_cookie(response, refresh_token_new)

    audit = _audit_repo()
    await audit.log(
        actor_id=doc["_id"],
        action="user.password_changed",
        resource_type="user",
        resource_id=doc["_id"],
    )

    await event_bus.publish(
        Topics.AUDIT_LOGGED,
        AuditLoggedEvent(actor_id=doc["_id"], action="user.password_changed", resource_type="user", resource_id=doc["_id"]),
    )

    return TokenResponseDto(
        access_token=access_token,
        expires_in=settings.jwt_access_token_expire_minutes * 60,
    )


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
