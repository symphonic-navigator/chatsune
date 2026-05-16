# Privacy Badge Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `PRIVACY` capability badge to providers (Tensorix, Chutes) and models, surfaced as an emerald-green pill in ModelBrowser, ModelConfigModal, Premium Providers settings, and the chat topbar.

**Architecture:** Two additive contract changes (`Capability.PRIVACY` on provider, `is_privacy_preserving: bool = False` on `ModelMetaDto`). Tensorix adapter sets the flag for all curated models; Chutes adapter maps from `entry.confidential_compute`. Frontend renders a new `PrivacyBadge` component at four surfaces.

**Tech Stack:** Python 3.12, Pydantic v2, FastAPI (backend) — React 18, TypeScript, Tailwind (frontend).

**Spec:** `devdocs/specs/2026-05-16-privacy-badge-design.md`

**Project conventions (from CLAUDE.md):**

- British English in code/comments. German in user-facing strings is okay where existing UI uses it; this UI uses English.
- No DB wipes — all schema additions must be default-initialised.
- `uv run python -m py_compile <file>` for backend syntax check; `pnpm tsc --noEmit` for frontend.
- Commit style: imperative, free-form.
- Tests only where appropriate. This change is DTO + UI rendering; manual verification + clean builds are the bar.

---

## File Structure

**Backend (changes):**

| File | Change |
|---|---|
| `shared/dtos/providers.py` | Add `PRIVACY = "privacy"` to `Capability` enum (line 11-18 block) |
| `shared/dtos/llm.py` | Add `is_privacy_preserving: bool = False` to `ModelMetaDto` (after line 85, before computed fields at line 87) |
| `backend/modules/providers/_registry.py` | Add `Capability.PRIVACY` to Tensorix (line 51-64) and Chutes (line 66-81) `capabilities=[...]` lists |
| `backend/modules/llm/_adapters/_tensorix_http.py` | Add `is_privacy_preserving=True` to every entry in `_TENSORIX_MODELS` (line 99-177) |
| `backend/modules/llm/_adapters/_chutes_http.py` | In `_entry_to_meta` (line 99-158), map `entry.get("confidential_compute") is True` → `is_privacy_preserving` |

**Frontend (changes):**

| File | Change |
|---|---|
| `frontend/src/core/components/PrivacyBadge.tsx` | NEW: shared emerald pill component |
| `frontend/src/app/components/model-browser/ModelBrowser.tsx` | Render `<PrivacyBadge />` in model row near CapBadge cluster (line 462-466 area) |
| `frontend/src/app/components/model-browser/ModelConfigModal.tsx` | Render `<PrivacyBadge />` in model header (line 88-101 area) |
| `frontend/src/app/components/providers/PremiumAccountCard.tsx` | Render `<PrivacyBadge />` next to provider display name (line 46-51 area) when capabilities include `"privacy"` |
| `frontend/src/app/components/topbar/Topbar.tsx` | Render `<PrivacyBadge />` in `ModelPill` tooltip (line 21-65 area) when active model is privacy-preserving |

**No new tests.** This is DTO field addition + conditional rendering. Manual verification suffices per CLAUDE.md.

---

## Task 1: Add PRIVACY to Capability enum

**Files:**
- Modify: `shared/dtos/providers.py:11-18`

- [ ] **Step 1: Add the new enum value**

Open `shared/dtos/providers.py` and locate the `Capability` enum. Add `PRIVACY = "privacy"` as the last entry.

Final state of the enum (lines 11-19 after the change):

```python
class Capability(str, Enum):
    LLM = "llm"
    TTS = "tts"
    STT = "stt"
    WEBSEARCH = "websearch"
    TTI = "tti"
    ITI = "iti"
    PRIVACY = "privacy"
```

- [ ] **Step 2: Verify Python compiles**

Run: `uv run python -m py_compile shared/dtos/providers.py`
Expected: no output, exit code 0.

- [ ] **Step 3: Commit**

```bash
git add shared/dtos/providers.py
git commit -m "Add PRIVACY to Capability enum"
```

