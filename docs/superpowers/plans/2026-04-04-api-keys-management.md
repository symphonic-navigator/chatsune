# API-Keys Management Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let users manage their upstream provider API keys with warning indicators when keys are missing or broken.

**Architecture:** Add `test_status` / `last_test_error` to the credential document and DTO (backend), then build a new `ApiKeysTab` in the existing User Modal (frontend). Wire warning logic into AppLayout and Sidebar so missing/broken keys surface prominently.

**Tech Stack:** Python/FastAPI/Pydantic (backend), React/TypeScript/Tailwind (frontend)

---

## File Map

### Backend (modified)

| File | Change |
|------|--------|
| `shared/dtos/llm.py` | Add `test_status`, `last_test_error` to `ProviderCredentialDto` |
| `frontend/src/core/types/llm.ts` | Mirror TS type changes |
| `backend/modules/llm/_models.py` | Add `test_status`, `last_test_error` to `UserCredentialDocument` |
| `backend/modules/llm/_credentials.py` | Update `upsert` to reset test_status, add `update_test_status` method, update `to_dto` |
| `backend/modules/llm/_handlers.py` | Test endpoint updates stored test_status |

### Frontend (new)

| File | Purpose |
|------|---------|
| `frontend/src/app/components/user-modal/ApiKeysTab.tsx` | API-Keys tab component |

### Frontend (modified)

| File | Change |
|------|--------|
| `frontend/src/app/components/user-modal/UserModal.tsx` | Add api-keys tab with warning indicator |
| `frontend/src/app/layouts/AppLayout.tsx` | Auto-open logic, provider fetch, problem state |
| `frontend/src/app/components/sidebar/Sidebar.tsx` | Conditional avatar click target |

---

### Task 1: Add test_status to backend credential model and DTO

**Files:**
- Modify: `shared/dtos/llm.py:7-11`
- Modify: `backend/modules/llm/_models.py:6-16`
- Modify: `backend/modules/llm/_credentials.py:37-84`
- Modify: `frontend/src/core/types/llm.ts:1-7`

- [ ] **Step 1: Add test_status and last_test_error to ProviderCredentialDto**

In `shared/dtos/llm.py`, update the `ProviderCredentialDto` class:

```python
class ProviderCredentialDto(BaseModel):
    provider_id: str
    display_name: str
    is_configured: bool
    requires_key_for_listing: bool = True
    test_status: str | None = None        # "untested" | "valid" | "failed" | None (not configured)
    last_test_error: str | None = None
    created_at: datetime | None = None
```

- [ ] **Step 2: Add test_status and last_test_error to UserCredentialDocument**

In `backend/modules/llm/_models.py`, update the `UserCredentialDocument` class:

```python
class UserCredentialDocument(BaseModel):
    """Internal MongoDB document model for LLM user credentials. Never expose outside llm module."""

    id: str = Field(alias="_id")
    user_id: str
    provider_id: str
    api_key_encrypted: str  # Fernet-encrypted; never returned via API
    test_status: str = "untested"  # "untested" | "valid" | "failed"
    last_test_error: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"populate_by_name": True}
```

- [ ] **Step 3: Update CredentialRepository — reset test_status on upsert, add update_test_status, update to_dto**

In `backend/modules/llm/_credentials.py`:

Update `upsert` to reset `test_status` when a key is saved:

```python
async def upsert(self, user_id: str, provider_id: str, api_key: str) -> dict:
    now = datetime.now(UTC)
    encrypted = encrypt(api_key)
    existing = await self.find(user_id, provider_id)
    if existing:
        await self._collection.update_one(
            {"_id": existing["_id"]},
            {"$set": {
                "api_key_encrypted": encrypted,
                "test_status": "untested",
                "last_test_error": None,
                "updated_at": now,
            }},
        )
        return await self.find(user_id, provider_id)
    doc = {
        "_id": str(uuid4()),
        "user_id": user_id,
        "provider_id": provider_id,
        "api_key_encrypted": encrypted,
        "test_status": "untested",
        "last_test_error": None,
        "created_at": now,
        "updated_at": now,
    }
    await self._collection.insert_one(doc)
    return doc
```

Add a new method:

```python
async def update_test_status(
    self, user_id: str, provider_id: str, test_status: str, last_test_error: str | None = None
) -> dict | None:
    now = datetime.now(UTC)
    result = await self._collection.find_one_and_update(
        {"user_id": user_id, "provider_id": provider_id},
        {"$set": {
            "test_status": test_status,
            "last_test_error": last_test_error,
            "updated_at": now,
        }},
        return_document=True,
    )
    return result
```

Update `to_dto`:

