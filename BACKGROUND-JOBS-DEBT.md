# Background-Jobs — Technical Debt & Pre-Release-Sicherheitsanalyse

> Analyse vor dem Open-Source-Test-Release für eine kleine Gruppe von Freiwilligen.
> Ziel: Sicherstellen, dass Tester nicht durch Bugs ihre Ollama-Cloud-Usage
> verbraten und dass keine Jobs hängen bleiben oder das System instabil machen.
>
> Stand: 2026-04-08 — nach Commits `fd5e1d6` und `148a2ae`.

---

## Executive Summary

Das Background-Job-System hat durch die jüngsten Commits (`148a2ae`, `fd5e1d6`)
erhebliche Stabilitäts-Verbesserungen erhalten, ist aber **noch nicht bereit für
ein öffentliches Test-Release**. Die Hauptrisiken:

1. **Ollama-Cloud-Kostenexplosion** — Es gibt weder ein globales Rate-Limit
   pro User noch ein Daily-Token-Budget. Ein Bug in Memory-Extraction oder
   Retry-Logik kann in Minuten tausende API-Calls erzeugen.
2. **Heartbeat-Auto-Cancel Race Conditions** — Die globalen Dicts
   (`_last_heartbeat`, `_cancel_user_ids`, `_cancel_events`) werden ohne
   `asyncio.Lock` mutiert. Disconnect + Heartbeat-Timeout können gleichzeitig
   laufen und Inferences nicht sauber abbrechen.
3. **Memory-Consolidation Context-Window-Overflows** — Memory-Bodies werden
   nie truncated. Bei langer Nutzung kann ein einzelner Consolidation-Call
   das Context-Window sprengen und mit 3 Retries hunderttausende Tokens verschwenden.
4. **Fehlender Circuit-Breaker / Kill-Switch** — Wenn Ollama Cloud Probleme hat,
   laufen Retries weiter und feuern kontinuierlich fehlschlagende Requests.
5. **Fehlendes per-User Budget-Tracking** — Niemand (weder User noch Operator)
   kann sehen, wie viele Tokens bereits verbraucht wurden.

**Empfehlung:** Vor dem Release mindestens die **Critical** Items unten
abarbeiten. Die **Hard Safeguards** (Rate-Limit, Kill-Switch, Daily Budget)
sind die wichtigste Notbremse und sollten auch dann da sein, wenn man einzelne
andere Findings verschiebt.

---

## Findings

### Critical

#### C-001 — Keine globale Ollama-Cloud Rate-Limiting
**Dateien:** `backend/jobs/handlers/_memory_extraction.py`,
`backend/jobs/handlers/_memory_consolidation.py`,
`backend/jobs/handlers/_title_generation.py`

**Problem:** Jeder LLM-Call aus einem Job-Handler kann einen ganzen Streaming-
Request gegen Ollama Cloud abfeuern. Es gibt keinerlei Obergrenze dafür, wie
viele Calls ein User pro Minute oder pro Stunde auslösen kann. Memory-Extraction
lädt existierende Bodies + Journal-Einträge und kann schnell mehrere Tausend
Tokens pro Call erreichen. Memory-Consolidation bei ≥25 committed Entries ist
noch deutlich größer.

**Szenario:**
1. User aktiviert Ollama Cloud als Provider.
2. Auto-Dreaming triggert (alle 6 h ab ≥10 committed entries).
3. Ein Fehler im Handler oder ein Provider-Timeout löst einen Retry aus.
4. 2 × Retries × 3 Job-Typen × 10 aktive Sessions → Hunderte von Handler-
   Ausführungen innerhalb einer Stunde, jede mit mehreren Tausend Tokens.
5. User-Kontingent ist in kurzer Zeit aufgebraucht.

**Auswirkung:** Unerwartete Kosten für Tester. Schadet Vertrauen im
Open-Source-Release.

**Empfehlung:**
- **MUSS**: Globales Rate-Limit pro User pro Provider (z. B. 50 Calls/min).
- **SOLLTE**: Daily Token-Budget pro User (z. B. 1 M Tokens/Tag).
- **SOLLTE**: Circuit-Breaker pro Provider bei Error-Rate > 30 % in 5 min.

---

#### C-002 — Heartbeat-Watchdog Race Condition
**Datei:** `backend/modules/chat/_orchestrator.py` (~Zeilen 360–420),
`backend/ws/router.py` (~Zeilen 140–147)