---

## Task 2: Add is_privacy_preserving field to ModelMetaDto

**Files:**
- Modify: `shared/dtos/llm.py` (insert after line 85, before any computed fields / methods around line 87)

- [ ] **Step 1: Add the field**

Open `shared/dtos/llm.py` and locate `ModelMetaDto`. Add a new field directly after `remarks` (the last existing simple field, line 85) and before any computed-field decorators / model methods.

Insertion (one new line):

```python
    is_privacy_preserving: bool = False
```

Default `False` is required: it keeps deserialisation of any previously persisted / cached `ModelMetaDto` documents backwards-compatible per CLAUDE.md's no-wipe data-migration rule.

- [ ] **Step 2: Verify Python compiles**

Run: `uv run python -m py_compile shared/dtos/llm.py`
Expected: no output, exit code 0.

- [ ] **Step 3: Commit**

```bash
git add shared/dtos/llm.py
git commit -m "Add is_privacy_preserving field to ModelMetaDto"
```

---

## Task 3: Mark Tensorix and Chutes providers as PRIVACY-capable

**Files:**
- Modify: `backend/modules/providers/_registry.py:51-81`

- [ ] **Step 1: Update Tensorix capabilities**

Locate the `register(PremiumProviderDefinition(id="tensorix", ...))` call around lines 51-64. In the `capabilities=[...]` list, append `Capability.PRIVACY`.

Final state of that field:

```python
        capabilities=[Capability.LLM, Capability.PRIVACY],
```

- [ ] **Step 2: Update Chutes capabilities**

Locate the `register(PremiumProviderDefinition(id="chutes", ...))` call around lines 66-81. In its `capabilities=[...]` list, append `Capability.PRIVACY`.

Final state:

```python
        capabilities=[Capability.LLM, Capability.PRIVACY],
```

- [ ] **Step 3: Verify Python compiles**

Run: `uv run python -m py_compile backend/modules/providers/_registry.py`
Expected: no output, exit code 0.

- [ ] **Step 4: Commit**

```bash
git add backend/modules/providers/_registry.py
git commit -m "Mark Tensorix and Chutes providers as PRIVACY-capable"
```

---

## Task 4: Set is_privacy_preserving=True on all Tensorix curated models

**Files:**
- Modify: `backend/modules/llm/_adapters/_tensorix_http.py:99-177`

- [ ] **Step 1: Inspect the adapter to find where ModelMetaDto is built**

Open `backend/modules/llm/_adapters/_tensorix_http.py`. Read the `_TENSORIX_MODELS` tuple (line 99 onwards) and find the helper that converts `_TensorixModelEntry` → `ModelMetaDto`. The privacy flag must end up on the emitted `ModelMetaDto`. There are two equivalent ways to do this; pick the one that matches the existing pattern:

- **Option A:** Add an `is_privacy_preserving: bool = True` field on the `_TensorixModelEntry` dataclass and pass it through when constructing `ModelMetaDto`.
- **Option B:** Hard-code `is_privacy_preserving=True` directly where `ModelMetaDto(...)` is instantiated for Tensorix models, since the guarantee applies unconditionally to all Tensorix offerings.

Choose **Option B** unless `_TensorixModelEntry` is already extended elsewhere for similar flags — it's the simpler change and matches the unconditional nature of the Tensorix privacy guarantee.

- [ ] **Step 2: Apply Option B**

In the helper / call site where the adapter creates each `ModelMetaDto` for Tensorix, add `is_privacy_preserving=True` to the constructor kwargs.

Example (the exact location depends on the file — read it first):

```python
return ModelMetaDto(
    ...
    is_privacy_preserving=True,
)
```

If the construction loops over `_TENSORIX_MODELS` once and emits all DTOs in one place, a single insertion suffices.

- [ ] **Step 3: Verify Python compiles**

Run: `uv run python -m py_compile backend/modules/llm/_adapters/_tensorix_http.py`
Expected: no output, exit code 0.

- [ ] **Step 4: Commit**