```python
@staticmethod
def to_dto(doc: dict, display_name: str) -> ProviderCredentialDto:
    return ProviderCredentialDto(
        provider_id=doc["provider_id"],
        display_name=display_name,
        is_configured=True,
        test_status=doc.get("test_status", "untested"),
        last_test_error=doc.get("last_test_error"),
        created_at=doc["created_at"],
    )
```

- [ ] **Step 4: Update TypeScript ProviderCredentialDto type**

In `frontend/src/core/types/llm.ts`, update the interface:

```typescript
export interface ProviderCredentialDto {
  provider_id: string
  display_name: string
  is_configured: boolean
  requires_key_for_listing: boolean
  test_status: "untested" | "valid" | "failed" | null
  last_test_error: string | null
  created_at: string | null
}
```

- [ ] **Step 5: Commit**

```bash
git add shared/dtos/llm.py backend/modules/llm/_models.py backend/modules/llm/_credentials.py frontend/src/core/types/llm.ts
git commit -m "Add test_status and last_test_error to credential model and DTO"
```

---

### Task 2: Update test endpoint to persist test_status

**Files:**
- Modify: `backend/modules/llm/_handlers.py:118-148`

- [ ] **Step 1: Update test_provider_key to store test result**

In `backend/modules/llm/_handlers.py`, replace the `test_provider_key` function:

```python
@router.post("/providers/{provider_id}/test", status_code=200)
async def test_provider_key(
    provider_id: str,
    body: SetProviderKeyDto,
    user: dict = Depends(require_active_session),
    event_bus: EventBus = Depends(get_event_bus),
):
    if provider_id not in ADAPTER_REGISTRY:
        raise HTTPException(status_code=404, detail="Unknown provider")

    adapter = ADAPTER_REGISTRY[provider_id](base_url=PROVIDER_BASE_URLS[provider_id])
    error_message = None
    try:
        valid = await adapter.validate_key(body.api_key)
        if not valid:
            error_message = "Key rejected by provider"
    except NotImplementedError:
        raise HTTPException(
            status_code=501,
            detail=f"Provider '{provider_id}' is not yet fully implemented",
        )
    except Exception as exc:
        valid = False
        error_message = str(exc)

    # Persist test result
    repo = _credential_repo()
    test_status = "valid" if valid else "failed"
    await repo.update_test_status(user["sub"], provider_id, test_status, error_message)

    await event_bus.publish(
        Topics.LLM_CREDENTIAL_TESTED,
        LlmCredentialTestedEvent(
            provider_id=provider_id,
            user_id=user["sub"],
            valid=valid,
            timestamp=datetime.now(timezone.utc),
        ),
        target_user_ids=[user["sub"]],
    )

    return {"valid": valid, "error": error_message}
```

- [ ] **Step 2: Update TestKeyResponse TypeScript type**

In `frontend/src/core/types/llm.ts`, update:

```typescript
export interface TestKeyResponse {
  valid: boolean
  error: string | null
}
```

- [ ] **Step 3: Commit**

```bash
git add backend/modules/llm/_handlers.py frontend/src/core/types/llm.ts
git commit -m "Persist test_status when testing provider keys"
```

---

### Task 3: Build ApiKeysTab component

**Files:**
- Create: `frontend/src/app/components/user-modal/ApiKeysTab.tsx`

- [ ] **Step 1: Create ApiKeysTab.tsx**

