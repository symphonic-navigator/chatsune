# Per-User Key Infrastructure — Design

**Status:** Draft
**Date:** 2026-04-23
**Scope:** Prepare the cryptographic foundations for later per-user data encryption. This spec builds infrastructure only; no existing data is encrypted by this work.

---

## 1. Purpose

Lay the groundwork for at-rest encryption of user-owned data (MongoDB documents and filesystem artefacts) such that **no holder of the database dump, environment file, or live server — including the operator — can read a user's data without that user's password or recovery key**.

The encryption of actual data fields is explicitly out of scope here and will be rolled out collection-by-collection in later work. This spec delivers the key-management plumbing so that later rollout becomes a per-collection, backwards-compatible change.

---

## 2. Threat Model

Protect against:

- **Offline database dumps** (stolen backups, inspected Docker volumes, leaked replicas)
- **Offline environment leaks** (`.env` with `encryption_key` falling into wrong hands — compromising the Fernet master key must not compromise user data)
- **Operator/admin inspection without the user's cooperation** (operators cannot read user data by looking at the DB, even combined with the master key)
- **Physical hardware theft** in cold state

Explicitly *not* protected against:

- **Live RAM capture of a running server while a user session is active** — during an active session the server necessarily holds the user's DEK in memory so it can run LLM calls, memory consolidation, embeddings, etc.
- **Live traffic interception between client and server** — the client sends password-derived material to the server over TLS; anyone terminating TLS in the request path with administrative privilege can derive the KEK. Acceptable because TLS termination already implies full-server-compromise territory.
- **Forgotten password *and* lost recovery key** — the data is gone. This is a deliberate consequence of the trust model.

---

## 3. Key Hierarchy

```
User password  (only in the browser)
        │
        │ Argon2id(kdf_salt, kdf_params)
        ▼
      H  (64 bytes, client-side)
        │
   ┌────┴────┐
   │ HKDF    │ HKDF
   │ "auth"  │ "kek"
   ▼         ▼
 H_auth    H_kek
   │         │
   ▼         ▼
 (sent to server)
   │         │
   ▼         ▼
 bcrypt     unwrap wrapped_dek
 verify     → DEK (32 bytes)
                │
                ▼
         Redis session_dek:{session_id}
         (TTL = access-token-TTL)
                │
                ▼
         (later) encrypt user data fields / blobs
```

- **Password** never leaves the browser. Both hashes are derived client-side and transmitted separately.
- **`H_auth`** is treated as the "password" for authentication — `bcrypt` is applied server-side with a fresh salt, stored in `users.password_hash`.
- **`H_kek`** is used once per login to unwrap the DEK, then forgotten server-side.
- **DEK** is a 32-byte CSRNG key, wrapped with `H_kek` (`wrapped_by_password`) and with a separate recovery key (`wrapped_by_recovery`). Stored in the new `user_keys` collection.
- **Recovery Key** is a 32-character Crockford-Base32 string (~160 bit entropy), generated client-side at signup/migration, shown **once**, never transmitted outside that single unlock call.

Key rotation is supported by design (see §6, `deks` map keyed by version).

---

## 4. Data Model

### New collection: `user_keys`

One document per user, created at signup or on first login for legacy users.

```python
# backend/modules/user/_models.py  (new model)

class UserKeysDocument(BaseModel):
    user_id: ObjectId                    # FK to users._id, unique index
    kdf_salt: bytes                       # 32 random bytes, not secret
    kdf_params: Argon2Params              # m, t, p — persisted per user for future tuning
    current_dek_version: int              # active version for new writes; starts at 1
    deks: dict[str, WrappedDekPair]       # str key is version (e.g. "1")
    dek_recovery_required: bool = False   # set True on admin reset, cleared after recovery
    created_at: datetime
    updated_at: datetime

class Argon2Params(BaseModel):
    memory_kib: int = 65536   # 64 MiB
    iterations: int = 3
    parallelism: int = 4

class WrappedDekPair(BaseModel):
    wrapped_by_password: bytes   # AES-256-GCM(key=HKDF(H_kek, "dek-wrap"), nonce||ct||tag)
    wrapped_by_recovery: bytes   # AES-256-GCM(key=HKDF(rec_key, "dek-wrap"), nonce||ct||tag)
    created_at: datetime
```

