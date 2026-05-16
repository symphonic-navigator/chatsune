# Privacy Badge — Design

**Date:** 2026-05-16
**Status:** Approved
**Scope:** Provider + Model capability to mark privacy-preserving LLM offerings, surfaced in UI.

---

## Motivation

Two of our Premium Upstream Providers offer privacy-preserving inference and
should be discoverable as such:

- **Tensorix** — guarantees GDPR + zero data retention as a matter of
  principle. Applies to all curated models.
- **Chutes** — exposes models through confidential compute (TEE); we already
  filter the catalogue to TEE-only entries (`confidential_compute==true`).

Users currently have no way to tell at a glance which providers / models
respect privacy. The aim of this feature is to surface that fact wherever a
provider or a model is shown in the UI.

---

## Hard Decisions (Approved)

1. **Badge style:** wide pill labelled `PRIVACY`, emerald-green tinted —
   visually distinct from existing compact letter badges (R / V / T).
2. **Surfaces:** ModelBrowser, ModelConfigModal, Premium Provider settings,
   Chat header (active model). All four.
3. **Filter chip:** **none.** Badge is informational only.
4. **Data shape:** both provider-level capability **and** model-level
   boolean flag. Provider capability is the catalogue truth; the model flag
   is the per-model truth. Frontend does not aggregate or infer.

---

## Architecture

### Backend — Shared Contracts

**`shared/dtos/providers.py`:** extend `Capability` enum.

```python
class Capability(StrEnum):
    LLM = "llm"
    TTS = "tts"
    STT = "stt"
    WEBSEARCH = "websearch"
    TTI = "tti"
    ITI = "iti"
    PRIVACY = "privacy"   # NEW
```

The enum is additive — no migration required. Existing
`PremiumProviderDefinitionDto` documents stay valid.

**`shared/dtos/llm.py`:** extend `ModelMetaDto`.

```python
class ModelMetaDto(BaseModel):
    ...
    is_privacy_preserving: bool = False   # NEW
```

Default `False` keeps reads backwards-compatible with any persisted /
cached model metadata — required by CLAUDE.md's no-wipe data-migration
rules.

### Backend — Provider Registry

**`backend/modules/providers/_registry.py`:** add `Capability.PRIVACY` to
the Tensorix and Chutes entries.

```python
# Tensorix
capabilities=[Capability.LLM, Capability.PRIVACY],

# Chutes
capabilities=[Capability.LLM, Capability.PRIVACY],
```

### Backend — Adapter Mapping

**Tensorix adapter** (curated static list): set
`is_privacy_preserving=True` on all entries in the `_TENSORIX_MODELS`
tuple. Tensorix's guarantee is unconditional — every curated model
qualifies.

**Chutes adapter** (`backend/modules/llm/_adapters/_chutes_http.py`):
in `_entry_to_meta`, map `entry.confidential_compute` to
`is_privacy_preserving`. The existing filter
(`confidential_compute==true AND context_length >= 80_000`) means every
exposed model will currently have `True`, but the flag is set from the
upstream attribute itself rather than hard-coded — defensive against
future filter relaxations.

### Frontend — Badge Component

New shared component `PrivacyBadge.tsx`:

```tsx
export function PrivacyBadge({ className }: { className?: string }) {
  return (
    <span
      className={
        "inline-flex items-center gap-1 rounded-full " +
        "bg-emerald-500/15 border border-emerald-400/30 " +
        "px-2 py-0.5 text-[10px] font-semibold tracking-wider " +
        "text-emerald-300 uppercase " +
        (className ?? "")
      }
      title="Privacy-preserving — runs in confidential compute or with guaranteed zero data retention"
    >
      Privacy
    </span>
  )
}
```

Location: `frontend/src/app/components/common/PrivacyBadge.tsx` (or
nearest existing shared-components directory; final placement decided
during implementation by inspecting where similar shared atoms live).

### Frontend — Surface Integration

Four insertion points. In each, render `<PrivacyBadge />` conditionally
when the relevant flag is truthy:

| Surface | File (approximate) | Condition |
|---|---|---|
| Model row in ModelBrowser | `frontend/src/app/components/model-browser/ModelBrowser.tsx` | `model.is_privacy_preserving` |
| Model header in ModelConfigModal | `frontend/src/app/components/model-browser/ModelConfigModal.tsx` | `model.is_privacy_preserving` |
| Provider row in Premium Providers settings | Premium Providers settings page | `provider.capabilities.includes("privacy")` |
| Active model display in Chat header | Chat header component | `currentModel.is_privacy_preserving` |

The precise integration point inside each file is left to the
implementation plan — these are well-bounded edits with clear
conditional rendering. No new prop drilling required as the model and
provider DTOs already reach each of these surfaces.

---

## Data Flow

```
Adapter (Tensorix / Chutes)
    ─ sets is_privacy_preserving on ModelMetaDto
    ─ (Chutes maps from entry.confidential_compute)
            │
            ▼
    Models list endpoint (existing)
            │
            ▼
    Frontend ModelMeta state
            │
            ├──► ModelBrowser → <PrivacyBadge /> per row
            ├──► ModelConfigModal → <PrivacyBadge /> in header
            └──► Chat header → <PrivacyBadge /> for active model

PremiumProviderDefinition
    ─ capabilities includes PRIVACY
            │
            ▼
    Premium provider settings DTO (existing)
            │
            ▼
    Premium Providers settings page
            │
            └──► <PrivacyBadge /> per qualifying provider row
```

No new endpoints. No new event topics. Pure DTO extension + UI rendering.

---

## What is NOT in Scope

- **No filter chip** in ModelBrowser. Privacy is surfaced as an
  indicator, not a filter. Users who specifically want privacy-preserving
  models can already filter by provider (Tensorix / Chutes).
- **No YAML override** for `is_privacy_preserving` in
  `backend/modules/llm/data/model_capabilities.yaml`. The source of truth
  is the adapter / provider catalogue. Adding an override layer here
  would invite contradiction with the upstream signal.
- **No badge aggregation logic** in the frontend ("this provider has
  privacy because all its models do"). Provider and model carry their
  own truth.
- **No retroactive flag computation** for cached / persisted model
  metadata in MongoDB. The default-`False` field ensures clean reads;
  fresh model fetches will populate the flag.

---

## Migration / Rollout

- **No DB migration required.** Both changes are additive (new enum
  value, new optional field with default).
- **No frontend breaking changes.** New optional fields, new rendered
  badges only.
- **Verification:** after the change, the next model-list fetch from
  Tensorix returns all 7 models with `is_privacy_preserving=true`; the
  next Chutes fetch returns all currently-filtered models with the
  same. Confirm in UI by visiting ModelBrowser and Premium Providers
  settings.

---

## Testing

This is a low-complexity DTO + rendering change. Manual verification is
sufficient:

1. Build backend and frontend cleanly (`uv run python -m py_compile`
   on changed files; `pnpm tsc --noEmit` on frontend).
2. Spin up the stack, open ModelBrowser, confirm the `PRIVACY` pill
   shows up on Tensorix + Chutes rows and nowhere else.
3. Open a model-config modal for a Tensorix model — pill visible.
4. Open Premium Providers settings — Tensorix and Chutes rows show
   the pill; other providers do not.
5. Pin a Tensorix model in a chat — pill appears in the chat header.

No new automated tests warranted; the change does not introduce
non-trivial logic.

---

## Files Touched (Summary)

**Backend (5):**

- `shared/dtos/providers.py` — `Capability.PRIVACY`
- `shared/dtos/llm.py` — `ModelMetaDto.is_privacy_preserving`
- `backend/modules/providers/_registry.py` — Tensorix & Chutes capabilities
- `backend/modules/llm/_adapters/_tensorix_*.py` — flag on all curated models
- `backend/modules/llm/_adapters/_chutes_http.py` — map from `confidential_compute`

**Frontend (5):**

- `frontend/src/app/components/common/PrivacyBadge.tsx` — new component
- `frontend/src/app/components/model-browser/ModelBrowser.tsx` — badge in row
- `frontend/src/app/components/model-browser/ModelConfigModal.tsx` — badge in header
- Premium Providers settings page — badge per qualifying provider
- Chat header component — badge for active model
