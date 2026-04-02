# User Module & Authentication — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the user module with master admin setup, user management (CRUD + roles), JWT/refresh auth, audit log, and all shared contracts — the entire authentication foundation for Chatsune.

**Architecture:** Modular Monolith — the `user` module owns all user/auth/audit data in MongoDB. Refresh tokens live in Redis. All cross-module types live in `shared/`. FastAPI async-first throughout. Docker Compose provides MongoDB (RS0) + Redis + backend.

**Tech Stack:** Python 3.12, FastAPI, Pydantic v2, Motor (async MongoDB driver), redis.asyncio, PyJWT, bcrypt, uv (package manager), pytest + pytest-asyncio + httpx (testing), Docker Compose

---

## File Map

### New files to create

| File | Responsibility |
|---|---|
| `docker-compose.yml` | MongoDB RS0 + Redis + backend services |
| `backend/Dockerfile` | Backend container image |
| `.env.example` | Environment variable template |
| `.gitignore` | Python, env, Docker ignores |
| `backend/pyproject.toml` | Python project config with dependencies |
| `backend/main.py` | FastAPI app entrypoint, lifespan, router mounting |
| `backend/config.py` | Settings loaded from env vars via pydantic-settings |
| `backend/database.py` | MongoDB + Redis connection singletons |
| `backend/dependencies.py` | FastAPI dependency injection (current user, role checks) |
| `shared/__init__.py` | Package marker |
| `shared/dtos/__init__.py` | Package marker |
| `shared/dtos/auth.py` | All auth/user DTOs |
| `shared/events/__init__.py` | Package marker |
| `shared/events/auth.py` | Auth event models |
| `shared/events/system.py` | ErrorEvent model |
| `shared/topics.py` | Topic name constants |
| `backend/modules/__init__.py` | Package marker |
| `backend/modules/user/__init__.py` | UserService public API |
| `backend/modules/user/_models.py` | Internal MongoDB document models |
| `backend/modules/user/_repository.py` | MongoDB CRUD operations |
| `backend/modules/user/_handlers.py` | FastAPI route handlers |
| `backend/modules/user/_auth.py` | JWT creation/validation, refresh token logic |
| `backend/modules/user/_audit.py` | Audit log repository |
| `tests/conftest.py` | Shared test fixtures (app, client, db, auth helpers) |
| `tests/test_setup.py` | Master admin setup tests |
| `tests/test_auth.py` | Login, refresh, logout, password change tests |
| `tests/test_user_management.py` | User CRUD, roles, permissions tests |
| `tests/test_audit_log.py` | Audit log endpoint tests |

---

## Task 1: Docker Compose & Project Scaffold

**Files:**
- Create: `docker-compose.yml`
- Create: `backend/Dockerfile`
- Create: `.env.example`
- Create: `.gitignore`
- Create: `backend/pyproject.toml`

- [ ] **Step 1: Create `.gitignore`**

```gitignore
# Python
__pycache__/
*.py[cod]
*.egg-info/
dist/
build/
.venv/

# Environment
.env

# Docker
docker-compose.override.yml

# IDE
.idea/
.vscode/
*.swp
*.swo

# Testing
.pytest_cache/
.coverage
htmlcov/

# uv
uv.lock

# Obsidian state
obsidian/.obsidian/workspace.json
obsidian/.obsidian/workspace-mobile.json
obsidian/.obsidian/graph.json
```

- [ ] **Step 2: Create `.env.example`**

```env
# Master admin setup — required for first-time setup via POST /api/setup
MASTER_ADMIN_PIN=change-me-1234

# JWT signing secret — generate with: openssl rand -hex 32
JWT_SECRET=change-me-generate-a-real-secret

# MongoDB — must include replicaSet=rs0 for transactions and vector search
MONGODB_URI=mongodb://mongodb:27017/chatsune?replicaSet=rs0

# Redis — used for refresh tokens and event streams
REDIS_URI=redis://redis:6379/0
```

- [ ] **Step 3: Create `docker-compose.yml`**

```yaml
services:
  mongodb:
    image: mongo:7.0
    command: ["mongod", "--replSet", "rs0", "--bind_ip_all"]
    ports:
      - "27017:27017"
    volumes:
      - mongodb_data:/data/db
    healthcheck:
      test: >
        mongosh --eval "
          try {
            rs.status().ok
          } catch(e) {
            rs.initiate({_id: 'rs0', members: [{_id: 0, host: 'mongodb:27017'}]});
            1;
          }
        "
      interval: 5s
      timeout: 10s
      retries: 5
      start_period: 10s

  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"
    volumes:
      - redis_data:/data
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 5s
      timeout: 3s
      retries: 5

  backend:
    build:
      context: .
      dockerfile: backend/Dockerfile
    ports:
      - "8000:8000"
    env_file:
      - .env
    depends_on:
      mongodb:
        condition: service_healthy
      redis:
        condition: service_healthy
    volumes:
      - ./backend:/app/backend
      - ./shared:/app/shared

volumes:
  mongodb_data:
  redis_data:
```

- [ ] **Step 4: Create `backend/Dockerfile`**

```dockerfile
FROM python:3.12-slim

WORKDIR /app

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

COPY backend/pyproject.toml ./backend/
RUN cd backend && uv sync --no-dev --no-install-project

COPY backend/ ./backend/
COPY shared/ ./shared/

ENV PATH="/app/backend/.venv/bin:$PATH"

EXPOSE 8000

CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

- [ ] **Step 5: Create `backend/pyproject.toml`**

```toml
[project]
name = "chatsune-backend"
version = "0.1.0"
description = "Chatsune backend — privacy-first AI companion platform"
requires-python = ">=3.12"
dependencies = [
    "fastapi>=0.115",
    "uvicorn[standard]>=0.34",
    "pydantic>=2.10",
    "pydantic-settings>=2.7",
    "motor>=3.7",
    "redis>=5.2",
    "pyjwt>=2.10",
    "bcrypt>=4.2",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.3",
    "pytest-asyncio>=0.25",
    "httpx>=0.28",
]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["../tests"]
```

- [ ] **Step 6: Create placeholder directories and `__init__.py` files**

Create empty `__init__.py` in:
- `shared/__init__.py`
- `shared/dtos/__init__.py`
- `shared/events/__init__.py`
- `backend/modules/__init__.py`

Create empty placeholder directories:
- `frontend/` (with a `.gitkeep`)
- `obsidian/.obsidian/` (Obsidian vault per project conventions)

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "Scaffold project structure with Docker Compose, Dockerfile, and pyproject.toml"
```

---

## Task 2: Configuration & Database Connections

**Files:**
- Create: `backend/config.py`
- Create: `backend/database.py`
- Create: `backend/main.py`

- [ ] **Step 1: Create `backend/config.py`**