Blob layout for every wrapped value: `12-byte nonce || ciphertext || 16-byte tag`.

Unique index: `{user_id: 1}`.

### Changes to existing `users` documents

Add one field:

```python
users.password_hash_version: int = 1
```

- Version `1` means `password_hash = bcrypt(H_auth)` (the new format).
- Legacy documents have no field (treated as "raw-password flavour"). They are auto-upgraded at first login (see §8).

No other field in `users` changes. No field is removed.

### `dek_version` field convention (future use, reserved now)

The following convention is specified here but **not applied to any collection by this work**:

| Value on a user-owned document | Meaning |
|---|---|
| `dek_version` absent / `null` | Document is **plaintext** (pre-encryption or legacy) |
| `dek_version: N` (N ≥ 1) | Document's encrypted fields are sealed with the user's DEK version `N` |

Every later collection rollout will:
1. Add per-document encrypted byte fields next to (or replacing) plaintext ones.
2. Set `dek_version` to the user's `current_dek_version` at write time.
3. Read path branches on `dek_version`: absent → plaintext, present → decrypt.

This lets us:
- Roll out encryption collection-by-collection without a global flag day.
- Run lazy re-encryption jobs for key rotation.
- Know exactly which documents are affected in a "recovery failed" scenario (§7).

---

## 5. API Surface

### 5.1 `POST /api/auth/kdf-params`

**Public, no auth required.** Returns the Argon2id salt + parameters for a given username so the client can derive `H` before `POST /api/auth/login`.

Request:
```json
{ "username": "chris" }
```

Response (200, always):
```json
{
  "kdf_salt": "<base64url, 32 bytes>",
  "kdf_params": { "memory_kib": 65536, "iterations": 3, "parallelism": 4 }
}
```

**User-enumeration defence:** for unknown usernames, return a **deterministic pseudo-salt** derived as `HMAC-SHA256(server_kdf_pepper, username.lower().strip())[:32]`. `server_kdf_pepper` is a 32-byte secret in `.env` (new env var `kdf_pepper`, separate from `encryption_key`). Response shape and timing are indistinguishable from real users; the login attempt fails at `bcrypt_verify` afterwards. The pseudo-salt is stable per username so repeated probes yield the same answer.

### 5.2 `POST /api/auth/login` (updated contract)

Request (new shape):
```json
{
  "username": "chris",
  "h_auth": "<base64url, 32 bytes>",
  "h_kek":  "<base64url, 32 bytes>"
}
```

Server behaviour:
1. `bcrypt_checkpw(h_auth, users.password_hash)` — fail → `401 invalid_credentials`.
2. If `dek_recovery_required` is true on `user_keys` → respond `200` with body `{ "status": "recovery_required" }` and no tokens. Frontend triggers recovery flow (§7).
3. Otherwise: `DEK = aes_gcm_unwrap(user_keys.deks[current_dek_version].wrapped_by_password, key=HKDF(h_kek, "dek-wrap"))`.
   - If unwrap fails with tag mismatch → `500 dek_integrity_error` (this should never happen; it indicates DB corruption).
4. Store `DEK` in Redis under `session_dek:{session_id}` with TTL = `access_token_ttl_seconds`.
5. Issue access + refresh tokens as today. Access-token claims are unchanged (the existing `session_id` is the lookup key).

**Legacy-password fallback:** if `users.password_hash_version` is absent, the server interprets the request as a legacy login where the client still submitted `{username, password}` (via the pre-deployment frontend code). See §8 for the transitional contract.

