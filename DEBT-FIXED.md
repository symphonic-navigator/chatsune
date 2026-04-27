# Debt Fixed — 2026-04-27 Sweep

Companion to [TECHNICAL-DEBT-260427.md](TECHNICAL-DEBT-260427.md). This file
records what was actually changed on branch `claude/analyze-technical-debt-yDyKh`
during the autonomous-fix pass. Master is untouched beyond the audit doc; the
fixes live on this branch and await your review before merging.

---

## Summary

| Item   | Verdict              | Files touched                                                               |
| ------ | -------------------- | --------------------------------------------------------------------------- |
| TD-001 | ✅ FIXED              | 3 frontend files                                                            |
| TD-002 | ✅ FIXED              | `pyproject.toml`, `backend/pyproject.toml`                                  |
| TD-003 | ✅ FIXED              | `backend/modules/user/_models.py`, `backend/modules/artefact/_models.py`    |
| TD-005 | ✅ FIXED              | `frontend/src/app/components/admin-modal/AdminMcpTab.tsx`                   |
| TD-007 | ✅ PARTIALLY FIXED    | `backend/modules/llm/__init__.py`, `backend/modules/integrations/_voice_adapters/_xai.py` |
| TD-010 | ❌ FALSE ALARM        | none — finding was wrong                                                    |

---

## TD-001 — OPTION_STYLE on dropdown options

Native `<select>` elements only style their open dropdown list when the
`<option>` children carry inline `style`. Fixed by adding the project-standard
`OPTION_STYLE` constant and spreading it on each `<option>`.

- `frontend/src/app/components/user-modal/HistoryTab.tsx`
- `frontend/src/app/components/user-modal/UploadsTab.tsx`
- `frontend/src/app/components/user-modal/BookmarksTab.tsx`

`JobLogTab.tsx` already had the pattern; left unchanged.

**Verification:** `pnpm exec tsc --noEmit` clean. Visual confirmation
deferred — I cannot drive a browser here. Recommend a quick eyeball when
reviewing.

---

## TD-002 — pyproject.toml drift

Both `pyproject.toml` (root) and `backend/pyproject.toml` were rewritten so the
runtime dependencies match. Specifically:

- Root file's impossible pins (`transformers>=5.5.0`, `huggingface-hub>=1.9.0`,
  `pillow>=12.2.0`, `numpy>=2.4.4`, `onnxruntime>=1.24.4`) were corrected to
  match the realistic pins in the backend file.
- Removed `passlib` and `uvloop` from the root file — neither package is
  imported anywhere in `backend/` or `shared/` (verified via `grep`).