```python
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    master_admin_pin: str
    jwt_secret: str
    mongodb_uri: str = "mongodb://mongodb:27017/chatsune?replicaSet=rs0"
    redis_uri: str = "redis://redis:6379/0"

    jwt_access_token_expire_minutes: int = 15
    jwt_refresh_token_expire_days: int = 30

    model_config = {"env_file": ".env"}


settings = Settings()
```

- [ ] **Step 2: Create `backend/database.py`**

```python
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from redis.asyncio import Redis

from backend.config import settings

_mongo_client: AsyncIOMotorClient | None = None
_redis_client: Redis | None = None


async def connect_db() -> None:
    global _mongo_client, _redis_client
    _mongo_client = AsyncIOMotorClient(settings.mongodb_uri)
    _redis_client = Redis.from_url(settings.redis_uri, decode_responses=True)


async def disconnect_db() -> None:
    global _mongo_client, _redis_client
    if _mongo_client:
        _mongo_client.close()
    if _redis_client:
        await _redis_client.aclose()


def get_db() -> AsyncIOMotorDatabase:
    return _mongo_client.get_database()


def get_redis() -> Redis:
    return _redis_client
```

- [ ] **Step 3: Create `backend/main.py`**

```python
from contextlib import asynccontextmanager

from fastapi import FastAPI

from backend.database import connect_db, disconnect_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    await connect_db()
    yield
    await disconnect_db()


app = FastAPI(title="Chatsune", version="0.1.0", lifespan=lifespan)


@app.get("/api/health")
async def health():
    return {"status": "ok"}
```

- [ ] **Step 4: Verify Docker Compose starts**

```bash
cp .env.example .env
docker compose up -d
# Wait for healthy
docker compose ps
# Test health endpoint
curl http://localhost:8000/api/health
# Expected: {"status":"ok"}
docker compose down
```

- [ ] **Step 5: Commit**

```bash
git add backend/config.py backend/database.py backend/main.py
git commit -m "Add config, database connections, and FastAPI entrypoint with health check"
```

---

## Task 3: Shared Contracts

**Files:**
- Create: `shared/topics.py`
- Create: `shared/dtos/auth.py`
- Create: `shared/events/system.py`
- Create: `shared/events/auth.py`

- [ ] **Step 1: Create `shared/topics.py`**

```python
class Topics:
    USER_CREATED = "user.created"
    USER_UPDATED = "user.updated"
    USER_DEACTIVATED = "user.deactivated"
    USER_PASSWORD_RESET = "user.password_reset"
    ERROR = "error"
```

- [ ] **Step 2: Create `shared/dtos/auth.py`**

```python
from datetime import datetime

from pydantic import BaseModel, EmailStr


class UserDto(BaseModel):
    id: str
    username: str
    email: str
    display_name: str
    role: str
    is_active: bool
    must_change_password: bool
    created_at: datetime
    updated_at: datetime


class SetupRequestDto(BaseModel):
    pin: str
    username: str
    email: EmailStr
    password: str


class LoginRequestDto(BaseModel):
    username: str
    password: str


class CreateUserRequestDto(BaseModel):
    username: str
    email: EmailStr
    display_name: str
    role: str = "user"


class UpdateUserRequestDto(BaseModel):
    display_name: str | None = None
    email: EmailStr | None = None
    is_active: bool | None = None
    role: str | None = None


class ChangePasswordRequestDto(BaseModel):
    current_password: str
    new_password: str


class TokenResponseDto(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


class SetupResponseDto(BaseModel):
    user: UserDto
    access_token: str
    token_type: str = "bearer"
    expires_in: int


class CreateUserResponseDto(BaseModel):
    user: UserDto
    generated_password: str


class ResetPasswordResponseDto(BaseModel):
    user: UserDto
    generated_password: str


class AuditLogEntryDto(BaseModel):
    id: str
    timestamp: datetime
    actor_id: str
    action: str
    resource_type: str
    resource_id: str | None = None
    detail: dict | None = None
```

- [ ] **Step 3: Create `shared/events/system.py`**

```python
from pydantic import BaseModel


class ErrorEvent(BaseModel):
    type: str = "error"
    correlation_id: str
    error_code: str
    recoverable: bool
    user_message: str
    detail: str | None = None
```

- [ ] **Step 4: Create `shared/events/auth.py`**

```python
from datetime import datetime

from pydantic import BaseModel


class UserCreatedEvent(BaseModel):
    type: str = "user.created"
    user_id: str
    username: str
    role: str
    timestamp: datetime


class UserUpdatedEvent(BaseModel):
    type: str = "user.updated"
    user_id: str
    changes: dict
    timestamp: datetime


class UserDeactivatedEvent(BaseModel):
    type: str = "user.deactivated"
    user_id: str
    timestamp: datetime


class UserPasswordResetEvent(BaseModel):
    type: str = "user.password_reset"
    user_id: str
    timestamp: datetime
```

- [ ] **Step 5: Commit**

```bash
git add shared/
git commit -m "Add shared contracts: DTOs, events, and topic constants"
```

---

## Task 4: User Module — Internal Models & Repository

**Files:**
- Create: `backend/modules/user/_models.py`
- Create: `backend/modules/user/_repository.py`
- Create: `backend/modules/user/_audit.py`
- Create: `backend/modules/user/__init__.py` (empty for now)

- [ ] **Step 1: Create `backend/modules/user/_models.py`**

```python
from datetime import datetime

from pydantic import BaseModel, EmailStr, Field


class UserDocument(BaseModel):
    """Internal MongoDB document model for users. Never expose outside the user module."""

    id: str = Field(alias="_id")
    username: str
    email: str
    display_name: str
    password_hash: str
    role: str  # "master_admin" | "admin" | "user"
    is_active: bool = True
    must_change_password: bool = False
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    model_config = {"populate_by_name": True}


class AuditLogDocument(BaseModel):
    """Internal MongoDB document model for audit log entries."""

    id: str = Field(alias="_id")
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    actor_id: str
    action: str
    resource_type: str
    resource_id: str | None = None
    detail: dict | None = None

    model_config = {"populate_by_name": True}
```

- [ ] **Step 2: Create `backend/modules/user/_repository.py`**