**Problem:** Globale Dicts `_last_heartbeat`, `_cancel_user_ids`,
`_cancel_events`, `_heartbeat_watchdogs` werden ohne Lock gelesen und
mutiert. `record_heartbeat()`, der Watchdog-Loop und `cancel_all_for_user()`
laufen concurrent.

**Szenario:**
1. User verliert Internet → WS-Disconnect.
2. `cancel_all_for_user()` setzt cancel_events und ruft `pop()` auf den
   Tracking-Dicts.
3. Gleichzeitig prüft der Watchdog-Loop `_last_heartbeat.get(cid)`.
4. Race: KeyError oder Stale-Value, Watchdog setzt cancel_event evtl. zu spät
   oder doppelt.
5. Upstream-Stream läuft noch ≥12 s nach Disconnect → User wird für Tokens
   berechnet, die niemand mehr sieht.

**Auswirkung:** Unberechenbare Token-Kosten bei jedem Verbindungsabbruch.

**Empfehlung:**
- **MUSS**: Ein `asyncio.Lock` (modul-global) um alle Operationen auf diesen
  Dicts.
- **MUSS**: Beim Finally-Block des Inference-Runners auch den Watchdog-Task
  explizit canceln und aus `_heartbeat_watchdogs` entfernen.
- **SOLLTE**: Guard gegen doppeltes `cancel_event.set()`.

---

#### C-003 — `_periodic_extraction_loop` Cursor-Handling bei Redis-Exceptions
**Datei:** `backend/main.py` (~Zeilen 272–380)

**Problem:** Wenn `redis.scan()` innerhalb der `while True`-Schleife eine
Exception wirft (flaky Redis, Timeout), wird der Fehler nur geloggt, aber der
Cursor nicht zurückgesetzt. Je nach Exception-Pfad kann die Schleife mit einem
stale Cursor weiterlaufen und Keys mehrfach verarbeiten.

**Szenario:**
1. Redis unter Last, `scan()` timeouted.
2. Exception gelogged, Loop iteriert weiter.
3. Keys werden doppelt oder unvollständig verarbeitet → doppelte
   Extraction-Submits.
4. Dedup-Slots im In-Flight-Cache werden schnell verbraucht, legitime
   Extractions können nicht mehr submitted werden.

**Auswirkung:** Queue-Flood, verzögerte User-Requests, Budget-Verbrauch für
redundante Arbeit.

**Empfehlung:**
- **MUSS**: Cursor bei Exception zurücksetzen und maximal N Retries im Loop.
- **MUSS**: Rate-Limit auf Extraction-Submits (max. 1 pro User alle 5 min im
  periodischen Loop).
- **SOLLTE**: Dedup-Slot-TTL von 1 h auf 6 h anheben.

---

#### C-004 — Memory-Extraction Idempotenz-Lücke zwischen Journal-Writes und Mark-Extracted
**Datei:** `backend/jobs/handlers/_memory_extraction.py` (~Zeilen 218–250)

**Problem:** Der Handler schreibt Journal-Entries einzeln, publisht sofort
Events, und markiert die Quell-Messages erst danach als extracted. Wenn der
Handler zwischen diesen Schritten crasht, werden Journal-Entries persistiert,
aber die Messages gelten als noch-nicht-extracted. Der Retry erzeugt Duplikate.

**Szenario:**
1. Handler erstellt 10 Journal-Entries und publisht 10 Events.
2. `mark_messages_extracted()` wirft Exception (MongoDB-Hiccup).
3. Job wird als failed markiert und retried.
4. Retry lädt dieselben Messages, erzeugt erneut Journal-Entries.
5. User sieht dieselben Facts mehrfach.

**Auswirkung:** Datenqualitätsverlust, doppelte LLM-Calls, Tokens verschwendet.

**Empfehlung:**
- **MUSS**: Atomare Reihenfolge — entweder in einer MongoDB-Transaction oder
  mit einem Transactional-Inbox-Pattern.
- **SOLLTE**: Idempotenz-Key (job_id + attempt) in allen Event-Publishes,
  damit Frontend Duplikate erkennt.

---

### High

#### H-001 — Memory-Consolidation ohne Token-Limit-Check
**Datei:** `backend/jobs/handlers/_memory_consolidation.py` (~Zeilen 109–122)

**Problem:** Memory-Body wird geladen und als System-Prompt hingegeben, egal
wie groß er ist. Es gibt keine Token-Length-Prüfung vor dem LLM-Call.

