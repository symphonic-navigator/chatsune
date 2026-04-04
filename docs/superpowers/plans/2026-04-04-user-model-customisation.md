# User Model Customisation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let users personalise their model list with custom display names, hidden models, context size limits, and fix existing table bugs.

**Architecture:** Extend the existing `UserModelConfigDto` with two new fields (`custom_display_name`, `custom_context_window`). Backend changes are minimal (DTO + repository + validation). Frontend restructures the `ModelBrowser` table columns, enhances `ModelConfigModal` with new controls, and adds a hidden-models filter.

**Tech Stack:** Python/FastAPI/Pydantic (backend DTOs + handlers), React/TypeScript (frontend components), MongoDB (storage via existing repository pattern)

---

### Task 1: Extend Shared DTOs

**Files:**
- Modify: `shared/dtos/llm.py:65-78`

- [ ] **Step 1: Write the failing test**

Add tests for the two new fields to the existing contract tests.

In `tests/test_shared_user_model_config_contracts.py`, add at the end of the file:

```python
def test_user_model_config_dto_with_new_fields():
    dto = UserModelConfigDto(
        model_unique_id="ollama_cloud:llama3.2",
        custom_display_name="My Llama",
        custom_context_window=128_000,
    )
    assert dto.custom_display_name == "My Llama"
    assert dto.custom_context_window == 128_000


def test_user_model_config_dto_new_fields_default_none():
    dto = UserModelConfigDto(model_unique_id="ollama_cloud:llama3.2")
    assert dto.custom_display_name is None
    assert dto.custom_context_window is None


def test_set_user_model_config_dto_new_fields():
    dto = SetUserModelConfigDto(
        custom_display_name="My Llama",
        custom_context_window=128_000,
    )
    assert dto.custom_display_name == "My Llama"
    assert dto.custom_context_window == 128_000


def test_set_user_model_config_dto_new_fields_default_none():
    dto = SetUserModelConfigDto()
    assert dto.custom_display_name is None
    assert dto.custom_context_window is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_shared_user_model_config_contracts.py -v`
Expected: FAIL — `custom_display_name` and `custom_context_window` are unexpected fields.

- [ ] **Step 3: Add new fields to both DTOs**

In `shared/dtos/llm.py`, modify `UserModelConfigDto` (line 65):

```python
class UserModelConfigDto(BaseModel):
    model_unique_id: str
    is_favourite: bool = False
    is_hidden: bool = False
    custom_display_name: str | None = None
    custom_context_window: int | None = None
    notes: str | None = None
    system_prompt_addition: str | None = None
```

Modify `SetUserModelConfigDto` (line 73):

```python
class SetUserModelConfigDto(BaseModel):
    is_favourite: bool | None = None
    is_hidden: bool | None = None
    custom_display_name: str | None = None
    custom_context_window: int | None = None
    notes: str | None = None
    system_prompt_addition: str | None = None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_shared_user_model_config_contracts.py -v`
Expected: All PASS.

- [ ] **Step 5: Commit**

```bash
git add shared/dtos/llm.py tests/test_shared_user_model_config_contracts.py
git commit -m "Add custom_display_name and custom_context_window to user model config DTOs"
```

---

### Task 2: Extend Backend Repository and Handler

**Files:**
- Modify: `backend/modules/llm/_user_config.py:23-83`
- Modify: `backend/modules/llm/_handlers.py:347-380`
- Modify: `tests/test_user_model_config.py`

- [ ] **Step 1: Write failing integration tests for the new fields**

Add at the end of `tests/test_user_model_config.py`:

```python
async def test_set_custom_display_name(client: AsyncClient):
    token = await _setup_admin(client)
    resp = await client.put(
        "/api/llm/providers/ollama_cloud/models/llama3/user-config",
        json={"custom_display_name": "My Llama"},
        headers=_auth(token),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["custom_display_name"] == "My Llama"
    assert data["custom_context_window"] is None


async def test_set_custom_context_window(client: AsyncClient):
    token = await _setup_admin(client)
    resp = await client.put(
        "/api/llm/providers/ollama_cloud/models/llama3/user-config",
        json={"custom_context_window": 128_000},
        headers=_auth(token),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["custom_context_window"] == 128_000


async def test_custom_display_name_too_long_rejected(client: AsyncClient):
    token = await _setup_admin(client)
    resp = await client.put(
        "/api/llm/providers/ollama_cloud/models/llama3/user-config",
        json={"custom_display_name": "x" * 101},
        headers=_auth(token),
    )
    assert resp.status_code == 422


async def test_custom_context_window_below_minimum_rejected(client: AsyncClient):
    token = await _setup_admin(client)
    resp = await client.put(
        "/api/llm/providers/ollama_cloud/models/llama3/user-config",
        json={"custom_context_window": 32_000},
        headers=_auth(token),
    )
    assert resp.status_code == 422


async def test_partial_update_preserves_new_fields(client: AsyncClient):
    token = await _setup_admin(client)
    await client.put(
        "/api/llm/providers/ollama_cloud/models/llama3/user-config",
        json={"custom_display_name": "My Llama", "custom_context_window": 128_000},
        headers=_auth(token),
    )
    resp = await client.put(
        "/api/llm/providers/ollama_cloud/models/llama3/user-config",
        json={"is_favourite": True},
        headers=_auth(token),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["custom_display_name"] == "My Llama"
    assert data["custom_context_window"] == 128_000
    assert data["is_favourite"] is True


async def test_get_config_returns_new_field_defaults(client: AsyncClient):
    token = await _setup_admin(client)
    resp = await client.get(
        "/api/llm/providers/ollama_cloud/models/llama3/user-config",
        headers=_auth(token),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["custom_display_name"] is None
    assert data["custom_context_window"] is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_user_model_config.py -v -k "custom"`
Expected: FAIL — repository doesn't handle new fields, validation doesn't exist.

- [ ] **Step 3: Add validation to SetUserModelConfigDto**

In `shared/dtos/llm.py`, add a `field_validator` import and validators to `SetUserModelConfigDto`:

```python
from pydantic import BaseModel, computed_field, field_validator
```

```python
class SetUserModelConfigDto(BaseModel):
    is_favourite: bool | None = None
    is_hidden: bool | None = None
    custom_display_name: str | None = None
    custom_context_window: int | None = None
    notes: str | None = None
    system_prompt_addition: str | None = None

    @field_validator("custom_display_name")
    @classmethod
    def validate_display_name(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip()
        if len(v) == 0:
            return None
        if len(v) > 100:
            raise ValueError("custom_display_name must be 100 characters or fewer")
        return v

    @field_validator("custom_context_window")
    @classmethod
    def validate_context_window(cls, v: int | None) -> int | None:
        if v is None:
            return None
        if v < 96_000:
            raise ValueError("custom_context_window must be at least 96000")
        return v
```

- [ ] **Step 4: Extend the repository upsert and to_dto**

In `backend/modules/llm/_user_config.py`, update the `upsert` method signature (line 23) to accept the new fields:

```python
    async def upsert(
        self,
        user_id: str,
        model_unique_id: str,
        is_favourite: bool | None = None,
        is_hidden: bool | None = None,
        custom_display_name: str | None = None,
        custom_context_window: int | None = None,
        notes: str | None = None,
        system_prompt_addition: str | None = None,
    ) -> dict:
        now = datetime.now(UTC)
        existing = await self.find(user_id, model_unique_id)

        if existing:
            update_fields: dict = {"updated_at": now}
            if is_favourite is not None:
                update_fields["is_favourite"] = is_favourite
            if is_hidden is not None:
                update_fields["is_hidden"] = is_hidden
            if custom_display_name is not None:
                update_fields["custom_display_name"] = custom_display_name
            if custom_context_window is not None:
                update_fields["custom_context_window"] = custom_context_window
            if notes is not None:
                update_fields["notes"] = notes
            if system_prompt_addition is not None:
                update_fields["system_prompt_addition"] = system_prompt_addition
            await self._collection.update_one(
                {"_id": existing["_id"]},
                {"$set": update_fields},
            )
            return await self.find(user_id, model_unique_id)

        doc = {
            "_id": str(uuid4()),
            "user_id": user_id,
            "model_unique_id": model_unique_id,
            "is_favourite": is_favourite if is_favourite is not None else False,
            "is_hidden": is_hidden if is_hidden is not None else False,
            "custom_display_name": custom_display_name,
            "custom_context_window": custom_context_window,
            "notes": notes,
            "system_prompt_addition": system_prompt_addition,
            "created_at": now,
            "updated_at": now,
        }
        await self._collection.insert_one(doc)
        return doc
```

