# Tech & UX Debt — Consolidated Backlog

Stand: 2026-04-07. Konsolidiert offene Punkte aus `BACKEND-DEBT.md`,
`FRONTEND-DEBT.md` und `UX-DEBT.md` an einem Ort. Bei Aktualisierung der
Quelldateien hier nachziehen.

Legende: **Impact / Effort / Risk** = high (H) / medium (M) / low (L).

---

## Backend

### Autonom lösbar

- [ ] **`config.py:12`** — `mongodb_uri` Default ohne Auth. Akzeptabel im internen Compose-Netz, aber via `.env` erzwingen. **Impact M · Effort L · Risk L** *(bewusst zurückgestellt: self-contained, Port wird nicht exposed)*
- [ ] **`modules/storage/_handlers.py:73`** — `data = await file.read()` lädt komplette Datei in RAM (50 MB Limit). Streaming zur Disk wäre besser, out of scope für Phase 1. **Impact M · Effort H · Risk L**
- [ ] **Deferred Imports** — 20+ Stellen mit `from backend.modules.X._Y import ...` im Funktionsrumpf zur Vermeidung von Circular Imports. Symptom für falsch verteilte Abhängigkeiten / fehlende öffentliche API-Re-Exports. **Impact M · Effort H · Risk M**

### Benötigt User-Entscheidung

- **BD-031 Admin-Event-Broadcast ohne Resource-Scoping** (`ws/event_bus.py:21-23`) — Per-Admin-Scoping einführen oder so belassen? **H/H/M**
- **Cross-Module Memory ↔ Chat Coupling** — Public API in `chat` erweitern, Memory in Chat einbetten, oder gemeinsames "session-data"-Modul? **H/H/M**
- **`main.py` Lifespan überfrachtet** — In `backend/scheduler/` als eigenes Subsystem extrahieren? **M/H/L**
- **`shared/dtos/inference.py`** — In llm-Modul-Public-API verschieben? **L/M/L**
- **HS256 Secret ohne Rotation** — Key-Rotation-Strategie? **M/H/M**
- **Fernet-verschlüsselte API-Keys, Key in `.env`** — HSM/Vault-Integration oder pro-User-Key-Derivation? **H/H/H**
- **WS-Token im Query-Parameter** — Auf Header (`Sec-WebSocket-Protocol`) wechseln? **M/M/L**
- **In-Memory WS Connection State** — Phase 2 auf Redis-Pub/Sub-basiertes Fan-out? **M/H/L**
- **Single-Worker Embedding-Queue** — Externer Embedding-Service? **M/H/M**
- **Lokales Filesystem Blob-Store** — S3/MinIO-Adapter? **M/M/L**
- **Single Consumer Group** — Horizontal skalieren? **L/M/L**
- **Hard-coded Dreaming-Schwellen, Idle-Extraction-Delay, Storage-Limits** — Konfigurierbar machen? **L/L/L**
- **`shared/topics.py` Fan-out-Tabelle** — Fail-Loud beim Startup (Vollständigkeitscheck)? **M/L/L**

---

## Frontend

### A. Type-Safety / Verträge

- [ ] **`useChatStream.ts:13-128`** — Massive `as` Casts auf jedem Payload-Feld. Sollte typed Event-DTOs aus `shared/` benutzen oder `assertString`-Helper. **I:H E:M R:L**
- [ ] **`useChatSessions.ts:30-78`** — Manuelle DTO-Konstruktion mit Casts. **I:M E:M R:L**
- [ ] **`usePersonas.ts:31, 38`** — `as unknown as PersonaDto` Double-Cast. **I:M E:L R:L**
- [ ] **`connection.ts:59`** — `JSON.parse(msg.data)` ohne Schema-Validierung. Verstösst gegen "validate at system boundaries". **I:H E:M R:L**
- [ ] **`useChatStream.ts:14`** — `event.payload as Record<string, unknown>`. **I:M E:L R:L**

### B. Effects / Cleanup