**Szenario:**
1. Persona läuft seit 3 Monaten, Memory-Body ist ~40 kB Text.
2. Consolidation triggert bei 25 committed entries.
3. Input-Prompt: ~42 k Tokens, Modell hat 8 k Context-Window.
4. Request schlägt fehl mit `context_window_exceeded`.
5. 3 × Retry versucht immer wieder mit demselben Body → 126 k Tokens
   verschwendet auf fehlschlagende Requests.

**Auswirkung:** Silente Kostenwelle bei Power-Usern.

**Empfehlung:**
- **MUSS**: Token-Length-Check vor `stream_completion`. Wenn Input > 70 % des
  Context-Windows → `UnrecoverableJobError` (kein Retry).
- **MUSS**: Memory-Body-Truncation bei 50 % Context-Window mit Marker.
- **SOLLTE**: Chunked Consolidation für sehr große Bodies.

---

#### H-002 — `asyncio.timeout()` bricht Upstream-Stream nicht ab
**Datei:** `backend/jobs/_consumer.py` (~Zeilen 139–157)

**Problem:** Der Job-Consumer wrapped Handler in `asyncio.timeout()`. Wenn
das Timeout feuert, wird die Coroutine gecancelt, aber der Upstream-
HTTP-Request an Ollama läuft serverseitig weiter. Ollama tokenized die
komplette Response und rechnet sie ab, obwohl der Client sie nie sieht.

**Szenario:**
1. Consolidation startet, Stream beginnt zu liefern.
2. Nach 180 s feuert `asyncio.timeout()`, Handler wird gecancelt.
3. Ollama generiert und berechnet die Response komplett zu Ende.
4. Job wird retried → noch ein Request, noch mehr Tokens.

**Auswirkung:** Bezahlte Tokens, die nie persistiert werden.

**Empfehlung:**
- **SOLLTE**: Beim Cancel den zugrundeliegenden `httpx`-Request abbrechen
  (Stream-Client `aclose()`).
- **SOLLTE**: Exponential Backoff statt fester Retry-Delays.
- **MUSS**: Bei Timeout correlation_id + user_id + model strukturiert loggen.

---

#### H-003 — `trigger_disconnect_extraction` schluckt Exceptions
**Dateien:** `backend/ws/router.py` (~Zeilen 150–154),
`backend/modules/chat/_orchestrator.py` (~Zeilen 765–800)

**Problem:** Der finally-Block im WS-Router schluckt alle Exceptions silent.
Wenn Redis unter Last ist und der Submit timeouted, verliert man die
Extraction still.

**Szenario:**
1. User disconnected nach intensiver Nutzung.
2. `trigger_disconnect_extraction()` submitted Job.
3. Redis-Submit timeouted (z. B. wegen gleichzeitigem Stream-Trim).
4. Exception wird swallowed.
5. Memory bleibt nicht erfasst — User-Notes verloren.

**Auswirkung:** Datenverlust, Vertrauensbruch.

**Empfehlung:**
- **MUSS**: Retry-Loop mit 3 Attempts und Exponential Backoff.
- **MUSS**: Logging auf ERROR, nicht silent.
- **SOLLTE**: Lokaler Fallback-Buffer (SQLite oder In-Memory + periodic sync).

---

#### H-004 — NDJSON-Parsing fragil bei malformed Chunks
**Datei:** `backend/modules/llm/_adapters/_ollama_base.py` (~Zeilen 180–216)

**Problem:** Malformed NDJSON-Lines werden einfach geskipped. Wenn ein
kritischer `done: true`-Chunk verloren geht oder fragmentiert ankommt, wartet
der Loop ewig.

**Szenario:**
1. Ollama Cloud unter Last, Response fragmentiert.
2. `done: true`-Chunk kommt als zwei Teile an.
3. Beide Teile schlagen bei `json.loads` fehl → skipped.
4. Der Handler wartet auf weitere Chunks, bis das Timeout auf Job-Ebene greift.
5. Job wird als timeout markiert und retried.

**Auswirkung:** Gestuckte Jobs und wiederholte Upstream-Calls.

**Empfehlung:**
- **SOLLTE**: Gutter-Timeout pro Chunk (z. B. 30 s ohne neue Daten → StreamDone).
- **SOLLTE**: Line-Buffer mit Wiederverbindung fragmentierter Zeilen.

---

#### H-005 — Job-Lifecycle ohne persistenten Status
**Datei:** `backend/jobs/_consumer.py` (~Zeilen 51–130), `backend/jobs/_models.py`

