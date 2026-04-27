# Invitation Tokens Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add admin-generated one-time invitation links so new users can self-register through the existing E2E crypto flow.

**Architecture:** New `invitation_tokens` collection in the `user` module. Three new endpoints (`/api/admin/invitations`, `/api/invitations/{token}/validate`, `/api/invitations/{token}/register`). Existing `/auth/setup` user-creation block is refactored into a private `_provision_new_user` helper that both endpoints share. New public frontend route `/register/:token` (opulent style) and a new "+ Invitation Link" button beside "+ New User" in the existing AdminModal Users tab.

**Tech Stack:** FastAPI, Motor (async MongoDB) with Replica Set transactions, Pydantic v2, Argon2 (client-side), React + TSX + Tailwind, Vite, pnpm.

**Spec:** `devdocs/specs/2026-04-27-invitation-tokens-design.md`

**Reference files (read before starting):**
- `backend/modules/user/_handlers.py:154-249` — current `/auth/setup` (the reference flow to mirror)
- `backend/modules/user/_handlers.py:904-961` — current `POST /api/admin/users` (must remain unchanged)
- `backend/modules/user/__init__.py:34` — `init_indexes(db)` (where to wire new indexes)
- `backend/main.py:32,98` — startup wiring of `init_indexes`
- `backend/modules/user/_repository.py:11-90` — `UserRepository` (template for new repo)
- `frontend/src/core/api/auth.ts:88-108` — current `setup()` client (reference for `register*` calls)
- `frontend/src/app/pages/LoginPage.tsx:300-400` — setup form/UI (reference for RegisterPage)
- `frontend/src/features/auth/RecoveryKeyModal.tsx` — reused as-is
- `frontend/src/app/components/admin-modal/UsersTab.tsx:200` — where the new button goes

**Test commands** (run from repo root):
- Backend host (excludes DB-dependent files): `cd backend && uv run pytest --ignore=tests/modules/user/test_invitations.py --ignore=tests/modules/user/test_handlers.py --ignore=tests/integration -q`
- Backend Docker (full suite): `docker compose run --rm backend uv run pytest backend/tests/modules/user/test_invitations.py -v`
- Frontend type check + build: `cd frontend && pnpm run build` (NOT `pnpm tsc --noEmit` — the full build catches stricter type errors)

---

## Task 1: Backend — Extract `_provision_new_user` helper (refactor)

Pure refactor of existing `/auth/setup` user-creation block into a private helper. No behaviour change, no new endpoint yet. Validates the helper signature and that the existing setup flow still works end-to-end.

**Files:**
- Modify: `backend/modules/user/_handlers.py:154-249` (extract helper, call from setup)
- (No new test file — rely on existing setup tests + test added at end of task)

- [ ] **Step 1: Read the current setup endpoint**

Read `backend/modules/user/_handlers.py:154-249`. Identify the exact block that:
1. Hashes h_auth, creates user document, sets password_hash_version
2. Generates kdf_salt, decodes h_kek, provisions DEK with recovery_key
3. Unlocks DEK and returns it

Everything *outside* this block (PIN check, master_admin existence check, session creation, audit log, event publishing) stays in the endpoint.

- [ ] **Step 2: Add the helper function above the endpoints**

Insert this helper just above `@router.post("/auth/setup")` in `_handlers.py`:

```python
async def _provision_new_user(
    *,
    users_repo: UserRepository,
    svc: UserKeyService,
    username: str,
    email: str,
    display_name: str,
    h_auth: str,
    h_kek: str,
    recovery_key: str,
    role: str,
    must_change_password: bool = False,
) -> tuple[dict, bytes]:
    """Create user document and provision DEK/KEK keys.

    Pure user+key creation — no session, no audit, no event publishing.
    Caller is responsible for those side effects so it can compose them
    inside its own transaction or sequence.

    Returns (user_doc, unlocked_dek). Raises on collision (DuplicateKeyError)
    or crypto failure.
    """
    password_hash = hash_h_auth(h_auth)
    doc = await users_repo.create(
        username=username,
        email=email,
        display_name=display_name,
        password_hash=password_hash,
        role=role,
        must_change_password=must_change_password,
    )
    user_id = str(doc["_id"])
    await users_repo.set_password_hash_and_version(
        user_id, password_hash=password_hash, version=1
    )

    kdf_salt = os.urandom(32)
    h_kek_bytes = decode_base64url(h_kek)
    await svc.provision_for_new_user(
        user_id=user_id,
        h_kek=h_kek_bytes,
        recovery_key=recovery_key,
        kdf_salt=kdf_salt,
    )

    dek = await svc.unlock_with_password(user_id=user_id, h_kek=h_kek_bytes)
    return doc, dek
```

- [ ] **Step 3: Refactor `/auth/setup` to use the helper**

Replace the lines from `password_hash = hash_h_auth(body.h_auth)` through `dek = await svc.unlock_with_password(...)` (the user-creation block, roughly lines 174-197) with:

```python
    doc, dek = await _provision_new_user(
        users_repo=users_repo,
        svc=svc,
        username=body.username,
        email=body.email,
        display_name=body.display_name,
        h_auth=body.h_auth,
        h_kek=body.h_kek,
        recovery_key=body.recovery_key,
        role="master_admin",
        must_change_password=False,
    )
    user_id = str(doc["_id"])
```

Everything before (PIN check, existing-master check) and after (session_id, access_token, refresh_token, audit, events) stays untouched.

- [ ] **Step 4: Verify the build still compiles**

Run: `cd backend && uv run python -m py_compile backend/modules/user/_handlers.py`
Expected: no output (success)

- [ ] **Step 5: Run existing setup-related tests on host**

Run: `cd backend && uv run pytest --ignore=tests/modules/user/test_handlers.py --ignore=tests/integration -k 'not handlers' -q`
Expected: all pass (we are explicitly NOT running the DB-bound test_handlers; that comes via Docker)

- [ ] **Step 6: Run setup smoke test in Docker**

Run: `docker compose run --rm backend uv run pytest backend/tests/modules/user/test_handlers.py -k 'setup' -v`
Expected: all existing setup tests pass

- [ ] **Step 7: Commit**

```bash
git add backend/modules/user/_handlers.py
git commit -m "Extract _provision_new_user helper from /auth/setup

Pure refactor in preparation for the invitation-token register endpoint
which needs the same user+key creation sequence with a different role
and gating mechanism."
```

---

## Task 2: Backend — InvitationToken model + repository + indexes

Add the data layer. No endpoints yet.

**Files:**
- Create: `backend/modules/user/_invitation_repository.py`
- Modify: `backend/modules/user/_models.py` (add `InvitationTokenDocument`)
- Modify: `backend/modules/user/__init__.py` (wire `create_indexes` into `init_indexes`)
- Test: `backend/tests/modules/user/test_invitation_repository.py`

- [ ] **Step 1: Add the model**

In `backend/modules/user/_models.py`, append:

```python
class InvitationTokenDocument(BaseModel):
    """One-time admin-generated link that lets a new user self-register.

    The token field is a URL-safe random string (~43 chars) generated via
    `secrets.token_urlsafe(32)`. The expires_at field drives MongoDB TTL
    cleanup.
    """
    model_config = {"arbitrary_types_allowed": True}

    id: ObjectId = Field(alias="_id")
    token: str
    created_at: datetime
    expires_at: datetime
    used: bool = False
    used_at: datetime | None = None
    used_by_user_id: str | None = None
    created_by: str
```