```tsx
import { useCallback, useEffect, useRef, useState } from 'react'
import { llmApi } from '../../../core/api/llm'
import type { ProviderCredentialDto } from '../../../core/types/llm'

type TestStatus = 'untested' | 'valid' | 'failed' | 'testing'

interface KeyState {
  provider: ProviderCredentialDto
  editing: boolean
  editValue: string
  localTestStatus: TestStatus | null
  localTestError: string | null
  saving: boolean
  confirmDelete: boolean
}

const STATUS_BADGE: Record<string, { label: string; className: string }> = {
  valid:    { label: 'VERIFIED',   className: 'bg-green-400/8 text-green-400 border-green-400/20' },
  failed:   { label: 'FAILED',    className: 'bg-red-400/10 text-red-400 border-red-400/20' },
  untested: { label: 'UNTESTED',  className: 'bg-white/6 text-white/40 border-white/10' },
  testing:  { label: 'TESTING...', className: 'bg-yellow-400/10 text-yellow-400 border-yellow-400/20' },
}

const BTN = 'px-1.5 py-0.5 rounded text-[10px] font-mono uppercase tracking-wider border transition-colors cursor-pointer'
const BTN_NEUTRAL = `${BTN} border-white/8 text-white/40 hover:text-white/60 hover:border-white/15`
const BTN_GOLD = `${BTN} border-gold/30 text-gold hover:bg-gold/10 hover:border-gold/40`
const BTN_RED = `${BTN} border-red-400/30 text-red-400 bg-red-400/10 hover:bg-red-400/15`

export function ApiKeysTab({ onProvidersLoaded }: { onProvidersLoaded?: (providers: ProviderCredentialDto[]) => void }) {
  const [keys, setKeys] = useState<KeyState[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const deleteTimers = useRef<Record<string, ReturnType<typeof setTimeout>>>({})

  const fetchProviders = useCallback(async () => {
    try {
      const providers = await llmApi.listProviders()
      setKeys(providers.map((p) => ({
        provider: p,
        editing: false,
        editValue: '',
        localTestStatus: null,
        localTestError: null,
        saving: false,
        confirmDelete: false,
      })))
      onProvidersLoaded?.(providers)
      setError(null)
    } catch {
      setError('Failed to load providers')
    } finally {
      setLoading(false)
    }
  }, [onProvidersLoaded])

  useEffect(() => {
    fetchProviders()
    return () => {
      Object.values(deleteTimers.current).forEach(clearTimeout)
    }
  }, [fetchProviders])

  function updateKey(providerId: string, patch: Partial<KeyState>) {
    setKeys((prev) => prev.map((k) =>
      k.provider.provider_id === providerId ? { ...k, ...patch } : k
    ))
  }

  function startEdit(providerId: string) {
    updateKey(providerId, { editing: true, editValue: '' })
  }

  function cancelEdit(providerId: string) {
    updateKey(providerId, { editing: false, editValue: '', saving: false })
  }

  async function handleSave(providerId: string, apiKey: string) {
    updateKey(providerId, { saving: true })
    try {
      await llmApi.setKey(providerId, { api_key: apiKey })
      updateKey(providerId, { editing: false, editValue: '', saving: false, localTestStatus: 'testing', localTestError: null })
      // Update is_configured immediately
      setKeys((prev) => prev.map((k) =>
        k.provider.provider_id === providerId
          ? { ...k, provider: { ...k.provider, is_configured: true, test_status: 'untested', last_test_error: null } }
          : k
      ))
      // Auto-test
      try {
        const result = await llmApi.testKey(providerId, { api_key: apiKey })
        const status = result.valid ? 'valid' : 'failed'
        updateKey(providerId, { localTestStatus: status, localTestError: result.error })
        setKeys((prev) => prev.map((k) =>
          k.provider.provider_id === providerId
            ? { ...k, provider: { ...k.provider, test_status: status, last_test_error: result.error } }
            : k
        ))
        // Re-fetch to get authoritative state
        const providers = await llmApi.listProviders()
        setKeys((prev) => prev.map((k) => {
          const fresh = providers.find((p) => p.provider_id === k.provider.provider_id)
          return fresh ? { ...k, provider: fresh, localTestStatus: null, localTestError: null } : k
        }))
        onProvidersLoaded?.(providers)
      } catch {
        updateKey(providerId, { localTestStatus: 'failed', localTestError: 'Test request failed' })
      }
    } catch {
      updateKey(providerId, { saving: false })
      setError('Failed to save key')
    }
  }

  async function handleTest(providerId: string) {
    updateKey(providerId, { localTestStatus: 'testing', localTestError: null })
    try {
      const result = await llmApi.testStoredKey(providerId)
      const status = result.valid ? 'valid' : 'failed'
      updateKey(providerId, { localTestStatus: status, localTestError: result.error })
      setKeys((prev) => prev.map((k) =>
        k.provider.provider_id === providerId
          ? { ...k, provider: { ...k.provider, test_status: status, last_test_error: result.error } }
          : k
      ))
      const providers = await llmApi.listProviders()
      setKeys((prev) => prev.map((k) => {
        const fresh = providers.find((p) => p.provider_id === k.provider.provider_id)
        return fresh ? { ...k, provider: fresh, localTestStatus: null, localTestError: null } : k
      }))
      onProvidersLoaded?.(providers)
    } catch {
      updateKey(providerId, { localTestStatus: 'failed', localTestError: 'Test request failed' })
    }
  }

  async function handleDelete(providerId: string) {
    try {
      await llmApi.removeKey(providerId)
      setKeys((prev) => prev.map((k) =>
        k.provider.provider_id === providerId
          ? {
              ...k,
              provider: { ...k.provider, is_configured: false, test_status: null, last_test_error: null, created_at: null },
              confirmDelete: false,
              editing: false,
              localTestStatus: null,
              localTestError: null,
            }
          : k
      ))
      const providers = await llmApi.listProviders()
      onProvidersLoaded?.(providers)
    } catch {
      setError('Failed to delete key')
    }
  }

  function startDeleteConfirm(providerId: string) {
    // Clear any existing timer for this provider
    if (deleteTimers.current[providerId]) clearTimeout(deleteTimers.current[providerId])
    updateKey(providerId, { confirmDelete: true })
    deleteTimers.current[providerId] = setTimeout(() => {
      updateKey(providerId, { confirmDelete: false })
    }, 3000)
  }

  function getDisplayStatus(k: KeyState): TestStatus | null {
    if (k.localTestStatus) return k.localTestStatus
    if (!k.provider.is_configured) return null
    return (k.provider.test_status as TestStatus) ?? 'untested'
  }

  function getDisplayError(k: KeyState): string | null {
    if (k.localTestError !== null) return k.localTestError
    return k.provider.last_test_error
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center py-20">
        <div className="h-4 w-4 animate-spin rounded-full border-2 border-gold/30 border-t-gold" />
      </div>
    )
  }

  if (error && keys.length === 0) {
    return (
      <div className="flex flex-col items-center gap-3 py-20">
        <p className="text-[12px] text-red-400">{error}</p>
        <button type="button" onClick={fetchProviders} className={BTN_GOLD}>Retry</button>
      </div>
    )
  }

  return (
    <div className="flex-1 overflow-y-auto">
      {/* Error banner */}
      {error && (
        <div className="mx-4 mt-3 rounded-lg border border-red-400/20 bg-red-400/5 px-4 py-2 text-[11px] text-red-400">
          {error}
        </div>
      )}

      {/* Table */}
      <div className="px-4 pt-3">
        {/* Header */}
        <div className="grid grid-cols-[1fr_1fr_6rem_6rem] gap-2 border-b border-white/6 px-3 py-2">
          <span className="text-[10px] uppercase tracking-wider text-white/30 font-mono">Provider</span>
          <span className="text-[10px] uppercase tracking-wider text-white/30 font-mono">Key</span>
          <span className="text-[10px] uppercase tracking-wider text-white/30 font-mono">Status</span>
          <span className="text-[10px] uppercase tracking-wider text-white/30 font-mono text-right">Ops</span>
        </div>

        {/* Rows */}
        {keys.map((k) => {
          const status = getDisplayStatus(k)
          const errorMsg = getDisplayError(k)
          const isFailed = status === 'failed'

          return (
            <div key={k.provider.provider_id}>
              {/* Main row */}
              <div
                className={[
                  'grid grid-cols-[1fr_1fr_6rem_6rem] gap-2 items-center px-3 py-2.5 border-b border-white/6 transition-colors group',
                  isFailed ? 'bg-red-400/[0.03]' : 'hover:bg-white/4',
                ].join(' ')}
              >
                {/* Provider name */}
                <span className={`text-[12px] font-mono ${k.provider.is_configured ? 'text-white/80' : 'text-white/40'}`}>
                  {k.provider.display_name}
                </span>

                {/* Key display */}
                <span className={`text-[12px] font-mono ${k.provider.is_configured ? 'text-white/25 tracking-[2px]' : 'text-white/15 italic'}`}>
                  {k.provider.is_configured ? '••••••••••••' : 'not configured'}
                </span>

                {/* Status badge */}
                <div>
                  {status && STATUS_BADGE[status] ? (
                    <span className={`inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[9px] uppercase tracking-wider border font-mono ${STATUS_BADGE[status].className}`}>
                      {status === 'testing' && (
                        <span className="inline-block h-2 w-2 animate-spin rounded-full border border-yellow-400/30 border-t-yellow-400" />
                      )}
                      {STATUS_BADGE[status].label}
                    </span>
                  ) : (
                    <span className="text-[11px] text-white/15">—</span>
                  )}
                </div>

                {/* Ops */}
                <div className="flex gap-1 justify-end">
                  {k.provider.is_configured ? (
                    <>
                      <button type="button" onClick={() => startEdit(k.provider.provider_id)} className={BTN_NEUTRAL}>
                        EDIT
                      </button>
                      <button
                        type="button"
                        onClick={() => handleTest(k.provider.provider_id)}
                        disabled={status === 'testing'}
                        className={`${BTN_NEUTRAL} ${status === 'testing' ? 'opacity-30 cursor-not-allowed' : ''}`}
                      >
                        TEST
                      </button>
                      {k.confirmDelete ? (
                        <button type="button" onClick={() => handleDelete(k.provider.provider_id)} className={BTN_RED}>
                          SURE?
                        </button>
                      ) : (
                        <button type="button" onClick={() => startDeleteConfirm(k.provider.provider_id)} className={BTN_NEUTRAL}>
                          DEL
                        </button>
                      )}
                    </>
                  ) : (
                    <button type="button" onClick={() => startEdit(k.provider.provider_id)} className={BTN_GOLD}>
                      SET
                    </button>
                  )}
                </div>
              </div>

              {/* Edit expansion */}
              {k.editing && (
                <EditRow
                  editValue={k.editValue}
                  saving={k.saving}
                  errorMessage={isFailed ? errorMsg : null}
                  onChangeValue={(v) => updateKey(k.provider.provider_id, { editValue: v })}
                  onSave={() => handleSave(k.provider.provider_id, k.editValue)}
                  onCancel={() => cancelEdit(k.provider.provider_id)}
                />
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}

function EditRow({
  editValue,
  saving,
  errorMessage,
  onChangeValue,
  onSave,
  onCancel,
}: {
  editValue: string
  saving: boolean
  errorMessage: string | null
  onChangeValue: (v: string) => void
  onSave: () => void
  onCancel: () => void
}) {
  const inputRef = useRef<HTMLInputElement>(null)
  const [visible, setVisible] = useState(false)

  useEffect(() => {
    inputRef.current?.focus()
  }, [])

  function onKeyDown(e: React.KeyboardEvent) {
    if (e.key === 'Enter' && editValue.trim()) onSave()
    if (e.key === 'Escape') onCancel()
  }

  return (
    <div className="px-3 py-3 bg-white/[0.02] border-b border-white/6">
      {errorMessage && (
        <p className="text-[10px] text-red-400 mb-2 font-mono">{errorMessage}</p>
      )}
      <div className="flex gap-2 items-center">
        <div className="relative flex-1">
          <input
            ref={inputRef}
            type={visible ? 'text' : 'password'}
            value={editValue}
            onChange={(e) => onChangeValue(e.target.value)}
            onKeyDown={onKeyDown}
            placeholder="Paste your API key..."
            className="w-full rounded-lg border border-white/10 bg-white/[0.03] px-3 py-1.5 pr-8 text-[12px] font-mono text-white/75 placeholder-white/20 outline-none focus:border-gold/30 transition-colors"
          />
          <button
            type="button"
            onClick={() => setVisible(!visible)}
            className="absolute right-2 top-1/2 -translate-y-1/2 text-[11px] text-white/25 hover:text-white/50 transition-colors"
            tabIndex={-1}
          >
            {visible ? '◉' : '○'}
          </button>
        </div>
        <button
          type="button"
          onClick={onSave}
          disabled={!editValue.trim() || saving}
          className={`${BTN_GOLD} ${(!editValue.trim() || saving) ? 'opacity-30 cursor-not-allowed' : ''}`}
        >
          {saving ? 'SAVING...' : 'SAVE'}
        </button>
        <button type="button" onClick={onCancel} className={BTN_NEUTRAL}>
          CANCEL
        </button>
      </div>
      <p className="mt-1.5 text-[9px] text-white/25 font-mono">Saving will automatically run a connectivity test</p>
    </div>
  )
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/app/components/user-modal/ApiKeysTab.tsx
git commit -m "Add ApiKeysTab component for user API key management"
```