```python
from datetime import datetime
from uuid import uuid4

from motor.motor_asyncio import AsyncIOMotorDatabase

from shared.dtos.auth import UserDto


class UserRepository:
    def __init__(self, db: AsyncIOMotorDatabase) -> None:
        self._collection = db["users"]

    async def create_indexes(self) -> None:
        await self._collection.create_index("username", unique=True)
        await self._collection.create_index("email", unique=True)

    async def find_by_username(self, username: str) -> dict | None:
        return await self._collection.find_one({"username": username})

    async def find_by_id(self, user_id: str) -> dict | None:
        return await self._collection.find_one({"_id": user_id})

    async def find_by_role(self, role: str) -> dict | None:
        return await self._collection.find_one({"role": role})

    async def create(
        self,
        username: str,
        email: str,
        display_name: str,
        password_hash: str,
        role: str,
        must_change_password: bool = False,
    ) -> dict:
        now = datetime.utcnow()
        doc = {
            "_id": str(uuid4()),
            "username": username,
            "email": email,
            "display_name": display_name,
            "password_hash": password_hash,
            "role": role,
            "is_active": True,
            "must_change_password": must_change_password,
            "created_at": now,
            "updated_at": now,
        }
        await self._collection.insert_one(doc)
        return doc

    async def update(self, user_id: str, fields: dict) -> dict | None:
        fields["updated_at"] = datetime.utcnow()
        await self._collection.update_one(
            {"_id": user_id}, {"$set": fields}
        )
        return await self.find_by_id(user_id)

    async def list_users(
        self, skip: int = 0, limit: int = 50
    ) -> list[dict]:
        cursor = self._collection.find().skip(skip).limit(limit)
        return await cursor.to_list(length=limit)

    async def count(self) -> int:
        return await self._collection.count_documents({})

    @staticmethod
    def to_dto(doc: dict) -> UserDto:
        return UserDto(
            id=doc["_id"],
            username=doc["username"],
            email=doc["email"],
            display_name=doc["display_name"],
            role=doc["role"],
            is_active=doc["is_active"],
            must_change_password=doc["must_change_password"],
            created_at=doc["created_at"],
            updated_at=doc["updated_at"],
        )
```

- [ ] **Step 3: Create `backend/modules/user/_audit.py`**

```python
from datetime import datetime
from uuid import uuid4

from motor.motor_asyncio import AsyncIOMotorDatabase

from shared.dtos.auth import AuditLogEntryDto


class AuditRepository:
    def __init__(self, db: AsyncIOMotorDatabase) -> None:
        self._collection = db["audit_log"]

    async def create_indexes(self) -> None:
        await self._collection.create_index("actor_id")
        await self._collection.create_index("action")
        await self._collection.create_index("resource_type")
        await self._collection.create_index("timestamp")

    async def log(
        self,
        actor_id: str,
        action: str,
        resource_type: str,
        resource_id: str | None = None,
        detail: dict | None = None,
    ) -> dict:
        doc = {
            "_id": str(uuid4()),
            "timestamp": datetime.utcnow(),
            "actor_id": actor_id,
            "action": action,
            "resource_type": resource_type,
            "resource_id": resource_id,
            "detail": detail,
        }
        await self._collection.insert_one(doc)
        return doc

    async def list_entries(
        self,
        skip: int = 0,
        limit: int = 50,
        actor_id: str | None = None,
        action: str | None = None,
        resource_type: str | None = None,
        resource_id: str | None = None,
    ) -> list[dict]:
        query: dict = {}
        if actor_id:
            query["actor_id"] = actor_id
        if action:
            query["action"] = action
        if resource_type:
            query["resource_type"] = resource_type
        if resource_id:
            query["resource_id"] = resource_id

        cursor = (
            self._collection.find(query)
            .sort("timestamp", -1)
            .skip(skip)
            .limit(limit)
        )
        return await cursor.to_list(length=limit)

    @staticmethod
    def to_dto(doc: dict) -> AuditLogEntryDto:
        return AuditLogEntryDto(
            id=doc["_id"],
            timestamp=doc["timestamp"],
            actor_id=doc["actor_id"],
            action=doc["action"],
            resource_type=doc["resource_type"],
            resource_id=doc.get("resource_id"),
            detail=doc.get("detail"),
        )
```

- [ ] **Step 4: Create empty `backend/modules/user/__init__.py`**

```python
"""User module — auth, user management, audit log."""
```

- [ ] **Step 5: Commit**

```bash
git add backend/modules/
git commit -m "Add user module internal models, repository, and audit log"
```

---

## Task 5: JWT & Auth Utilities

**Files:**
- Create: `backend/modules/user/_auth.py`
- Create: `tests/conftest.py`
- Create: `tests/test_auth_utils.py`

- [ ] **Step 1: Write failing tests for JWT and password utilities**

Create `tests/conftest.py`:

```python
import asyncio
from collections.abc import AsyncGenerator

import httpx
import pytest
from motor.motor_asyncio import AsyncIOMotorClient

from backend.config import settings
from backend.main import app


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
async def client() -> AsyncGenerator[httpx.AsyncClient, None]:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as ac:
        yield ac


@pytest.fixture(autouse=True)
async def clean_db():
    """Drop test database before each test."""
    mongo_client = AsyncIOMotorClient(settings.mongodb_uri)
    db = mongo_client.get_database()
    collections = await db.list_collection_names()
    for col in collections:
        await db[col].drop()
    mongo_client.close()
    yield
```

Create `tests/test_auth_utils.py`:

```python
from datetime import timedelta
from uuid import uuid4

import pytest

from backend.modules.user._auth import (
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
    generate_random_password,
)


def test_hash_and_verify_password():
    password = "test-password-123"
    hashed = hash_password(password)
    assert hashed != password
    assert verify_password(password, hashed) is True
    assert verify_password("wrong-password", hashed) is False


def test_create_and_decode_access_token():
    user_id = str(uuid4())
    session_id = str(uuid4())
    token = create_access_token(
        user_id=user_id, role="admin", session_id=session_id
    )
    payload = decode_access_token(token)
    assert payload["sub"] == user_id
    assert payload["role"] == "admin"
    assert payload["session_id"] == session_id
    assert "mcp" not in payload


def test_access_token_with_mcp_claim():
    user_id = str(uuid4())
    session_id = str(uuid4())
    token = create_access_token(
        user_id=user_id,
        role="user",
        session_id=session_id,
        must_change_password=True,
    )
    payload = decode_access_token(token)
    assert payload["mcp"] is True


def test_decode_expired_token_raises():
    token = create_access_token(
        user_id="x",
        role="user",
        session_id="y",
        expires_delta=timedelta(seconds=-1),
    )
    with pytest.raises(Exception):
        decode_access_token(token)


def test_generate_random_password():
    pw = generate_random_password()
    assert len(pw) == 20
    assert pw.isalnum()

    # Two calls should produce different passwords
    pw2 = generate_random_password()
    assert pw != pw2
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd backend && uv sync --all-extras && cd ..
uv run --project backend pytest tests/test_auth_utils.py -v
```

Expected: ImportError — `_auth` module does not exist yet.

- [ ] **Step 3: Implement `backend/modules/user/_auth.py`**