```bash
git add backend/modules/llm/_adapters/_tensorix_http.py
git commit -m "Flag all Tensorix curated models as privacy-preserving"
```

---

## Task 5: Map confidential_compute → is_privacy_preserving in Chutes adapter

**Files:**
- Modify: `backend/modules/llm/_adapters/_chutes_http.py:99-158` (inside `_entry_to_meta`)

- [ ] **Step 1: Locate the ModelMetaDto construction**

Open `backend/modules/llm/_adapters/_chutes_http.py`. In `_entry_to_meta` (around line 99-158), find the `ModelMetaDto(...)` instantiation (around lines 143-158). Note the existing `entry.get("confidential_compute")` check at line 111 — that same value is the truth we want to propagate.

- [ ] **Step 2: Set the field**

Inside the `ModelMetaDto(...)` constructor, add:

```python
        is_privacy_preserving=bool(entry.get("confidential_compute")),
```

Use `bool(...)` to coerce truthy values (`True`, `1`, etc.) defensively in case the upstream attribute shape varies. Currently the filter at line 111 only lets `True` entries through, so all emitted DTOs will have `True` — but mapping from the source attribute keeps the flag truthful if the filter is ever relaxed.

- [ ] **Step 3: Verify Python compiles**

Run: `uv run python -m py_compile backend/modules/llm/_adapters/_chutes_http.py`
Expected: no output, exit code 0.

- [ ] **Step 4: Commit**

```bash
git add backend/modules/llm/_adapters/_chutes_http.py
git commit -m "Map Chutes confidential_compute to is_privacy_preserving"
```

---

## Task 6: Create PrivacyBadge component

**Files:**
- Create: `frontend/src/core/components/PrivacyBadge.tsx`

- [ ] **Step 1: Write the component**

Create a new file with the following content:

```tsx
import type { CSSProperties } from 'react'

type PrivacyBadgeProps = {
  className?: string
  style?: CSSProperties
  title?: string
}

const DEFAULT_TITLE =
  'Privacy-preserving — runs in confidential compute or with guaranteed zero data retention'

export function PrivacyBadge({ className, style, title }: PrivacyBadgeProps) {
  return (
    <span
      title={title ?? DEFAULT_TITLE}
      style={style}
      className={
        'inline-flex items-center rounded-full ' +
        'bg-emerald-500/15 border border-emerald-400/30 ' +
        'px-2 py-0.5 text-[10px] font-semibold tracking-wider ' +
        'text-emerald-300 uppercase ' +
        (className ?? '')
      }
    >
      Privacy
    </span>
  )
}
```

The component accepts optional `className` and `style` overrides so each surface can fine-tune spacing without forking the component.

- [ ] **Step 2: Verify TypeScript compiles**

Run from `frontend/`:

```bash
pnpm tsc --noEmit
```

Expected: no errors. The new file imports nothing app-specific so it should not introduce regressions.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/core/components/PrivacyBadge.tsx
git commit -m "Add PrivacyBadge shared component"
```

---

## Task 7: Render PrivacyBadge in ModelBrowser rows

**Files:**
- Modify: `frontend/src/app/components/model-browser/ModelBrowser.tsx` (line 462-466 area)

- [ ] **Step 1: Import PrivacyBadge**

At the top of `ModelBrowser.tsx`, add (alongside other imports from `core/components` if any exist; otherwise add a new import line):

```tsx
import { PrivacyBadge } from '../../../core/components/PrivacyBadge'
```

(Adjust the relative path if the file's location differs from expectations — count `../` until you reach `frontend/src/`.)

- [ ] **Step 2: Render the badge near the existing cap-badges**

Locate the existing badge cluster (around line 462-466):

```tsx
<div className="flex items-center gap-1">
  {model.supports_reasoning && <CapBadge label="R" title="Reasoning" />}
  {model.supports_vision && <CapBadge label="V" title="Vision" />}
  {model.supports_tool_calls && <CapBadge label="T" title="Tools" />}
