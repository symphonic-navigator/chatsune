# User Module & Authentication — Design Spec

**Date:** 2026-04-02
**Scope:** Master admin setup, user management, JWT/refresh token system, audit log
**Phase:** 1 (foundation)

---

## 1. Infrastructure

### Docker Compose Services

- **mongodb** — Mongo 7.0, single-node replica set (RS0), persistent volume
- **redis** — Redis 7, persistent volume
- **backend** — FastAPI app, depends on mongo + redis

### Environment Variables (`.env.example`)

| Variable | Description | Example |
|---|---|---|
| `MASTER_ADMIN_PIN` | PIN required for initial master admin setup | `change-me-1234` |
| `JWT_SECRET` | Secret key for signing access tokens (HS256) | `super-secret-key-change-me` |
| `MONGODB_URI` | MongoDB connection string | `mongodb://mongodb:27017/chatsune?replicaSet=rs0` |
| `REDIS_URI` | Redis connection string | `redis://redis:6379/0` |

### Directory Structure (Phase 1 only)

```
chatsune/
  backend/
    main.py
    modules/
      user/
        __init__.py
        _repository.py
        _handlers.py
        _models.py
  shared/
    dtos/
      auth.py
    events/
      auth.py
      system.py
    topics.py
  frontend/               (placeholder, no code yet)
  docs/
  docker-compose.yml
```

---

## 2. User Model

Stored in MongoDB collection `users`.

| Field | Type | Description |
|---|---|---|
| `_id` | ObjectId | Primary key |
| `username` | str (unique) | Login identifier |
| `email` | str (unique) | User email address |
| `display_name` | str | Display name shown in UI |
| `password_hash` | str | bcrypt hash |
| `role` | str | One of `master_admin`, `admin`, `user` |
| `is_active` | bool | `false` = soft-deleted/disabled |
| `must_change_password` | bool | `true` = forced password change on next login |
| `created_at` | datetime | Account creation timestamp |
| `updated_at` | datetime | Last modification timestamp |

---

## 3. Master Admin Setup

**Endpoint:** `POST /api/setup`

**Request body:**
```json
{
  "pin": "the-configured-pin",
  "username": "admin",
  "email": "admin@example.com",
  "password": "chosen-password"
}
```

**Flow:**
1. Check if a user with role `master_admin` exists in DB. If yes → 409 Conflict.
2. Validate `pin` against `MASTER_ADMIN_PIN` env var. If mismatch → 403 Forbidden.
3. Create user with `role: master_admin`, `must_change_password: false`, `is_active: true`.
4. Generate session (access token + refresh token).
5. Return user DTO + access token. Set refresh token as httpOnly cookie.

**Audit log entry:** `action: user.created`, `resource_type: user`

---

## 4. User Management

### Role Hierarchy

- **master_admin** — exactly one. Can manage all users including admins. Cannot be deactivated or deleted.
- **admin** — can manage users with role `user` only. Cannot touch other admins or master_admin.
- **user** — no management permissions.

### Endpoints

| Method | Path | Access | Description |
|---|---|---|---|
| `POST` | `/api/admin/users` | master_admin, admin | Create user |
| `GET` | `/api/admin/users` | master_admin, admin | List users (paginated) |
| `GET` | `/api/admin/users/{id}` | master_admin, admin | Get single user |
| `PATCH` | `/api/admin/users/{id}` | master_admin, admin | Update user (display_name, email, is_active, role) |
| `POST` | `/api/admin/users/{id}/reset-password` | master_admin, admin | Generate new password |
| `DELETE` | `/api/admin/users/{id}` | master_admin, admin | Soft-delete (set is_active = false) |

### Permission Rules

- Admins can only manage users with role `user`.
- Only master_admin can assign or revoke the `admin` role.
- Nobody can deactivate or delete the master_admin.
- Nobody can deactivate themselves.

### User Creation

- Admin provides: `username`, `email`, `display_name`, `role`.
- System generates alphanumeric random password (20 characters).
- Response includes the generated password in plaintext (one-time display).
- User is created with `must_change_password: true`.

### Password Reset

- Generates a new alphanumeric random password (20 characters).
- Sets `must_change_password: true`.
- Response includes the new password in plaintext (one-time display).
- Audit log entry recorded.