---

### Task 4: Add backend endpoint for testing stored keys

The current `POST /providers/{provider_id}/test` requires the API key in the request body. For the "re-test" button (testing an already-stored key), we need an endpoint that decrypts and tests the stored key.

**Files:**
- Modify: `backend/modules/llm/_handlers.py`
- Modify: `frontend/src/core/api/llm.ts`

- [ ] **Step 1: Add test-stored endpoint to backend**

In `backend/modules/llm/_handlers.py`, add after the existing `test_provider_key` function (after line 148):

```python
@router.post("/providers/{provider_id}/test-stored", status_code=200)
async def test_stored_provider_key(
    provider_id: str,
    user: dict = Depends(require_active_session),
    event_bus: EventBus = Depends(get_event_bus),
):
    """Test the stored (encrypted) API key for this provider without requiring the key in the request."""
    if provider_id not in ADAPTER_REGISTRY:
        raise HTTPException(status_code=404, detail="Unknown provider")

    repo = _credential_repo()
    doc = await repo.find(user["sub"], provider_id)
    if not doc:
        raise HTTPException(status_code=404, detail="No key configured for this provider")

    raw_key = repo.get_raw_key(doc)
    adapter = ADAPTER_REGISTRY[provider_id](base_url=PROVIDER_BASE_URLS[provider_id])
    error_message = None
    try:
        valid = await adapter.validate_key(raw_key)
        if not valid:
            error_message = "Key rejected by provider"
    except NotImplementedError:
        raise HTTPException(
            status_code=501,
            detail=f"Provider '{provider_id}' is not yet fully implemented",
        )
    except Exception as exc:
        valid = False
        error_message = str(exc)

    test_status = "valid" if valid else "failed"
    await repo.update_test_status(user["sub"], provider_id, test_status, error_message)

    await event_bus.publish(
        Topics.LLM_CREDENTIAL_TESTED,
        LlmCredentialTestedEvent(
            provider_id=provider_id,
            user_id=user["sub"],
            valid=valid,
            timestamp=datetime.now(timezone.utc),
        ),
        target_user_ids=[user["sub"]],
    )

    return {"valid": valid, "error": error_message}
```