Update `to_dto` (line 76) to include the new fields:

```python
    @staticmethod
    def to_dto(doc: dict) -> UserModelConfigDto:
        return UserModelConfigDto(
            model_unique_id=doc["model_unique_id"],
            is_favourite=doc.get("is_favourite", False),
            is_hidden=doc.get("is_hidden", False),
            custom_display_name=doc.get("custom_display_name"),
            custom_context_window=doc.get("custom_context_window"),
            notes=doc.get("notes"),
            system_prompt_addition=doc.get("system_prompt_addition"),
        )
```

- [ ] **Step 5: Pass new fields through the handler**

In `backend/modules/llm/_handlers.py`, update the `set_user_model_config` handler (line 360) to pass the new fields:

```python
    doc = await repo.upsert(
        user_id=user["sub"],
        model_unique_id=model_unique_id,
        is_favourite=body.is_favourite,
        is_hidden=body.is_hidden,
        custom_display_name=body.custom_display_name,
        custom_context_window=body.custom_context_window,
        notes=body.notes,
        system_prompt_addition=body.system_prompt_addition,
    )
```

- [ ] **Step 6: Run all user model config tests**

Run: `uv run pytest tests/test_user_model_config.py tests/test_shared_user_model_config_contracts.py -v`
Expected: All PASS.

- [ ] **Step 7: Commit**

```bash
git add shared/dtos/llm.py backend/modules/llm/_user_config.py backend/modules/llm/_handlers.py tests/test_user_model_config.py tests/test_shared_user_model_config_contracts.py
git commit -m "Wire custom_display_name and custom_context_window through backend"
```

---

### Task 3: Update Frontend Type Definitions

**Files:**
- Modify: `frontend/src/core/types/llm.ts:56-69`

- [ ] **Step 1: Add new fields to TypeScript interfaces**

In `frontend/src/core/types/llm.ts`, update `UserModelConfigDto` (line 56):

```typescript
export interface UserModelConfigDto {
  model_unique_id: string
  is_favourite: boolean
  is_hidden: boolean
  custom_display_name: string | null
  custom_context_window: number | null
  notes: string | null
  system_prompt_addition: string | null
}
```

Update `SetUserModelConfigRequest` (line 64):

```typescript
export interface SetUserModelConfigRequest {
  is_favourite?: boolean
  is_hidden?: boolean
  custom_display_name?: string | null
  custom_context_window?: number | null
  notes?: string | null
  system_prompt_addition?: string | null
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/core/types/llm.ts
git commit -m "Add custom_display_name and custom_context_window to frontend types"
```

---

### Task 4: Fix Table Column Order and Rating Display

**Files:**
- Modify: `frontend/src/app/components/model-browser/ModelBrowser.tsx`

- [ ] **Step 1: Fix SORT_FIELDS order to match data render order**

In `ModelBrowser.tsx`, replace the SORT_FIELDS array (line 20-26) with:

```typescript
const SORT_FIELDS: { field: SortField; label: string }[] = [
  { field: "name", label: "Name" },
  { field: "provider", label: "Provider" },
  { field: "params", label: "Params" },
  { field: "context", label: "Context" },
]
```

Note: Rating and Caps are not sortable fields — they were causing the mismatch. Rating sort still exists in `modelFilters.ts` if needed later, but is removed from the header for now since it wasn't correctly aligned.