### 5.3 `POST /api/auth/recover-dek`

Used when the user's login returned `{status: "recovery_required"}`.

Request:
```json
{
  "username": "chris",
  "h_auth": "...",
  "h_kek":  "...",
  "recovery_key": "XXXX-XXXX-XXXX-XXXX-XXXX-XXXX-XXXX-XXXX"
}
```

Server:
1. Normalise recovery key: strip hyphens, uppercase, Crockford-Base32-decode. Reject on invalid checksum.
2. `bcrypt_checkpw(h_auth, users.password_hash)` — must succeed.
3. `DEK = aes_gcm_unwrap(wrapped_by_recovery, key=HKDF(decoded_recovery, "dek-wrap"))` — fail → `401 invalid_recovery_key`. Rate-limit this endpoint (Redis, 5 attempts / 15 min / user).
4. Rewrap with current `H_kek`: replace `wrapped_by_password` in the active DEK version.
5. Clear `dek_recovery_required`.
6. Issue tokens + store DEK in Redis (as in login step 4–5).

### 5.4 `POST /api/auth/change-password` (updated contract)

Request:
```json
{
  "h_auth_old": "...",
  "h_kek_old":  "...",
  "h_auth_new": "...",
  "h_kek_new":  "..."
}
```

Server: verify old H_auth, unwrap DEK with old H_kek, rewrap with new H_kek, update `password_hash = bcrypt(h_auth_new)`. `wrapped_by_recovery` stays untouched.

### 5.5 `POST /api/auth/decline-recovery`

Called by frontend when user clicks "I do not have my recovery key" on the recovery screen.

Server: set `users.is_active = false` (keeps `dek_recovery_required=true`, no DEK rewrap). Publish `AuditLoggedEvent`. Subsequent login attempts fail with `403 account_disabled`. Only an admin can reactivate the account (and at that point the admin-side data-destruction flow — out of scope here — will become necessary once any data is actually encrypted).

### 5.6 Signup & admin-setup flows

The client generates the recovery key (32 random bytes, Crockford-Base32-encoded) before submitting, and sends it in the single signup request. The server uses it to derive the second wrap key, persists the wraps, and drops the plaintext recovery key from memory.

Request body:

```json
{
  "username": "...",
  "h_auth": "...",
  "h_kek":  "...",
  "recovery_key": "<plaintext, sent once, then forgotten server-side>"
}
```

Server:

1. Generate a 32-byte DEK (CSRNG).
2. `users.password_hash = bcrypt(h_auth)`, `password_hash_version = 1`.
3. Persist `user_keys`: `current_dek_version = 1`, `deks["1"] = { wrapped_by_password: AES-GCM(key=HKDF(h_kek, "dek-wrap"), DEK), wrapped_by_recovery: AES-GCM(key=HKDF(recovery_key, "dek-wrap"), DEK) }`.
4. Drop the plaintext recovery key and plaintext DEK from memory.
5. Publish `UserKeyProvisionedEvent{reason: "signup"}`, issue tokens.

Frontend: the client already holds the recovery key (it generated it). Immediately after the signup response arrives, it opens the recovery-key modal with "Copy", "Download as .txt", and "I have saved this" checkbox. Modal is non-dismissable until the checkbox is ticked.

**Rationale for sending the recovery key over the wire during this single request:** the alternative is to have the client perform the AES-GCM wrap itself and send the already-wrapped blob, which would duplicate HKDF + AES-GCM code on both sides. The server-side wrap during the one-shot signup window is acceptable because (a) this request is the initial trust moment anyway, (b) the plaintext recovery key is not persisted or logged, and (c) all subsequent recovery uses go through `/recover-dek`, which already has the same transient-exposure property.

### 5.7 Admin reset (updated UX)

`POST /admin/users/{user_id}/reset-password` changes:

- Admin UI gains a **warning dialog**: "This reset does not give you access to the user's data. If the user does not have their recovery key, all encrypted data for this account will become permanently inaccessible."
- Admin confirms → server generates random password, sets `users.password_hash = bcrypt(H_auth_for_that_password)`, `must_change_password = true`, **`user_keys.dek_recovery_required = true`**.
- `wrapped_by_password` stays untouched — the admin does not have the cryptographic ability to rewrap.

Caveat: for the admin path, the random password is generated server-side, so the server *does* see a plaintext password briefly. This is acceptable because: (a) the admin hands it to the user out-of-band, (b) it is single-use and the user will change it immediately after recovery, (c) this is a reset path, not a regular auth path.

---

## 6. Crypto Primitives

| Purpose | Primitive | Library |
|---|---|---|
| Client password KDF | Argon2id (m=64 MiB, t=3, p=4) | `argon2-browser` (WASM) in a Web Worker |
| Client HKDF (`H` → `H_auth`, `H_kek`) | HKDF-SHA-256 | Native `SubtleCrypto.deriveBits` |
| Server auth hash | bcrypt (cost 12) over `H_auth` | existing `bcrypt` dependency |
| DEK generation | `secrets.token_bytes(32)` | stdlib |
| DEK wrap / unwrap | AES-256-GCM, 12-byte random nonce per wrap, 16-byte tag | `cryptography.hazmat.primitives.ciphers.aead.AESGCM` |
| Wrap-key derivation | HKDF-SHA-256(input, info=b"dek-wrap", length=32) | `cryptography.hazmat.primitives.kdf.hkdf` |
| Recovery-key format | 32-char Crockford-Base32 (`0-9`, `A-Z` minus `I L O U`), grouped `4-4-4-4-4-4-4-4` | implementation in `backend/modules/user/_recovery_key.py` |
| Pseudo-salt for ghost users | HMAC-SHA-256(`kdf_pepper`, username.lower()) truncated to 32 bytes | `hmac` + `hashlib` |

All wrapped blobs are stored as raw bytes (Mongo `BinData`), not base64.

The existing `encryption_key` (Fernet) continues to cover *integration credentials* and *premium provider accounts* — it is the "server-held at-rest key for data the server must use autonomously even without a user session". It is explicitly **not** involved in user-data encryption. Keeping these two key materials separate is a correctness property of this design.

---

## 7. Flows (detailed)

### 7.1 Signup

1. Admin opens setup page (first-run PIN flow) → provides credentials.
2. Frontend: generate `recovery_key` client-side (Crockford-Base32, 32 chars via `crypto.getRandomValues`).
3. Frontend: derive `H` → `H_auth, H_kek` via Argon2id + HKDF.
4. Frontend: `POST /api/auth/setup` with `{..., h_auth, h_kek, recovery_key}`.
5. Server: create user, generate DEK, wrap twice, persist, issue tokens, publish `UserCreatedEvent` + `UserKeyProvisionedEvent {reason: "signup"}`.
6. Frontend already holds the recovery key (it generated it in step 2), so it opens the recovery-key modal as soon as the signup response arrives. `UserKeyProvisionedEvent` is published for audit purposes only; the UI does not wait for it.

### 7.2 Normal login

Exactly as §5.2 steps 1–5.

### 7.3 Post-admin-reset login (recovery path)

1. User logs in with admin-provided password → `POST /api/auth/login` → `{status: "recovery_required"}`.
2. Frontend shows recovery-key entry screen with two actions: "Enter my recovery key" and "I do not have it".
3. "Enter" → `POST /api/auth/recover-dek` (§5.3) → tokens issued, DEK in Redis.
4. User is then routed through the normal `must_change_password` flow (§5.4) to replace the admin-provided password with one they choose.
5. "Do not have it" → `POST /api/auth/decline-recovery` → account deactivated.

### 7.4 Password change (user-initiated, while logged in)