- [ ] **Step 2: Add testStoredKey to frontend API client**

In `frontend/src/core/api/llm.ts`, add to the `llmApi` object:

```typescript
testStoredKey: (providerId: string) =>
  api.post<TestKeyResponse>(`/api/llm/providers/${providerId}/test-stored`),
```

- [ ] **Step 3: Commit**

```bash
git add backend/modules/llm/_handlers.py frontend/src/core/api/llm.ts
git commit -m "Add endpoint for testing stored API keys without re-entering them"
```

---

### Task 5: Wire ApiKeysTab into UserModal with warning indicator

**Files:**
- Modify: `frontend/src/app/components/user-modal/UserModal.tsx`

- [ ] **Step 1: Add api-keys tab to UserModal**

Update the imports at the top of `UserModal.tsx`:

```typescript
import { useEffect, useRef, useState } from 'react'
import { AboutMeTab } from './AboutMeTab'
import { SettingsTab } from './SettingsTab'
import { HistoryTab } from './HistoryTab'
import { ProjectsTab } from './ProjectsTab'
import { KnowledgeTab } from './KnowledgeTab'
import { UploadsTab } from './UploadsTab'
import { ArtefactsTab } from './ArtefactsTab'
import { BookmarksTab } from './BookmarksTab'
import { ModelsTab } from './ModelsTab'
import { ApiKeysTab } from './ApiKeysTab'
```