If `ObjectId`, `Field`, `datetime` are not yet imported in this file, add the imports at the top.

- [ ] **Step 2: Write the failing repository test**

Create `backend/tests/modules/user/test_invitation_repository.py`:

```python
import pytest
from datetime import datetime, timedelta, timezone
from backend.modules.user._invitation_repository import InvitationRepository


@pytest.mark.asyncio
async def test_create_returns_token_doc(db):
    repo = InvitationRepository(db)
    await repo.create_indexes()
    doc = await repo.create(created_by="admin-id-1", ttl_hours=24)
    assert doc["token"]
    assert len(doc["token"]) >= 32
    assert doc["used"] is False
    assert doc["created_by"] == "admin-id-1"
    assert doc["expires_at"] > doc["created_at"]


@pytest.mark.asyncio
async def test_find_by_token_returns_doc(db):
    repo = InvitationRepository(db)
    await repo.create_indexes()
    created = await repo.create(created_by="admin", ttl_hours=24)
    found = await repo.find_by_token(created["token"])
    assert found is not None
    assert found["_id"] == created["_id"]


@pytest.mark.asyncio
async def test_find_by_token_returns_none_for_unknown(db):
    repo = InvitationRepository(db)
    await repo.create_indexes()
    assert await repo.find_by_token("nonexistent-token") is None


@pytest.mark.asyncio
async def test_mark_used_atomic_only_once(db):
    """find_one_and_update with the used:false filter must only succeed once."""
    repo = InvitationRepository(db)
    await repo.create_indexes()
    created = await repo.create(created_by="admin", ttl_hours=24)
    first = await repo.mark_used_atomic(created["token"], used_by_user_id="user-1")
    second = await repo.mark_used_atomic(created["token"], used_by_user_id="user-2")
    assert first is not None
    assert first["used"] is True
    assert first["used_by_user_id"] == "user-1"
    assert second is None  # second attempt finds no eligible doc


@pytest.mark.asyncio
async def test_mark_used_atomic_skips_expired(db):
    """An expired token must not be markable, even if unused."""
    repo = InvitationRepository(db)
    await repo.create_indexes()
    # Create with negative TTL so it's already expired
    created = await repo.create(created_by="admin", ttl_hours=-1)
    result = await repo.mark_used_atomic(created["token"], used_by_user_id="user-1")
    assert result is None


@pytest.mark.asyncio
async def test_indexes_created(db):
    repo = InvitationRepository(db)
    await repo.create_indexes()
    indexes = await db["invitation_tokens"].index_information()
    # Unique index on token
    assert any(idx.get("unique") and idx["key"] == [("token", 1)] for idx in indexes.values())
    # TTL index on expires_at
    assert any(
        idx.get("expireAfterSeconds") == 0 and idx["key"] == [("expires_at", 1)]
        for idx in indexes.values()
    )
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `docker compose run --rm backend uv run pytest backend/tests/modules/user/test_invitation_repository.py -v`
Expected: ImportError (`InvitationRepository` not defined)

- [ ] **Step 4: Implement the repository**

Create `backend/modules/user/_invitation_repository.py`:

```python
"""Repository for one-time admin-generated invitation tokens.

A token authorises exactly one self-registration. The unique index on
`token` and the TTL index on `expires_at` are both applied at startup
via the module-level `init_indexes` hook.
"""

from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone

from motor.motor_asyncio import AsyncIOMotorDatabase
from pymongo import ASCENDING


class InvitationRepository:
    """CRUD for `invitation_tokens` collection."""

    def __init__(self, db: AsyncIOMotorDatabase) -> None:
        self._collection = db["invitation_tokens"]

    async def create_indexes(self) -> None:
        # Unique index ensures token uniqueness and supports fast lookup.
        await self._collection.create_index([("token", ASCENDING)], unique=True)
        # TTL index removes documents 24h after expires_at automatically.
        # MongoDB sweeps once per minute. Setting expireAfterSeconds=0 means
        # the document is removed when expires_at is in the past.
        await self._collection.create_index(
            [("expires_at", ASCENDING)], expireAfterSeconds=0
        )

    async def create(self, *, created_by: str, ttl_hours: int = 24) -> dict:
        now = datetime.now(timezone.utc)
        doc = {
            "token": secrets.token_urlsafe(32),
            "created_at": now,
            "expires_at": now + timedelta(hours=ttl_hours),
            "used": False,
            "used_at": None,
            "used_by_user_id": None,
            "created_by": created_by,
        }
        result = await self._collection.insert_one(doc)
        doc["_id"] = result.inserted_id
        return doc

    async def find_by_token(self, token: str) -> dict | None:
        return await self._collection.find_one({"token": token})

    async def mark_used_atomic(
        self,
        token: str,
        *,
        used_by_user_id: str,
        session=None,
    ) -> dict | None:
        """Atomically mark the token as used.

        Filter requires `used: false` AND `expires_at > now`, so this returns
        None if the token is already consumed, expired, or unknown. Callers
        rely on the None return value as the rejection signal — there is no
        distinct error type because the cause does not matter at the call
        site (always 410 Gone).
        """
        now = datetime.now(timezone.utc)
        return await self._collection.find_one_and_update(
            {"token": token, "used": False, "expires_at": {"$gt": now}},
            {
                "$set": {
                    "used": True,
                    "used_at": now,
                    "used_by_user_id": used_by_user_id,
                }
            },
            return_document=True,  # ReturnDocument.AFTER
            session=session,
        )
```

Note: `return_document=True` is the boolean form. If the linter prefers, swap for `from pymongo import ReturnDocument` then `return_document=ReturnDocument.AFTER`.

- [ ] **Step 5: Run repo tests in Docker — verify they pass**

Run: `docker compose run --rm backend uv run pytest backend/tests/modules/user/test_invitation_repository.py -v`
Expected: all 6 tests pass

- [ ] **Step 6: Wire indexes into module init**

Modify `backend/modules/user/__init__.py`. Add the import:

```python
from backend.modules.user._invitation_repository import InvitationRepository
```

Find the `init_indexes(db)` function and append:

```python
    await InvitationRepository(db).create_indexes()
```

Also add `InvitationRepository` to the module's exported public surface (the `__all__` list if present, or just ensure the import is at module level so `from backend.modules.user import InvitationRepository` works).

- [ ] **Step 7: Commit**

```bash
git add backend/modules/user/_models.py backend/modules/user/_invitation_repository.py backend/modules/user/__init__.py backend/tests/modules/user/test_invitation_repository.py
git commit -m "Add InvitationRepository with TTL and unique-token indexes

