# Debt-Sweep Summary — 2026-04-07

Drei Audits + elf parallele Fix-Subagents. Details siehe `BACKEND-DEBT.md`,
`FRONTEND-DEBT.md`, `UX-DEBT.md` (jeweils mit `[x]`/`[~]` Status pro Item).

---

## Audit-Phase

| Bereich  | Datei              | Findings (autonom / Decision) |
|----------|--------------------|-------------------------------|
| Backend  | `BACKEND-DEBT.md`  | ~50 / 14                      |
| Frontend | `FRONTEND-DEBT.md` | ~35 / 10                      |
| UX       | `UX-DEBT.md`       | ~45 / 10                      |

---

## Fix-Phase — Subagents

### Backend (3 Agents, parallel)

**Backend-1 — Bugs & Quality (25 Items, vollständig erledigt)**
- Embedding-Queue: toter Sentinel-Code + Future-Default-Bombe gefixt
  (`backend/modules/embedding/_queue.py:23-26,86-96`).
- WS-Router: `since` validiert + defensive Token-Claim-Checks
  (`backend/ws/router.py:1-72`).
- Event-Bus: Inline-`xtrim` entfernt, Trim-Fehler werden geloggt
  (`backend/ws/event_bus.py:164-205`).
- WS-Manager: `send_to_user` parallelisiert via `asyncio.gather`
  (`backend/ws/manager.py`).
- Ollama-Adapter: Markdown-erhaltender `""`-Join, `fetch_models` parallel
  mit Semaphore(5) (`backend/modules/llm/_adapters/_ollama_cloud.py`).
- Persona-Handlers: `ReorderPersonasDto`, `UpdateAvatarCropRequest`,
  zentraler `get_optional_user`-Helper.
- Memory-Handler: N+1 in `commit_journal_entries` aufgelöst, `_ensure_aware`
  für tz-naive Datetimes.
- Config-Validator für `encryption_key` (Fernet 32-byte base64).
- `Role`-Enum statt Magic Strings (`shared/dtos/auth.py`).
- Token-Counter-Duplikat (`backend/modules/chat/_token_counter.py`) gelöscht.
- LLM-Harness nutzt jetzt `backend.modules.llm` Re-Exports.
- Avatar-Signing: separater `avatar_signing_key` Settings-Wert mit Fallback.
- Plus 13 weitere Kleinfixes (Database-Get-DB, Storage-Trim, Credentials-
  Pagination-Warning, Jobs-Consumer-Backoff, etc.).

**Backend-2 — Module Boundaries (5/5 erledigt)**
- `memory/_handlers.py` → `chat.get_latest_user_messages_for_persona` (Public-API).
- `jobs/handlers/_memory_extraction.py` → `chat.mark_messages_extracted`.
- `tools/_executors.py` → `knowledge.search` Re-Export.
- **Artefact-Logik aus `tools/_executors.py` verschoben** in
  `artefact/__init__.py` (`create_artefact`/`update_artefact`/`read_artefact`/
  `list_artefacts`) inkl. Versionierung + Eventing.
- `chat/_inference.py` → `llm.ToolCallEvent` Re-Export.

**Backend-3 — main.py + Security (8/8 erledigt)**
- `CORSMiddleware` mit `settings.cors_allowed_origins`.
- Cursor-Bug `b"0"` → `"0"` (decode_responses=True).
- `_periodic_extraction_loop` cross-modul-frei: nutzt neue Public-Functions
  `chat.find_sessions_for_extraction` + `chat.list_unextracted_messages_for_session`.
- `_session_cleanup_loop`: stille `try/except: pass` durch
  `_log.warning(..., exc_info=True)` ersetzt.
- Login-Rate-Limit: `get_client_ip()` parst `X-Forwarded-For`.
- JWT: `iss="chatsune"` + `aud="chatsune"` Claims gesetzt + validiert.
- Refresh-Cookie `domain=settings.cookie_domain` (optional).

### Frontend Tech + ChatView UX (1 Agent)

- **ChatView Race Conditions**: `cancelled`-Flag in Session-Resolve und
  Load-Effects, 15s-Timeout mit Retry-Button, sichtbarer `loadError`-State.
- Effect-Deps minimiert (`persona?.id`/`model_unique_id` statt Object-Ref).
- `applyModelCapabilities` Helper extrahiert.
- Reconnect-Backoff bekommt ±20% Jitter.
- **Refresh-Promise-Sharing**: `connection.ts` und `client.ts` teilen
  `currentRefresh`-Promise — keine parallelen 401-Storms mehr.
- `eventBus.ts` Prefix-Matching jetzt rekursiv.
- `eventStore.lastSequence: string | null` (war `string` mit Default `""`).
- `ArtefactPreview`: `mermaidPromise` Module-Cache, `unescape`-deprecated
  raus → `TextEncoder`-basierter base64-Helper.