As §5.4. Recovery key not involved.

### 7.5 Logout

Delete `session_dek:{session_id}` from Redis (new side-effect added to existing logout handler).

### 7.6 Refresh-token exchange

On successful refresh, extend the TTL of `session_dek:{session_id}` by `access_token_ttl_seconds`. If the key is missing (e.g. user was idle longer than TTL and Redis evicted) the refresh endpoint must **force re-login** rather than issuing a new access token without the DEK reachable.

---

## 8. Legacy-user migration (lazy, at next login)

When the deployment ships, existing users have:
- `users.password_hash` = bcrypt over **raw password** (old format)
- `users.password_hash_version` **absent**
- no `user_keys` document

### Transitional login handling

`POST /api/auth/login` accepts the new shape `{username, h_auth, h_kek}`. But the first time an existing user logs in *after the frontend upgrade*, the frontend has only their password (they enter it as usual); it derives `H`, `H_auth`, `H_kek` using the salt it got from `/kdf-params`.

**Problem:** the legacy `users.password_hash` was computed from the raw password, not from `H_auth`. So `bcrypt_checkpw(h_auth, old_hash)` will fail.

**Solution — transitional `POST /api/auth/login-legacy` endpoint:**

For the migration window, the frontend detects legacy mode by reading `users.password_hash_version` from the `/kdf-params` response (extended with a `password_hash_version: int | null` field). If `null`, the frontend falls back to the legacy flow:

1. `POST /api/auth/login-legacy` with `{username, password_plaintext, h_auth, h_kek}`.
2. Server: `bcrypt_checkpw(password_plaintext, users.password_hash)` — old-style verify.
3. If passes: rotate `users.password_hash = bcrypt(h_auth)`, set `password_hash_version = 1`.
4. Generate DEK, generate recovery key **server-side**, wrap twice, persist `user_keys`.
5. Issue tokens + DEK in Redis.
6. Respond with `{access_token, refresh_token, recovery_key}` — the recovery key is returned **once** in the response body.
7. Publish `UserKeyProvisionedEvent {reason: "migration"}`.
8. Frontend shows the recovery-key modal (same component as signup).

After step 3–4, the user's row looks identical to a freshly signed-up user and will use the normal `/api/auth/login` path on all subsequent logins.

**Removal of the legacy endpoint:** keep `login-legacy` for one release. In a follow-up PR, remove it and fail any remaining legacy user with "please contact admin to reset". Track remaining legacy users via `count_documents({password_hash_version: {$exists: false}})`.

---

## 9. Event Contracts

New topic constants in `shared/topics.py`:

```python
USER_KEY_PROVISIONED = "user.key.provisioned"
USER_KEY_RECOVERY_REQUIRED = "user.key.recovery_required"
USER_KEY_RECOVERED = "user.key.recovered"
```

New DTOs in `shared/events/auth.py` (or new `shared/events/user_keys.py`):

```python
class UserKeyProvisionedEvent(BaseModel):
    user_id: str
    reason: Literal["signup", "migration"]
    # Recovery key is never in this event. Signup: the client already has it (it generated it).
    # Migration: the server returns it once in the /login-legacy HTTP response body (§8).

class UserKeyRecoveryRequiredEvent(BaseModel):
    user_id: str
    triggered_by_admin_id: str | None

class UserKeyRecoveredEvent(BaseModel):
    user_id: str

class UserKeyRecoveryDeclinedEvent(BaseModel):
    user_id: str
```

These events are primarily for audit logging. The frontend modal is driven by the HTTP response (signup and migration return `recovery_key` in the body; recovery-required is the HTTP status body), not by a WS event — because the user has no session yet at the moment the decision is made.

---

## 10. Module Boundaries