- Added `pymongo>=4.9` to **both** files. `pymongo` is imported directly (not
  via motor's transitive surface) in 7 places under `backend/modules/`, so
  CLAUDE.md's "no transitive installs" rule requires it to be listed
  explicitly.
- The backend file had **two competing dev-dependency sections** (the old
  `[project.optional-dependencies] dev = [...]` and the modern
  `[dependency-groups] dev = [...]`) with conflicting pins
  (`pytest>=8.3` vs `pytest>=9.0.2`, the latter being unreleased). Collapsed
  to a single `[dependency-groups] dev` block (PEP 735 / uv-native).

**Verification:** `uv sync` resolved cleanly; the only delta on disk was an
uninstall of the now-unused `passlib`. `find backend shared -name "*.py" |
xargs uv run python -m py_compile` clean. Adapter and registry test suites
pass (192 + 17 cases under `backend/tests/modules/llm/`).

---

## TD-003 — Deprecated `datetime.utcnow()` and naive `datetime.now()`

`datetime.utcnow()` is deprecated in Python 3.12+ and silently produces a
naive datetime. The audit flagged six call sites across two files. All were
replaced with a small module-local helper that returns a UTC-aware datetime:

```python
from datetime import datetime, timezone

def _utcnow() -> datetime:
    return datetime.now(timezone.utc)
```

Touched:

- `backend/modules/user/_models.py` — `UserDocument.created_at`,
  `UserDocument.updated_at`, `AuditLogDocument.timestamp`.
- `backend/modules/artefact/_models.py` — three
  `ArtefactDocument`/`ArtefactVersionDocument` defaults.

**Backwards-compat note:** existing documents in MongoDB stored as naive
datetimes will deserialise normally — Pydantic does not coerce stored values
on read, only enforces them on write/default. New writes will be UTC-aware.

**Verification:** `grep -r "datetime\.utcnow\|datetime\.now()" backend/` is
now empty. py_compile clean.

---

## TD-005 — AdminMcpTab fire-and-forget mutations

Three handlers in `AdminMcpTab.tsx` invoked `mcpApi.updateAdminGateway(...).then(() => fetchGateways())`
without a `.catch()`. Silent failure: if the update RPC errored the UI kept
the optimistic state but the server diverged, with no signal to the operator.

Refactored into a single `persistGatewayUpdate` helper that:

1. `await`s `mcpApi.updateAdminGateway(gatewayId, patch)`.
2. Refetches on success or failure (so the UI converges with the server
   on both branches).
3. Surfaces the error message via the existing `setError` slot the
   component already renders into a banner.

Each handler now invokes it as `void persistGatewayUpdate(gateway.id, patch)`,
matching the pre-existing optimistic-update pattern.

**Verification:** `pnpm exec tsc --noEmit` clean.

---

## TD-007 — Module boundary violations (partial)

The audit identified two distinct classes of internal imports:

**Class A — fixable through public-API exports:**

- `backend/modules/llm/__init__.py` — was importing
  `backend.modules.providers._registry.get` and
  `backend.modules.providers._repository.PremiumProviderAccountRepository`
  inside two functions. The `providers` package already re-exports both
  symbols (`get_definition`, `PremiumProviderAccountRepository`) via its
  `__init__.py`. Switched to public imports.
- `backend/modules/integrations/_voice_adapters/_xai.py` — was deferring an
  import to `providers._repository`. Switched to the public re-export.

**Class B — left in place for [REVIEW]:**

- `backend/main.py` lines 49–86 / 147 / 159 — bootstrap and migration
  imports. Acceptable in principle (main.py is the bootstrapper) but worth a
  cleanup pass via dedicated init hooks.
- `backend/dependencies.py:17, 60` — deferred imports of
  `backend.modules.user._auth` to break a circular import. Already
  documented; would prefer a contract refactor to a shim.
- `backend/jobs/handlers/_memory_consolidation.py`,
  `backend/jobs/handlers/_memory_extraction.py` — repeated internal imports
  from the `memory` module. Should be exposed through `memory.__init__`.
- `backend/ws/router.py:24, 25, 241` — internal imports from the `tools`
  module. Same fix shape: expose via `tools.__init__`.
- `backend/migrations/m_2026_04_24_session_toggles.py:19` — imports
  `backend.modules.chat._toggle_defaults` from a migration script.
  Defensible (one-shot migration), but worth a public alias.
- `backend/modules/user/_handlers.py` — three function-local imports
  (`tools._namespace`, `providers._probe`, `tools._mcp_executor`).

These all need a small, deliberate fix per module (decide what to expose in
the `__init__.py`, deprecate the private path) — not appropriate for an
autonomous sweep without your sign-off.

**Verification:** py_compile clean across `backend/` and `shared/`. Adapter
and registry test suites still pass.

---

## TD-010 — False alarm

Audit claimed `vite ^8.0.1` and `vitest ^4.1.2` in `frontend/package.json` were
unreleased ghost versions. Wrong: `pnpm-lock.yaml` shows `vite@8.0.3` and
`vitest@4.1.2` resolved cleanly, and `@vitejs/plugin-react`'s peer
dependency declares vite 5/6/7/8 support.

No change made. Item retracted in the audit doc.

---

## Build & test status after the sweep

| Check                                                  | Result    |
| ------------------------------------------------------ | --------- |
| `pnpm exec tsc --noEmit` (frontend)                    | ✅ clean   |
| `find backend shared -name "*.py" \| xargs py_compile` | ✅ clean   |
| `uv sync`                                              | ✅ clean   |
| `pytest backend/tests/modules/llm/adapters`            | ✅ 192 / 192 |
| `pytest backend/tests/modules/llm/{test_image_normaliser,test_registry,test_semaphores}.py` | ✅ 17 / 17 |
| `pytest` of integration suites needing real Mongo/Redis | ⏭ skipped — infra not available in this sandbox |

---

## What's left

The [REVIEW] and [INFO] items in the audit doc still need your direction.
Highlights:

- **TD-004** — wire pytest / pnpm tests into `.github/workflows/docker.yml`
  before more changes ship.
- **TD-006** — 19/20 backend modules still untested.
- **TD-007** Class B above — finish the boundary cleanup once you decide
  which symbols belong on each module's public surface.
- **TD-008** — confirm whether the invitation-countdown polling stays as a
  documented exception or moves to a CSS clock.
- **TD-009** — Dockerfile hardening (non-root user, healthcheck, resource
  limits).
- **TD-011, TD-011a** — supervised background loops and dict-mutation
  hardening in `ConnectionManager` / `_orchestrator`.

Branch is **not** merged. When you're ready, review the diff and either merge
to `master` or drop me a list of follow-ups.