- [ ] **Step 2: Fix ratingBadge to show "Available" for uncurated models**

Replace the `ratingBadge` function (line 28-39) with:

```typescript
function ratingBadge(model: EnrichedModelDto) {
  const rating = model.curation?.overall_rating ?? "available"
  switch (rating) {
    case "recommended":
      return <span className="text-[10px] text-[#a6e3a1]">Recommended</span>
    case "available":
      return <span className="text-[10px] text-[#89b4fa]">Available</span>
    case "not_recommended":
      return <span className="text-[10px] text-[#f38ba8]">Not Recommended</span>
  }
}
```

- [ ] **Step 3: Remove CFG column and "..." menu, restructure grid**

Replace the column headers `div` (line 255-270) with:

```tsx
      {/* Column headers */}
      <div className="grid grid-cols-[2rem_1fr_5.5rem_5rem_4rem_3.5rem_6.5rem] items-center gap-1 border-b border-white/6 px-4 py-1.5 text-[10px] font-medium uppercase tracking-wider text-white/30">
        <span title="Favourite">Fav</span>
        {SORT_FIELDS.map((sf) => (
          <button
            key={sf.field}
            type="button"
            onClick={() => handleSort(sf.field)}
            className="cursor-pointer text-left hover:text-white/50 transition-colors"
          >
            {sf.label}{sortIndicator(sf.field)}
          </button>
        ))}
        <span>Caps</span>
        <span>Rating</span>
      </div>
```

- [ ] **Step 4: Restructure model rows to match new grid**

Replace the model row rendering (the `return` inside `sorted.map`, lines 302-389) with:

```tsx
          return (
            <div
              key={model.unique_id}
              onClick={() => onEditConfig?.(model)}
              className={[
                "grid grid-cols-[2rem_1fr_5.5rem_5rem_4rem_3.5rem_6.5rem] items-center gap-1 border-b border-white/6 px-4 py-2 text-[12px] transition-colors",
                "cursor-pointer",
                isSelected
                  ? "bg-gold/8 border-l-2 border-l-gold"
                  : "hover:bg-white/4",
                model.user_config?.is_hidden ? "opacity-45" : "",
              ].join(" ")}
            >
              {/* Favourite star */}
              <button
                type="button"
                onClick={(e) => {
                  e.stopPropagation()
                  onToggleFavourite?.(model)
                }}
                className={[
                  "text-[13px] transition-colors cursor-pointer",
                  isFav ? "text-gold" : "text-white/15 hover:text-white/30",
                ].join(" ")}
                title={isFav ? "Remove from favourites" : "Add to favourites"}
              >
                {isFav ? "\u2605" : "\u2606"}
              </button>

              {/* Name + customisation indicator */}
              <div className="min-w-0 flex items-center gap-1.5">
                <span className="truncate text-[12px] text-white/80">
                  {model.user_config?.custom_display_name ?? model.display_name}
                </span>
                {hasConfig && (
                  <span className="text-[10px] text-[#cba6f7] flex-shrink-0" title="Customised">&#9670;</span>
                )}
                {model.user_config?.custom_display_name && (
                  <span className="truncate text-[9px] text-white/25 italic flex-shrink-0">
                    {model.display_name}
                  </span>
                )}
                {model.user_config?.is_hidden && (
                  <span className="text-[9px] text-white/30 flex-shrink-0">HIDDEN</span>
                )}
              </div>

              {/* Provider */}
              <span className="truncate text-[11px] text-white/40">{model.provider_id}</span>

              {/* Params */}
              <span className="text-[11px] text-white/55">
                {model.parameter_count ? (
                  <>
                    {model.parameter_count}
                    {model.quantisation_level && (
                      <span className="ml-1 text-[9px] text-white/25">{model.quantisation_level}</span>
                    )}
                  </>
                ) : (
                  <span className="text-white/20">--</span>
                )}
              </span>

              {/* Context */}
              <span className="text-[11px] text-white/40">{formatContext(model.context_window)}</span>

              {/* Capabilities */}
              {capabilityIcons(model)}

              {/* Rating */}
              {ratingBadge(model)}
            </div>
          )
```