- `MemoryBodySection`: gemeinsames `cancelRef` zwischen den beiden Effects.
- `setTimeout`-Cleanup-Pass in `markdownComponents`/`AssistantMessage`/
  `ArtefactOverlay`.
- ChatView UX: `text-white/20` → `/60`, sichtbare Fehler-Banner statt stille
  `.catch(()=>{})`, Header `max-w-[40vw] md:max-w-[400px]`,
  Cancel-mid-stream Inline-Notice.

**Übersprungen (`[~]`)**: Per-Bubble Optimistic-Send Retry (TODO im Code),
Optimistic-ID-Strategie, useAttachments-globaler-URL-Cleanup
(gehört in `uploadStore.clear()`, nicht in Hook).

### UX (6 Agents, FILE-OWNERSHIP-basiert parallel)

**Shell** (Sidebar/PersonaCard/PersonaItem/ChatInput/AppLayout/App.tsx):
- Skip-Link + `<main>`/`<nav aria-label="Primary navigation">` Landmarks.
- `aria-label`/`title` auf alle icon-only Buttons (Pin/Drag/Avatar/Logout/
  Send/Attach/Cancel/etc.).
- `safeLocalStorage`-Helper, alle 4 Sidebar-Calls + App.tsx-LastRoute-Tracker
  gewrappt.
- Hover-only Reveals → `focus-within:opacity-100` ergänzt.
- Kontrast-Pass: `text-white/20|25|30` Funktionstext → `/60`.

**LoginPage**:
- `useId()` + `htmlFor` für alle 6 Inputs (Login + Setup).
- `aria-label` Fallbacks unter den themed Labels ("Omen"/"Incantation").
- Microcopy-Subtitles unter den Themed-Begriffen.
- Live-Validation (Passwort ≥8, E-Mail-Regex, PIN-Regex).
- Caps-Lock-Warnung an beiden Password-Feldern.
- Per-Field-Errors aus FastAPI-`detail`-Arrays mit `aria-invalid`/`role="alert"`.

**admin-modal**:
- `AdminModal` Tab-Strip mit vollem ARIA-Tab-Pattern + `tabpanel`.
- `NewUserForm` mit `useId()` und gebundenen Labels.
- `UsersTab`: Avatar-copy-fail Inline-Notice, `aria-live` für DEL→SURE,
  Empty-State CTA "Create your first user".
- `ModelsTab`/`ModelList`/`SystemTab`: aria-labels, Capability-Filter
  `aria-pressed`, Empty-State "Refresh providers", Kontrast-Pass.

**user-modal**:
- `UserModal` Tab-Strip-ARIA-Pattern + `tabpanel`.
- **`DocumentEditorModal`**: `window.confirm` ersetzt durch zweistufiges
  Inline "Cancel → Discard?"-Pattern.
- `LibraryEditorModal`: `useId()`-Bindings, ARIA-dialog.
- `ApiKeysTab`: Empty-State "Add your first API key" mit Erklärung,
  alle DEL/SET/EDIT Buttons aria-labelled, generische Errors verbessert.
- `HistoryTab`/`BookmarksTab`/`UploadsTab`/`ProjectsTab`/`ArtefactsTab`/
  `KnowledgeTab`: aria-labels, Empty-State-Hinweise, Kontrast-Pass.

**persona-overlay**:
- `EditTab`: `useId()` für alle Form-Felder, Chakra-Swatches als
  `role="radiogroup"`/`role="radio"`. **Custom Toggle (Zeile 417)**:
  `<div onClick>` → `<button role="switch" aria-checked tabIndex>` mit
  Space/Enter-Handler.
- `PersonaOverlay` Tab-Strip-ARIA-Pattern + `tabpanel`.
- `HistoryTab`: `deleteTimer` Ref typed, Title-Gen 10s-Fallback zeigt jetzt
  Inline-Error statt silent reset, `aria-live` Region, `focus-within:` Reveals.
- `OverviewTab`/`KnowledgeTab`: aria-labels, Kontrast-Pass.

**Standalone-Modals + neue Hooks**:
- **Neuer Hook `useFocusTrap`** (`frontend/src/app/hooks/useFocusTrap.ts`):
  Tab/Shift+Tab cycling + Focus-Restore.
- **Neuer Hook `useUnsavedChangesGuard`**: gibt
  `{confirmingClose, attemptClose, confirmDiscard, cancelDiscard}` zurück.
- Patches in `ModelConfigModal`, `CurationModal`, `AvatarCropModal`,
  `LibraryEditorModal`, `BookmarkModal`: focus trap, `aria-labelledby`,
  responsive widths (`w-full sm:max-w-md`), Kontrast-Pass.
- `LibraryEditorModal` + `BookmarkModal` nutzen `useUnsavedChangesGuard`
  inklusive Inline-Discard-Prompt.

---

## Verification