- New internal file: `backend/modules/user/_key_service.py` — `UserKeyService` (public export from `backend.modules.user.__init__`). Responsibilities: DEK generation, wrap/unwrap, `user_keys` CRUD, Redis session-DEK lifecycle.
- New internal file: `backend/modules/user/_recovery_key.py` — Crockford-Base32 encode/decode + checksum.
- New internal file: `backend/modules/user/_kdf.py` — server-side HKDF wrap-key derivation, pseudo-salt HMAC, Argon2-param constants.
- Updated: `backend/modules/user/_models.py`, `_handlers.py`, `_repository.py`, `_auth.py`.
- Updated: `backend/config.py` — new env var `kdf_pepper` (required, 32 bytes urlsafe-base64).
- Updated: `backend/main.py` — no startup migration needed (lazy per user), but the new `kdf_pepper` must be validated on boot.

No other module imports `UserKeyService` directly for this PR (nothing encrypts yet). The service is exported ready for later consumers (e.g. `ChatService`) to call `UserKeyService.get_session_dek(session_id)` when encrypting.

---

## 11. Frontend Changes

- New worker: `frontend/src/core/crypto/argon2.worker.ts` wrapping `argon2-browser` (WASM).
- New module: `frontend/src/core/crypto/keyDerivation.ts` — orchestrates `kdf-params` call, Argon2id in worker, HKDF via SubtleCrypto.
- New module: `frontend/src/core/crypto/recoveryKey.ts` — Crockford-Base32 encode/decode.
- Updated: `frontend/src/core/api/auth.ts` — new request shapes for login, signup, change-password.
- New component: `frontend/src/features/auth/RecoveryKeyModal.tsx` — non-dismissable modal, "Copy", "Download as .txt", "I have saved this" confirmation checkbox gating the "Continue" button.
- New component: `frontend/src/features/auth/RecoveryKeyPrompt.tsx` — entry field + "I do not have it" link.
- Updated: login page state machine to handle `{status: "recovery_required"}`, `recovery_key` in response, legacy-mode branch.

---

## 12. Security Considerations

- **Timing attacks on `/kdf-params`:** response time must be independent of user existence. Since the pseudo-salt is pure HMAC and the real salt is a field read, both paths are O(1) and indistinguishable. Add a constant-ish sleep floor only if profiling shows a measurable gap.
- **Recovery-key entropy:** 160 bit from `crypto.getRandomValues` meets OWASP recovery-code guidance (≥128 bit).
- **Rate limiting:** `/recover-dek` is the highest-value target and needs stricter limits than login (5 / 15 min / username is proposed; login keeps its existing 10 / 15 min / IP).
- **Storage of `kdf_pepper`:** new env var, documented in `.env.example`, separate from `encryption_key`. Losing `kdf_pepper` does **not** compromise users — it only makes the ghost-user defence weaker (enumeration becomes possible because the pseudo-salts would differ). Real user salts are stored in Mongo and are not affected.
- **bcrypt on a high-entropy input:** bcrypt-72-byte-truncation does apply (bcrypt silently truncates after 72 bytes). `H_auth` is 32 bytes, well under the limit.
- **Web Worker Argon2id timing:** expected 200–500 ms on desktop Chrome for these params. Acceptable for a login. Mobile may push 800 ms; if real-user-monitoring shows it being painful, tune `memory_kib` down to 32 MiB.
- **No recovery-key escrow:** server never persists the recovery key or a derivative from which it could be recovered. The only materials stored are `wrapped_by_recovery` (which requires the recovery key to open) and the 16-byte SHA-256 prefix confirmation from signup.

---

## 13. Out of Scope (explicit)

The following are explicitly **not** delivered by this work:

- Encryption of any existing or future data field. No chat messages, memory entries, journal entries, uploads, avatars, or anything else is encrypted by this PR.
- The `dek_version` field on user-owned documents. Convention is defined; no collection starts writing it here.
- `UserKeyService.encrypt_for_user(...)` / `decrypt_for_user(...)` helper APIs. They will be introduced when the first collection gets encrypted.
- Admin-side "Destroy and reactivate account" flow. Will be specified separately once any collection holds encrypted data.
- DEK rotation tooling. The schema supports it; the tooling does not exist yet.
- Export / "download my data" flow. Separate feature.