- [ ] **Step 5: Update hasConfig check to include new fields**

Replace the `hasConfig` variable (lines 295-300) with:

```typescript
          const hasConfig = model.user_config != null && (
            model.user_config.is_favourite ||
            model.user_config.is_hidden ||
            model.user_config.custom_display_name != null ||
            model.user_config.custom_context_window != null ||
            (model.user_config.notes != null && model.user_config.notes.length > 0) ||
            (model.user_config.system_prompt_addition != null && model.user_config.system_prompt_addition.length > 0)
          )
```

- [ ] **Step 6: Remove onSelect prop from interface and usage**

In the `ModelBrowserProps` interface (line 11-18), remove `onSelect` and `currentModelId`:

```typescript
interface ModelBrowserProps {
  onEditConfig?: (model: EnrichedModelDto) => void
  onToggleFavourite?: (model: EnrichedModelDto) => void
  models?: EnrichedModelDto[]
}
```

Remove `currentModelId` and `onSelect` from the destructured props (line 69-75):

```typescript
export function ModelBrowser({
  onEditConfig,
  onToggleFavourite,
  models: externalModels,
}: ModelBrowserProps) {
```

Remove the `isSelected` variable from the row rendering — replace with `false` or remove the conditional:

```typescript
// Remove this line:
// const isSelected = currentModelId === model.unique_id
// And simplify the className — remove the isSelected conditional
```

- [ ] **Step 7: Verify the app compiles**

Run: `cd frontend && pnpm tsc --noEmit`
Expected: No type errors.

- [ ] **Step 8: Commit**

```bash
git add frontend/src/app/components/model-browser/ModelBrowser.tsx
git commit -m "Fix table column order, remove CFG column, add customisation indicator"
```

---

### Task 5: Add Hidden Filter to ModelBrowser

**Files:**
- Modify: `frontend/src/app/components/model-browser/modelFilters.ts`
- Modify: `frontend/src/app/components/model-browser/ModelBrowser.tsx`

- [ ] **Step 1: Add showHidden to ModelFilters and update filterModels**

In `modelFilters.ts`, add `showHidden` to the interface (line 3-12):

```typescript
export interface ModelFilters {
  search?: string
  provider?: string
  capTools?: boolean
  capVision?: boolean
  capReason?: boolean
  curation?: "recommended" | "available" | "not_recommended"
  favouritesOnly?: boolean
  hasCustomisation?: boolean
  showHidden?: boolean
}
```

In the `filterModels` function, add hidden filtering logic right after the opening `return models.filter((m) => {` (line 42), as the FIRST filter check:

```typescript
    // Hidden filter: by default exclude user-hidden models; when active show ONLY hidden
    if (filters.showHidden) {
      if (!m.user_config?.is_hidden) return false
    } else {
      if (m.user_config?.is_hidden) return false
    }
```

Update the `hasCustomisation` check (lines 69-78) to include the new fields:

```typescript
    if (filters.hasCustomisation) {
      const cfg = m.user_config
      if (!cfg) return false
      const hasCustom =
        cfg.is_favourite ||
        cfg.is_hidden ||
        cfg.custom_display_name != null ||
        cfg.custom_context_window != null ||
        (cfg.notes != null && cfg.notes.length > 0) ||
        (cfg.system_prompt_addition != null && cfg.system_prompt_addition.length > 0)
      if (!hasCustom) return false
    }
```

Also update `matchesSearch` (line 28-35) to search custom display names:

```typescript
export function matchesSearch(model: EnrichedModelDto, query: string): boolean {
  const q = query.toLowerCase().trim()
  if (!q) return true
  return (
    model.display_name.toLowerCase().includes(q) ||
    model.model_id.toLowerCase().includes(q) ||
    (model.user_config?.custom_display_name?.toLowerCase().includes(q) ?? false)
  )
}
```

- [ ] **Step 2: Add Hidden filter button to ModelBrowser header**