**Problem:** Job-Status ist nur implizit durch Redis-Stream-PEL und Retry-Hash
repräsentiert. Nach einem Backend-Crash wird ein PEL-Eintrag beim Restart erneut
ausgeführt, ohne dass der Handler eine Idempotenz-Garantie hat.

**Szenario:**
1. Memory-Extraction läuft, Deployment startet Backend neu.
2. Beim Start pickt `xreadgroup` mit ID `"0"` den Job aus dem PEL.
3. Handler läuft erneut, erzeugt ggf. doppelte Journal-Entries (siehe C-004).

**Auswirkung:** Dateninkonsistenzen, doppelte Arbeit.

**Empfehlung:**
- **MUSS**: Ein `execution_token` in `JobEntry`, das vor dem Handler-Run in
  MongoDB gecheckt/gesetzt wird. Wenn schon gesehen → skippen.
- **SOLLTE**: Parallel-Status in MongoDB (`jobs` Collection) für Durability
  und Observability.

---

### Medium

#### M-001 — Unbegrenztes Wachstum der Memory-Bodies
**Problem:** Memory-Body wird nie archiviert oder truncated. Bei langer
Nutzung → mehrere 100 kB pro Persona.

**Auswirkung:** Slow MongoDB-Queries, Consolidation trifft Context-Window,
Speicher-Kosten steigen.

**Empfehlung:**
- **SOLLTE**: Memory-Body-Truncation / Chunked-Archive.
- **SOLLTE**: Admin-UI für Memory-Usage pro Persona.

---

#### M-002 — Embedding-Queue ohne `maxsize`
**Datei:** `backend/modules/embedding/_queue.py` (~Zeilen 36–54)

**Problem:** `asyncio.Queue()` ohne Limit. Bei großem Document-Upload mit
10 k Chunks wächst die Queue unkontrolliert.

**Auswirkung:** Memory-OOM bei bulk imports.

**Empfehlung:**
- **SOLLTE**: `asyncio.Queue(maxsize=1000)` + 503 bei Overflow.

---

#### M-003 — Event-Bus Stream Trim nur alle 10 min
**Datei:** `backend/ws/event_bus.py` (~Zeilen 195–212)

**Problem:** Trim läuft alle 10 Minuten und nur nach `minid`. Bei vielen
gleichzeitigen Sessions kann Redis-Memory explosionsartig wachsen.

**Auswirkung:** Redis-OOM bei vielen aktiven Sessions.

**Empfehlung:**
- **MUSS**: Trim-Interval auf 2 Minuten.
- **MUSS**: `MAXLEN ~ 1000` pro Stream zusätzlich zu `MINID`.

---

#### M-004 — Kein per-User Budget-Tracking
**Problem:** Niemand weiß, wie viele Tokens ein User heute verbraucht hat.

**Empfehlung:**
- **MUSS**: MongoDB-Collection `user_quotas` mit Tagesverbrauch.
- **SOLLTE**: Daily Reset, Alert bei 80 %.

---

#### M-005 — `_idle_extraction_tasks` ohne Lock
**Datei:** `backend/modules/chat/_orchestrator.py` (~Zeilen 690–730)

**Problem:** Dict wird concurrent von Track- und Trigger-Disconnect-Pfaden
mutiert.

**Empfehlung:**
- **MUSS**: `asyncio.Lock` um alle Mutationen.

---

### Low

#### L-001 — Logging ohne Cost-Strukturdaten
**Empfehlung:** Structured JSON Logs mit `tokens_input`, `tokens_output`,
`provider`, `user_id`, `correlation_id`.

#### L-002 — Keine graceful Degradation bei Redis-Slowness
**Empfehlung:** Lokaler SQLite-Fallback-Queue als Pufferebene.

---

## Was ist bereits gut

1. **Heartbeat-Watchdog-Architektur** — Konzeptionell solide, nur die Race-
   Conditions müssen beseitigt werden (C-002).
2. **In-Flight-Dedup für Memory-Extraction** — Das SET-NX-EX-Pattern ist
   robust gegen Queue-Flooding.
3. **Per-User Job-Serialization** — `asyncio.Lock` pro User verhindert
   doppeltes Handler-Running.
4. **`UnrecoverableJobError`** — Provider-Down wird sofort erkannt und
   skippt die Retry-Chain. Das spart Tokens.