Data layer for one-time admin-generated invitation links. Atomic
mark_used_atomic returns None for already-consumed/expired/unknown
tokens; callers translate that to 410 Gone."
```

---

## Task 3: Backend — Shared contracts (DTOs, topics, events)

Define the wire format before any endpoint or frontend code.

**Files:**
- Create: `shared/dtos/invitation.py`
- Modify: `shared/topics.py` (add two constants)
- Modify: `shared/events/auth.py` (add two event classes)

- [ ] **Step 1: Create the DTOs**

Create `shared/dtos/invitation.py`:

```python
"""DTOs for one-time invitation-link self-registration."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, EmailStr, Field


class CreateInvitationResponseDto(BaseModel):
    """Returned to admins after they generate a fresh invitation link.

    The URL itself is built client-side from `window.location.origin` so
    the backend does not need to know its public hostname.
    """
    token: str
    expires_at: datetime


class ValidateInvitationResponseDto(BaseModel):
    """Public response from POST /api/invitations/{token}/validate.

    The HTTP status is always 200 — the reason lives in the body to prevent
    enumeration via response codes.
    """
    valid: bool
    reason: Literal["expired", "used", "not_found"] | None = None


class RegisterViaInvitationRequestDto(BaseModel):
    """Submitted by the unauthenticated user during self-registration."""
    username: str = Field(min_length=3, max_length=64)
    email: EmailStr
    display_name: str = Field(min_length=1, max_length=128)
    h_auth: str        # client-derived Argon2 hash, urlsafe-base64
    h_kek: str         # client-derived KEK, urlsafe-base64
    recovery_key: str  # client-generated; backend wraps DEK with this


class RegisterViaInvitationResponseDto(BaseModel):
    success: bool
    user_id: str
```

- [ ] **Step 2: Add topic constants**

Modify `shared/topics.py`. Add (preserve existing ordering/grouping conventions in the file):

```python
class Topics:
    # ... existing ...
    INVITATION_CREATED = "user.invitation.created"
    INVITATION_USED = "user.invitation.used"
```

Place these alongside other `user.*` topics if grouping is by prefix.

- [ ] **Step 3: Add event classes**

Modify `shared/events/auth.py`. Append:

```python
class InvitationCreatedEvent(BaseModel):
    """Emitted when an admin generates a fresh invitation link."""
    token_id: str
    created_by: str    # admin user id
    expires_at: datetime


class InvitationUsedEvent(BaseModel):
    """Emitted when a user successfully registers via an invitation link."""
    token_id: str
    used_by_user_id: str
```

If `datetime` is not already imported, add it.

- [ ] **Step 4: Verify imports compile**

Run: `cd backend && uv run python -c "from shared.dtos.invitation import CreateInvitationResponseDto, ValidateInvitationResponseDto, RegisterViaInvitationRequestDto, RegisterViaInvitationResponseDto; from shared.topics import Topics; assert Topics.INVITATION_CREATED == 'user.invitation.created'; from shared.events.auth import InvitationCreatedEvent, InvitationUsedEvent; print('ok')"`

Expected: `ok`

- [ ] **Step 5: Commit**

```bash
git add shared/dtos/invitation.py shared/topics.py shared/events/auth.py
git commit -m "Add shared contracts for invitation-token flow

Three DTOs (create response, validate response, register request/response)
plus two events (created, used) and topic constants. Validate responses
always return HTTP 200 with reason in body to defeat enumeration."
```

---

## Task 4: Backend — `POST /api/admin/invitations` endpoint

Admin-only generation. TDD with one failing test, then minimal implementation.

**Files:**
- Create: `backend/modules/user/_invitation_handlers.py`
- Modify: `backend/modules/user/_handlers.py` (mount the new sub-router OR add to existing router — see Step 4)
- Test: `backend/tests/modules/user/test_invitation_endpoints.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/modules/user/test_invitation_endpoints.py`:

```python
import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_create_invitation_returns_token_and_expiry(client_admin: AsyncClient):
    resp = await client_admin.post("/api/admin/invitations", json={})
    assert resp.status_code == 201
    body = resp.json()
    assert "token" in body and len(body["token"]) >= 32
    assert "expires_at" in body


@pytest.mark.asyncio
async def test_create_invitation_requires_admin(client_user: AsyncClient):
    resp = await client_user.post("/api/admin/invitations", json={})
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_create_invitation_unauthenticated(client_anon: AsyncClient):
    resp = await client_anon.post("/api/admin/invitations", json={})
    assert resp.status_code == 401
```

The `client_admin`, `client_user`, `client_anon` fixtures must already exist for similar admin-endpoint tests in `backend/tests/`. If not, look at `backend/tests/conftest.py` and copy the fixture pattern from existing admin endpoint tests (e.g. tests of `POST /api/admin/users`).

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose run --rm backend uv run pytest backend/tests/modules/user/test_invitation_endpoints.py -v`
Expected: 404 (endpoint not registered) or import error

- [ ] **Step 3: Create the handlers file**

Create `backend/modules/user/_invitation_handlers.py`:

```python
"""HTTP handlers for invitation tokens.

Three endpoints:
- POST /api/admin/invitations         (admin-only, generate fresh token)
- POST /api/invitations/{t}/validate  (public, check status)
- POST /api/invitations/{t}/register  (public, atomic register-and-mark)

The register endpoint runs inside a MongoDB transaction so token-mark
and user/key creation are all-or-nothing.
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pymongo.errors import DuplicateKeyError

from backend.database import get_db, get_mongo_client
from backend.modules.user._auth import require_admin
from backend.modules.user._audit import AuditRepository
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
from shared.events.system import AuditLoggedEvent
from shared.topics import Topics

router = APIRouter(prefix="/api")


def _invitation_repo() -> InvitationRepository:
    return InvitationRepository(get_db())


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

    audit = AuditRepository(get_db())
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
            created_by=user["sub"],
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
```

- [ ] **Step 4: Mount the new router**

In `backend/main.py`, find where `user_router` is included (search for `user_router`). Add:

```python
from backend.modules.user._invitation_handlers import router as invitation_router
# ... near the other app.include_router calls ...
app.include_router(invitation_router)
```

Both routers share the `/api` prefix. They do not collide — different paths.

- [ ] **Step 5: Run the test — verify it passes**

Run: `docker compose run --rm backend uv run pytest backend/tests/modules/user/test_invitation_endpoints.py::test_create_invitation_returns_token_and_expiry backend/tests/modules/user/test_invitation_endpoints.py::test_create_invitation_requires_admin backend/tests/modules/user/test_invitation_endpoints.py::test_create_invitation_unauthenticated -v`

Expected: all 3 pass

- [ ] **Step 6: Commit**

```bash
git add backend/modules/user/_invitation_handlers.py backend/main.py backend/tests/modules/user/test_invitation_endpoints.py
git commit -m "Add POST /api/admin/invitations endpoint

Generates a fresh token-urlsafe(32) value, persists it with 24h TTL,
publishes audit + invitation-created event. Admin-only; URL is built
client-side from window.location.origin."
```

---

## Task 5: Backend — `POST /api/invitations/{token}/validate` endpoint

Public, no auth, always returns HTTP 200 with reason in body.

**Files:**
- Modify: `backend/modules/user/_invitation_handlers.py`
- Modify: `backend/tests/modules/user/test_invitation_endpoints.py`

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/modules/user/test_invitation_endpoints.py`:

```python
@pytest.mark.asyncio
async def test_validate_returns_valid_for_fresh_token(client_admin, client_anon):
    create_resp = await client_admin.post("/api/admin/invitations", json={})
    token = create_resp.json()["token"]

    resp = await client_anon.post(f"/api/invitations/{token}/validate")
    assert resp.status_code == 200
    body = resp.json()
    assert body == {"valid": True, "reason": None}


@pytest.mark.asyncio
async def test_validate_returns_not_found_for_unknown(client_anon):
    resp = await client_anon.post("/api/invitations/garbage-token/validate")
    assert resp.status_code == 200
    body = resp.json()
    assert body == {"valid": False, "reason": "not_found"}


@pytest.mark.asyncio
async def test_validate_returns_expired(client_admin, client_anon, db):
    create_resp = await client_admin.post("/api/admin/invitations", json={})
    token = create_resp.json()["token"]

    # Backdate the token so it is expired
    from datetime import datetime, timezone
    await db["invitation_tokens"].update_one(
        {"token": token},
        {"$set": {"expires_at": datetime(2020, 1, 1, tzinfo=timezone.utc)}},
    )

    resp = await client_anon.post(f"/api/invitations/{token}/validate")
    assert resp.status_code == 200
    assert resp.json() == {"valid": False, "reason": "expired"}


@pytest.mark.asyncio
async def test_validate_returns_used(client_admin, client_anon, db):
    create_resp = await client_admin.post("/api/admin/invitations", json={})
    token = create_resp.json()["token"]

    await db["invitation_tokens"].update_one(
        {"token": token}, {"$set": {"used": True}}
    )

    resp = await client_anon.post(f"/api/invitations/{token}/validate")
    assert resp.status_code == 200
    assert resp.json() == {"valid": False, "reason": "used"}


@pytest.mark.asyncio
async def test_validate_status_always_200(client_admin, client_anon, db):
    """No HTTP-code enumeration possible across not_found / used / expired."""
    # not_found
    r1 = await client_anon.post("/api/invitations/never-existed/validate")
    # used
    create_resp = await client_admin.post("/api/admin/invitations", json={})
    token = create_resp.json()["token"]
    await db["invitation_tokens"].update_one({"token": token}, {"$set": {"used": True}})
    r2 = await client_anon.post(f"/api/invitations/{token}/validate")
    assert r1.status_code == r2.status_code == 200
```

- [ ] **Step 2: Run tests — verify they fail**

Run: `docker compose run --rm backend uv run pytest backend/tests/modules/user/test_invitation_endpoints.py -v -k validate`
Expected: 404 (endpoint not registered)

- [ ] **Step 3: Implement the validate endpoint**

Append to `backend/modules/user/_invitation_handlers.py`:

```python
@router.post(
    "/invitations/{token}/validate",
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
```

- [ ] **Step 4: Run validate tests — verify all pass**

Run: `docker compose run --rm backend uv run pytest backend/tests/modules/user/test_invitation_endpoints.py -v -k validate`
Expected: all 5 validate tests pass

- [ ] **Step 5: Commit**

```bash
git add backend/modules/user/_invitation_handlers.py backend/tests/modules/user/test_invitation_endpoints.py
git commit -m "Add POST /api/invitations/{token}/validate endpoint

Public, always returns HTTP 200; reason lives in body so the response
code never leaks whether the token is unknown, used, or expired."
```

---

## Task 6: Backend — `POST /api/invitations/{token}/register` endpoint with transaction

The atomic mark-and-create. This is the most security-critical task.

**Files:**
- Modify: `backend/modules/user/_invitation_handlers.py`
- Modify: `backend/modules/user/_handlers.py` (export `_provision_new_user` for cross-file use OR move it to a shared module-internal location)
- Modify: `backend/tests/modules/user/test_invitation_endpoints.py`

- [ ] **Step 1: Make `_provision_new_user` importable**

In `backend/modules/user/_handlers.py`, ensure `_provision_new_user` is module-level (it is, from Task 1). Confirm it can be imported as:

```python
from backend.modules.user._handlers import _provision_new_user
```

If the file structure makes that awkward (circular import, etc.), move the helper to a new file `backend/modules/user/_provisioning.py` instead, and re-import it in `_handlers.py`. Use the simpler option that works.

- [ ] **Step 2: Write the failing tests**

Append to `backend/tests/modules/user/test_invitation_endpoints.py`. These tests use real client-derived h_auth/h_kek values — copy the helper from existing setup tests if one exists (search `backend/tests/` for `derive_auth_kek` or similar). If no helper exists, the simplest path is to use fixed test vectors:

```python
import asyncio
import base64
import secrets


def _make_register_body(username: str = "alice", email: str = "alice@example.com"):
    """Test vectors mirroring what a real client would send."""
    # Real clients derive these from password+salt via Argon2. For these
    # backend-only tests we can use fixed strings — the handler does not
    # validate cryptographic content, only forwards to the helper which
    # does its own validation against the freshly-generated user_keys doc.
    return {
        "username": username,
        "email": email,
        "display_name": "Alice",
        "h_auth": base64.urlsafe_b64encode(secrets.token_bytes(32)).decode(),
        "h_kek": base64.urlsafe_b64encode(secrets.token_bytes(32)).decode(),
        "recovery_key": secrets.token_urlsafe(24),
    }


@pytest.mark.asyncio
async def test_register_creates_user_and_marks_token_used(client_admin, client_anon, db):
    create_resp = await client_admin.post("/api/admin/invitations", json={})
    token = create_resp.json()["token"]

    body = _make_register_body()
    resp = await client_anon.post(f"/api/invitations/{token}/register", json=body)
    assert resp.status_code == 200
    out = resp.json()
    assert out["success"] is True
    assert out["user_id"]

    # Token now used
    doc = await db["invitation_tokens"].find_one({"token": token})
    assert doc["used"] is True
    assert doc["used_by_user_id"] == out["user_id"]

    # User created with role=user
    user = await db["users"].find_one({"_id": out["user_id"]})
    if user is None:
        from bson import ObjectId
        user = await db["users"].find_one({"_id": ObjectId(out["user_id"])})
    assert user is not None
    assert user["role"] == "user"
    assert user["must_change_password"] is False


@pytest.mark.asyncio
async def test_register_with_used_token_returns_410(client_admin, client_anon):
    create_resp = await client_admin.post("/api/admin/invitations", json={})
    token = create_resp.json()["token"]

    # Use it once
    await client_anon.post(f"/api/invitations/{token}/register", json=_make_register_body("bob1", "bob1@example.com"))
    # Try again
    resp = await client_anon.post(f"/api/invitations/{token}/register", json=_make_register_body("bob2", "bob2@example.com"))
    assert resp.status_code == 410


@pytest.mark.asyncio
async def test_register_with_unknown_token_returns_410(client_anon):
    resp = await client_anon.post(
        "/api/invitations/garbage-token/register",
        json=_make_register_body(),
    )
    assert resp.status_code == 410


@pytest.mark.asyncio
async def test_register_with_expired_token_returns_410(client_admin, client_anon, db):
    create_resp = await client_admin.post("/api/admin/invitations", json={})
    token = create_resp.json()["token"]

    from datetime import datetime, timezone
    await db["invitation_tokens"].update_one(
        {"token": token},
        {"$set": {"expires_at": datetime(2020, 1, 1, tzinfo=timezone.utc)}},
    )

    resp = await client_anon.post(
        f"/api/invitations/{token}/register",
        json=_make_register_body(),
    )
    assert resp.status_code == 410


@pytest.mark.asyncio
async def test_register_username_collision_returns_409_and_token_unused(
    client_admin, client_anon, db
):
    # Pre-create a user named "taken"
    await client_admin.post(
        "/api/admin/users",
        json={"username": "taken", "email": "taken@example.com", "display_name": "T", "role": "user"},
    )

    create_resp = await client_admin.post("/api/admin/invitations", json={})
    token = create_resp.json()["token"]

    body = _make_register_body(username="taken", email="other@example.com")
    resp = await client_anon.post(f"/api/invitations/{token}/register", json=body)
    assert resp.status_code == 409

    # Token MUST still be usable (transaction rollback)
    doc = await db["invitation_tokens"].find_one({"token": token})
    assert doc["used"] is False, "Token was marked used despite registration failing — rollback broken"


@pytest.mark.asyncio
async def test_register_concurrent_same_token_only_one_succeeds(client_admin, client_anon):
    create_resp = await client_admin.post("/api/admin/invitations", json={})
    token = create_resp.json()["token"]

    body_a = _make_register_body("conc-a", "a@example.com")
    body_b = _make_register_body("conc-b", "b@example.com")

    results = await asyncio.gather(
        client_anon.post(f"/api/invitations/{token}/register", json=body_a),
        client_anon.post(f"/api/invitations/{token}/register", json=body_b),
        return_exceptions=False,
    )
    statuses = sorted(r.status_code for r in results)
    assert statuses == [200, 410], f"Expected exactly one 200 and one 410, got {statuses}"


@pytest.mark.asyncio
async def test_register_creates_user_with_role_user_no_escalation(
    client_admin, client_anon, db
):
    """An invitation token can NEVER create an admin or master_admin."""
    create_resp = await client_admin.post("/api/admin/invitations", json={})
    token = create_resp.json()["token"]

    body = _make_register_body("regularalice", "regular@example.com")
    resp = await client_anon.post(f"/api/invitations/{token}/register", json=body)
    assert resp.status_code == 200
    user_id = resp.json()["user_id"]

    user = await db["users"].find_one({"_id": user_id})
    if user is None:
        from bson import ObjectId
        user = await db["users"].find_one({"_id": ObjectId(user_id)})
    assert user["role"] == "user"
    assert user["role"] != "admin"
    assert user["role"] != "master_admin"
```