- [ ] **`useChatStream.ts:133`** — StrictMode double-mount kann kurz zwei Listener haben. **I:L E:L R:L**
- [~] **`MemoryBodySection.tsx:45,55`** — Cancel-Flag via `useRef`, disable-Comments stehen weiter. **I:M E:L R:L**
- [ ] **`useBootstrap.ts:48`** — StrictMode-double-fire-Suppression dokumentationswürdig. **I:L E:L R:L**
- [ ] **`HistoryTab.tsx:220` (persona-overlay)** — Effect deps `[session.title]`, brittle wenn Title extern wechselt. **I:M E:M R:L**

### C. Race Conditions / Polling

- [ ] **`useAutoScroll.ts:58-65`** — `setInterval(80ms)` während Streaming. Sollte `requestAnimationFrame` oder Event-getriggert. Verstösst gegen No-Polling-Prinzip. **I:M E:M R:M**
- [ ] **`useChatStream.ts:88`** — Frontend erfindet `Date.now()` IDs + Timestamps; führt zu Re-Render-Flicker und Duplikaten bei Reconnect. **I:M E:M R:M**

### D. Memory / Resource

- [~] **`useAttachments.ts:20`** — Object-URLs im globalen `uploadStore`; jetzt via Logout cleanup. Tab-Wechsel-Pfade bleiben offen. **I:M E:L R:L**

### E. Fetch-Pattern (Polling-Geruch)

- [ ] **`UsersTab.tsx:55`** — `setInterval(1000ms)` Countdown ohne WS-Refresh, inkonsistent. **I:L E:L R:L**
- [ ] **`useUsers.ts:31-33` / `useEnrichedModels.ts:56-58`** — Full-Refetch via REST bei jedem Event. Verstösst gegen "Frontend ist View, kein Participant". **I:M E:M R:M**
- [~] **`ChatView.tsx:161-168`** — `applyModelCapabilities` extrahiert; TODO für Persona-DTO-Pfad bleibt. **I:M E:M R:L**

### F. Sicherheit

- [ ] **`ArtefactPreview.tsx:106-162`** — `preprocessJsx` Regex-basiert, fragil. Sandbox iframe ok, CSP fehlt. **I:L E:M R:L**
- [ ] **`ArtefactPreview.tsx:67-83`** — `HtmlPreview` injiziert vor `</head>`; user-controlled JS in iframe. Per Setting deaktivierbar wäre besser. **I:M E:M R:M**
- [ ] **`ArtefactPreview.tsx:168-170`** — JSX-Sandbox lädt React/Babel von **unpkg.com** zur Laufzeit. Supply-Chain + offline broken. Sollte gebundelt aus `public/` kommen. **I:M E:M R:L**

### G. WebSocket

- [ ] **`useWebSocket.ts:14-32`** — StrictMode double-mount kurze Disconnect/Reconnect-Sequenz. **I:M E:M R:M**
- [ ] **`connection.ts:11`** — Modul-globaler State, schwer testbar. **I:L E:M R:L**

### H. State Management

- [ ] **`MemoryBodySection.tsx:7`** — `EMPTY_ENTRIES` Module-Konstante; shallow-selector wäre einfacher. **I:L E:L R:L**
- [ ] **`Sidebar.tsx:154-167`** — `useState` + `localStorage` parallel, kein storage-event listener für Tab-Sync. **I:L E:L R:L**

### Benötigt User-Entscheidung

- **Event-DTO-Typing strategy** — Codegen aus Pydantic, manuelle Mirror oder Zod-Runtime-Validation an WS-Boundary?
- **REST-Refetch on Event vs. Payload-in-Event** — Backend-Events erweitern oder Frontend umstellen?
- **`useAutoScroll` Polling** — `MutationObserver` oder explizite `stream-tick`-Events?
- **JSX/HTML Artefact-Sandbox Sicherheit** — CSP-Header und/oder Toggle?
- **unpkg.com Runtime-Dependency** — In `public/` bundlen?
- **Optimistic UI vs. Server Truth** — Strategie für `useChatStream` Date.now-IDs?
- **Strict ESLint** mit `react-hooks/exhaustive-deps`?
- **Zod oder valibot** an WS- und API-Boundary?
- **Test-Coverage** für Stores/Hooks priorisieren?

---

## UX

### Feedback / Empty / Error States

- [ ] **No empty-state component family** — Lists rendern nichts wenn leer. Konsistente illustrierte Empty States pro Tab. **H/M/L**

### Accessibility

