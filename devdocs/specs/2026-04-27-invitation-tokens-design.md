# Spec: One-Time Invitation Links

**Status:** Draft  
**Date:** 2026-04-27  
**Owner:** Chris

---

## Context & Motivation

Chatsune currently requires manual user creation by an admin (`POST /api/admin/users`)
after Discord approval. The admin generates a random password server-side and shares
it out-of-band; the new user then logs in and changes the password. This is friction-heavy
and error-prone, and it does not extend to the BYO-key crypto scheme correctly: the
generated password is created server-side, so the user's data encryption key (DEK) is
provisioned without the user ever holding the corresponding KEK material.

This spec introduces a token-based self-registration flow: the admin generates a one-time
link, shares it via Discord, and the new user creates their own account — choosing their
own password — without further admin involvement. The flow uses the existing E2E crypto
schema (Argon2 client-side hash, wrapped DEK, recovery key) so it is fully compatible
with all current and future security guarantees.

The existing `POST /api/admin/users` flow is **not removed**. It remains available for
admin-driven creation (edge cases, recovery scenarios). The invitation flow is purely
additive — a transparent add-on that breaks nothing.

---

## Out of Scope

- Email verification / double opt-in
- Password reset flow (already exists separately)
- Listing / revoking active tokens (YAGNI — tokens expire after 24h)
- Rate limiting on registration attempts (defer to later)
- Audit-trail UI (audit lives in the existing `audit_log` collection)

---

## Architecture Overview

Invitation tokens live in the **user** module (no new module needed — they are part of
the user/auth lifecycle). They share the existing user-creation primitives via a
refactored helper `_provision_new_user`, which both `/auth/setup` (master-admin) and
the new `/invitations/.../register` endpoint call.

The token is a cryptographically random value (32 URL-safe bytes via
`secrets.token_urlsafe(32)`). Validation, registration, and admin generation are three
separate endpoints. All token state transitions (mark-used + user-create + key-provision)
happen inside a single MongoDB transaction so that race conditions and partial failures
cannot leave the system in an inconsistent state.