---

## 14. Manual Verification Steps

**On staging with a clean DB:**

1. **Fresh install signup**
   - Hit the first-run setup page, create master admin.
   - Observe: recovery-key modal appears, shows 32-character Crockford-Base32 grouped 4-4-4-... .
   - Copy the key. Check the "I have saved this" checkbox. "Continue" becomes enabled. Click.
   - Verify `db.user_keys.findOne({})` has `current_dek_version: 1`, `deks["1"]` exists with both wraps, `dek_recovery_required: false`.
   - Verify `redis-cli GET session_dek:<session_id>` returns a 32-byte value.

2. **Normal login**
   - Log out, log back in with the same password.
   - Verify no recovery modal shows.
   - Verify Redis key is reset with fresh TTL.

3. **Pre-login endpoint — enumeration defence**
   - `curl -X POST /api/auth/kdf-params -d '{"username":"chris"}'` → note salt.
   - `curl -X POST /api/auth/kdf-params -d '{"username":"does-not-exist"}'` → must return 200, a salt, and identical parameter object.
   - Re-run the second call — pseudo-salt must be byte-identical.
   - Time both calls (several samples, `hyperfine` or similar): should be within the same order of magnitude, no obvious step.

4. **Password change (normal)**
   - While logged in, change the password.
   - Note `user_keys.deks["1"].wrapped_by_password` value (shell or hex-dump). After change, this value must differ.
   - `wrapped_by_recovery` must be byte-identical to before.
   - Log out, log back in with new password. Success.
   - Log out, attempt login with old password. Failure (`401 invalid_credentials`).

5. **Admin reset + recovery**
   - As master admin, create a second user with known password.
   - Log in as that user, trigger the recovery-key modal, save the key.
   - Log out. Back to admin, click "Reset password" on that user.
   - Observe: warning dialog shows the data-destruction notice.
   - Confirm reset. Admin sees the new random password.
   - Log out admin. Log in as user with the new random password.
   - Observe: recovery prompt appears (not normal dashboard).
   - Enter the saved recovery key. Observe: successful unlock, routed to "must change password" screen.
   - Change password. Log out. Log back in with new password — normal login path.
   - `db.user_keys.findOne({user_id: <second>})`: `dek_recovery_required: false`, both wraps updated.

6. **Admin reset — user declines recovery**
   - Repeat (5) but click "I do not have my recovery key".
   - Confirm the destructive warning.
   - Observe: user is logged out and shown "account disabled". Further login attempts → `403 account_disabled`.
   - `db.users.findOne({...})` → `is_active: false`, `user_keys.dek_recovery_required: true` still set.

7. **Legacy user migration**
   - Seed DB with a user in pre-migration shape: `password_hash = bcrypt(raw_password)`, no `password_hash_version` field, no `user_keys` document. (Use a Mongo shell script.)
   - Deploy the new frontend + backend.
   - Log in as that user with the raw password.
   - Observe: login-legacy branch is used. On success, recovery-key modal appears with `reason: "migration"`.
   - Save the key.
   - `db.users.findOne(...)` → now has `password_hash_version: 1`, new `password_hash`.
   - `db.user_keys.findOne({user_id: ...})` exists with both wraps.
   - Log out, log back in — uses normal login path.

8. **Logout clears Redis**
   - Log in. `redis-cli GET session_dek:<sid>` present.
   - Click logout. `redis-cli GET session_dek:<sid>` → nil.

9. **Refresh extends TTL**
   - Log in. Inspect TTL: `redis-cli TTL session_dek:<sid>` ≈ 900 s.
   - Wait 5 min.
   - Trigger a refresh (via UI activity or `/api/auth/refresh` directly).
   - TTL resets to ≈ 900 s.