```python
import secrets
import string
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import bcrypt
import jwt

from backend.config import settings


def hash_password(password: str) -> str:
    return bcrypt.hashpw(
        password.encode(), bcrypt.gensalt()
    ).decode()


def verify_password(password: str, password_hash: str) -> bool:
    return bcrypt.checkpw(
        password.encode(), password_hash.encode()
    )


def generate_random_password(length: int = 20) -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


def create_access_token(
    user_id: str,
    role: str,
    session_id: str,
    must_change_password: bool = False,
    expires_delta: timedelta | None = None,
) -> str:
    if expires_delta is None:
        expires_delta = timedelta(
            minutes=settings.jwt_access_token_expire_minutes
        )
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "role": role,
        "session_id": session_id,
        "iat": now,
        "exp": now + expires_delta,
    }
    if must_change_password:
        payload["mcp"] = True
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


def decode_access_token(token: str) -> dict:
    return jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])


def generate_refresh_token() -> str:
    return secrets.token_urlsafe(48)


def generate_session_id() -> str:
    return str(uuid4())
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run --project backend pytest tests/test_auth_utils.py -v
```

Expected: All 5 tests pass.

- [ ] **Step 5: Commit**

```bash
git add backend/modules/user/_auth.py tests/conftest.py tests/test_auth_utils.py
git commit -m "Add JWT and password utilities with tests"
```

---

## Task 6: FastAPI Dependencies (Auth Middleware)

**Files:**
- Create: `backend/dependencies.py`

- [ ] **Step 1: Create `backend/dependencies.py`**

```python
from fastapi import Cookie, Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from backend.modules.user._auth import decode_access_token

_bearer_scheme = HTTPBearer()


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer_scheme),
) -> dict:
    """Decode JWT and return payload. Raises 401 if invalid/expired."""
    try:
        payload = decode_access_token(credentials.credentials)
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    return payload


async def require_active_session(
    user: dict = Depends(get_current_user),
) -> dict:
    """Reject requests from users who must change their password (mcp claim)."""
    if user.get("mcp"):
        raise HTTPException(
            status_code=403,
            detail="Password change required before accessing this resource",
        )
    return user


async def require_admin(
    user: dict = Depends(require_active_session),
) -> dict:
    """Require admin or master_admin role."""
    if user["role"] not in ("admin", "master_admin"):
        raise HTTPException(status_code=403, detail="Admin access required")
    return user


async def require_master_admin(
    user: dict = Depends(require_active_session),
) -> dict:
    """Require master_admin role."""
    if user["role"] != "master_admin":
        raise HTTPException(
            status_code=403, detail="Master admin access required"
        )
    return user
```

- [ ] **Step 2: Commit**

```bash
git add backend/dependencies.py
git commit -m "Add FastAPI auth dependencies for role-based access control"
```

---

## Task 7: Refresh Token Service

**Files:**
- Create: `backend/modules/user/_refresh.py`
- Create: `tests/test_refresh.py`

- [ ] **Step 1: Write failing tests for refresh token storage**

Create `tests/test_refresh.py`:

```python
import pytest
from redis.asyncio import Redis

from backend.config import settings
from backend.modules.user._refresh import RefreshTokenStore


@pytest.fixture
async def redis_client():
    client = Redis.from_url(settings.redis_uri, decode_responses=True)
    await client.flushdb()
    yield client
    await client.aclose()


@pytest.fixture
def store(redis_client):
    return RefreshTokenStore(redis_client)


async def test_store_and_retrieve_refresh_token(store):
    token = "test-token-abc"
    await store.store(token, user_id="user-1", session_id="sess-1")
    data = await store.get(token)
    assert data is not None
    assert data["user_id"] == "user-1"
    assert data["session_id"] == "sess-1"


async def test_consume_deletes_token(store):
    token = "test-token-def"
    await store.store(token, user_id="user-1", session_id="sess-1")
    data = await store.consume(token)
    assert data is not None
    assert data["user_id"] == "user-1"

    # Token is gone after consume
    again = await store.get(token)
    assert again is None


async def test_get_nonexistent_token_returns_none(store):
    data = await store.get("does-not-exist")
    assert data is None


async def test_revoke_all_for_user(store):
    await store.store("tok-1", user_id="user-1", session_id="s1")
    await store.store("tok-2", user_id="user-1", session_id="s2")
    await store.store("tok-3", user_id="user-2", session_id="s3")

    await store.revoke_all_for_user("user-1")

    assert await store.get("tok-1") is None
    assert await store.get("tok-2") is None
    # user-2's token is unaffected
    assert await store.get("tok-3") is not None
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run --project backend pytest tests/test_refresh.py -v
```

Expected: ImportError — `_refresh` module does not exist yet.

- [ ] **Step 3: Implement `backend/modules/user/_refresh.py`**

```python
import json
from datetime import datetime, timezone

from redis.asyncio import Redis

from backend.config import settings

_KEY_PREFIX = "refresh:"
_USER_INDEX_PREFIX = "user_refresh_tokens:"
_TTL_SECONDS = settings.jwt_refresh_token_expire_days * 86400


class RefreshTokenStore:
    def __init__(self, redis: Redis) -> None:
        self._redis = redis

    async def store(
        self, token: str, user_id: str, session_id: str
    ) -> None:
        data = json.dumps(
            {
                "user_id": user_id,
                "session_id": session_id,
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
        )
        pipe = self._redis.pipeline()
        pipe.setex(f"{_KEY_PREFIX}{token}", _TTL_SECONDS, data)
        pipe.sadd(f"{_USER_INDEX_PREFIX}{user_id}", token)
        await pipe.execute()

    async def get(self, token: str) -> dict | None:
        data = await self._redis.get(f"{_KEY_PREFIX}{token}")
        if data is None:
            return None
        return json.loads(data)

    async def consume(self, token: str) -> dict | None:
        data = await self.get(token)
        if data is None:
            return None
        pipe = self._redis.pipeline()
        pipe.delete(f"{_KEY_PREFIX}{token}")
        pipe.srem(f"{_USER_INDEX_PREFIX}{data['user_id']}", token)
        await pipe.execute()
        return data

    async def revoke_all_for_user(self, user_id: str) -> None:
        index_key = f"{_USER_INDEX_PREFIX}{user_id}"
        tokens = await self._redis.smembers(index_key)
        if tokens:
            pipe = self._redis.pipeline()
            for token in tokens:
                pipe.delete(f"{_KEY_PREFIX}{token}")
            pipe.delete(index_key)
            await pipe.execute()
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run --project backend pytest tests/test_refresh.py -v
```

Expected: All 4 tests pass.

- [ ] **Step 5: Commit**

```bash
git add backend/modules/user/_refresh.py tests/test_refresh.py
git commit -m "Add refresh token store with Redis backend and user-level revocation"
```

---

## Task 8: Setup Endpoint (Master Admin Creation)

**Files:**
- Create: `backend/modules/user/_handlers.py`
- Modify: `backend/main.py` (mount router)
- Create: `tests/test_setup.py`

- [ ] **Step 1: Write failing tests for setup endpoint**

Create `tests/test_setup.py`:

```python
import pytest
from httpx import AsyncClient


async def test_setup_creates_master_admin(client: AsyncClient):
    response = await client.post(
        "/api/setup",
        json={
            "pin": "change-me-1234",
            "username": "admin",
            "email": "admin@example.com",
            "password": "SecurePass123",
        },
    )
    assert response.status_code == 201
    data = response.json()
    assert data["user"]["role"] == "master_admin"
    assert data["user"]["username"] == "admin"
    assert data["user"]["is_active"] is True
    assert data["user"]["must_change_password"] is False
    assert "access_token" in data
    assert data["token_type"] == "bearer"

    # Refresh cookie should be set
    assert "refresh_token" in response.cookies


async def test_setup_rejects_wrong_pin(client: AsyncClient):
    response = await client.post(
        "/api/setup",
        json={
            "pin": "wrong-pin",
            "username": "admin",
            "email": "admin@example.com",
            "password": "SecurePass123",
        },
    )
    assert response.status_code == 403


async def test_setup_rejects_second_call(client: AsyncClient):
    # First call succeeds
    await client.post(
        "/api/setup",
        json={
            "pin": "change-me-1234",
            "username": "admin",
            "email": "admin@example.com",
            "password": "SecurePass123",
        },
    )
    # Second call is rejected
    response = await client.post(
        "/api/setup",
        json={
            "pin": "change-me-1234",
            "username": "admin2",
            "email": "admin2@example.com",
            "password": "SecurePass123",
        },
    )
    assert response.status_code == 409
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run --project backend pytest tests/test_setup.py -v
```

Expected: 404 — route not defined yet.

- [ ] **Step 3: Implement `backend/modules/user/_handlers.py`**

```python
from fastapi import APIRouter, Depends, HTTPException, Response

from backend.database import get_db, get_redis
from backend.config import settings
from backend.dependencies import require_admin, require_active_session
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
```

- [ ] **Step 4: Mount router in `backend/main.py`**

Update `backend/main.py` — add after the app definition:

```python
from contextlib import asynccontextmanager

from fastapi import FastAPI

from backend.database import connect_db, disconnect_db, get_db
from backend.modules.user._handlers import router as user_router
from backend.modules.user._repository import UserRepository
from backend.modules.user._audit import AuditRepository


@asynccontextmanager
async def lifespan(app: FastAPI):
    await connect_db()
    # Ensure indexes
    db = get_db()
    await UserRepository(db).create_indexes()
    await AuditRepository(db).create_indexes()
    yield
    await disconnect_db()


app = FastAPI(title="Chatsune", version="0.1.0", lifespan=lifespan)
app.include_router(user_router)


@app.get("/api/health")
async def health():
    return {"status": "ok"}
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
uv run --project backend pytest tests/test_setup.py -v
```

Expected: All 3 tests pass.

- [ ] **Step 6: Commit**

```bash
git add backend/modules/user/_handlers.py backend/main.py tests/test_setup.py
git commit -m "Add master admin setup endpoint with PIN verification"
```

---

## Task 9: Auth Endpoints (Login, Refresh, Logout, Password Change)

**Files:**
- Modify: `backend/modules/user/_handlers.py`
- Create: `tests/test_auth.py`

- [ ] **Step 1: Write failing tests for auth endpoints**

Create `tests/test_auth.py`:

```python
import pytest
from httpx import AsyncClient


async def _setup_master_admin(client: AsyncClient) -> dict:
    """Helper: create master admin and return response data."""
    resp = await client.post(
        "/api/setup",
        json={
            "pin": "change-me-1234",
            "username": "admin",
            "email": "admin@example.com",
            "password": "SecurePass123",
        },
    )
    return resp.json(), resp.cookies


async def test_login_success(client: AsyncClient):
    await _setup_master_admin(client)

    response = await client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "SecurePass123"},
    )
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"
    assert "refresh_token" in response.cookies


async def test_login_wrong_password(client: AsyncClient):
    await _setup_master_admin(client)

    response = await client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "WrongPass"},
    )
    assert response.status_code == 401


async def test_login_nonexistent_user(client: AsyncClient):
    response = await client.post(
        "/api/auth/login",
        json={"username": "nobody", "password": "whatever"},
    )
    assert response.status_code == 401


async def test_login_inactive_user_rejected(client: AsyncClient):
    data, cookies = await _setup_master_admin(client)
    token = data["access_token"]

    # Create a user, then deactivate them
    create_resp = await client.post(
        "/api/admin/users",
        json={
            "username": "testuser",
            "email": "test@example.com",
            "display_name": "Test User",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    user_id = create_resp.json()["user"]["id"]

    await client.delete(
        f"/api/admin/users/{user_id}",
        headers={"Authorization": f"Bearer {token}"},
    )

    # Login as deactivated user should fail
    response = await client.post(
        "/api/auth/login",
        json={
            "username": "testuser",
            "password": create_resp.json()["generated_password"],
        },
    )
    assert response.status_code == 403


async def test_refresh_token_rotation(client: AsyncClient):
    await _setup_master_admin(client)

    login_resp = await client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "SecurePass123"},
    )
    refresh_cookie = login_resp.cookies["refresh_token"]

    # Use refresh token
    refresh_resp = await client.post(
        "/api/auth/refresh",
        cookies={"refresh_token": refresh_cookie},
    )
    assert refresh_resp.status_code == 200
    assert "access_token" in refresh_resp.json()

    # Old refresh token should no longer work
    replay_resp = await client.post(
        "/api/auth/refresh",
        cookies={"refresh_token": refresh_cookie},
    )
    assert replay_resp.status_code == 401


async def test_logout_clears_refresh_token(client: AsyncClient):
    await _setup_master_admin(client)

    login_resp = await client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "SecurePass123"},
    )
    token = login_resp.json()["access_token"]
    refresh_cookie = login_resp.cookies["refresh_token"]

    # Logout
    logout_resp = await client.post(
        "/api/auth/logout",
        headers={"Authorization": f"Bearer {token}"},
        cookies={"refresh_token": refresh_cookie},
    )
    assert logout_resp.status_code == 200

    # Refresh token no longer works
    refresh_resp = await client.post(
        "/api/auth/refresh",
        cookies={"refresh_token": refresh_cookie},
    )
    assert refresh_resp.status_code == 401


async def test_change_password(client: AsyncClient):
    data, _ = await _setup_master_admin(client)
    token = data["access_token"]

    response = await client.patch(
        "/api/auth/password",
        json={
            "current_password": "SecurePass123",
            "new_password": "NewSecurePass456",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    assert "access_token" in response.json()

    # Old password no longer works
    login_resp = await client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "SecurePass123"},
    )
    assert login_resp.status_code == 401

    # New password works
    login_resp = await client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "NewSecurePass456"},
    )
    assert login_resp.status_code == 200


async def test_must_change_password_restricts_access(client: AsyncClient):
    data, _ = await _setup_master_admin(client)
    admin_token = data["access_token"]

    # Create user (gets must_change_password=True)
    create_resp = await client.post(
        "/api/admin/users",
        json={
            "username": "newuser",
            "email": "new@example.com",
            "display_name": "New User",
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    generated_pw = create_resp.json()["generated_password"]

    # Login as new user
    login_resp = await client.post(
        "/api/auth/login",
        json={"username": "newuser", "password": generated_pw},
    )
    mcp_token = login_resp.json()["access_token"]

    # Trying to access admin endpoints should fail with 403
    list_resp = await client.get(
        "/api/admin/users",
        headers={"Authorization": f"Bearer {mcp_token}"},
    )
    assert list_resp.status_code == 403

    # But password change should work
    pw_resp = await client.patch(
        "/api/auth/password",
        json={
            "current_password": generated_pw,
            "new_password": "MyNewPassword789",
        },
        headers={"Authorization": f"Bearer {mcp_token}"},
    )
    assert pw_resp.status_code == 200
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run --project backend pytest tests/test_auth.py -v
```