---

## 5. Audit Log

Stored in MongoDB collection `audit_log`. Append-only — no updates, no deletes.

| Field | Type | Description |
|---|---|---|
| `_id` | ObjectId | Primary key |
| `timestamp` | datetime | When the action occurred |
| `actor_id` | str | User ID of who performed the action |
| `action` | str | e.g. `user.created`, `user.deactivated`, `llm.model_blocked` |
| `resource_type` | str | e.g. `user`, `llm_model`, `system_config` |
| `resource_id` | str or null | ID of the affected resource |
| `detail` | dict or null | Additional context |

### Endpoint

`GET /api/admin/audit-log`

- **master_admin**: sees all entries
- **admin**: sees only entries where `actor_id` matches their own user ID
- Pagination via `skip`/`limit` query parameters
- Optional filters: `action`, `resource_type`, `resource_id`, `actor_id`

---

## 6. JWT & Refresh Token System

### Access Token (JWT)

- Algorithm: HS256, signed with `JWT_SECRET`
- Expiry: 15 minutes
- Payload claims: `sub` (user_id), `role`, `session_id`, `exp`, `iat`, `mcp` (must change password, only present when `true`)

### Refresh Token

- Opaque random string, 64 characters, alphanumeric
- Stored in Redis: key `refresh:{token}` → value `{user_id, session_id, created_at}`
- TTL: 30 days
- Delivered as `httpOnly`, `Secure`, `SameSite=Strict` cookie

### Endpoints

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/auth/login` | Authenticate with username + password |
| `POST` | `/api/auth/refresh` | Exchange refresh token for new token pair |
| `POST` | `/api/auth/logout` | Invalidate refresh token, clear cookie |
| `PATCH` | `/api/auth/password` | Change own password (also used for must_change_password flow) |

### Login Flow

1. Validate username + password against DB (bcrypt verify).
2. Check `is_active == true`. If not → 403.
3. Generate `session_id` (UUID).
4. Create access token JWT with claims.
5. Create refresh token, store in Redis with 30-day TTL.
6. Return access token in response body. Set refresh token as httpOnly cookie.

### Token Refresh Flow

1. Read refresh token from cookie.
2. Look up in Redis. If not found → 401.
3. Delete old refresh token from Redis.
4. Generate new access token + new refresh token.
5. Store new refresh token in Redis.
6. Return new access token. Set new refresh cookie.

### Replay Detection

If a refresh token that has already been consumed (deleted from Redis) is presented again, this indicates a potential token theft. Response: delete ALL refresh tokens for that user (all keys matching the user_id), forcing re-login on all devices.

### must_change_password Flow

- When `must_change_password` is `true`, the access token includes claim `mcp: true`.
- With an `mcp: true` token, only these endpoints are accessible:
  - `PATCH /api/auth/password`
  - `POST /api/auth/logout`
- All other endpoints return 403 with a clear error message.
- After successful password change: `must_change_password` set to `false`, new token pair issued without `mcp` claim.

---

## 7. Shared Contracts (Phase 1)

### DTOs (`shared/dtos/auth.py`)

- `UserDto` — id, username, email, display_name, role, is_active, must_change_password, created_at, updated_at
- `SetupRequestDto` — pin, username, email, password
- `LoginRequestDto` — username, password
- `CreateUserRequestDto` — username, email, display_name, role
- `UpdateUserRequestDto` — display_name (opt), email (opt), is_active (opt), role (opt)
- `ChangePasswordRequestDto` — current_password, new_password
- `TokenResponseDto` — access_token, token_type, expires_in
- `CreateUserResponseDto` — user (UserDto), generated_password
- `AuditLogEntryDto` — id, timestamp, actor_id, action, resource_type, resource_id, detail

### Events (`shared/events/auth.py`)

- `UserCreatedEvent`
- `UserUpdatedEvent`
- `UserDeactivatedEvent`
- `UserPasswordResetEvent`

### Topics (`shared/topics.py`)

- `Topics.USER_CREATED`
- `Topics.USER_UPDATED`
- `Topics.USER_DEACTIVATED`
- `Topics.USER_PASSWORD_RESET`

### Error Events (`shared/events/system.py`)

- `ErrorEvent` as defined in CLAUDE.md