Update the `UserModalTab` type:

```typescript
export type UserModalTab = 'about-me' | 'projects' | 'history' | 'knowledge' | 'bookmarks' | 'uploads' | 'artefacts' | 'models' | 'settings' | 'api-keys'
```

Update the `TABS` array — add api-keys as the last entry:

```typescript
const TABS: Tab[] = [
  { id: 'about-me', label: 'About me' },
  { id: 'projects', label: 'Projects' },
  { id: 'history', label: 'History' },
  { id: 'knowledge', label: 'Knowledge' },
  { id: 'bookmarks', label: 'Bookmarks' },
  { id: 'uploads', label: 'Uploads' },
  { id: 'artefacts', label: 'Artefacts' },
  { id: 'models', label: 'Models' },
  { id: 'settings', label: 'Settings' },
  { id: 'api-keys', label: 'API-Keys' },
]
```

Add `hasApiKeyProblem` to the props:

```typescript
interface UserModalProps {
  activeTab: UserModalTab
  onClose: () => void
  onTabChange: (tab: UserModalTab) => void
  displayName: string
  hasApiKeyProblem: boolean
}
```

Update the function signature and the tab bar button to show a warning indicator for the api-keys tab:

```typescript
export function UserModal({ activeTab, onClose, onTabChange, displayName, hasApiKeyProblem }: UserModalProps) {
```

Replace the tab bar `{TABS.map(...)}` section with:

```tsx
{TABS.map((tab) => (
  <button
    key={tab.id}
    type="button"
    onClick={() => onTabChange(tab.id)}
    className={[
      'px-3 py-2.5 text-[12px] border-b-2 -mb-px cursor-pointer transition-colors whitespace-nowrap',
      activeTab === tab.id
        ? 'border-gold text-gold'
        : 'border-transparent text-white/55 hover:text-white/75 hover:underline',
    ].join(' ')}
  >
    {tab.label}
    {tab.id === 'api-keys' && hasApiKeyProblem && (
      <span className="ml-1.5 text-[10px] text-red-400" title="API key issue detected">!</span>
    )}
  </button>
))}
```

Add the tab content rendering for api-keys (before the closing `</div>` of the tab content area):

```tsx
{activeTab === 'api-keys' && <ApiKeysTab />}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/app/components/user-modal/UserModal.tsx
git commit -m "Wire ApiKeysTab into UserModal with warning indicator"
```

---

### Task 6: Add problem state detection and auto-open to AppLayout

**Files:**
- Modify: `frontend/src/app/layouts/AppLayout.tsx`

- [ ] **Step 1: Add provider fetching, problem state, and auto-open logic**

Add imports at the top:

```typescript
import { useCallback, useEffect, useMemo, useRef, useState } from "react"
```

And add the `llmApi` import:

```typescript
import { llmApi } from "../../core/api/llm"
import type { ProviderCredentialDto } from "../../core/types/llm"
```