- [ ] **Step 3: Run tests — verify they fail**

Run: `docker compose run --rm backend uv run pytest backend/tests/modules/user/test_invitation_endpoints.py -v -k register`
Expected: 404 / NotImplementedError

- [ ] **Step 4: Implement register with MongoDB transaction**

Append to `backend/modules/user/_invitation_handlers.py`:

```python
from backend.modules.user._handlers import _provision_new_user
from backend.modules.user._key_service import UserKeyService


@router.post(
    "/invitations/{token}/register",
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
    usable). Returns 200 with the new user_id on success — NO auto-login;
    the user navigates to /login themselves.
    """
    db = get_db()
    repo = InvitationRepository(db)
    users_repo = UserRepository(db)
    svc = UserKeyService(db)

    client = get_mongo_client()
    async with await client.start_session() as session:
        try:
            async with session.start_transaction():
                marked = await repo.mark_used_atomic(
                    token,
                    used_by_user_id="pending",  # patched below
                    session=session,
                )
                if marked is None:
                    raise HTTPException(
                        status_code=410,
                        detail="invitation_invalid",
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
                    )
                except DuplicateKeyError:
                    raise HTTPException(
                        status_code=409,
                        detail="username_or_email_taken",
                    )

                user_id = str(user_doc["_id"])
                # Patch the token doc with the real user id
                await db["invitation_tokens"].update_one(
                    {"_id": marked["_id"]},
                    {"$set": {"used_by_user_id": user_id}},
                    session=session,
                )
        except HTTPException:
            raise

    # Side effects after the transaction commits — outside the txn so a
    # failed audit-log write does not roll back the whole registration.
    audit = AuditRepository(db)
    await audit.log(
        actor_id=user_id,
        action="user.invitation_used",
        resource_type="invitation",
        resource_id=str(marked["_id"]),
        detail={},
    )
    await event_bus.publish(
        Topics.INVITATION_USED,
        InvitationUsedEvent(
            token_id=str(marked["_id"]),
            used_by_user_id=user_id,
        ),
    )
    await event_bus.publish(
        Topics.AUDIT_LOGGED,
        AuditLoggedEvent(
            actor_id=user_id,
            action="user.invitation_used",
            resource_type="invitation",
            resource_id=str(marked["_id"]),
            detail={},
        ),
    )

    return RegisterViaInvitationResponseDto(success=True, user_id=user_id)
```

If `get_mongo_client` does not exist in `backend/database.py`, search for how transactions are used elsewhere in the codebase (`grep -rn "start_transaction\|start_session" backend/`) and follow the existing pattern. The Motor client is typically held alongside `get_db()`.

- [ ] **Step 5: Run all register tests in Docker**

Run: `docker compose run --rm backend uv run pytest backend/tests/modules/user/test_invitation_endpoints.py -v -k register`
Expected: all 7 register tests pass

- [ ] **Step 6: Run full invitation test file**

Run: `docker compose run --rm backend uv run pytest backend/tests/modules/user/test_invitation_endpoints.py -v`
Expected: all tests pass (admin endpoint + validate + register)

- [ ] **Step 7: Smoke test that existing setup is still intact**

Run: `docker compose run --rm backend uv run pytest backend/tests/modules/user/test_handlers.py -k 'setup' -v`
Expected: all existing setup tests pass

- [ ] **Step 8: Commit**

```bash
git add backend/modules/user/_invitation_handlers.py backend/tests/modules/user/test_invitation_endpoints.py
git commit -m "Add POST /api/invitations/{token}/register with atomic transaction

Token mark-used and user/key provisioning happen inside a single MongoDB
transaction. Username collisions trigger 409 with the token rolled back
to unused. Concurrent requests on the same token: exactly one wins, the
other gets 410. Always creates role=user — no privilege escalation
surface."
```

---

## Task 7: Frontend — Invitation API client

Add the typed client wrappers before any UI code.

**Files:**
- Modify: `frontend/src/core/api/auth.ts` (extend `authApi` object)

- [ ] **Step 1: Add the new client methods**

In `frontend/src/core/api/auth.ts`, add inside the `authApi` object (after the existing `setup` method):

```typescript
async validateInvitation(token: string): Promise<{ valid: boolean; reason?: 'expired' | 'used' | 'not_found' }> {
  return apiRequest<{ valid: boolean; reason?: 'expired' | 'used' | 'not_found' }>(
    "POST",
    `/api/invitations/${encodeURIComponent(token)}/validate`,
    undefined,
    true,  // public, no auth
  )
},

async registerWithInvitation(
  token: string,
  opts: { username: string; email: string; displayName: string; password: string },
): Promise<{ recoveryKey: string; userId: string }> {
  // Mirrors the setup() flow above, minus the PIN, gated by the token in the URL.
  // Recovery key is generated client-side; the server never sees the password.
  const params = await fetchKdfParams(opts.username)
  const salt = fromBase64Url(params.kdf_salt)
  const { hAuth, hKek } = await deriveAuthAndKek(opts.password, salt, params.kdf_params)
  const recoveryKey = generateRecoveryKey()
  const resp = await apiRequest<{ success: boolean; user_id: string }>(
    "POST",
    `/api/invitations/${encodeURIComponent(token)}/register`,
    {
      username: opts.username,
      email: opts.email,
      display_name: opts.displayName,
      h_auth: toBase64Url(hAuth),
      h_kek: toBase64Url(hKek),
      recovery_key: recoveryKey,
    },
    true,  // public, no auth
  )
  return { recoveryKey, userId: resp.user_id }
},

async createInvitation(): Promise<{ token: string; expiresAt: string }> {
  const resp = await apiRequest<{ token: string; expires_at: string }>(
    "POST",
    "/api/admin/invitations",
    {},
  )
  return { token: resp.token, expiresAt: resp.expires_at }
},
```

- [ ] **Step 2: Verify TypeScript build**

Run: `cd frontend && pnpm run build`
Expected: build succeeds with no type errors

- [ ] **Step 3: Commit**

