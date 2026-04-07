# Frontend Technical Debt

Audit-Datum: 2026-04-07
Scope: `frontend/src/**` — TS/React/Vite, kein UX-Fokus.
Bewertung pro Finding: **Impact** (Bug-Risiko) / **Effort** / **Risk** (regression).

Legende: H = high, M = med, L = low.

---

## Autonom lösbar

### A. Type-Safety / Verträge

- [ ] **`useChatStream.ts:13-128`** — Massive `as` Casts auf jedem Payload-Feld (`p.delta as string`, `p.tool_call_id as string`, `p.context_status as 'green'|...`). Keine Validierung; ein Backend-Schema-Drift bricht silent. Sollte typed Event-DTOs aus `shared/` benutzen oder zumindest eine Helper-Funktion `assertString(p, 'delta')`. **I:H E:M R:L**
- [ ] **`useChatSessions.ts:30-78`** — Gleiches Problem: `p.session_id as string`, `p.user_id as string` etc. Manuelle DTO-Konstruktion in Frontend statt typed Payload. **I:M E:M R:L**
- [ ] **`usePersonas.ts:31, 38`** — `event.payload.persona as unknown as PersonaDto` — Double-Cast über `unknown` umgeht TS bewusst. **I:M E:L R:L**
- [x] **`eventStore.ts:1-18`** — `lastSequence: string | null` mit Default `null`; `connection.ts` checks `!== null`. (BaseEvent.sequence ist im Frontend-Type bereits string.) **I:H E:L R:M**
- [ ] **`connection.ts:59`** — `JSON.parse(msg.data)` ohne Schema-Validierung; direkt zu `BaseEvent` gecastet. Kein Zod o.ä. an der Systemgrenze (verstößt gegen CLAUDE.md "validate at system boundaries"). **I:H E:M R:L**
- [ ] **`useChatStream.ts:14`** — `event.payload as Record<string, unknown>` — payload sollte typed sein. **I:M E:L R:L**
- [ ] **`HistoryTab.tsx:163`** (persona-overlay) — `useRef<ReturnType<typeof setTimeout>>()` ohne Initialwert; in TS strict ist das nun ein Fehler in React 19 (`useRef` requires arg). **I:L E:L R:L**

### B. useEffect / Cleanup / Dependencies

- [ ] **`useChatStream.ts:133`** — Dependency-Array nur `[sessionId]`, aber Closure liest `Topics`/`store()` (ok via getState), trotzdem fehlen ggf. nichts. OK, aber: Effect setzt Subscription auf `chat.*` ohne Filter — wenn Session wechselt, gibt es kurzzeitig zwei Listener (StrictMode double-mount). Cleanup ist korrekt. **I:L E:L R:L**
- [x] **`ChatView.tsx:212`** — Deps jetzt `[sessionId, scrollToBottom, isIncognito, persona?.id, persona?.model_unique_id, applyModelCapabilities]`. **I:H E:L R:L**
- [x] **`ChatView.tsx:262`** — `searchParams` und `scrollToMessage` ergänzt. **I:M E:L R:L**
- [~] **`MemoryBodySection.tsx:45,55`** — Cancel-Flag jetzt geteilt via `useRef`. Disable-Comments stehen weiter (Setter sind stabil). **I:M E:L R:L**
- [ ] **`useBootstrap.ts:48`** — Deps-Array enthält Setter-Refs; mit `hasRun.current` Guard ist es defensiv, aber StrictMode-double-fire wird trotzdem unterdrückt. OK, aber dokumentationswürdig. **I:L E:L R:L**
- [ ] **`HistoryTab.tsx:220` (persona-overlay)** — Effect deps `[session.title]`, soll aber bei "GEN button done" feuern; Race wenn Title sich extern ändert, schaltet GEN OK an. Brittle. **I:M E:M R:L**
- [x] **`ChatView.tsx:139-141`** — Deps auf `[isIncognito]` reduziert. **I:L E:L R:L**

### C. Race Conditions

- [x] **`ChatView.tsx:53-85`** — Session-Resolve mit `cancelled` Flag, 15s Timeout, Retry-Button. **I:H E:L R:M**
- [x] **`ChatView.tsx:175-211`** — Cancel-Flag für `getMessages`/`getSession`/`artefactApi.list`; sichtbarer `loadError` State. **I:H E:M R:M**
- [x] **`MemoryBodySection.tsx:24-46`** — Geteiltes `cancelRef` zwischen beiden Effects. **I:M E:L R:L**
- [x] **`connection.ts:129-144`** — `handleTokenRefresh` nutzt geteiltes `currentRefresh` Promise. **I:M E:M R:M**
- [ ] **`useAutoScroll.ts:58-65`** — `setInterval(80ms)` während Streaming. Polling-Pattern; sollte über `requestAnimationFrame` oder Event-getriggerter `flushSync` laufen. Verstößt gegen "no polling" Prinzip aus CLAUDE.md. **I:M E:M R:M**
- [ ] **`useChatStream.ts:88`** — `setMessages` bei stream end nutzt `Date.now()` als Fallback ID, `created_at: new Date().toISOString()` — Frontend erfindet Daten, die später durch Server-State überschrieben werden müssen → führt zu Re-Render-Flicker und ggf. duplizierten Messages bei Reconnect. **I:M E:M R:M**