Expected: 404 — auth routes not implemented yet.

- [ ] **Step 3: Add auth endpoints to `backend/modules/user/_handlers.py`**

Append to the existing `_handlers.py` file, after the setup endpoint:

```python
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
        # Possible replay attack — but we don't know which user.
        # The token was already consumed or never existed.
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
```

Also add the missing import at the top of `_handlers.py`:

```python
from backend.dependencies import get_current_user, require_admin, require_active_session
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run --project backend pytest tests/test_auth.py -v
```

Expected: All 8 tests pass.

- [ ] **Step 5: Commit**

```bash
git add backend/modules/user/_handlers.py tests/test_auth.py
git commit -m "Add auth endpoints: login, refresh with rotation, logout, password change"
```

---

## Task 10: User Management Endpoints

**Files:**
- Modify: `backend/modules/user/_handlers.py`
- Create: `tests/test_user_management.py`

- [ ] **Step 1: Write failing tests for user management**

Create `tests/test_user_management.py`:

```python
import pytest
from httpx import AsyncClient


async def _setup_and_login(client: AsyncClient) -> str:
    """Create master admin and return access token."""
    resp = await client.post(
        "/api/setup",
        json={
            "pin": "change-me-1234",
            "username": "admin",
            "email": "admin@example.com",
            "password": "SecurePass123",
        },
    )
    return resp.json()["access_token"]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def test_create_user(client: AsyncClient):
    token = await _setup_and_login(client)

    response = await client.post(
        "/api/admin/users",
        json={
            "username": "testuser",
            "email": "test@example.com",
            "display_name": "Test User",
        },
        headers=_auth(token),
    )
    assert response.status_code == 201
    data = response.json()
    assert data["user"]["username"] == "testuser"
    assert data["user"]["role"] == "user"
    assert data["user"]["must_change_password"] is True
    assert len(data["generated_password"]) == 20
    assert data["generated_password"].isalnum()


async def test_create_admin_user_only_by_master(client: AsyncClient):
    master_token = await _setup_and_login(client)

    # Master admin creates an admin
    resp = await client.post(
        "/api/admin/users",
        json={
            "username": "newadmin",
            "email": "newadmin@example.com",
            "display_name": "New Admin",
            "role": "admin",
        },
        headers=_auth(master_token),
    )
    assert resp.status_code == 201
    admin_pw = resp.json()["generated_password"]

    # Login as the new admin
    login_resp = await client.post(
        "/api/auth/login",
        json={"username": "newadmin", "password": admin_pw},
    )
    admin_token_mcp = login_resp.json()["access_token"]

    # Change password first (must_change_password)
    pw_resp = await client.patch(
        "/api/auth/password",
        json={"current_password": admin_pw, "new_password": "AdminPass123"},
        headers=_auth(admin_token_mcp),
    )
    admin_token = pw_resp.json()["access_token"]

    # Admin tries to create another admin — should fail
    resp2 = await client.post(
        "/api/admin/users",
        json={
            "username": "anotheradmin",
            "email": "another@example.com",
            "display_name": "Another Admin",
            "role": "admin",
        },
        headers=_auth(admin_token),
    )
    assert resp2.status_code == 403


async def test_list_users(client: AsyncClient):
    token = await _setup_and_login(client)

    # Create two users
    for i in range(2):
        await client.post(
            "/api/admin/users",
            json={
                "username": f"user{i}",
                "email": f"user{i}@example.com",
                "display_name": f"User {i}",
            },
            headers=_auth(token),
        )

    response = await client.get("/api/admin/users", headers=_auth(token))
    assert response.status_code == 200
    data = response.json()
    assert len(data["users"]) == 3  # master admin + 2 users
    assert "total" in data


async def test_get_single_user(client: AsyncClient):
    token = await _setup_and_login(client)

    create_resp = await client.post(
        "/api/admin/users",
        json={
            "username": "single",
            "email": "single@example.com",
            "display_name": "Single User",
        },
        headers=_auth(token),
    )
    user_id = create_resp.json()["user"]["id"]

    response = await client.get(
        f"/api/admin/users/{user_id}", headers=_auth(token)
    )
    assert response.status_code == 200
    assert response.json()["username"] == "single"


async def test_update_user(client: AsyncClient):
    token = await _setup_and_login(client)

    create_resp = await client.post(
        "/api/admin/users",
        json={
            "username": "updatable",
            "email": "up@example.com",
            "display_name": "Old Name",
        },
        headers=_auth(token),
    )
    user_id = create_resp.json()["user"]["id"]

    response = await client.patch(
        f"/api/admin/users/{user_id}",
        json={"display_name": "New Name", "email": "new@example.com"},
        headers=_auth(token),
    )
    assert response.status_code == 200
    assert response.json()["display_name"] == "New Name"
    assert response.json()["email"] == "new@example.com"


async def test_soft_delete_user(client: AsyncClient):
    token = await _setup_and_login(client)

    create_resp = await client.post(
        "/api/admin/users",
        json={
            "username": "deletable",
            "email": "del@example.com",
            "display_name": "Deletable",
        },
        headers=_auth(token),
    )
    user_id = create_resp.json()["user"]["id"]

    response = await client.delete(
        f"/api/admin/users/{user_id}", headers=_auth(token)
    )
    assert response.status_code == 200

    # Verify user is inactive
    get_resp = await client.get(
        f"/api/admin/users/{user_id}", headers=_auth(token)
    )
    assert get_resp.json()["is_active"] is False


async def test_reset_password(client: AsyncClient):
    token = await _setup_and_login(client)

    create_resp = await client.post(
        "/api/admin/users",
        json={
            "username": "resetme",
            "email": "reset@example.com",
            "display_name": "Reset Me",
        },
        headers=_auth(token),
    )
    user_id = create_resp.json()["user"]["id"]

    response = await client.post(
        f"/api/admin/users/{user_id}/reset-password",
        headers=_auth(token),
    )
    assert response.status_code == 200
    data = response.json()
    assert len(data["generated_password"]) == 20
    assert data["user"]["must_change_password"] is True


async def test_cannot_delete_master_admin(client: AsyncClient):
    resp = await client.post(
        "/api/setup",
        json={
            "pin": "change-me-1234",
            "username": "admin",
            "email": "admin@example.com",
            "password": "SecurePass123",
        },
    )
    token = resp.json()["access_token"]
    master_id = resp.json()["user"]["id"]

    response = await client.delete(
        f"/api/admin/users/{master_id}", headers=_auth(token)
    )
    assert response.status_code == 403


async def test_cannot_deactivate_self(client: AsyncClient):
    resp = await client.post(
        "/api/setup",
        json={
            "pin": "change-me-1234",
            "username": "admin",
            "email": "admin@example.com",
            "password": "SecurePass123",
        },
    )
    token = resp.json()["access_token"]
    master_id = resp.json()["user"]["id"]

    response = await client.patch(
        f"/api/admin/users/{master_id}",
        json={"is_active": False},
        headers=_auth(token),
    )
    assert response.status_code == 403


async def test_admin_cannot_manage_other_admin(client: AsyncClient):
    master_token = await _setup_and_login(client)

    # Create two admins
    resp1 = await client.post(
        "/api/admin/users",
        json={
            "username": "admin1",
            "email": "a1@example.com",
            "display_name": "Admin 1",
            "role": "admin",
        },
        headers=_auth(master_token),
    )
    resp2 = await client.post(
        "/api/admin/users",
        json={
            "username": "admin2",
            "email": "a2@example.com",
            "display_name": "Admin 2",
            "role": "admin",
        },
        headers=_auth(master_token),
    )
    admin2_id = resp2.json()["user"]["id"]
    admin1_pw = resp1.json()["generated_password"]

    # Login as admin1 and change password
    login_resp = await client.post(
        "/api/auth/login",
        json={"username": "admin1", "password": admin1_pw},
    )
    mcp_token = login_resp.json()["access_token"]
    pw_resp = await client.patch(
        "/api/auth/password",
        json={"current_password": admin1_pw, "new_password": "Admin1Pass"},
        headers=_auth(mcp_token),
    )
    admin1_token = pw_resp.json()["access_token"]

    # Admin1 tries to update Admin2 — should fail
    response = await client.patch(
        f"/api/admin/users/{admin2_id}",
        json={"display_name": "Hacked"},
        headers=_auth(admin1_token),
    )
    assert response.status_code == 403
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run --project backend pytest tests/test_user_management.py -v
```