</div>
```

Replace it with:

```tsx
<div className="flex items-center gap-1">
  {model.supports_reasoning && <CapBadge label="R" title="Reasoning" />}
  {model.supports_vision && <CapBadge label="V" title="Vision" />}
  {model.supports_tool_calls && <CapBadge label="T" title="Tools" />}
  {model.is_privacy_preserving && <PrivacyBadge />}
</div>
```

The `flex gap-1` already gives correct spacing between the small letter badges and the wider Privacy pill.

- [ ] **Step 3: Verify TypeScript compiles**

Run from `frontend/`:

```bash
pnpm tsc --noEmit
```

Expected: no errors. If `is_privacy_preserving` is unknown on the model type, the shared DTO type generation has not yet been re-run / the import path is wrong. Investigate before proceeding.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/app/components/model-browser/ModelBrowser.tsx
git commit -m "Show Privacy badge in ModelBrowser rows"
```

---

## Task 8: Render PrivacyBadge in ModelConfigModal header

**Files:**
- Modify: `frontend/src/app/components/model-browser/ModelConfigModal.tsx` (line 88-101 area)

- [ ] **Step 1: Import PrivacyBadge**

At the top of `ModelConfigModal.tsx`, add:

```tsx
import { PrivacyBadge } from '../../../core/components/PrivacyBadge'
```

- [ ] **Step 2: Render the badge in the model header**

Locate the model header block (around lines 88-101). Find the element that shows the model display name. Adjacent to that name (typically wrapped together inside a flex container), add:

```tsx
{model.is_privacy_preserving && <PrivacyBadge className="ml-2" />}
```

If the name's parent is not already a flex container, wrap the name and the badge in one:

```tsx
<div className="flex items-center gap-2">
  <span>{model.display_name}</span>
  {model.is_privacy_preserving && <PrivacyBadge />}
</div>
```

The model prop in this modal is the same `ModelMetaDto` used elsewhere — `is_privacy_preserving` is already present.

- [ ] **Step 3: Verify TypeScript compiles**

Run from `frontend/`:

```bash
pnpm tsc --noEmit
```

Expected: no errors.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/app/components/model-browser/ModelConfigModal.tsx
git commit -m "Show Privacy badge in ModelConfigModal header"
```

---

## Task 9: Render PrivacyBadge in Premium Providers settings

**Files:**
- Modify: `frontend/src/app/components/providers/PremiumAccountCard.tsx` (line 44-51 area)

- [ ] **Step 1: Import PrivacyBadge**

At the top of `PremiumAccountCard.tsx`, add:

```tsx
import { PrivacyBadge } from '../../../core/components/PrivacyBadge'
```

- [ ] **Step 2: Render the badge next to the provider display name**

Locate the provider name block (around lines 46-51):

```tsx
<div className="flex items-start justify-between gap-3">
  <span className="text-[13px] font-semibold text-white/90">
    {definition.display_name}
  </span>
  <span className="text-[11px] font-mono text-white/50">{status}</span>
</div>
```

Wrap the display name and the badge together so the badge sits inline with the name (left side stays one unit, status stays right):

```tsx
<div className="flex items-start justify-between gap-3">
  <div className="flex items-center gap-2">
    <span className="text-[13px] font-semibold text-white/90">
      {definition.display_name}
    </span>
    {definition.capabilities.includes('privacy') && <PrivacyBadge />}
  </div>
  <span className="text-[11px] font-mono text-white/50">{status}</span>
</div>
```

If `definition.capabilities` is typed as an array of a specific string-literal union, the literal `'privacy'` must be included in that union (it should be, given the shared DTO regen from Task 1). If TypeScript complains here, the shared type has not picked up the new enum value — investigate before proceeding.

- [ ] **Step 3: Verify TypeScript compiles**

Run from `frontend/`:

```bash
pnpm tsc --noEmit
```

Expected: no errors.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/app/components/providers/PremiumAccountCard.tsx
git commit -m "Show Privacy badge on Premium Provider cards"
```

---

## Task 10: Render PrivacyBadge in chat Topbar ModelPill