Inside the `AppLayout` function, after the existing state declarations (after `const [adminTab, setAdminTab] = ...`), add:

```typescript
// API key problem state
const [providers, setProviders] = useState<ProviderCredentialDto[]>([])
const autoOpenFired = useRef(false)

const hasApiKeyProblem = useMemo(() => {
  const configured = providers.filter((p) => p.is_configured)
  if (configured.length === 0) return true
  return configured.some((p) => p.test_status === 'failed')
}, [providers])

const fetchProviders = useCallback(async () => {
  try {
    const result = await llmApi.listProviders()
    setProviders(result)
  } catch {
    // Silently fail — providers will show as empty, triggering problem state
  }
}, [])

// Fetch providers on mount
useEffect(() => {
  if (user) fetchProviders()
}, [user, fetchProviders])

// Auto-open API-Keys tab once per session if there's a problem
useEffect(() => {
  if (hasApiKeyProblem && !autoOpenFired.current && user && providers.length > 0) {
    autoOpenFired.current = true
    openModal('api-keys')
  }
}, [hasApiKeyProblem, user, providers])
```

Update the `UserModal` rendering to pass `hasApiKeyProblem` and a callback to refresh providers:

```tsx
{modalTab !== null && (
  <UserModal
    activeTab={modalTab}
    onClose={closeModal}
    onTabChange={setModalTab}
    displayName={displayName}
    hasApiKeyProblem={hasApiKeyProblem}
  />
)}
```

Also pass `hasApiKeyProblem` and `fetchProviders` to the Sidebar so it can decide the avatar click target:

Update the `Sidebar` component call:

```tsx
<Sidebar
  personas={personas}
  sessions={sessions}
  activePersonaId={activePersonaId}
  activeSessionId={activeSessionId}
  onOpenModal={openModal}
  onCloseModal={closeModal}
  activeModalTab={modalTab}
  onOpenAdmin={openAdmin}
  isAdminOpen={adminTab !== null}
  hasApiKeyProblem={hasApiKeyProblem}
/>
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/app/layouts/AppLayout.tsx
git commit -m "Add API key problem state detection and auto-open to AppLayout"
```

---

### Task 7: Update Sidebar for conditional avatar click target

**Files:**
- Modify: `frontend/src/app/components/sidebar/Sidebar.tsx`

- [ ] **Step 1: Add hasApiKeyProblem prop and conditional avatar behaviour**

Update the `SidebarProps` interface:

```typescript
interface SidebarProps {
  personas: PersonaDto[]
  sessions: ChatSessionDto[]
  activePersonaId: string | null
  activeSessionId: string | null
  onOpenModal: (tab: UserModalTab) => void
  onCloseModal: () => void
  activeModalTab: UserModalTab | null
  onOpenAdmin: () => void
  isAdminOpen: boolean
  hasApiKeyProblem: boolean
}
```

Update the destructuring in the function signature to include `hasApiKeyProblem`:

```typescript
export function Sidebar({
  personas,
  sessions,
  activePersonaId,
  activeSessionId,
  onOpenModal,
  onCloseModal,
  activeModalTab,
  onOpenAdmin,
  isAdminOpen,
  hasApiKeyProblem,
}: SidebarProps) {
```

Add a derived value for the avatar click target:

```typescript
const avatarTab: UserModalTab = hasApiKeyProblem ? 'api-keys' : 'about-me'
```

Update the `avatarHighlight` to also include api-keys:

```typescript
const avatarHighlight =
  activeModalTab === 'about-me' || activeModalTab === 'settings' || activeModalTab === 'api-keys'
```

**In the collapsed view**, find the user avatar button (the one with `onClick={() => onOpenModal('about-me')}`):

Replace:
```tsx
onClick={() => onOpenModal('about-me')}
```
with:
```tsx
onClick={() => onOpenModal(avatarTab)}
```

And add a warning dot when there's a problem. Replace the avatar button in the collapsed view:

```tsx
{/* User avatar */}
<button
  type="button"
  onClick={() => onOpenModal(avatarTab)}
  title={displayName}
  className={[
    "relative flex h-8 w-8 items-center justify-center rounded-full text-[11px] font-bold text-white transition-colors",
    avatarHighlight ? "ring-1 ring-gold" : "",
  ].join(" ")}
  style={{ background: "linear-gradient(to bottom right, var(--purple), var(--gold))" }}
>
  {initial}
  {hasApiKeyProblem && (
    <span className="absolute -top-0.5 -right-0.5 flex h-3 w-3 items-center justify-center rounded-full bg-red-500 text-[7px] font-bold text-white">!</span>
  )}
</button>
```