Expected: 404 — admin routes not implemented yet.

- [ ] **Step 3: Add user management endpoints to `backend/modules/user/_handlers.py`**

Append to the existing `_handlers.py` file:

```python
# --- User Management ---


@router.post("/admin/users", status_code=201)
async def create_user(
    body: CreateUserRequestDto,
    user: dict = Depends(require_admin),
):
    # Only master_admin can create admins
    if body.role == "admin" and user["role"] != "master_admin":
        raise HTTPException(
            status_code=403, detail="Only master admin can create admin users"
        )
    if body.role == "master_admin":
        raise HTTPException(
            status_code=403, detail="Cannot create another master admin"
        )
    if body.role not in ("admin", "user"):
        raise HTTPException(status_code=400, detail="Invalid role")

    repo = _user_repo()
    password = generate_random_password()
    password_hash = hash_password(password)

    try:
        doc = await repo.create(
            username=body.username,
            email=body.email,
            display_name=body.display_name,
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

    return UserRepository.to_dto(updated)


@router.delete("/admin/users/{user_id}")
async def delete_user(
    user_id: str,
    user: dict = Depends(require_admin),
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

    return {"status": "ok"}


@router.post("/admin/users/{user_id}/reset-password")
async def reset_password(
    user_id: str,
    user: dict = Depends(require_admin),
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

    return ResetPasswordResponseDto(
        user=UserRepository.to_dto(updated),
        generated_password=password,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run --project backend pytest tests/test_user_management.py -v
```

Expected: All 10 tests pass.

- [ ] **Step 5: Commit**

```bash
git add backend/modules/user/_handlers.py tests/test_user_management.py
git commit -m "Add user management endpoints with role-based permissions"
```

---

## Task 11: Audit Log Endpoint

**Files:**
- Modify: `backend/modules/user/_handlers.py`
- Create: `tests/test_audit_log.py`

- [ ] **Step 1: Write failing tests for audit log endpoint**

Create `tests/test_audit_log.py`:

```python
import pytest
from httpx import AsyncClient


async def _setup_and_login(client: AsyncClient) -> str:
    resp = await client.post(
        "/api/setup",
        json={
            "pin": "change-me-1234",
            "username": "admin",
            "email": "admin@example.com",
            "password": "SecurePass123",
        },
    )
    return resp.json()["access_token"]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def test_audit_log_records_setup(client: AsyncClient):
    token = await _setup_and_login(client)

    response = await client.get(
        "/api/admin/audit-log", headers=_auth(token)
    )
    assert response.status_code == 200
    entries = response.json()["entries"]
    assert len(entries) >= 1
    assert entries[0]["action"] == "user.created"
    assert entries[0]["resource_type"] == "user"


async def test_audit_log_records_user_creation(client: AsyncClient):
    token = await _setup_and_login(client)

    await client.post(
        "/api/admin/users",
        json={
            "username": "testuser",
            "email": "test@example.com",
            "display_name": "Test",
        },
        headers=_auth(token),
    )

    response = await client.get(
        "/api/admin/audit-log", headers=_auth(token)
    )
    entries = response.json()["entries"]
    actions = [e["action"] for e in entries]
    assert "user.created" in actions


async def test_audit_log_filter_by_action(client: AsyncClient):
    token = await _setup_and_login(client)

    # Create and deactivate a user to generate different actions
    create_resp = await client.post(
        "/api/admin/users",
        json={
            "username": "filterme",
            "email": "filter@example.com",
            "display_name": "Filter Me",
        },
        headers=_auth(token),
    )
    user_id = create_resp.json()["user"]["id"]
    await client.delete(
        f"/api/admin/users/{user_id}", headers=_auth(token)
    )

    response = await client.get(
        "/api/admin/audit-log?action=user.deactivated",
        headers=_auth(token),
    )
    entries = response.json()["entries"]
    assert len(entries) == 1
    assert entries[0]["action"] == "user.deactivated"


async def test_admin_sees_only_own_audit_entries(client: AsyncClient):
    master_token = await _setup_and_login(client)

    # Create an admin
    resp = await client.post(
        "/api/admin/users",
        json={
            "username": "auditor",
            "email": "audit@example.com",
            "display_name": "Auditor",
            "role": "admin",
        },
        headers=_auth(master_token),
    )
    admin_pw = resp.json()["generated_password"]

    # Login as admin, change password
    login_resp = await client.post(
        "/api/auth/login",
        json={"username": "auditor", "password": admin_pw},
    )
    mcp_token = login_resp.json()["access_token"]
    pw_resp = await client.patch(
        "/api/auth/password",
        json={"current_password": admin_pw, "new_password": "AuditorPass1"},
        headers=_auth(mcp_token),
    )
    admin_token = pw_resp.json()["access_token"]

    # Admin creates a user (generates an audit entry with admin as actor)
    await client.post(
        "/api/admin/users",
        json={
            "username": "newguy",
            "email": "new@example.com",
            "display_name": "New Guy",
        },
        headers=_auth(admin_token),
    )

    # Admin queries audit log — should only see own entries
    response = await client.get(
        "/api/admin/audit-log", headers=_auth(admin_token)
    )
    entries = response.json()["entries"]
    admin_id = resp.json()["user"]["id"]
    for entry in entries:
        assert entry["actor_id"] == admin_id


async def test_regular_user_cannot_access_audit_log(client: AsyncClient):
    master_token = await _setup_and_login(client)

    create_resp = await client.post(
        "/api/admin/users",
        json={
            "username": "normie",
            "email": "normie@example.com",
            "display_name": "Normie",
        },
        headers=_auth(master_token),
    )
    user_pw = create_resp.json()["generated_password"]

    login_resp = await client.post(
        "/api/auth/login",
        json={"username": "normie", "password": user_pw},
    )
    user_token = login_resp.json()["access_token"]

    # Even with mcp token, should be rejected (not admin)
    response = await client.get(
        "/api/admin/audit-log", headers=_auth(user_token)
    )
    assert response.status_code == 403
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run --project backend pytest tests/test_audit_log.py -v
```