The frontend gets a new public route `/register/:token` styled in the opulent
prototype style (this is the new user's first impression of Chatsune), and a small
"+ Invitation Link" button in the existing `AdminModal` → `UsersTab`, sitting beside
the existing "+ New User" button.

---

## Data Model

### New collection: `invitation_tokens`

```python
class InvitationTokenDocument(BaseModel):
    _id: ObjectId
    token: str                      # secrets.token_urlsafe(32)
    created_at: datetime
    expires_at: datetime            # created_at + 24h
    used: bool = False
    used_at: datetime | None = None
    used_by_user_id: str | None = None
    created_by: str                 # admin user id
```

### Indexes (idempotent, applied at module init)

- `{token: 1}` unique
- `{expires_at: 1}` with `expireAfterSeconds: 0` (MongoDB TTL — auto-cleanup of
  all tokens 24h after `expires_at`, including used ones; audit information lives
  in `audit_log`, so the token document itself does not need to persist beyond TTL)

### Audit log entries (existing `audit_log` collection)

- `action: "user.invitation_created"` — actor: admin user id, detail: `{ token_id }`
- `action: "user.invitation_used"` — actor: new user id, detail: `{ token_id }`

---

## Backend

### Module layout

```
backend/modules/user/
  _invitation_repository.py     ← new
  _invitation_handlers.py       ← new (sub-router under same APIRouter)
  _handlers.py                  ← extract _provision_new_user helper
```

### Helper extraction (refactor, no behaviour change)

The user-creation block in `/auth/setup` (lines ~172–197 of `_handlers.py`) becomes a
private helper:

```python
async def _provision_new_user(
    *,
    username: str,
    email: str,
    display_name: str,
    h_auth: str,
    h_kek: str,
    recovery_key: str,
    role: str,
) -> tuple[dict, bytes]:
    """Create user document + provision DEK/KEK keys.
    Returns (user_doc, unlocked_dek). Raises on collision or crypto error.
    Caller is responsible for session creation, audit, events, and event publishing.
    """
```

Both `/auth/setup` and `/invitations/{token}/register` call this. Only the surrounding
code (PIN check / token check, master-admin role enforcement, role choice) differs.

### Endpoint 1: `POST /api/admin/invitations`

- **Auth:** admin role required (`Depends(require_admin)`)
- **Body:** `{}` (empty — no note field)
- **Behaviour:**
  1. Generate token via `secrets.token_urlsafe(32)`
  2. Insert document with `created_at = now`, `expires_at = now + 24h`, `created_by = admin_id`
  3. Audit log + event publish (`Topics.INVITATION_CREATED`)
  4. Return `{ token, expires_at }` — **URL is built client-side** from `window.location.origin`
- **Response shape:**
  ```python
  class CreateInvitationResponseDto(BaseModel):
      token: str
      expires_at: datetime
  ```

### Endpoint 2: `POST /api/invitations/{token}/validate`

- **Auth:** none (public)
- **Why POST not GET:** prevents tokens leaking into server access logs and browser history
- **Behaviour:**
  1. Look up token
  2. Determine status: `valid` / `used` / `expired` / `not_found`
  3. **Always return HTTP 200** with `{ valid: bool, reason?: "..." }`
     — never 404/410, otherwise the HTTP status leaks the precise reason and enables
     enumeration. Frontend renders the reason from JSON.
- **Response:**
  ```python
  class ValidateInvitationResponseDto(BaseModel):
      valid: bool
      reason: Literal["expired", "used", "not_found"] | None = None
  ```

### Endpoint 3: `POST /api/invitations/{token}/register`

- **Auth:** none (public)
- **Body:** identical to `SetupRequestV2Dto` minus `pin`:
  ```python
  class RegisterViaInvitationRequestDto(BaseModel):
      username: str
      email: str
      display_name: str
      h_auth: str
      h_kek: str
      recovery_key: str
  ```
- **Behaviour (inside MongoDB transaction):**
  1. `find_one_and_update({token, used: False, expires_at: {$gt: now}}, {$set: {used: True, used_at: now, used_by_user_id: <placeholder>}})`
     — atomic check-and-set, single op, only one concurrent caller wins
  2. If no document returned → 410 Gone
  3. Call `_provision_new_user(role="user", ...)`
  4. Patch token document with real `used_by_user_id`
  5. Audit + event publishing
  6. Commit transaction; on **any** failure (collision, crypto error, etc.), the
     transaction aborts and the token returns to `used: False`
- **Response:**
  ```python
  class RegisterViaInvitationResponseDto(BaseModel):
      success: bool
      user_id: str
  ```
  **No auto-login**, no access token. The user navigates to `/login` themselves.
- **Error responses:**
  - 410 Gone — token consumed, expired, or unknown
  - 409 Conflict — username or email collision
  - 422 Unprocessable Entity — validation error

### Server-side password strength

The crypto schema means the password **never reaches the server** in any form — only
the client-derived `h_auth` and `h_kek` do. The server therefore cannot enforce
password strength rules. Strength validation is purely client-side (mirroring the
existing setup flow).

> **INSIGHTS note (to file during implementation):** record this constraint
> so it does not get re-litigated. A future server-side strength check would
> require shipping the password to the server, which would defeat the entire
> BYO-key model.

### Shared contracts

`shared/dtos/invitation.py` (new file):
- `CreateInvitationResponseDto`
- `ValidateInvitationResponseDto`
- `RegisterViaInvitationRequestDto`
- `RegisterViaInvitationResponseDto`

`shared/topics.py`:
- `INVITATION_CREATED = "user.invitation.created"`
- `INVITATION_USED = "user.invitation.used"`

`shared/events/auth.py` (extend):
- `InvitationCreatedEvent { token_id, created_by, expires_at }`
- `InvitationUsedEvent { token_id, used_by_user_id }`

---

## Frontend

### New page: `frontend/src/app/pages/RegisterPage.tsx`

**Route:** `/register/:token` (public, **outside** any `<RequireAuth>` wrapper)

**Style:** Opulent (prototype style) — matches `LoginPage`. Background, glow,
serif headline; the new user's first visual impression of Chatsune.

**State machine:**

```
validating  → POST /api/invitations/{token}/validate
   ├→ valid    → form
   └→ invalid  → invalid screen (rendered reason from JSON)
form        → user fills out and submits
   ├→ deriving (client: fetch fresh kdf_salt, run Argon2 → h_auth/h_kek, generate recoveryKey)
   ├→ submitting → POST /api/invitations/{token}/register
   ├→ recovery-key (RecoveryKeyModal — reused as-is)
   └→ success screen → "Account created" + button → /login
```

**Form fields** (mirror the master-admin setup block in `LoginPage`):
- Username
- Email
- Display name
- Password + confirm password
- Visual strength meter (client-side)
- Show/hide password toggle

**Error rendering:**
- 410 → "This invitation link has already been used or expired" + login button (no retry)
- 409 → inline at username/email field, user can correct and resubmit (token survives because of transaction rollback)
- 422 → inline field-level errors

### Code sharing with `LoginPage` setup block

The crypto + form logic in `LoginPage`'s setup mode is duplicated rather than
extracted into a hook. Rationale: rule of three. The third variant of "create-an-
account-with-DEK" will trigger the extraction; today, two copies with a
`// see also: LoginPage setup block` comment is the lower-risk choice.

> **INSIGHTS note (to file):** record "two copies of account-creation crypto;
> extract to `useAccountSetup` hook on third use".

### Admin trigger: `frontend/src/app/components/admin-modal/UsersTab.tsx`

Add a button beside the existing "+ New User":

```
Users                                  [ + Invitation Link ]  [ + New User ]
```

**Click → new local component `InvitationLinkDialog.tsx`** (Catppuccin, matches surrounding admin UI):

```
┌─ New Invitation Link ──────────────┐
│                                    │
│  Share this link with the new      │
│  user. It is valid for 24 hours    │
│  and can be used exactly once.     │
│                                    │
│  Save it before closing — you      │
│  cannot retrieve it again.         │
│                                    │
│  ┌──────────────────────────────┐  │
│  │ http://localhost:5173/...    │  │
│  └──────────────────────────────┘  │
│                                    │
│  [ Copy ]   [ Close ]              │
│                                    │
│  Expires: 2026-04-28 14:32 UTC     │
└────────────────────────────────────┘
```

**Behaviour:**
- "Generate" click → POST `/api/admin/invitations` → dialog opens
- URL is built **client-side** as `${window.location.origin}/register/${token}` —
  picks up correct host and port automatically (works for `localhost:5173`,
  prod hosts, anything in between)
- "Copy" → `navigator.clipboard.writeText()` with brief "Copied!" feedback
  (same pattern as `RecoveryKeyModal`)
- "Close" dismisses dialog; **token is not retrievable again** from the UI

**Not included** (deliberately): listing, revoke, history. YAGNI.

---

## Tests

### Backend (`backend/tests/modules/user/test_invitations.py`)

Note: these tests use MongoDB and therefore belong to the "Docker-only" test set
(per project convention; on host they are excluded).

1. `test_create_invitation_returns_token_and_expires`
2. `test_create_invitation_requires_admin` (user role → 403)
3. `test_validate_returns_valid_for_fresh_token`
4. `test_validate_returns_invalid_for_used_token` (reason `"used"`)
5. `test_validate_returns_invalid_for_expired_token`
6. `test_validate_returns_invalid_for_unknown_token` (reason `"not_found"`)
7. `test_validate_status_always_200` (no enumeration via HTTP code)
8. `test_register_creates_user_and_marks_token_used`
9. `test_register_with_used_token_returns_410`
10. `test_register_with_expired_token_returns_410`
11. `test_register_with_invalid_token_returns_410`
12. `test_register_concurrent_same_token` — two parallel calls; exactly one succeeds, the other gets 410
13. `test_register_username_collision_returns_409_and_token_unused` (transaction rollback)
14. `test_register_creates_user_with_role_user` (no privilege escalation possible via token)
15. `test_existing_setup_endpoint_unchanged_after_helper_extraction` (regression smoke)

### Frontend

No automated frontend tests for this feature (no existing page-level test convention
in the repo). Coverage relies on manual verification.

---

## Manual Verification

Run on **localhost** with backend + frontend dev servers and a fresh database.

### 1. Token generation
- Log in as master-admin → open Admin modal → Users tab
- Click "+ Invitation Link"
- Dialog appears with `http://localhost:5173/register/<token>` and expiry timestamp
- "Copy" button copies URL to clipboard (verify by pasting)
- "Close" dismisses dialog

### 2. Happy path
- Open the copied link in an incognito tab
- See validating spinner, then registration form
- Fill in valid username, email, display name, password (≥ 12 chars, mix)
- Submit → recovery-key modal appears
- Copy or download the recovery key, click "I have saved it"
- Success screen appears with login button
- Click login button → land on login page
- Log in with the new credentials → reach `/personas` successfully

### 3. Token reuse
- Open the same link again in another incognito tab
- See "This invitation link has already been used or expired" + login button
- Confirm via curl: `curl -X POST http://localhost:8000/api/invitations/<used_token>/register -d '...'`
  returns 410

### 4. Expired token
- Generate a fresh token
- In MongoDB shell: `db.invitation_tokens.updateOne({token: "..."}, {$set: {expires_at: ISODate("2020-01-01T00:00:00Z")}})`
- Open the link → see expired message

### 5. Unknown token
- Open `http://localhost:5173/register/garbage-token-string`
- See invalid message
- Verify HTTP response: validate returns status 200 with `{ valid: false, reason: "not_found" }` (NOT 404)

### 6. Concurrent race
- Open the same valid invitation link in two browser tabs
- Fill out the form in both tabs
- Submit both as close to simultaneously as possible
- Exactly one tab succeeds (recovery-key modal appears); the other shows 410

### 7. Username collision
- Generate a token
- Open it, enter the username of an existing user, submit
- See 409 inline error at username field; token remains usable
- Correct the username, submit again → success

### 8. Existing flows untouched
- Master-admin setup still works (fresh DB, existing `/auth/setup` flow)
- Existing "+ New User" admin flow still works (creates user with random password)

---

## Implementation Order

1. **Backend foundation**
   - `InvitationTokenDocument` model
   - `_invitation_repository.py` with indexes (TTL + unique)
   - Refactor `_provision_new_user` helper out of `/auth/setup`
2. **Backend endpoints**
   - `POST /api/admin/invitations`
   - `POST /api/invitations/{token}/validate`
   - `POST /api/invitations/{token}/register` (with transaction)
3. **Shared contracts**
   - `shared/dtos/invitation.py`
   - extend `shared/topics.py` and `shared/events/auth.py`
4. **Backend tests**
5. **Frontend register page**
   - `RegisterPage.tsx` with state machine
   - Crypto + form logic (duplicated from `LoginPage` setup block)
   - Reuse `RecoveryKeyModal`
6. **Frontend admin trigger**
   - `InvitationLinkDialog.tsx`
   - Wire into `UsersTab.tsx` next to "+ New User"
7. **Manual verification end-to-end** (the section above)
8. **INSIGHTS entries**
   - Server-side password strength impossibility (BYO-key constraint)
   - Account-creation crypto duplicated; extract on third use

---

## Acceptance Criteria

- [ ] Token works exactly once; second attempt returns 410
- [ ] Token older than 24h returns invalid (validate) / 410 (register)
- [ ] Registered user can immediately log in with the credentials they entered
- [ ] Two concurrent register requests with the same valid token: exactly one succeeds, one gets 410
- [ ] Username collision returns 409 and token remains usable (transaction rollback)
- [ ] Admin can generate token via the UI button; URL contains correct host:port
- [ ] Validate endpoint always returns HTTP 200 (no enumeration via status code)
- [ ] Existing `/auth/setup` flow remains functionally identical
- [ ] Existing `POST /api/admin/users` flow remains functionally identical
- [ ] Recovery key is shown exactly once via the existing `RecoveryKeyModal`
- [ ] No new role/escalation surface — invitation tokens always create `role="user"`