In `ModelBrowser.tsx`, in the header section (after the "Customised" button, around line 163), add:

```tsx
          <button
            type="button"
            onClick={() => updateFilter("showHidden", !filters.showHidden)}
            className={[
              "rounded-md px-2.5 py-1 text-[11px] font-medium transition-colors cursor-pointer",
              filters.showHidden
                ? "bg-[#f38ba8]/15 border border-[#f38ba8]/30 text-[#f38ba8]"
                : "border border-white/8 text-white/40 hover:text-white/60 hover:border-white/15",
            ].join(" ")}
          >
            Hidden
          </button>
```

- [ ] **Step 3: Verify compilation**

Run: `cd frontend && pnpm tsc --noEmit`
Expected: No type errors.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/app/components/model-browser/modelFilters.ts frontend/src/app/components/model-browser/ModelBrowser.tsx
git commit -m "Add hidden models filter and update customisation checks for new fields"
```

---

### Task 6: Enhance ModelConfigModal with New Controls

**Files:**
- Modify: `frontend/src/app/components/model-browser/ModelConfigModal.tsx`

- [ ] **Step 1: Add context step ladder constant**

At the top of `ModelConfigModal.tsx`, after the existing constants (line 7-8), add:

```typescript
const DISPLAY_NAME_LIMIT = 100
const MIN_CONTEXT_FOR_SLIDER = 96_000

const CONTEXT_STEPS: number[] = [
  96_000, 128_000, 160_000, 192_000, 224_000, 256_000,
  384_000, 512_000,
  768_000, 1_000_000, 1_250_000, 1_500_000, 2_000_000,
]

function availableSteps(maxContext: number): number[] {
  const steps = CONTEXT_STEPS.filter((s) => s <= maxContext)
  // If model max isn't exactly on a step boundary, add it as the final step
  if (steps.length === 0 || steps[steps.length - 1] !== maxContext) {
    steps.push(maxContext)
  }
  return steps
}

function formatContextLabel(ctx: number): string {
  if (ctx >= 1_000_000) {
    const val = ctx / 1_000_000
    return val % 1 === 0 ? `${val}M` : `${val.toFixed(2).replace(/0+$/, "").replace(/\.$/, "")}M`
  }
  return `${Math.round(ctx / 1_000)}k`
}
```

- [ ] **Step 2: Add auto-grow textarea helper**

After the `formatContextLabel` function, add:

```typescript
function autoGrow(el: HTMLTextAreaElement) {
  el.style.height = "auto"
  el.style.height = `${Math.min(el.scrollHeight, 12 * 24)}px` // max ~12 rows
}
```

- [ ] **Step 3: Add new state variables**

In the `ModelConfigModal` component, after the existing `useState` calls (lines 16-21), add:

```typescript
  const [isHidden, setIsHidden] = useState(model.user_config?.is_hidden ?? false)
  const [customDisplayName, setCustomDisplayName] = useState(
    model.user_config?.custom_display_name ?? "",
  )
  const [customContextWindow, setCustomContextWindow] = useState<number | null>(
    model.user_config?.custom_context_window ?? null,
  )
```

Compute the available steps and current slider index:

```typescript
  const contextSliderAvailable = model.context_window >= MIN_CONTEXT_FOR_SLIDER
  const steps = contextSliderAvailable ? availableSteps(model.context_window) : []
  const effectiveContext = customContextWindow ?? model.context_window
  const stepIndex = steps.length > 0
    ? steps.reduce((closest, s, i) =>
        Math.abs(s - effectiveContext) < Math.abs(steps[closest] - effectiveContext) ? i : closest, 0)
    : 0
```

- [ ] **Step 4: Update handleSave to include new fields**

Replace the `data` object in `handleSave` (lines 44-48) with:

```typescript
      const data: SetUserModelConfigRequest = {
        is_favourite: isFavourite,
        is_hidden: isHidden,
        custom_display_name: customDisplayName.trim() || null,
        custom_context_window: contextSliderAvailable && customContextWindow !== null && customContextWindow !== model.context_window
          ? customContextWindow
          : null,
        notes: notes.trim() || null,
        system_prompt_addition: systemPromptAddition.trim() || null,
      }