- [~] **Form inputs miss `htmlFor`/`id`** — login, setup, NewUserForm noch offen. **H/L/L**
- [~] **Modals lack focus trap / `aria-modal`** — AdminModal pending; UserModal/DocumentEditorModal Hook-Integration pending. **H/M/L**

### Keyboard Navigation

- [ ] **No documented shortcut surface** — `Shift+Esc` undiscoverable. `?`-Overlay. **M/M/L**
- [ ] **Sidebar navigation not keyboard-traversable** — keine Pfeil-Navigation. **M/M/L**
- [ ] **Drag-and-drop ohne Keyboard-Alternative** — `aria-keyshortcuts` Fallback. **M/M/L**

### Destruktive Aktionen

- [~] **3-second "SURE?" pattern** — `persona-overlay/HistoryTab.tsx` noch offen. **H/M/L**
- [ ] **Undo-Pattern auf alle Deletes** — persona, bookmark, knowledge, library, API-key, user delete. **H/M/L**
- [ ] **PersonaCard delete affordance** — Was geht verloren (sessions, memories, journal)? **H/M/M**

### Forms

- [ ] **`required` attribute only** — Browser-Bubbles clashen mit Dark Theme. **L/M/L**
- [~] **Unsaved changes guard** — EditTab (persona), NewUserForm, DocumentEditorModal pending. **H/M/L**
- [ ] **No character/length counters** — persona description, bookmark titles, knowledge docs, system prompts. **L/L/L**
- [ ] **Field error placement inconsistent** — login/ApiKeysTab/UsersTab divergieren. **L/M/L**

### Mobile / Responsive

- [ ] **Almost no responsive breakpoints** — Sidebars, Modals, Persona-Overlays desktop-only. **H/H/M**
- [ ] **Hover-only reveals** auf Touch unbenutzbar. **H/M/L**
- [ ] **Drag-and-drop touch-optimisation** — long-press delay per pointer type. **M/M/L**
- [ ] **Modals nicht full-screen auf mobile** — `max-w-*` overflow. **H/M/L**

### Onboarding

- [ ] **No first-run tour** — `/personas` ohne Guidance nach Setup. **M/M/L**
- [~] **API-key onboarding hidden** — Tab gut, Global gating offen.
- [~] **Empty-state CTAs** — user-modal Scope erledigt; restliche Surfaces offen.

### Microcopy

- [~] **Generic error messages** — ApiKeysTab gefixt, andere Surfaces offen.

### Misc Flows

- [ ] **Session-expired flow** — Toast verpassbar wenn user tippt; Modal-Interrupt erwägen. **L/L/L**
- [~] **Optimistic message rollback UI** — TODO in `ChatView.tsx:269-280`; per-bubble retry braucht MessageList plumbing. **M/M/L**

### Benötigt User-Entscheidung

- **Mystical/themed microcopy** vs. plain labels — Beibehalten + Subtitles, oder ersetzen?
- **Destruktive-confirm Pattern** — click-twice / modal / 8s-Undo-Toast als Standard?
- **Mobile support scope** — Phase 1, Phase 2 oder nie?
- **Accessibility target** — WCAG 2.1 AA voll oder best-effort?
- **Onboarding tour** — Interaktiv oder statisches Panel?
- **Incognito chat affordances** — Popover (jetzt erledigt) ausreichend?
- **Persona delete consequences** — Wording für Confirm-Dialog?
- **Error reporting verbosity** — Correlation IDs sichtbar oder nur friendly text?
- **Form validation strategy** — Backend-only oder client-side mirror?
- **Keyboard-shortcut surface** — Power-user (cmd-palette, j/k) oder maus-first?

---

## Hot Spots (höchster Pain pro Effort)

1. `aria-label`s + `htmlFor` Pass — ein PR, grosser a11y-Win
2. `text-white/20` in funktionalem Text auf `text-white/55+` heben
3. Hover-only Reveals → `focus-within:`
4. Destruktive Confirmation standardisieren *(braucht Entscheidung)*
5. Empty States mit CTAs für Knowledge / Bookmarks / Projects / Uploads / API keys
6. Focus traps + Esc auf alle Modals *(Esc-Audit erledigt; Focus-Trap-Hook ausrollen)*