```bash
git add frontend/src/core/api/auth.ts
git commit -m "Add invitation-token API client methods

validateInvitation, registerWithInvitation (mirrors setup flow with
client-side Argon2 derivation), and createInvitation for the admin trigger."
```

---

## Task 8: Frontend — RegisterPage component

The user-facing /register/:token page in opulent style. State machine: validating → form → recovery-key → success (or invalid).

**Files:**
- Create: `frontend/src/app/pages/RegisterPage.tsx`
- (route wiring in next task)

- [ ] **Step 1: Read the LoginPage setup block as reference**

Open `frontend/src/app/pages/LoginPage.tsx` and locate the setup-mode form (around lines 300-400 based on earlier grep). Read it end to end. The new RegisterPage mirrors this layout but:
- Replaces the PIN input with token validation on mount
- Submits via `authApi.registerWithInvitation` instead of `useAuth().setup`
- Success screen ends with a manual "Go to login" button instead of auto-redirecting to /personas

- [ ] **Step 2: Create the RegisterPage**

Create `frontend/src/app/pages/RegisterPage.tsx`:

```tsx
import { useEffect, useState } from "react"
import { useParams, Link, useNavigate } from "react-router-dom"

import { authApi } from "../../core/api/auth"
import { RecoveryKeyModal } from "../../features/auth/RecoveryKeyModal"

type Phase =
  | { kind: "validating" }
  | { kind: "invalid"; reason: "expired" | "used" | "not_found" }
  | { kind: "form" }
  | { kind: "submitting" }
  | { kind: "recovery-key"; key: string }
  | { kind: "success" }

const REASON_TEXT: Record<"expired" | "used" | "not_found", string> = {
  expired: "This invitation link has expired.",
  used: "This invitation link has already been used.",
  not_found: "This invitation link is no longer valid.",
}

export default function RegisterPage() {
  const { token = "" } = useParams<{ token: string }>()
  const navigate = useNavigate()

  const [phase, setPhase] = useState<Phase>({ kind: "validating" })
  const [username, setUsername] = useState("")
  const [email, setEmail] = useState("")
  const [displayName, setDisplayName] = useState("")
  const [password, setPassword] = useState("")
  const [confirm, setConfirm] = useState("")
  const [showPassword, setShowPassword] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [fieldError, setFieldError] = useState<{ field: string; msg: string } | null>(null)

  // Validate the token on mount
  useEffect(() => {
    let cancelled = false
    void (async () => {
      try {
        const r = await authApi.validateInvitation(token)
        if (cancelled) return
        if (r.valid) {
          setPhase({ kind: "form" })
        } else {
          setPhase({ kind: "invalid", reason: r.reason ?? "not_found" })
        }
      } catch {
        if (!cancelled) setPhase({ kind: "invalid", reason: "not_found" })
      }
    })()
    return () => {
      cancelled = true
    }
  }, [token])

  const passwordStrength = scorePassword(password)

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault()
    setError(null)
    setFieldError(null)
    if (password !== confirm) {
      setFieldError({ field: "confirm", msg: "Passwords do not match." })
      return
    }
    if (passwordStrength < 3) {
      setFieldError({ field: "password", msg: "Password is too weak." })
      return
    }
    setPhase({ kind: "submitting" })
    try {
      const { recoveryKey } = await authApi.registerWithInvitation(token, {
        username,
        email,
        displayName,
        password,
      })
      setPhase({ kind: "recovery-key", key: recoveryKey })
    } catch (err: any) {
      const status = err?.status ?? err?.response?.status
      if (status === 410) {
        setPhase({ kind: "invalid", reason: "used" })
      } else if (status === 409) {
        setFieldError({ field: "username", msg: "Username or email already taken." })
        setPhase({ kind: "form" })
      } else {
        setError("Something went wrong. Please try again.")
        setPhase({ kind: "form" })
      }
    }
  }

  return (
    <div className="min-h-screen bg-[#0a0814] text-white/85">
      <div className="mx-auto flex min-h-screen max-w-md flex-col items-center justify-center px-6 py-12">
        <h1 className="mb-8 text-3xl font-serif tracking-tight text-white">
          Welcome to Chatsune
        </h1>

        {phase.kind === "validating" && <p className="text-white/60">Checking invitation…</p>}

        {phase.kind === "invalid" && (
          <div className="w-full rounded-lg border border-white/10 bg-white/[0.03] p-6 text-center">
            <p className="mb-4 text-white/80">{REASON_TEXT[phase.reason]}</p>
            <Link
              to="/login"
              className="inline-block rounded-md border border-white/15 px-4 py-2 text-sm hover:bg-white/[0.06]"
            >
              Go to login
            </Link>
          </div>
        )}

        {(phase.kind === "form" || phase.kind === "submitting") && (
          <form onSubmit={onSubmit} className="w-full space-y-4">
            <Field label="Username">
              <input
                type="text"
                required
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                className="w-full rounded-md border border-white/10 bg-white/[0.04] px-3 py-2"
              />
              {fieldError?.field === "username" && (
                <p className="mt-1 text-xs text-rose-300">{fieldError.msg}</p>
              )}
            </Field>
            <Field label="Email">
              <input
                type="email"
                required
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                className="w-full rounded-md border border-white/10 bg-white/[0.04] px-3 py-2"
              />
            </Field>
            <Field label="Display name">
              <input
                type="text"
                required
                value={displayName}
                onChange={(e) => setDisplayName(e.target.value)}
                className="w-full rounded-md border border-white/10 bg-white/[0.04] px-3 py-2"
              />
            </Field>
            <Field label="Password">
              <div className="relative">
                <input
                  type={showPassword ? "text" : "password"}
                  required
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  className="w-full rounded-md border border-white/10 bg-white/[0.04] px-3 py-2 pr-16"
                />
                <button
                  type="button"
                  onClick={() => setShowPassword((s) => !s)}
                  className="absolute right-2 top-1/2 -translate-y-1/2 text-xs text-white/50 hover:text-white/80"
                >
                  {showPassword ? "Hide" : "Show"}
                </button>
              </div>
              <StrengthBar score={passwordStrength} />
              {fieldError?.field === "password" && (
                <p className="mt-1 text-xs text-rose-300">{fieldError.msg}</p>
              )}
            </Field>
            <Field label="Confirm password">
              <input
                type={showPassword ? "text" : "password"}
                required
                value={confirm}
                onChange={(e) => setConfirm(e.target.value)}
                className="w-full rounded-md border border-white/10 bg-white/[0.04] px-3 py-2"
              />
              {fieldError?.field === "confirm" && (
                <p className="mt-1 text-xs text-rose-300">{fieldError.msg}</p>
              )}
            </Field>
            {error && <p className="text-sm text-rose-300">{error}</p>}
            <button
              type="submit"
              disabled={phase.kind === "submitting"}
              className="w-full rounded-md bg-white/10 py-2.5 text-sm font-medium hover:bg-white/15 disabled:opacity-50"
            >
              {phase.kind === "submitting" ? "Creating account…" : "Create account"}
            </button>
          </form>
        )}

        {phase.kind === "recovery-key" && (
          <RecoveryKeyModal
            recoveryKey={phase.key}
            onAcknowledged={() => setPhase({ kind: "success" })}
          />
        )}

        {phase.kind === "success" && (
          <div className="w-full rounded-lg border border-white/10 bg-white/[0.03] p-6 text-center">
            <p className="mb-4 text-white/80">
              Account created. You can now log in.
            </p>
            <button
              onClick={() => navigate("/login")}
              className="inline-block rounded-md border border-white/15 px-4 py-2 text-sm hover:bg-white/[0.06]"
            >
              Go to login
            </button>
          </div>
        )}
      </div>
    </div>
  )
}

// see also: LoginPage setup block — these helpers will be lifted to a shared
// hook on third use (rule of three). For now: deliberate duplication.

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <span className="mb-1 block text-xs uppercase tracking-wide text-white/50">{label}</span>
      {children}
    </label>
  )
}

function scorePassword(pw: string): number {
  // Simple heuristic 0-4. Not a security control — server cannot validate
  // because of BYO-key. This only protects users from typos and one-class
  // passwords.
  let score = 0
  if (pw.length >= 12) score++
  if (/[a-z]/.test(pw) && /[A-Z]/.test(pw)) score++
  if (/\d/.test(pw)) score++
  if (/[^A-Za-z0-9]/.test(pw)) score++
  return score
}

function StrengthBar({ score }: { score: number }) {
  const colours = ["bg-rose-500/60", "bg-orange-500/60", "bg-yellow-500/60", "bg-emerald-500/60"]
  return (
    <div className="mt-2 flex gap-1">
      {[0, 1, 2, 3].map((i) => (
        <div
          key={i}
          className={`h-1 flex-1 rounded ${i < score ? colours[Math.min(score - 1, 3)] : "bg-white/10"}`}
        />
      ))}
    </div>
  )
}
```