Alle Subagents haben individuell verifiziert:
- Backend: `python -m py_compile` (bzw. `ast.parse`) auf jeder geänderten Datei.
- Frontend: `pnpm tsc --noEmit` clean (Exit 0) nach jeder Agent-Phase.

**Empfehlung vor dem Commit**: nochmal global laufen lassen
```fish
cd /home/chris/workspace/chatsune
cd frontend && pnpm tsc --noEmit; and cd .. ; and pnpm --prefix frontend run build
uv run python -m py_compile (rg --files backend -t py | string split0)
```

---

## Was offen bleibt (User-Decision)

Kurzliste — Details in den drei DEBT-Files unter "Benötigt User-Entscheidung".

**Backend**:
1. Memory ↔ Chat Coupling — Public-API, Embedding oder neues Modul?
2. `main.py` Lifespan-Refactor in `backend/scheduler/`?
3. `chat/__init__.py` (928 Z.) Geschäftslogik-Auslagerung.
4. JWT-Key-Rotation-Strategie nötig?
5. Fernet-Key in `.env` vs. HSM/Vault.
6. WebSocket-Token via Header statt Query?
7. In-Memory WS-Connection-State vs. Redis-Pub/Sub-Fan-out (Phase 2?).
8. Single-Worker Embedding-Queue externalisieren?
9. Local Filesystem Blob-Store vs. S3/MinIO?
10. Admin-Event-Broadcast Per-Admin-Scoping?

**Frontend Tech**:
11. Event-DTO-Typing — Codegen aus Pydantic, manuelle Spiegel oder Zod?
12. REST-Refetch-on-Event Anti-Pattern in `useUsers`/`useEnrichedModels`:
    Backend-Events um Payloads erweitern oder Frontend umstellen?
13. `useAutoScroll.ts` Polling-Interval (80 ms) durch
    `MutationObserver` oder Stream-Tick-Events ersetzen?
14. Artefact-Sandbox CSP/Toggle?
15. `unpkg.com` Runtime-Dependency für React/Babel bundlen?
16. Optimistic-UI ID-Strategie bei Reconnect.
17. Strict ESLint einschalten?
18. Zod/Valibot an WS-/API-Boundary?

**UX**:
19. Mystical-Microcopy ("REN/GEN/DEL/SURE?") — beibehalten oder Plain-Labels?
20. Destructive-Confirmation kanonisches Pattern: 3s-SURE vs. Modal vs.
    Toast-with-Undo (wie schon bei Session-Delete)?
21. Mobile-Support-Scope (Phase 1/2/nie)?
22. WCAG 2.1 AA voll oder Best-Effort?
23. Onboarding-Tour vs. statisches Getting-Started-Panel?
24. INCOGNITO-Erklärungs-Popover?
25. Persona-Delete-Konsequenzen (was genau warnen)?
26. Error-Reporting-Verbosity (Correlation-IDs sichtbar oder versteckt)?
27. Form-Validation: Backend-only oder gespiegelt?
28. Keyboard-Power-User (cmd-palette, j/k) oder mouse-first?

---

## Touched Files (grob)

- **Backend** (~30 Files): `main.py`, `config.py`, `database.py`,
  `dependencies.py`, `modules/{chat,memory,persona,llm,tools,artefact,
  knowledge,storage,user,embedding}/__init__.py` + `_*.py`,
  `ws/{router,event_bus,manager}.py`, `jobs/{_consumer,handlers/_memory_extraction}.py`,
  `llm_harness/{_runner,_output}.py`, `shared/{dtos,events}/*.py`.
- **Frontend** (~35 Files): `App.tsx`, `core/{utils/safeStorage,
  stores/eventStore,eventBus,client}.ts`, `core/connection.ts`,
  `app/hooks/{useFocusTrap,useUnsavedChangesGuard}.ts` (neu),
  `app/layouts/AppLayout.tsx`, `app/components/{sidebar/*,persona-card/*,
  admin-modal/*,user-modal/*,persona-overlay/*,model-browser/*,
  avatar-crop/*}`, `app/pages/LoginPage.tsx`, `features/chat/*`,
  `ChatView.tsx`, `MemoryBodySection.tsx`, `ArtefactPreview.tsx`,
  `ArtefactOverlay.tsx`, `markdownComponents.tsx`, `AssistantMessage.tsx`.

---

## Nächste Schritte (Vorschlag)

1. `pnpm tsc --noEmit` + `pnpm run build` lokal verifizieren.
2. Backend smoke-test (Login + WS + Chat-Roundtrip), insbesondere weil
   CORS, JWT-iss/aud und Cursor-Bug touched wurden.
3. **User-Entscheidungen #19, #20, #21, #22 zuerst** — alles weitere UX-Work
   hängt am Confirm-Pattern, Mobile-Scope und WCAG-Ziel.
4. Commit in zwei Schichten: erst Backend-Sweep, dann Frontend/UX-Sweep —
   damit Bisect später machbar ist.