10. **Web Worker performance sanity**
    - DevTools → Performance → capture a cold login.
    - Argon2id worker run should be 200–500 ms on desktop. UI thread not blocked (no long tasks on main thread during that span).

---

## 15. Files — summary table

| Path | Action |
|---|---|
| `backend/modules/user/_models.py` | Add `UserKeysDocument`, `Argon2Params`, `WrappedDekPair`. Add `password_hash_version` to user model. |
| `backend/modules/user/_repository.py` | Add `user_keys` CRUD methods. |
| `backend/modules/user/_key_service.py` | New. `UserKeyService`: generate, wrap, unwrap, session Redis lifecycle. |
| `backend/modules/user/_recovery_key.py` | New. Crockford-Base32 encode/decode + checksum. |
| `backend/modules/user/_kdf.py` | New. HKDF wrap-key derivation, pseudo-salt HMAC, Argon2 param constants. |
| `backend/modules/user/_handlers.py` | Update signup, login, login-legacy, change-password, recover-dek, decline-recovery, admin-reset. |
| `backend/modules/user/_auth.py` | Adjust password-hash functions for `password_hash_version`. |
| `backend/modules/user/__init__.py` | Export `UserKeyService`. |
| `backend/ws/router.py` | On connect, verify Redis DEK presence (log-only; no behaviour change yet). On disconnect of the last WS for a session: no-op (logout handles DEK cleanup; disconnect != logout). |
| `backend/config.py` | Add `kdf_pepper` env var with validation. |
| `backend/main.py` | Validate `kdf_pepper` on boot. |
| `backend/pyproject.toml` | No new deps — `cryptography`, `hmac`, `hashlib`, `secrets` already present. Verify. |
| `backend/Dockerfile` backing `backend/pyproject.toml` | Same as above — ensure parity. |
| `.env.example` | Document new `kdf_pepper`. |
| `README.md` | Document `kdf_pepper`. |
| `shared/topics.py` | Add three new topics. |
| `shared/events/user_keys.py` | New. Four event DTOs. |
| `shared/dtos/auth.py` | Add new login/signup/change-password/recover-dek request & response DTOs, `KdfParamsDto`, `RecoveryResponseDto`. |
| `frontend/src/core/crypto/argon2.worker.ts` | New. |
| `frontend/src/core/crypto/keyDerivation.ts` | New. |
| `frontend/src/core/crypto/recoveryKey.ts` | New. |
| `frontend/src/core/api/auth.ts` | Update request/response types + functions. |
| `frontend/src/features/auth/RecoveryKeyModal.tsx` | New. |
| `frontend/src/features/auth/RecoveryKeyPrompt.tsx` | New. |
| `frontend/src/pages/LoginPage.tsx` | State-machine update. |
| `frontend/src/pages/SetupPage.tsx` | Integrate recovery-key modal into signup. |
| `frontend/package.json` | Add `argon2-browser`. |

---

## 16. Follow-ups (tracked, not in this PR)

1. Admin-side "Destroy encrypted data + reactivate account" flow. Needed once any collection actually encrypts.
2. `UserKeyService.encrypt_for_user(user_id, plaintext) -> (ciphertext, dek_version)` + `decrypt_for_user(user_id, ciphertext, dek_version) -> plaintext` helper API. Deferred until first-collection rollout.
3. DEK rotation tooling (CLI task + background re-encryption job).
4. Remove `login-legacy` endpoint after all known users have migrated (monitor `password_hash_version: {$exists: false}` count).
5. Recovery-key regeneration flow (user settings → "Generate new recovery key" → rewrap `wrapped_by_recovery` with a fresh key — requires current password).
6. Encryption of chat messages (first proposed pilot collection).
7. Encryption of memory bodies, journal entries, artefact blobs, uploads, avatars — collection by collection.
