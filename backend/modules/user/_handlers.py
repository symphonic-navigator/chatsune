from fastapi import APIRouter, Cookie, Depends, HTTPException, Response

from backend.config import settings
from backend.database import get_db, get_redis
from backend.dependencies import get_current_user, require_admin, require_active_session
from backend.modules.user._auth import (
    create_access_token,
    generate_random_password,
    generate_refresh_token,
    generate_session_id,
    hash_password,
    verify_password,
)
from backend.modules.user._audit import AuditRepository
from backend.modules.user._refresh import RefreshTokenStore
from backend.modules.user._repository import UserRepository
from shared.dtos.auth import (
    ChangePasswordRequestDto,
    CreateUserRequestDto,
    CreateUserResponseDto,
    LoginRequestDto,
    ResetPasswordResponseDto,
    SetupRequestDto,
    SetupResponseDto,
    TokenResponseDto,
    UpdateUserRequestDto,
    UserDto,
    AuditLogEntryDto,
)

router = APIRouter(prefix="/api")


def _user_repo() -> UserRepository:
    return UserRepository(get_db())


def _audit_repo() -> AuditRepository:
    return AuditRepository(get_db())


def _refresh_store() -> RefreshTokenStore:
    return RefreshTokenStore(get_redis())


def _set_refresh_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key="refresh_token",
        value=token,
        httponly=True,
        secure=True,
        samesite="strict",
        max_age=settings.jwt_refresh_token_expire_days * 86400,
    )


def _clear_refresh_cookie(response: Response) -> None:
    response.delete_cookie(
        key="refresh_token", httponly=True, secure=True, samesite="strict"
    )


# --- Setup ---


@router.post("/setup", status_code=201)
async def setup(body: SetupRequestDto, response: Response):
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

    return SetupResponseDto(
        user=UserRepository.to_dto(doc),
        access_token=access_token,
        expires_in=settings.jwt_access_token_expire_minutes * 60,
    )


# --- Auth ---


@router.post("/auth/login")
async def login(body: LoginRequestDto, response: Response):
    repo = _user_repo()
    user = await repo.find_by_username(body.username)

    if not user or not verify_password(body.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    if not user["is_active"]:
        raise HTTPException(status_code=403, detail="Account is deactivated")

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

    return TokenResponseDto(
        access_token=access_token,
        expires_in=settings.jwt_access_token_expire_minutes * 60,
    )