**In the expanded view**, find the user row section. Replace the avatar button's `onClick`:

From:
```tsx
onClick={() => onOpenModal('about-me')}
```
To:
```tsx
onClick={() => onOpenModal(avatarTab)}
```

And add the warning dot to the expanded avatar too. Replace the avatar div inside the expanded user row button:

```tsx
<div className="relative flex h-[30px] w-[30px] flex-shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-purple to-gold text-[12px] font-bold text-white">
  {initial}
  {hasApiKeyProblem && (
    <span className="absolute -top-0.5 -right-0.5 flex h-3 w-3 items-center justify-center rounded-full bg-red-500 text-[7px] font-bold text-white">!</span>
  )}
</div>
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/app/components/sidebar/Sidebar.tsx
git commit -m "Conditional avatar click target based on API key problem state"
```

---

### Task 8: Integration — wire onProvidersLoaded callback through

The `ApiKeysTab` component modifies keys (set/delete/test). After these operations, the `AppLayout` needs to re-evaluate `hasApiKeyProblem`. We pass a callback through `UserModal` to `ApiKeysTab`.

**Files:**
- Modify: `frontend/src/app/components/user-modal/UserModal.tsx`
- Modify: `frontend/src/app/layouts/AppLayout.tsx`

- [ ] **Step 1: Add onProvidersChanged callback to UserModal props**

In `UserModal.tsx`, update the props interface:

```typescript
interface UserModalProps {
  activeTab: UserModalTab
  onClose: () => void
  onTabChange: (tab: UserModalTab) => void
  displayName: string
  hasApiKeyProblem: boolean
  onProvidersChanged: (providers: ProviderCredentialDto[]) => void
}
```

Add the import:
```typescript
import type { ProviderCredentialDto } from '../../../core/types/llm'
```

Update function signature:
```typescript
export function UserModal({ activeTab, onClose, onTabChange, displayName, hasApiKeyProblem, onProvidersChanged }: UserModalProps) {
```

Update the api-keys tab rendering:

```tsx
{activeTab === 'api-keys' && <ApiKeysTab onProvidersLoaded={onProvidersChanged} />}
```

- [ ] **Step 2: Pass callback from AppLayout**

In `AppLayout.tsx`, update the `UserModal` rendering:

```tsx
{modalTab !== null && (
  <UserModal
    activeTab={modalTab}
    onClose={closeModal}
    onTabChange={setModalTab}
    displayName={displayName}
    hasApiKeyProblem={hasApiKeyProblem}
    onProvidersChanged={setProviders}
  />
)}
```

- [ ] **Step 3: Fix ApiKeysTab onProvidersLoaded calls**

In `ApiKeysTab.tsx`, the `handleSave` function has a broken `onProvidersLoaded?.(prev => prev)` call (passing a function instead of data). Remove that line and rely on the re-fetch below it which already calls `onProvidersLoaded?.(providers)`.

Find and remove this line from `handleSave`:
```typescript
onProvidersLoaded?.(prev => prev) // trigger re-evaluation
```

- [ ] **Step 4: Commit**

```bash
git add frontend/src/app/components/user-modal/UserModal.tsx frontend/src/app/layouts/AppLayout.tsx frontend/src/app/components/user-modal/ApiKeysTab.tsx
git commit -m "Wire onProvidersChanged callback for live problem state updates"
```

---

### Task 9: Manual verification

- [ ] **Step 1: Start backend and frontend**

```bash
cd /home/chris/workspace/chatsune && docker compose up -d
cd /home/chris/workspace/chatsune/backend && uv run uvicorn backend.main:app --reload --port 8000 &
cd /home/chris/workspace/chatsune/frontend && pnpm dev &
```

- [ ] **Step 2: Verify the following scenarios**

1. **No keys configured:** Login, verify User Modal auto-opens on API-Keys tab. Verify avatar shows red warning dot. Verify sidebar avatar click opens API-Keys tab.
2. **Set a key:** Click SET on a provider, enter a key, click SAVE. Verify auto-test runs and status updates.
3. **Failed key:** Enter an invalid key, save. Verify FAILED badge shows, row has red tint, warning indicator appears on tab.
4. **Re-test:** Click TEST on a configured key. Verify testing state and result update.
5. **Delete key:** Click DEL, then SURE?. Verify key is removed, status resets.
6. **Normal state:** Have at least one VERIFIED key and no FAILED keys. Verify no warning dot, avatar opens About Me, no auto-open on reload.
7. **Mixed state:** One VERIFIED key + one FAILED key. Verify warning shows (at least one failed = problem).

- [ ] **Step 3: Final commit (if any fixes needed)**

```bash
git add -A
git commit -m "Fix issues found during manual verification"
```
