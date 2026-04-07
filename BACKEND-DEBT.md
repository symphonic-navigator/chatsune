# Backend Technical Debt — Audit Findings

Audit date: 2026-04-07. Scope: `backend/` (excluding `.venv`).
Legend: **Impact** / **Effort** / **Risk** = high (H) / medium (M) / low (L).

---

## Autonom lösbar

### Architektur — Modulgrenzen-Verstösse (CLAUDE.md Hard Rule #1)

- [x] **Memory-Modul importiert ChatRepository direkt** — `backend/modules/memory/_handlers.py:13`. Public API von `chat` exportiert kein Pendant. Sollte über `chat` öffentliche Funktionen (z. B. `list_messages_for_persona_session`) gehen. **Impact H · Effort M · Risk L**
- [x] **Job-Handler `_memory_extraction.py:250` importiert `chat._repository.ChatRepository`** zum Markieren extrahierter Messages. Via öffentlicher Chat-API (`mark_messages_extracted`) verfügbar machen. **Impact H · Effort L · Risk L**
- [x] **`main.py:215` (`_periodic_extraction_loop`) importiert `chat._repository.ChatRepository` und greift zudem direkt auf `ext_db["chat_sessions"]` zu** — doppelte Verletzung (Modulgrenze + Cross-Module-DB-Zugriff, Hard Rule #4). Logik in chat-Modul kapseln (`find_session_for_extraction`). **Impact H · Effort M · Risk M**
- [x] **`tools/_executors.py:61`** importiert `knowledge._retrieval.search` direkt — sollte `from backend.modules.knowledge import search` sein. **Impact M · Effort L · Risk L**
- [x] **`tools/_executors.py:136`** importiert `artefact._repository.ArtefactRepository` und führt komplette Artefact-Mutationen direkt aus (inkl. Versionierung). Geschäftslogik gehört in artefact-Modul, Executor sollte nur `artefact.create_artefact(...)` aufrufen. **Impact H · Effort M · Risk M**
- [x] **`chat/_inference.py:9`** importiert `llm._adapters._events.ToolCallEvent`. `ToolCallEvent` muss in der `llm`-Public-API re-exportiert werden. **Impact M · Effort L · Risk L**
- [x] **`llm_harness/_runner.py:11-12`** und **`llm_harness/_output.py:12`** importieren llm-Adapter-Internals. Harness ist standalone, dennoch sollten dieselben Re-Exports verwendet werden. **Impact L · Effort L · Risk L**
- [x] **`persona/_handlers.py:31`** verwendet deferred internes Decoding. `_optional_user` auf zentrale Helper in `dependencies.py` umstellen. **Impact L · Effort L · Risk L**

### Bugs

- [x] **`embedding/_queue.py:91-93`** — `if embed_req is not None:` gefolgt von `if embed_req is None: break` ist toter Code (zweite Bedingung kann nie wahr sein). Sentinel-Handling für embed_queue fehlt damit komplett. **Impact M · Effort L · Risk L**
- [x] **`embedding/_queue.py:25`** — `field(default_factory=lambda: asyncio.get_event_loop().create_future())` läuft beim Modul-Import oder ausserhalb eines laufenden Loops in Fehler. Funktional überschrieben durch `submit_query`, aber das Default ist eine Bombe. Auf `field(default=None)` reduzieren. **Impact M · Effort L · Risk L**
- [x] **`ws/router.py:55`** — `xrange("events:global", min=f"({since}", ...)`: `since` ist beliebiger Client-String, ungeprüft. Bei ungültiger Stream-ID wirft Redis, der `try/except` schluckt einzelne Einträge nicht den Aufruf. Validieren oder in äusseren try/except hüllen. **Impact M · Effort L · Risk L**
- [x] **`ws/router.py:60`** (BaseEvent.sequence already `str` in `shared/events/base.py`) — `envelope["sequence"] = stream_id` schreibt Redis-Stream-ID (bytes/str) in ein Feld, das laut `BaseEvent` `int` ist. Inkonsistent mit `event_bus.publish()` → `envelope.sequence = stream_id` (gleiches Problem in `event_bus.py:169`). Type sollte `str` sein oder konvertiert. **Impact M · Effort L · Risk L**
- [x] **`main.py:290`** — `if cursor == b"0" or cursor == 0:` — Redis mit `decode_responses=True` (siehe `database.py:13`) liefert `cursor` als `str`, nie als `bytes` oder `int`. Schleife terminiert nur per Zufall (cursor wird `"0"`). Bedingung korrigieren. **Impact M · Effort L · Risk L**
- [x] **`main.py:224`** — `cursor = b"0"` als Init-Wert, danach reassigned. Mit `decode_responses=True` sollte es `cursor = 0` sein. **Impact L · Effort L · Risk L**
- [x] **`memory/_handlers.py:355`** — `(datetime.now(UTC) - last_extraction_at.replace(tzinfo=UTC))` setzt Timezone naiv auf UTC, falls in Mongo timezone-naive gespeichert. Gefahr falscher Werte, wenn DB tz-aware liefert. **Impact L · Effort L · Risk L**
- [x] **`modules/persona/_handlers.py:343`** — `crop` wird per `Form` als JSON-String entgegengenommen, dann mit `json.loads`. Sollte ein Pydantic-DTO sein wie der `crop`-PATCH-Endpoint nutzt. **Impact L · Effort L · Risk L**
- [x] **`modules/llm/_adapters/_ollama_cloud.py:88`** — `" ".join(text_parts)` joined alle Text-Parts mit Space, was Markdown/Code zerstören kann. Sollte `"\n".join` oder Reihenfolge erhalten. **Impact M · Effort L · Risk L**
- [x] **`modules/storage/_handlers.py:213`** — `display_name` Whitespace-Trim erfolgt nach Längen-Check; leere Strings werden korrekt geblockt, aber lange Whitespace-Strings nicht. Minor. **Impact L · Effort L · Risk L**

### Security

- [x] **`main.py` — Keine CORS-Middleware konfiguriert.** Wenn das Frontend in Production unter anderer Origin läuft, brechen Browser-Requests; oder schlimmer, alles offen wenn ein Reverse Proxy CORS umsetzt. Bewusst per `CORSMiddleware` mit Allowlist konfigurieren. **Impact H · Effort L · Risk L**
- [ ] **`config.py:12`** — `mongodb_uri` Default enthält `directConnection=true`, korrekt für Single-Node RS0. Kein Auth in der URI. Akzeptabel im internen Compose-Netz, aber via `.env` erzwingen. **Impact M · Effort L · Risk L**
- [x] **`modules/user/_rate_limit.py:7`** — Login-Rate-Limit nutzt `client.host`, das hinter Reverse Proxy stets dieselbe IP ist. `X-Forwarded-For` parsen oder `ProxyHeadersMiddleware` aktivieren. **Impact H · Effort L · Risk M**
- [ ] **`modules/user/_handlers.py:64`** — Refresh-Cookie ist `secure=True, samesite="strict"`. Gut. Allerdings keine `domain`-Begrenzung; in Multi-Subdomain-Setups potenziell zu permissiv. **Impact L · Effort L · Risk L**
- [x] **`modules/user/_auth.py:53`** — `decode_access_token` erlaubt nur HS256. Kein `audience`/`issuer`-Check. Bei Geheimnis-Leak akzeptiert jeder mit Zugriff alles. Mindestens `iss/aud` setzen und prüfen. **Impact M · Effort L · Risk L**
- [x] **`modules/persona/_avatar_url.py:13`** — Signierschlüssel ist `settings.jwt_secret`. Avatar-URL-Signing sollte separaten Key nutzen, sonst kann ein Avatar-Signaturen-Leak Token-Verfahren beeinflussen. **Impact L · Effort L · Risk L**
- [ ] **`modules/storage/_blob_store.py:15`** — `f"{user_id}/{file_id}.bin"`: `user_id` kommt aus JWT-Sub (UUID), `file_id` aus uuid4. Pfad-Traversal unwahrscheinlich, aber kein expliziter Sanity-Check. Defensive Prüfung wäre billig. **Impact L · Effort L · Risk L**
- [ ] **`modules/storage/_handlers.py:73`** — `data = await file.read()` lädt komplette Datei in RAM (50 MB Limit). Bei viel Concurrency Memory-Druck. Streaming zur Disk wäre besser, aber out of scope für Phase 1. **Impact M · Effort H · Risk L**
- [x] **`ws/router.py:38`** — Token-Decode wirft `Exception`, abgefangen. Aber `mcp`-Check erfolgt VOR `accept`, gut. Allerdings `payload["sub"]` etc. ungeprüft — bei Token ohne diese Claims wirft KeyError → 500. Defensiv prüfen. **Impact L · Effort L · Risk L**
- [x] **`modules/llm/_credentials.py:88`** — `list_all` projiziert nur `user_id, provider_id` — sicher, ABER `length=10000` Hard-Limit; bei mehr Usern stillschweigend abgeschnitten. Pagination nutzen. **Impact L · Effort L · Risk L**

### Performance / Anti-Patterns

- [x] **`memory/_handlers.py:178`** — In Schleife `list_journal_entries` für jedes Entry erneut von DB laden. N+1. Einmalig laden und in dict cachen. **Impact M · Effort L · Risk L**
- [x] **`ws/manager.py:27`** — `send_to_user` iteriert sequenziell über Sockets. Bei vielen parallelen Tabs einer Person additiv. `asyncio.gather` einsetzen. **Impact L · Effort L · Risk L**
- [x] **`ws/event_bus.py:166`** — `xadd` + `xtrim` bei JEDEM Event. Trim ist teuer; periodisches Trim existiert bereits (`start_periodic_trim`). Inline-Trim entfernen. **Impact M · Effort L · Risk L**
- [ ] **`main.py:295`** — Vier konkurrierende Background-Loops (`session_cleanup`, `extraction`, `consumer`, `trim`) ohne Coordination-Logging beim Start/Stop. Bei Crash schwer debugbar. Loops in dedizierte Module verlagern, mit klaren Lifetime-Logs. **Impact L · Effort M · Risk L**
- [ ] **`main.py:72-205`** — `_session_cleanup_loop` ist 130+ Zeilen riesig: Cleanup, auto-commit Memory, Dreaming-Auto-Trigger. Drei verschiedene Verantwortungen in einer Funktion mit verschachtelten try/except-pass. Aufteilen. **Impact M · Effort M · Risk L**
- [x] **`modules/llm/_adapters/_ollama_cloud.py:142`** — `fetch_models` lädt Tags + ruft pro Modell `/api/show` sequentiell. Bei vielen Modellen zeitraubend. `asyncio.gather` mit Bound. **Impact M · Effort L · Risk L**
- [ ] **`modules/chat/__init__.py` (928 Zeilen)** — Public-API-File ist riesig und enthält Geschäftslogik (`_run_inference`, `handle_*`). Logik in `_orchestrator.py`/`_handlers_ws.py` auslagern, `__init__.py` nur Re-Exports. **Impact M · Effort M · Risk M**
- [ ] **`modules/chat/__init__.py:73`** — `import json as _json` mehrfach lokal in Closure. Auf Modul-Top heben. **Impact L · Effort L · Risk L**
- [x] **`jobs/_consumer.py:46-50`** — Fallback-Read verwendet `block=5000` ms; in der `consumer_loop` sleept zusätzlich 1 s wenn `processed=False`. Doppeltes Backoff. **Impact L · Effort L · Risk L**
- [x] **`ws/event_bus.py:172-177`** — `try/except: pass` schluckt jeden trim-Fehler. Mindestens `_log.warning`. **Impact L · Effort L · Risk L**
- [x] **`main.py:78,82`** — `try/except: pass` ohne Logging in cleanup-Loop. Diagnose unmöglich. **Impact M · Effort L · Risk L**

### Code-Qualität / Maintainability

- [ ] **Deferred Imports** — Über 20 Stellen mit `from backend.modules.X._Y import ...` im Funktionsrumpf zur Vermeidung von Circular Imports. Symptom für falsch verteilte Abhängigkeiten / fehlende öffentliche API-Re-Exports. Top-Imports nach Refactor anstreben. **Impact M · Effort H · Risk M**
- [x] **`modules/chat/_inference.py:73`** — `extra_messages = []` ohne Type-Annotation, wird mit `CompletionMessage` gefüllt → schlechter Type-Support. **Impact L · Effort L · Risk L**
- [x] **`backend/token_counter.py`** und **`modules/chat/_token_counter.py`** existieren beide — Duplikat? Konsolidieren. **Impact L · Effort L · Risk L** (deleted unused `modules/chat/_token_counter.py`)
- [x] **`config.py`** — Settings hat keinen Validator für `encryption_key` (Fernet erwartet 32-Byte Base64). Bei falschem Wert crasht erst `Fernet(...)` zur Laufzeit beim ersten Credential-Zugriff. Beim Startup validieren. **Impact M · Effort L · Risk L**
- [x] **`database.py:25`** — `_mongo_client.get_database()` ohne Argument nutzt DB aus URI; bricht still wenn URI keine DB nennt. Explizit `get_database("chatsune")` mit Settings-Wert. **Impact L · Effort L · Risk L**
- [x] **`modules/user/_handlers.py:362`** — `if body.role == "admin"` etc. Magic Strings. Enum/Konstanten. **Impact L · Effort L · Risk L**
- [x] **`modules/persona/_handlers.py:121`** — `body: dict` in `reorder_personas`, statt Pydantic-DTO. **Impact L · Effort L · Risk L**

---

## Benötigt User-Entscheidung

### Architektur-Entscheidungen

- **BD-031 (`ws/event_bus.py:21-23`) — Admin-Event-Broadcast ohne Resource-Scoping.** Jeder Admin sieht alle `USER_UPDATED`-Payloads inkl. sensibler Felder. Bewusst akzeptiert. **Frage:** Per-Admin-Scoping einführen oder so belassen? **Impact H · Effort H · Risk M**

- **Cross-Module Memory ↔ Chat Coupling.** Memory-Modul braucht regelmäßig Chat-Daten (Sessions, unextracted messages). Aktuell 3 Stellen mit direktem Repo-Zugriff. **Frage:** (a) Public API in `chat` erweitern, (b) Memory-Modul in Chat einbetten, (c) gemeinsames "session-data"-Modul. **Impact H · Effort H · Risk M**

- **`main.py` Lifespan überfrachtet (~290 Zeilen).** Auto-Commit, Dreaming, Periodic Extraction, Session Cleanup, Trim alle im selben Loop. **Frage:** In `backend/scheduler/` als eigenes Subsystem extrahieren? **Impact M · Effort H · Risk L**

- **`shared/dtos/inference.py` lebt unter shared/, aber nur llm+chat nutzen es.** **Frage:** In llm-Modul-Public-API verschieben? **Impact L · Effort M · Risk L**

### Security-Entscheidungen

- **`modules/user/_auth.py` — Single HS256 Secret, keine Rotation.** **Frage:** Key-Rotation-Strategie definieren (kid-Header, RS256, etc.)? Für Self-Hosted Single-Tenant evtl. überflüssig. **Impact M · Effort H · Risk M**

- **`modules/llm/_credentials.py` — Verschlüsselung mit Fernet, Key in `.env`.** Bei Server-Compromise sind alle User-API-Keys lesbar. **Frage:** HSM/Vault-Integration oder pro-User-Key-Derivation? **Impact H · Effort H · Risk H**

- **WebSocket-Token im Query-Parameter (`ws/router.py:29`).** Tokens landen in Reverse-Proxy-Logs. **Frage:** Auf Header (`Sec-WebSocket-Protocol`) wechseln oder bewusst akzeptieren? **Impact M · Effort M · Risk L**

- **Avatar-URL-Signing mit JWT-Secret.** Schlüsselgeteilt zwischen zwei Systemen. **Frage:** Eigenes `avatar_signing_key` Setting? **Impact L · Effort L · Risk L**

### Performance-/Skalierungs-Entscheidungen

- **`ws/manager.py` — In-Memory Connection State.** Kein Multi-Instance-Support. **Frage:** Phase-1 OK; in Phase 2 auf Redis-Pub/Sub-basiertes Fan-out? **Impact M · Effort H · Risk L**

- **`embedding/_queue.py` — Single-Worker-Queue, In-Process.** Skaliert nicht über Prozessgrenzen. Bei langsamem Modell blockiert alles. **Frage:** Gewünscht oder externalisieren (separater Embedding-Service)? **Impact M · Effort H · Risk M**

- **`modules/storage/_blob_store.py` — Lokales Filesystem.** Bei mehreren Backend-Instanzen kaputt. **Frage:** S3/MinIO-Adapter? **Impact M · Effort M · Risk L**

- **`jobs/_consumer.py` — Single Consumer (`consumer-1`).** Stream Consumer Group ist da, aber nur ein Consumer. **Frage:** Bewusst, oder irgendwann horizontal skalieren? **Impact L · Effort M · Risk L**

### Feature-/Verhaltens-Entscheidungen

- **`main.py:151` — Hard-coded Dreaming-Schwellen (10/25 Entries, 6h Cooldown).** **Frage:** In Settings/per-Persona konfigurierbar machen? **Impact L · Effort L · Risk L**

- **`modules/chat/__init__.py:58` — Hard-coded `_IDLE_EXTRACTION_DELAY_SECONDS = 300`.** **Frage:** Konfigurierbar? **Impact L · Effort L · Risk L**

- **`modules/storage/_validators.py:13-15` — Größenlimits hart codiert.** **Frage:** Per-User/Tier? **Impact L · Effort L · Risk L**

- **`shared/topics.py` Fan-out-Tabelle in `event_bus.py` als Source of Truth.** Topics ohne Fan-out-Eintrag werden per Warning gedroppt. **Frage:** Fail-Loud beim Startup (Vollständigkeitscheck) oder so belassen? **Impact M · Effort L · Risk L**