### D. Memory Leaks / Resource Management

- [~] **`useAttachments.ts:20`** — Object-URLs leben im globalen `uploadStore`, nicht component-scoped. Blanket revoke-on-unmount würde Tab-Wechsel brechen; korrekte Lösung gehört in `clear()`/Logout-Pfad des Stores. Übersprungen. **I:M E:L R:L**
- [ ] **`uploadStore.ts:22`** — Globale Zustand-Store hält `pendingAttachments` über Component-Mounts hinweg; `URL.createObjectURL` Lebenszeit ist an Store geknüpft, nicht an Komponente. Bei Browser-Tab-Close OK, aber bei Logout sollten Object-URLs revoked werden — kein Hook in `authStore.clear()`. **I:L E:L R:L**
- [ ] **`eventBus.ts:5-39`** — Singleton ohne Limit; wenn ein Hook leakt, akkumulieren Listener unbegrenzt. Kein DEV-Warning bei N>100 Listeners pro Type. **I:L E:L R:L**
- [ ] **`useEventBus.ts:7-19`** — Hält `eventsRef` UND `events` State (doppelte Speicherung); harmlos aber unnötig. **I:L E:L R:L**
- [x] **`ArtefactPreview.tsx:215-245`** — Mermaid-Import jetzt als Module-level Promise gecached. **I:L E:L R:L**

### E. Doppelte / falsche fetch-Pattern (Polling-Geruch)

- [ ] **`UsersTab.tsx:55`** — `setInterval(1000ms)` für Countdown — OK fachlich, aber: gleichzeitig kein WebSocket-event-basierter Refresh, obwohl `useUsers.ts:31-33` events nutzt. Inkonsistent. **I:L E:L R:L**
- [ ] **`useUsers.ts:31-33`** / **`useEnrichedModels.ts:56-58`** — Anti-Pattern: Bei jedem Event vollständiger Refetch via REST. Verstößt gegen "Frontend ist View, kein Participant" — Backend sollte Payload mitschicken statt nur Trigger. **I:M E:M R:M**
- [~] **`ChatView.tsx:161-168`** — In `applyModelCapabilities` Helper extrahiert; TODO-Kommentar für Persona-DTO-Pfad gelassen (DTO trägt das Feld noch nicht). **I:M E:M R:L**

### F. Sicherheit

- [ ] **`ArtefactPreview.tsx:106-162`** — `preprocessJsx` macht Regex-basiertes JS-Parsing → fragil, kann user-Code mangeln. Akzeptabel da Sandbox iframe, aber: **`sandbox="allow-scripts"`** ohne `allow-same-origin` ist ok; CSP fehlt. **I:L E:M R:L**
- [ ] **`ArtefactPreview.tsx:67-83`** — `HtmlPreview` injiziert vor `</head>` per `replace`; wenn user-HTML kein `</head>` hat, läuft Fallback. Funktioniert, aber `srcDoc` mit `allow-scripts` führt user-controlled JS aus. Da self-hosted single-user Tool akzeptabel; sollte aber per Setting deaktivierbar sein. **I:M E:M R:M**
- [x] **`ArtefactPreview.tsx:89`** — Ersetzt durch `TextEncoder`-basierten `utf8ToBase64` Helper. **I:L E:L R:L**
- [ ] **`ArtefactPreview.tsx:168-170`** — JSX-Sandbox lädt React/Babel von **unpkg.com** zur Laufzeit → Supply-Chain-Risk + offline broken. Sollte gebundelt aus public/ kommen. **I:M E:M R:L**
- [ ] **`App.tsx:14-19`** und **`Sidebar.tsx:154,164`** — `localStorage` ohne try/catch (Quota / Privacy-Mode). Inkonsistent: `displaySettingsStore.ts:14` macht typeof-Check, andere nicht. **I:L E:L R:L**
- [x] **`client.ts:55-79`** — In-flight `currentRefresh` Promise wird geteilt. **I:M E:M R:L**

### G. Connection / WebSocket