Expected: 404 or failures — audit log route not implemented yet.

- [ ] **Step 3: Add audit log endpoint to `backend/modules/user/_handlers.py`**

Append to the existing `_handlers.py` file:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run --project backend pytest tests/test_audit_log.py -v
```

Expected: All 5 tests pass.

- [ ] **Step 5: Commit**

```bash
git add backend/modules/user/_handlers.py tests/test_audit_log.py
git commit -m "Add audit log endpoint with role-based filtering"
```

---

## Task 12: UserService Public API & Final Wiring

**Files:**
- Modify: `backend/modules/user/__init__.py`

- [ ] **Step 1: Define the public API in `backend/modules/user/__init__.py`**

```python
"""User module — auth, user management, audit log.

Public API: import only from this file.
"""

from backend.modules.user._handlers import router

__all__ = ["router"]
```

- [ ] **Step 2: Update `backend/main.py` to import from module public API**

```python
from contextlib import asynccontextmanager

from fastapi import FastAPI

from backend.database import connect_db, disconnect_db, get_db
from backend.modules.user import router as user_router
from backend.modules.user._repository import UserRepository
from backend.modules.user._audit import AuditRepository


@asynccontextmanager
async def lifespan(app: FastAPI):
    await connect_db()
    db = get_db()
    await UserRepository(db).create_indexes()
    await AuditRepository(db).create_indexes()
    yield
    await disconnect_db()


app = FastAPI(title="Chatsune", version="0.1.0", lifespan=lifespan)
app.include_router(user_router)


@app.get("/api/health")
async def health():
    return {"status": "ok"}
```

Note: `main.py` importing `_repository` and `_audit` for index creation is acceptable — `main.py` is the composition root, not another module. But we should expose an `init` function from the module's public API to keep this clean:

Update `backend/modules/user/__init__.py`:

```python
"""User module — auth, user management, audit log.

Public API: import only from this file.
"""

from backend.modules.user._handlers import router
from backend.modules.user._repository import UserRepository
from backend.modules.user._audit import AuditRepository


async def init_indexes(db) -> None:
    """Create MongoDB indexes for user module collections."""
    await UserRepository(db).create_indexes()
    await AuditRepository(db).create_indexes()


__all__ = ["router", "init_indexes"]
```

Update `backend/main.py`:

```python
from contextlib import asynccontextmanager

from fastapi import FastAPI

from backend.database import connect_db, disconnect_db, get_db
from backend.modules.user import router as user_router, init_indexes


@asynccontextmanager
async def lifespan(app: FastAPI):
    await connect_db()
    await init_indexes(get_db())
    yield
    await disconnect_db()


app = FastAPI(title="Chatsune", version="0.1.0", lifespan=lifespan)
app.include_router(user_router)


@app.get("/api/health")
async def health():
    return {"status": "ok"}
```

- [ ] **Step 3: Run full test suite**

```bash
uv run --project backend pytest tests/ -v
```

Expected: All tests pass (setup, auth, user management, audit log, auth utils, refresh).

- [ ] **Step 4: Commit**

```bash
git add backend/modules/user/__init__.py backend/main.py
git commit -m "Wire up user module public API and clean up main.py imports"
```

---

## Task 13: README & Documentation

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Update `README.md`**

```markdown
# Chatsune

Privacy-first, self-hosted, multi-user AI companion platform.

## Prerequisites

- [Docker](https://docs.docker.com/get-docker/) and Docker Compose
- [uv](https://docs.astral.sh/uv/) (for local development)

## Quick Start

```bash
# Copy environment template and configure
cp .env.example .env
# Edit .env — at minimum change MASTER_ADMIN_PIN and JWT_SECRET

# Start services
docker compose up -d

# Verify
curl http://localhost:8000/api/health
# {"status":"ok"}
```

## Initial Setup

Create the master admin account (one-time):

```bash
curl -X POST http://localhost:8000/api/setup \
  -H "Content-Type: application/json" \
  -d '{
    "pin": "your-configured-pin",
    "username": "admin",
    "email": "admin@example.com",
    "password": "your-secure-password"
  }'
```

## Environment Variables

| Variable | Description | Example |
|---|---|---|
| `MASTER_ADMIN_PIN` | PIN for initial master admin setup | `change-me-1234` |
| `JWT_SECRET` | Secret for signing JWTs. Generate with `openssl rand -hex 32` | (random hex string) |
| `MONGODB_URI` | MongoDB connection string (must include `replicaSet=rs0`) | `mongodb://mongodb:27017/chatsune?replicaSet=rs0` |
| `REDIS_URI` | Redis connection string | `redis://redis:6379/0` |

## Development

```bash
# Install backend dependencies
cd backend && uv sync --all-extras && cd ..

# Run tests (requires Docker services running)
uv run --project backend pytest tests/ -v
```

## Architecture

See [CLAUDE.md](CLAUDE.md) for full architectural documentation.
```

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "Update README with setup instructions and environment documentation"
```