```

- [ ] **Step 5: Add Hidden toggle after Favourite**

After the favourite `<label>` block (after line 116), add:

```tsx
          {/* Hidden toggle */}
          <div
            className="flex items-center gap-3 cursor-pointer py-2"
            onClick={() => setIsHidden(!isHidden)}
          >
            <div
              className={[
                "relative h-[18px] w-[32px] flex-shrink-0 rounded-full transition-colors",
                isHidden ? "bg-[#f38ba8]" : "bg-white/15",
              ].join(" ")}
            >
              <div
                className={[
                  "absolute top-[2px] h-[14px] w-[14px] rounded-full bg-white transition-all",
                  isHidden ? "left-[16px]" : "left-[2px]",
                ].join(" ")}
              />
            </div>
            <div>
              <div className="text-[12px] text-white/70">Hidden</div>
              <div className="text-[10px] text-white/30">
                Hide this model from your model selection lists
              </div>
            </div>
          </div>
```

- [ ] **Step 6: Add Custom Display Name input**

After the hidden toggle, add:

```tsx
          {/* Custom Display Name */}
          <div>
            <div className="mb-2 flex items-center justify-between">
              <label
                htmlFor="config-display-name"
                className="block text-[11px] font-medium uppercase tracking-wider text-white/40"
              >
                Custom Display Name
              </label>
              <span className={[
                "text-[10px]",
                customDisplayName.length > DISPLAY_NAME_LIMIT * 0.9
                  ? "text-[#f38ba8]"
                  : "text-white/20",
              ].join(" ")}>
                {customDisplayName.length}/{DISPLAY_NAME_LIMIT}
              </span>
            </div>
            <input
              id="config-display-name"
              type="text"
              value={customDisplayName}
              onChange={(e) => {
                if (e.target.value.length <= DISPLAY_NAME_LIMIT) {
                  setCustomDisplayName(e.target.value)
                }
              }}
              placeholder="Leave empty to use default name"
              className="w-full rounded-lg border border-white/8 bg-elevated px-3 py-2 text-[12px] text-white/80 placeholder-white/20 outline-none focus:border-gold/40 transition-colors"
            />
            {model.display_name && (
              <div className="mt-1 text-[10px] text-white/25">
                Original: {model.display_name}
              </div>
            )}
          </div>
```

- [ ] **Step 7: Add Context Size slider**

After the custom display name section, add:

```tsx
          {/* Context Size */}
          {contextSliderAvailable ? (
            <div>
              <div className="mb-2 flex items-center justify-between">
                <label className="block text-[11px] font-medium uppercase tracking-wider text-white/40">
                  Context Size
                </label>
                <span className="text-[12px] font-semibold text-gold">
                  {formatContextLabel(steps[stepIndex])}
                </span>
              </div>
              <input
                type="range"
                min={0}
                max={steps.length - 1}
                value={stepIndex}
                onChange={(e) => {
                  const idx = parseInt(e.target.value, 10)
                  const value = steps[idx]
                  setCustomContextWindow(value === model.context_window ? null : value)
                }}
                className="w-full accent-[#f9e2af]"
              />
              <div className="mt-1 flex justify-between text-[9px] text-white/20">
                <span>{formatContextLabel(steps[0])}</span>
                <span className={effectiveContext === model.context_window ? "text-white/50 font-semibold" : ""}>
                  {formatContextLabel(model.context_window)} (max)
                </span>
              </div>
              <div className="mt-1.5 text-[10px] text-white/25">
                Smaller context = lower cost per message. Default is the model's maximum.
              </div>
            </div>
          ) : (
            <div>
              <div className="mb-1 text-[11px] font-medium uppercase tracking-wider text-white/25">
                Context Size
              </div>
              <div className="text-[10px] text-white/20 italic">
                Context adjustment available for models with 96k+ context window.
                This model has {formatContextLabel(model.context_window)}.
              </div>
            </div>
          )}