- [ ] **Step 3: Verify TypeScript build**

Run: `cd frontend && pnpm run build`
Expected: build succeeds

- [ ] **Step 4: Commit**

```bash
git add frontend/src/app/pages/RegisterPage.tsx
git commit -m "Add RegisterPage for invitation-link self-registration

Opulent-style page at /register/:token. State machine: validating →
form/invalid → submitting → recovery-key (modal reused from setup) →
success. No auto-login — user explicitly navigates to /login."
```

---

## Task 9: Frontend — Wire `/register/:token` route

**Files:**
- Modify: `frontend/src/App.tsx` (add public route outside `<RequireAuth>`)

- [ ] **Step 1: Add the route**

Open `frontend/src/App.tsx`. Find the `<Routes>` block (around line 99 from earlier grep). The setup pattern shows that `<Route path="/personas" .../>` lives inside an authenticated wrapper. The `/register/:token` route must be a sibling **outside** any auth guard.

Add the import at the top:

```tsx
import RegisterPage from "./app/pages/RegisterPage"
```

Then add the route inside `<Routes>`, BEFORE the catch-all `<Route path="*" ...>`:

```tsx
<Route path="/register/:token" element={<RegisterPage />} />
```

Place it next to the existing `<Route ...>` for login (whichever line is the public route closest to line 100 of `App.tsx`). The exact placement is fine as long as it is outside any auth-required wrapper.

- [ ] **Step 2: Verify TypeScript build**

Run: `cd frontend && pnpm run build`
Expected: build succeeds

- [ ] **Step 3: Commit**

```bash
git add frontend/src/App.tsx
git commit -m "Wire /register/:token public route to RegisterPage"
```

---

## Task 10: Frontend — "+ Invitation Link" admin button + dialog

**Files:**
- Create: `frontend/src/app/components/admin-modal/InvitationLinkDialog.tsx`
- Modify: `frontend/src/app/components/admin-modal/UsersTab.tsx` (add button next to "+ New User")

- [ ] **Step 1: Create the dialog component**

Create `frontend/src/app/components/admin-modal/InvitationLinkDialog.tsx`:

```tsx
import { useEffect, useMemo, useState } from "react"

interface Props {
  token: string
  expiresAt: string  // ISO 8601 from backend
  onClose: () => void
}

/**
 * Shown immediately after an admin generates an invitation link. The link is
 * NOT retrievable again — the user must copy it before closing the dialog.
 */
export function InvitationLinkDialog({ token, expiresAt, onClose }: Props) {
  const [copied, setCopied] = useState(false)

  const url = useMemo(
    () => `${window.location.origin}/register/${token}`,
    [token],
  )

  const expiresFormatted = useMemo(() => {
    try {
      return new Date(expiresAt).toLocaleString()
    } catch {
      return expiresAt
    }
  }, [expiresAt])

  async function copy() {
    try {
      await navigator.clipboard.writeText(url)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    } catch {
      // Clipboard blocked — user can still copy manually from the input
    }
  }

  // Esc to close (after they have presumably copied)
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose()
    }
    window.addEventListener("keydown", handler)
    return () => window.removeEventListener("keydown", handler)
  }, [onClose])

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
      <div className="w-full max-w-md rounded-lg border border-[#45475a] bg-[#1e1e2e] p-6 text-[#cdd6f4]">
        <h2 className="mb-3 text-base font-medium">New invitation link</h2>
        <p className="mb-2 text-sm text-[#a6adc8]">
          Share this link with the new user. It is valid for 24 hours and can
          be used exactly once.
        </p>
        <p className="mb-4 text-xs text-[#f9e2af]">
          Save it before closing — you cannot retrieve it again.
        </p>

        <input
          type="text"
          readOnly
          value={url}
          onFocus={(e) => e.target.select()}
          className="mb-3 w-full rounded border border-[#45475a] bg-[#11111b] px-3 py-2 font-mono text-xs"
        />

        <div className="mb-4 flex gap-2">
          <button
            onClick={copy}
            className="flex-1 rounded bg-[#89b4fa] px-3 py-1.5 text-sm font-medium text-[#1e1e2e] hover:bg-[#74c7ec]"
          >
            {copied ? "Copied!" : "Copy"}
          </button>
          <button
            onClick={onClose}
            className="rounded border border-[#45475a] px-3 py-1.5 text-sm hover:bg-[#313244]"
          >
            Close
          </button>
        </div>

        <p className="text-xs text-[#6c7086]">Expires: {expiresFormatted}</p>
      </div>
    </div>
  )
}
```

- [ ] **Step 2: Wire button into UsersTab**

Open `frontend/src/app/components/admin-modal/UsersTab.tsx` and find the line with `+ New User` (line 200 from earlier grep).

At the top of the file, add imports:

```tsx
import { useState } from "react"  // if not already imported
import { authApi } from "../../../core/api/auth"
import { InvitationLinkDialog } from "./InvitationLinkDialog"
```

Add state hooks alongside the existing `showNewForm` state:

```tsx
const [generating, setGenerating] = useState(false)
const [invitation, setInvitation] = useState<{ token: string; expiresAt: string } | null>(null)
const [genError, setGenError] = useState<string | null>(null)

async function generateInvitation() {
  setGenError(null)
  setGenerating(true)
  try {
    const result = await authApi.createInvitation()
    setInvitation(result)
  } catch {
    setGenError("Failed to generate invitation link.")
  } finally {
    setGenerating(false)
  }
}
```

Add the button immediately before the existing "+ New User" button (around line 200). The exact JSX depends on the surrounding layout, but it should look roughly like:

```tsx
<button
  onClick={generateInvitation}
  disabled={generating}
  className="rounded border border-[#45475a] px-3 py-1.5 text-sm hover:bg-[#313244] disabled:opacity-50"
>
  {generating ? "Generating…" : "+ Invitation Link"}
</button>
{/* existing "+ New User" button stays unchanged immediately after */}
```

If `genError` is set, render an inline error message near the buttons:

```tsx
{genError && <p className="mt-2 text-xs text-rose-300">{genError}</p>}
```

At the very end of the component's returned JSX (just before the outer closing tag), conditionally render the dialog:

```tsx
{invitation && (
  <InvitationLinkDialog
    token={invitation.token}
    expiresAt={invitation.expiresAt}
    onClose={() => setInvitation(null)}
  />
)}
```

- [ ] **Step 3: Verify TypeScript build**

Run: `cd frontend && pnpm run build`
Expected: build succeeds

- [ ] **Step 4: Commit**

```bash
git add frontend/src/app/components/admin-modal/InvitationLinkDialog.tsx frontend/src/app/components/admin-modal/UsersTab.tsx
git commit -m "Add admin '+ Invitation Link' button and dialog

Catppuccin-styled dialog with copy button, ISO-formatted expiry, and a
warning that the link cannot be retrieved again. URL built from
window.location.origin so localhost:5173 and prod hosts both work."
```

---

## Task 11: Manual verification + INSIGHTS notes + final cleanup

**Files:**
- Modify: `INSIGHTS.md` (two new entries)
- (No code changes — verification only)

- [ ] **Step 1: Spin up the full stack**

Run: `docker compose up -d` (or whatever the project's standard dev start is — check `README.md` if unsure)

Then start the frontend dev server: `cd frontend && pnpm dev`

- [ ] **Step 2: Token generation (manual)**

- Log in as master-admin at `http://localhost:5173/login`
- Open Admin modal → Users tab
- Click "+ Invitation Link"
- Confirm dialog appears with `http://localhost:5173/register/<token>` and an expiry timestamp
- Click "Copy", paste into a text editor, confirm correct URL
- Click "Close"

- [ ] **Step 3: Happy-path registration (manual)**

- Open the copied URL in a fresh incognito window
- Confirm "Checking invitation…" briefly, then registration form
- Fill in: username `tester1`, email `tester1@example.com`, display name `Tester One`, password `TestPassword123!`, same in confirm
- Watch strength bar reach green
- Submit
- Recovery-key modal appears — copy or download, click "I have saved it"
- Success screen with "Go to login" button — click it
- Land at `/login`, log in with `tester1` + `TestPassword123!`
- Land at `/personas` — registration successful end-to-end

- [ ] **Step 4: Token reuse (manual)**

- Open the same invitation URL again in another incognito window
- Confirm "This invitation link has already been used." + "Go to login" button

- [ ] **Step 5: Expired token (manual)**

- Generate a fresh token via the admin button
- Backdate it via mongo shell:
  ```
  docker compose exec mongodb mongosh chatsune --eval 'db.invitation_tokens.updateOne({token: "<the-token>"}, {$set: {expires_at: ISODate("2020-01-01T00:00:00Z")}})'
  ```
- Open the URL → confirm "This invitation link has expired."

- [ ] **Step 6: Unknown token (manual)**

- Open `http://localhost:5173/register/garbage-string-not-real`
- Confirm "This invitation link is no longer valid."
- Verify response shape via curl:
  ```bash
  curl -X POST -i http://localhost:8000/api/invitations/garbage/validate
  ```
- Confirm `HTTP/1.1 200 OK` and body `{"valid":false,"reason":"not_found"}`

- [ ] **Step 7: Concurrent race (manual)**

- Generate a fresh token
- Open the URL in two browser tabs side-by-side
- Fill out both forms with **different** usernames/emails
- Submit both as close to simultaneously as possible (Cmd+Enter / Ctrl+Enter in both)
- Confirm exactly one tab succeeds (recovery-key modal); the other shows "This invitation link has already been used."

- [ ] **Step 8: Username collision keeps token usable (manual)**

- Generate a fresh token
- Open URL, fill form with the username of an already-existing user
- Submit → see inline 409 error at username field
- **Important**: change to a unique username, submit again → success
- This proves the transaction rollback worked

- [ ] **Step 9: Existing flows still work (manual smoke)**

- Log out
- Confirm `/login` still works for existing users
- As admin, open Admin modal → Users tab → click "+ New User" (the existing button) → create a user the old way → confirm it still works

- [ ] **Step 10: Add INSIGHTS entries**

Append to `INSIGHTS.md` (use the next free INS-XXX number — check the file first):

```markdown
## INS-XXX — Server cannot enforce password strength (BYO-key constraint)

**Decision:** Password-strength validation lives entirely in the client.
The server has no knowledge of the plaintext password and therefore
cannot apply length/complexity/zxcvbn rules.

**Why:** Chatsune uses an end-to-end encrypted key schema. The client
derives `h_auth` (Argon2 hash for authentication) and `h_kek` (key
encryption key for wrapping the user's DEK) from the password locally.
Only those derived values reach the server. A server-side strength check
would require shipping the password itself, which would defeat the entire
BYO-key threat model.

**What this means in practice:**
- Strength meters and basic typo checks (length, character classes,
  confirm-password match) are client-side concerns.
- This applies to all account-creation flows: master-admin setup,
  invitation-token registration, change-password, recovery flow.
- A future "server enforces strength" change is not a small ticket — it
  would require fundamental rework of the auth scheme. Do not file it
  as a routine improvement.

## INS-XXX — Account-creation crypto duplicated; extract on third use

**Decision:** The form + Argon2 derivation + recovery-key generation
sequence currently lives in two places: the master-admin setup mode
in `LoginPage.tsx` and the new `RegisterPage.tsx` for invitation-token
self-registration. Both files carry a `// see also` comment pointing
at the other.

**Why duplicate:** Rule of three. Two implementations are easier to
keep correct than one premature abstraction whose seams may not
match the third use case.

**Trigger for extraction:** The third place that needs this sequence
(e.g. a hypothetical "join an existing org via link" flow, or a
multi-tenant invitation variant) is the cue to pull a shared
`useAccountSetup({ mode })` hook into `frontend/src/features/auth/`.
Until then, two copies are fine.
```

- [ ] **Step 11: Verify the spec acceptance criteria are all met**

Re-read `devdocs/specs/2026-04-27-invitation-tokens-design.md` → "Acceptance Criteria" section. Tick each one off mentally:

- Token works exactly once (Step 4 above)
- Expired token returns invalid/410 (Step 5)
- Registered user can log in (Step 3)
- Concurrent: one wins, one 410 (Step 7)
- Username collision → 409, token still usable (Step 8)
- Admin generates via UI, URL has correct host:port (Steps 2-3)
- Validate always 200 (Step 6)
- `/auth/setup` and `POST /admin/users` unchanged (Step 9 + Task 6 Step 7)
- Recovery key shown via reused modal (Step 3)
- No privilege-escalation surface (Task 6 test #7)

If any acceptance criterion fails: file a bug, fix it, re-run the affected manual step before declaring done.

- [ ] **Step 12: Final commit**

```bash
git add INSIGHTS.md
git commit -m "Add INSIGHTS entries for invitation-token feature

INS-XXX: server cannot enforce password strength (BYO-key constraint).
INS-XXX: account-creation crypto duplicated, extract on rule of three."
```

---

## Done

After Task 11 completes successfully:
- All 11 acceptance criteria from the spec are met
- Existing setup and admin-user-creation flows are untouched
- Server-side password-strength constraint and code-duplication trade-off are documented in INSIGHTS
- The feature is ready for tester rollout

The feature is **not** merged or pushed by this plan. The user (Chris) decides when and how to merge.