- [x] **`connection.ts:120-127`** — ±20% Jitter ergänzt; Cap-Reset bereits in `onopen`. **I:L E:L R:L**
- [ ] **`useWebSocket.ts:14-32`** — Effect deps `[isAuthenticated]`, ruft bei jedem mount `connect()` auf, plus `disconnect()` im Cleanup. StrictMode double-mount → kurze Disconnect/Reconnect-Sequenz beim Start. Connection-Modul guarded mit `ws !== socket`, aber unnötig fragil. **I:M E:M R:M**
- [ ] **`connection.ts:11`** — Modul-globaler State (`ws`, `reconnectTimer`, `intentionalClose`, `isRefreshing`) — schwer zu testen, kein Reset für Unit-Tests. **I:L E:M R:L**
- [x] **`eventBus.ts:28-33`** — Prefix-Matching jetzt auf alle Tiefen (`persona.*`, `persona.memory.*` …). **I:M E:L R:L**

### H. State Management

- [ ] **`useChatStream.ts:11`** — `const store = useChatStore.getState` (Funktionsreferenz, nicht aufgerufen) — funktioniert aber unidiomatisch und macht Code verwirrend. **I:L E:L R:L**
- [ ] **`MemoryBodySection.tsx:7`** — `EMPTY_ENTRIES` als Module-Konstante mit dynamic-import-type; OK aber Pattern wäre einfacher als shallow-selector. **I:L E:L R:L**
- [ ] **`Sidebar.tsx:154-167`** — `useState(() => localStorage.getItem(...))` Lazy-Init OK, aber State und localStorage werden parallel gehalten ohne Sync zwischen Tabs (kein storage-event listener). **I:L E:L R:L**

### I. Code-Qualität / Wiederholung

- [x] **`ChatView.tsx:158-167`** und **`ChatView.tsx:198-208`** — In `applyModelCapabilities` Helper extrahiert. **I:L E:L R:L**
- [ ] **`HistoryTab.tsx:58` (persona-overlay)** und **`HistoryTab.tsx:59` (user-modal)** — Wahrscheinlich duplizierte History-Tab-Implementierungen. Bestätigen + extrahieren. **I:M E:M R:M**
- [x] **`markdownComponents.tsx:13`, `AssistantMessage.tsx:22`, `ArtefactOverlay.tsx:66`** — `useRef`-basierter Cleanup ergänzt. Weitere Stellen in der Codebase bleiben offen. **I:L E:L R:L**

---

## Benötigt User-Entscheidung

### Architektur

- **Event-DTO-Typing strategy**: Aktuell castet jedes Hook seine Payload-Felder einzeln. Sollte ein gemeinsames Frontend-`shared/`-Pendant existieren? Optionen:
  1. Codegen aus Pydantic → TS Interfaces (z.B. `datamodel-code-generator`).
  2. Manuell gepflegtes `frontend/src/core/types/events/*.ts` als Spiegel von `shared/events/*.py`.
  3. Runtime-Validation mit Zod an WS-Boundary.
  Welche Richtung?

- **REST-Refetch on Event vs. Payload-in-Event**: `useUsers.ts`/`useEnrichedModels.ts` machen Full-Refetch bei jedem Event. CLAUDE.md sagt explizit: "Events carry DTOs — the frontend never makes a follow-up REST call". Soll ich Backend-Events erweitern, oder Frontend-Hooks umstellen sobald Backend-Events Payloads tragen?

- **`useAutoScroll.ts:58` Polling-Interval (80ms)**: Verstößt gegen No-Polling-Prinzip. Alternative: `MutationObserver` auf MessageList oder explizite "stream-tick"-Events. Welcher Ansatz ist gewünscht?

- **JSX/HTML Artefact-Sandbox Sicherheit**: User-Code wird in iframe `allow-scripts` ohne CSP ausgeführt. Single-User self-hosted ist OK, aber bei Multi-User-Phase wird das ein XSS-Vektor (Cross-User über shared persona/artefact?). Soll ich CSP-Header und/oder Toggle einbauen?

- **Unpkg.com Runtime-Dependency**: `ArtefactPreview.tsx:168-170` lädt React/Babel zur Laufzeit von unpkg → offline-broken + Supply-Chain. Soll ich diese in `public/` bundlen?

- **Optimistic UI vs. Server Truth**: `useChatStream.ts:67` erfindet `Date.now()`-IDs und `new Date()` Timestamps für streaming-end Messages. Bei Reconnect/Resync entsteht potenziell Duplikat. Strategie?

### Tooling

- **Strict ESLint?** Aktuell scheinen `react-hooks/exhaustive-deps` Verstöße toleriert. Soll ich auf strict stellen und alle Findings in B fixen?

- **Zod oder valibot** an WS- und API-Boundary einführen?

- **Test-Coverage** für Stores/Hooks ist dünn (`useChatStream`, `useChatSessions` ohne Tests). Priorisieren?