```

- [ ] **Step 8: Make textareas auto-growing**

Replace the System Prompt Addition textarea (lines 136-147) with:

```tsx
            <textarea
              id="config-system-prompt"
              value={systemPromptAddition}
              onChange={(e) => {
                if (e.target.value.length <= SYSTEM_PROMPT_LIMIT) {
                  setSystemPromptAddition(e.target.value)
                }
              }}
              onInput={(e) => autoGrow(e.currentTarget)}
              placeholder="Additional instructions appended to the system prompt when this model is used"
              rows={4}
              className="w-full resize-none rounded-lg border border-white/8 bg-elevated px-3 py-2 text-[12px] text-white/80 placeholder-white/20 outline-none focus:border-gold/40 transition-colors overflow-y-auto"
              style={{ maxHeight: `${12 * 24}px` }}
            />
```

Replace the Notes textarea (lines 168-178) with:

```tsx
            <textarea
              id="config-notes"
              value={notes}
              onChange={(e) => {
                if (e.target.value.length <= NOTES_LIMIT) {
                  setNotes(e.target.value)
                }
              }}
              onInput={(e) => autoGrow(e.currentTarget)}
              placeholder="Personal notes about this model (only visible to you)"
              rows={3}
              className="w-full resize-none rounded-lg border border-white/8 bg-elevated px-3 py-2 text-[12px] text-white/80 placeholder-white/20 outline-none focus:border-gold/40 transition-colors overflow-y-auto"
              style={{ maxHeight: `${12 * 24}px` }}
            />
```

- [ ] **Step 9: Verify compilation**

Run: `cd frontend && pnpm tsc --noEmit`
Expected: No type errors.

- [ ] **Step 10: Commit**

```bash
git add frontend/src/app/components/model-browser/ModelConfigModal.tsx
git commit -m "Add hidden toggle, display name, context slider, and auto-grow textareas to config modal"
```

---

### Task 7: Update ModelsTab to Adapt to New ModelBrowser Props

**Files:**
- Modify: `frontend/src/app/components/user-modal/ModelsTab.tsx`

- [ ] **Step 1: Update optimistic favourite toggle to include new fields**

In `ModelsTab.tsx`, update the optimistic config object inside `handleToggleFavourite` (lines 25-31) to include the new fields:

```typescript
              user_config: {
                model_unique_id: m.unique_id,
                is_favourite: newFav,
                is_hidden: m.user_config?.is_hidden ?? false,
                custom_display_name: m.user_config?.custom_display_name ?? null,
                custom_context_window: m.user_config?.custom_context_window ?? null,
                notes: m.user_config?.notes ?? null,
                system_prompt_addition: m.user_config?.system_prompt_addition ?? null,
              },
```

- [ ] **Step 2: Remove currentModelId and onSelect from ModelBrowser usage**

In `ModelsTab.tsx`, the `ModelBrowser` is already used without `currentModelId` and `onSelect` (line 80-84). Verify it only passes `models`, `onToggleFavourite`, and `onEditConfig`. No changes needed here if it already matches.

- [ ] **Step 3: Verify compilation**

Run: `cd frontend && pnpm tsc --noEmit`
Expected: No type errors.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/app/components/user-modal/ModelsTab.tsx
git commit -m "Update ModelsTab optimistic update with new user config fields"
```

---

### Task 8: Run Full Test Suite

**Files:** None (verification only)

- [ ] **Step 1: Run all backend tests**

Run: `uv run pytest tests/ -v`
Expected: All PASS.

- [ ] **Step 2: Run frontend type check**

Run: `cd frontend && pnpm tsc --noEmit`
Expected: No type errors.

- [ ] **Step 3: Run frontend linting (if configured)**

Run: `cd frontend && pnpm lint` (if this script exists)
Expected: No errors.

- [ ] **Step 4: Final commit if any fixes were needed**

If any fixes were required, commit them:
```bash
git add -A
git commit -m "Fix issues found during full test suite run"
```