**Files:**
- Modify: `frontend/src/app/components/topbar/Topbar.tsx` (line 21-65 area)

- [ ] **Step 1: Import PrivacyBadge**

At the top of `Topbar.tsx`, add:

```tsx
import { PrivacyBadge } from '../../../core/components/PrivacyBadge'
```

- [ ] **Step 2: Render the badge in the ModelPill tooltip rows**

Locate the `ModelPill` component (around lines 21-65) and the tooltip rows section (around lines 42-61). After the existing rows (Provider, Model ID, Size, Context, etc.) but before the closing `</div>` at line 61, insert:

```tsx
{model?.is_privacy_preserving && (
  <div className="mt-1">
    <PrivacyBadge />
  </div>
)}
```

`mt-1` separates the badge from the rows above. Use whatever `model` reference variable the surrounding tooltip code uses — read the file to determine the exact identifier (could be `model`, `activeModel`, `currentModel`, etc.).

- [ ] **Step 3: Verify TypeScript compiles**

Run from `frontend/`:

```bash
pnpm tsc --noEmit
```

Expected: no errors.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/app/components/topbar/Topbar.tsx
git commit -m "Show Privacy badge in Topbar active-model tooltip"
```

---

## Task 11: Final verification

**Files:** none modified.

- [ ] **Step 1: Run a clean frontend build**

From `frontend/`:

```bash
pnpm run build
```

Expected: build succeeds without errors. If type errors appear, fix them in the relevant task's file before continuing.

- [ ] **Step 2: Backend smoke-compile**

From repo root:

```bash
uv run python -m py_compile shared/dtos/providers.py shared/dtos/llm.py backend/modules/providers/_registry.py backend/modules/llm/_adapters/_tensorix_http.py backend/modules/llm/_adapters/_chutes_http.py
```

Expected: no output, exit code 0.

- [ ] **Step 3: Manual UI verification (smoke test)**

Start the stack (existing dev workflow — `docker compose up` or whatever the project uses). Then:

1. Open ModelBrowser → confirm `PRIVACY` pill appears on every Tensorix and Chutes model row, and nowhere else.
2. Click a Tensorix model → confirm `PRIVACY` pill in ModelConfigModal header.
3. Open Premium Providers settings → confirm `PRIVACY` pill on Tensorix and Chutes cards.
4. Pin a Tensorix or Chutes model to a persona → hover ModelPill in Topbar → confirm `PRIVACY` pill in tooltip.

If any surface fails to render the pill where expected, the most likely cause is either (a) the relevant DTO field hasn't propagated through the frontend's generated types — check that the shared DTOs were touched and any codegen / hot reload ran; or (b) the conditional rendering uses the wrong prop name — read the actual model prop in the surrounding component to confirm.

- [ ] **Step 4: Merge to master (per CLAUDE.md)**

Per project convention ("Please always merge to master after implementation"), confirm the working branch is clean, then merge.

```bash
git status   # expect: clean
# assuming you are on a feature branch — example only; if you are on master, skip
git checkout master
git merge --no-ff <feature-branch>
```

Adjust to the actual workflow (worktree / branch name) in use.

---

## Self-Review Notes

- **Spec coverage:** All 5 backend file changes + 5 frontend file changes from the spec are covered (Tasks 1-10). Manual verification covers the spec's "Testing" section (Task 11).
- **No placeholders:** Every code-touching step shows the exact code to write.
- **Type consistency:** `is_privacy_preserving` (snake_case) is used consistently in backend (Pydantic) and frontend (because the shared DTO is the source of truth). `Capability.PRIVACY` / string literal `'privacy'` is the only capability spelling used.
- **DRY:** A single `PrivacyBadge` component is reused at four surfaces.
- **YAGNI:** No filter chip, no aggregation logic, no provider-level model rollup logic. Strictly what was approved in the spec.
- **CLAUDE.md instruction priority:** Tests are intentionally omitted per project policy. Build verification (`py_compile`, `tsc --noEmit`, `pnpm run build`) substitutes.