5. **Ack+Del-Pattern** — Commit `148a2ae` hat Zombie-PEL-Leaks behoben.
6. **Event-Bus Fan-Out Matrix** — Explicit, maintainable (`_FANOUT`).
7. **Embedding-Queue Priority** — Queries werden nicht von Bulk-Embeds
   gestarved.
8. **`asyncio.timeout()` um Handler** — Grundlegend solide, auch wenn H-002
   den Upstream-Abbruch fehlt.
9. **Periodic Maintenance Loops** — Session-Cleanup, Auto-Commit und
   Dreaming-Trigger sind wohldurchdacht.

---

## Hard Safeguards (Notbremsen)

Diese Mechanismen sollten existieren, **egal welche anderen Findings noch
offen sind**, weil sie die Tester vor unbeabsichtigten Kosten schützen.

### SG-001 — Per-User Rate-Limit pro Provider
Einfache Redis-INCR-Lösung:

```python
# backend/modules/llm/_rate_limiter.py
async def check_rate_limit(user_id: str, provider_id: str) -> None:
    redis = get_redis()
    key = f"ratelimit:{user_id}:{provider_id}"
    current = await redis.incr(key)
    if current == 1:
        await redis.expire(key, 60)
    limit = _LIMITS.get(provider_id, 1000)
    if current > limit:
        raise RateLimitExceededError(...)
```

### SG-002 — Daily Token-Budget pro User
MongoDB-Collection `user_quotas` mit `{user_id, date, tokens_spent, budget}`.
Vor jedem LLM-Call prüfen, nach jedem Call `$inc`.

### SG-003 — Globaler Kill-Switch via Environment
```python
OLLAMA_CLOUD_EMERGENCY_STOP = os.environ.get("OLLAMA_CLOUD_EMERGENCY_STOP", "false") == "true"
```
Wenn gesetzt, lehnt der LLM-Adapter alle neuen Requests sofort ab. Kann im
Notfall ohne Redeploy aktiviert werden (env-change + reload).

### SG-004 — Extraction-Job-Ratelimit (1 pro 5 min pro User)
Handler-intern mit Redis-Key `extraction:ratelimit:{user_id}`.

### SG-005 — Circuit-Breaker pro Provider
Bei Error-Rate > N pro Fenster → alle neuen Requests für diesen Provider für
M Minuten blockieren.

---

## Release-Checkliste

> Medium/Low items intentionally deferred to a follow-up pass after initial
> test-release feedback.

### Blockiert Release (Critical)
- [x] **C-001** — Globales Rate-Limit (50 Calls/min/User) implementiert (Tasks 4, 8)
- [x] **C-002** — `asyncio.Lock` um Heartbeat/Cancel Dicts (Task 10)
- [x] **C-003** — Cursor-Reset + Retry-Limit im periodic extraction loop (Task 11)
- [x] **C-004** — Atomare Journal-Write + Mark-Extracted (Task 12)
- [x] **H-001** — Token-Length-Check vor Consolidation-LLM-Call (Task 13)
- [x] **H-002** — Exponential Backoff statt fester Retry-Delays (Task 14)
- [x] **SG-001** — Rate-Limiter live (Task 3)
- [x] **SG-002** — Daily Token-Budget live (Tasks 5, 17)
- [x] **SG-003** — Kill-Switch per Env-Variable (Tasks 2, 8)

### Sollte vor Release (High)
- [x] **H-003** — Retry-Loop in `trigger_disconnect_extraction` (Task 15)
- [x] **H-004** — Gutter-Timeout pro Stream-Chunk (Task 16)
- [x] **H-005** — `execution_token` für Idempotenz (Task 12)
- [ ] **M-001** — Memory-Body-Truncation
- [ ] **M-003** — Event-Bus Trim alle 2 min + MAXLEN
- [ ] **M-004** — User-Quota Collection
- [ ] **M-005** — Lock um `_idle_extraction_tasks`
- [x] **SG-004** — Extraction-Ratelimit (Task 11)
- [x] **SG-005** — Circuit-Breaker (Task 6)

### Vor Beta (Medium/Low)
- [ ] **L-001** — Structured JSON Logs mit Cost-Daten
- [ ] **L-002** — Redis-Fallback-Queue
- [ ] **M-002** — Embed-Queue `maxsize`
- [ ] Load-Test: 1 000 concurrent users, 100 extraction jobs/min
- [ ] Chaos-Test: Redis-Restart und Backend-Restart während aktiver Jobs
