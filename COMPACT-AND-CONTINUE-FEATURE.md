# Compact and Continue — Project Brief

**Status:** Draft / Pre-Implementation
**Owner:** Chris
**Erstellt:** 2026-05-01
**Zielrelease:** TBD (nach beta polish)

---

## 1. Vision in einem Satz

Wenn das Kontextfenster vollläuft, soll der User per Knopfdruck den bisherigen Chat
auf einen kompakten Briefing-Text destillieren, die letzten Runden aber 1:1 behalten —
sodass die Konversation nahtlos und tokensparsam weiterläuft, ohne dass der User
Information verliert oder neu starten muss.

## 2. Kernidee

Klassische Compaction (vgl. Claude Codes `/compact`) komprimiert die ganze Konversation
auf ~40 % und ist damit token-ökonomisch immer noch suboptimal. Unser Ansatz:

- **Compact auf 5–10 %** der ursprünglichen Tokens
- **Tail behalten** (letzte _N_ Runden, ungekürzt, mit Tool-Results)
- **Tail-Wahl hybrid**: min 6 Runden _oder_ bis 20 % des Modell-Kontexts — was MEHR ist
- **Knowledge-/Memory-Injektion bleibt** wie gehabt pro Turn (PTI + Memory-XML-Block)
- **User sieht alles** im Chat-UI; **LLM sieht nur ab Checkpoint**
- **Visueller Trenner** im Chat zeigt „hier wurde compacted"
- **Sparkly Button** wird ab 60 % Kontextfüllung aktiv und drängt sich progressiv mit
  steigender Auslastung auf, ohne je automatisch auszulösen

## 3. Was wir aus der Codeanalyse wissen (Anker)

### Backend

- **Chat-Module-Public-API**: `backend/modules/chat/__init__.py` — alle Internals `_`-prefixed
- **Inference-Orchestrator**: `backend/modules/chat/_orchestrator.py:560-599` — `run_inference()`
  baut die Message-History via `repo.list_messages()` + `_filter_usable_history()` +
  `select_message_pairs()` (Token-Budget-basiert)
- **System-Prompt-Builder**: `backend/modules/chat/_prompt_assembler.py:50` — `assemble()`
  schichtet Admin → Model → Persona → Soft-CoT → **Memory (Zeile 114–117)** → Integration-Extensions → User-About-Me. Genau hier hängen wir den Compact-Block ein.
- **LLM-Aufruf**: `backend/modules/llm/__init__.py:140` — `stream_completion()` ist
  Session-agnostisch und nimmt beliebige `CompletionRequest` mit Messages-Liste
- **Job-Vorbild**: `backend/jobs/handlers/_memory_consolidation.py` — exakte
  Blueprint-Struktur (Submit → Build-Prompt → Token-Guard → LLM-Call → Persist → Events)
- **Token-Counter**: `backend/token_counter.py:6-11` — tiktoken cl100k_base, bereits projektweit verwendet
- **Modell-Metadaten**: `ModelMetaDto.context_window` in `shared/dtos/llm.py:18` (immer gesetzt)
- **Session-Context-Metriken**: `ChatSessionDocument` enthält bereits `context_status`,
  `context_fill_percentage`, `context_used_tokens`, `context_max_tokens`
  (`backend/modules/chat/_repository.py:833-856`)

### Frontend

- **Chat-View**: `frontend/src/features/chat/ChatView.tsx:69-1443`
- **Message-Liste**: `frontend/src/features/chat/MessageList.tsx`
- **TimelineEntry-Renderer**: `MessageList.tsx:94-144` — bereits Pattern für `knowledge_search`,
  `web_search`, `tool_call`, `artefact`, `image`. Neuer `kind: 'compacted'` fügt sich nahtlos ein.
- **Context-Pill**: `frontend/src/features/chat/ContextStatusPill.tsx` — zeigt schon
  status/fill/used/max
- **WebSocket-Event-Empfang**: `frontend/src/features/chat/useChatStream.ts:36-150`
- **Mobile-Breakpoint**: `lg:` (Tailwind, 1024px) — wie restlich im Repo
- **Top-Bar-Position**: Desktop `ChatView.tsx:1187+`, Mobile `ChatView.tsx:1222+`

### Shared

- **Topics-Konstanten**: `shared/topics.py` — neue Topics werden hier ergänzt
- **DTOs / Events**: `shared/dtos/`, `shared/events/`

## 4. Datenmodell

### 4.1 Neue Compaction-Checkpoint-Struktur

In `backend/modules/chat/_models.py` ergänzen:

```python
class CompactionCheckpoint(BaseModel):
    id: str                         # UUID
    created_at: datetime
    model_unique_id: str            # welches Modell hat compacted
    summary_markdown: str           # der eigentliche Compact-Text (Markdown)
    last_message_id_before: str     # letzte Message, die im Compact-Source war
    tail_start_message_id: str      # erste Message des Tails
    tokens_before: int              # Tokens des Source-Bereichs (vor Compact)
    tokens_after: int               # Tokens des Compact-Texts
    tail_token_count: int           # Tokens, die im Tail mitgeführt werden
```

Erweiterung von `ChatSessionDocument`:

```python
compaction_checkpoints: list[CompactionCheckpoint] = Field(default_factory=list)
```

**Migrations-Verträglichkeit** (`CLAUDE.md` Hard Rule): Default `[]` → existing Sessions
deserialisieren ohne Fehler. Keine Migration nötig.

### 4.2 Neuer JobType

In `backend/jobs/types.py` (oder wo `JobType` lebt):

```python
class JobType(str, Enum):
    ...
    CHAT_COMPACTION = "chat_compaction"
```

### 4.3 Neue Topics

In `shared/topics.py`:

```python
CHAT_COMPACTION_STARTED = "chat.compaction.started"
CHAT_COMPACTION_PROGRESS = "chat.compaction.progress"
CHAT_COMPACTION_COMPLETED = "chat.compaction.completed"
CHAT_COMPACTION_FAILED = "chat.compaction.failed"
```

### 4.4 Neue Events

In `shared/events/chat.py`:

```python
class ChatCompactionStartedEvent(BaseModel):
    session_id: str
    correlation_id: str
    tokens_before: int
    estimated_tokens_after: int
    tail_message_count: int

class ChatCompactionCompletedEvent(BaseModel):
    session_id: str
    correlation_id: str
    checkpoint: CompactionCheckpoint
    tokens_saved: int
    new_context_fill_percentage: float

class ChatCompactionFailedEvent(BaseModel):
    session_id: str
    correlation_id: str
    error_code: str
    user_message: str
    recoverable: bool
```

## 5. Backend-Flow

### 5.1 Trigger (Frontend → Backend)

User klickt Sparkly Button → WS-Event `chat.compaction.request` mit
`{session_id, correlation_id}`. Handler validiert:

- Session gehört User
- Aktuelle `context_fill_percentage >= 0.50` (untere Schranke; manueller Trigger erlaubt
  auch unter 60 %, aber nicht unter 50 % — sonst macht Compact keinen Sinn)
- Keine laufende Compaction (Idempotenz-Lock im Redis: `compaction:lock:{session_id}`,
  TTL 5 min)

Bei Erfolg: Submit `JobType.CHAT_COMPACTION`. Sofortige Antwort an User: `CHAT_COMPACTION_STARTED`-Event.

### 5.2 Compaction-Job-Handler

Pfad: `backend/jobs/handlers/_chat_compaction.py` — analog zu `_memory_consolidation.py`.

Schritte:

1. **Lade Session + alle Messages** chronologisch
2. **Bestimme Tail**: rückwärts gehen, bis _entweder_ 6 Runden (12 Messages) erreicht _oder_
   20 % des Modell-Kontexts kumuliert sind. Ergebnis: `tail_start_message_id`.
3. **Bestimme Source**: alles vor dem Tail. Wenn ein vorheriger Compaction-Checkpoint
   existiert, beginne erst nach `tail_start_message_id` des Vorgängers (Re-Compact).
4. **Source-Sanitize**: Aus Source-Messages **alle Tool-Roles und Tool-Calls entfernen**.
   `assistant`-Messages, die nur Tool-Calls waren, droppen. (`user`+`assistant`-Inhaltsmessages
   bleiben.)
5. **Source-Token-Guard**: Wenn Source > 70 % des Modell-Kontexts → in Chunks compacten
   (rekursiv, hierarchical summarisation). MVP: einfache Truncierung mit Warnung.
6. **Compaction-Prompt zusammenbauen** (siehe 5.3)
7. **LLM-Call** via `stream_completion()` mit `temperature=0.3`, `max_output_tokens=2000`,
   `source="job:chat_compaction"`. Streaming-Output sammeln (kein Frontend-Streaming —
   User sieht Spinner).
8. **Validate Output**: muss Markdown sein, muss alle Pflicht-Sections enthalten
   (siehe 5.3 Schema). Bei Validierungsfehler: Retry einmalig mit explizitem
   Reminder-Prompt; danach Fail.
9. **Persist**: `CompactionCheckpoint` in Session-Doc anhängen
10. **Event publizieren**: `CHAT_COMPACTION_COMPLETED` mit DTO

### 5.3 Compaction-Prompt-Schema

System-Prompt:

```
You are a conversation-compaction assistant. Below is a transcript of a conversation
between a user and an AI assistant. Your job is to extract a structured briefing
that allows another AI to seamlessly continue this conversation in a new context window.

Output rules:
- Output Markdown only. No preamble, no "I have summarised", no meta-commentary.
- Use the exact section headings shown below, in order.
- Be terse but complete. Aim for 5–10 % of the original token count.
- Preserve the user's language preferences, name, and any established facts about them.
- Quote critical user phrasings verbatim if they carry intent (e.g. preferences, decisions).
- Do not invent information. If a section has no content, write "_(none)_".

Required sections:

## Topic & Goal
What is this conversation about? What is the user trying to achieve?

## Established Facts
Concrete facts, decisions, names, numbers, conclusions reached. Bullet list.

## Open Threads
Questions left unanswered, things the user said they would come back to.

## User Preferences Observed
Communication style, expertise level, language preferences, anything that should
shape how the next AI responds.

## Pending References
Files, URLs, artefacts, tools that the user mentioned and that the next assistant
should know about. Do not paste their content — just reference them by name.

## Tone & Persona Adherence
One sentence on how the persona has been speaking (formal/informal, etc.).
```

User-Prompt (transcript): die Source-Messages als plain-text-rendered Konversation,
prefixed mit `User:` / `Assistant:`. Tool-Roles sind bereits entfernt.

### 5.4 Inference-Slicer (run_inference modifizieren)

In `backend/modules/chat/_orchestrator.py:run_inference()`:

```python
# Pseudo-Code
session = await repo.get_session(session_id)
all_messages = await repo.list_messages(session_id)

if session.compaction_checkpoints:
    latest = session.compaction_checkpoints[-1]
    # Slice: nur Messages ab dem Tail mitschicken
    tail_messages = [m for m in all_messages if m.created_at >= tail_start(latest)]
    history_for_llm = _filter_usable_history(tail_messages)
    compact_text = latest.summary_markdown
else:
    history_for_llm = _filter_usable_history(all_messages)
    compact_text = None
```

Im `_prompt_assembler.assemble()`: wenn `compact_text` vorhanden, als XML-Block ergänzen
(analog Memory):

```xml
<conversation_compact>
The earlier portion of this conversation has been compacted into the briefing below.
Use it as authoritative context. Do not refer to it explicitly unless the user asks
about earlier topics.

[Markdown-Compact-Text]
</conversation_compact>
```

Position: zwischen Memory-Block und Integration-Extensions.

### 5.5 Edit-Schutz vor Compact-Checkpoint

In `handle_chat_edit` (`backend/modules/chat/_handlers_ws.py`): wenn
`message.created_at < tail_start(latest_checkpoint)` → Edit ablehnen mit
`ErrorEvent { error_code: "edit_before_compact", user_message: "Diese Nachricht ist Teil
eines Compact-Checkpoints. Entferne den Checkpoint, um sie zu bearbeiten." }`.

MVP: kein „Checkpoint entfernen"-Pfad — User muss neue Session anfangen, wenn er weit
zurück will. (Erweiterung später, wenn bedarf da ist.)

## 6. Frontend-Flow

### 6.0 Trigger-Modi (User-Setting)

Drei Modi, per-User konfigurierbar, Default **Manual**:

| Modus | Default | Verhalten |
|---|---|---|
| **Manual** | ✓ | Sparkly Button erscheint laut §6.1, User klickt selbst |
| **Suggest** | — | Bei Schwellen-Überschreitung erscheint zusätzlich ein nicht-blockierender Toast mit Ein-Klick-Trigger („Konversation compacten? — Compacten / Später") |
| **Auto** | — | System triggert selbständig, mit 3-s-Cancel-Window (siehe §6.5) |

**Discovery-Pfad**: Nach erfolgreichem **erstem** manuellem Compact einmaliger Dialog
(„Soll das in Zukunft automatisch passieren? [Ja, bei 60 %] [Ja, bei 75 %] [Nein,
manuell] [Frag mich nicht mehr]"). User-Auswahl wird persistiert in
`UserPreferences.compaction_mode` und `UserPreferences.compaction_auto_threshold`.

**Settings-UI** (`Settings → Chat → Auto-Compaction`): Mode-Picker + Threshold-Slider
mit Hinweistext: _„Each automatic compaction sends the older portion of your
conversation to your active LLM provider for summarisation. With BYOK providers
this counts towards your token usage."_ — Kostentransparenz ist wichtig.

### 6.1 Sparkly Button

Position: Desktop-Top-Bar in `ChatView.tsx:1187+`, **rechts neben** `ContextStatusPill`.
Mobile: in der kompakten Indicator-Zeile `ChatView.tsx:1222+` als Icon-only-Pill.

State-abhängige Sichtbarkeit / Animation:

| `context_status` | Button-Zustand |
|---|---|
| green (<60 %) | Versteckt (außer im Settings-Menü als „Manuell compacten") |
| yellow (60–75 %) | Sichtbar, dezent, Tooltip „Konversation compacten?" |
| orange (75–90 %) | Sichtbar, ✨ Sparkle-Animation (subtil pulsierend) |
| red (>90 %) | Sichtbar + Modal-Hint öffnet sich beim ersten Mal („Empfohlen: jetzt compacten") |

Klick öffnet eine kleine Confirmation-Dialog-Card mit:
- aktuellem Token-Stand (z. B. „87.300 / 128.000 Tokens, 68 %")
- geschätztem Resultat („nach Compact: ~4.000 Tokens")
- erklärung in einem Satz („Die letzten 6 Runden bleiben erhalten, alles davor wird
  zu einem Briefing zusammengefasst.")
- Buttons: „Compacten" (primär) / „Abbrechen"

Wenn der Job läuft: Button → Loading-Spinner mit Text „✨ Compacting…", Input-Area
gesperrt mit Overlay „Konversation wird compactet — einen Moment".

### 6.2 Compacted-Marker im Chat

Neuer TimelineEntry-`kind: 'compacted'` in `MessageList.tsx:94-144`. Rendering:

- Horizontaler Trenner mit zentriertem Pill-Label
- Pill: `✨ Compacted · 14:23 · 87k → 4k Tokens`
- Klick öffnet Detail-Drawer mit dem Markdown-Compact-Text (read-only) — der User soll
  sehen können, was das LLM jetzt als „Story so far" hat. Wichtig für Vertrauen.

Visueller Stil: passt zum bestehenden Pill-Vokabular (subtle bg, mono-fontish). Siehe
[inline marker aesthetic memory](file://...) — non-intrusive but present.

### 6.3 Token-Anzeige aktualisieren

Nach erfolgreichem Compact: Backend-Event aktualisiert `context_used_tokens` und
`context_fill_percentage`. `ContextStatusPill` zeigt sofort den neuen Wert.

### 6.5 Auto-Mode Trigger-Logik (Hard Rules)

Auto-Mode darf nur unter folgenden Bedingungen feuern:

1. **Idle-State**: kein laufender Inference-Stream, Input-Field leer, kein
   Send-Pending
2. **Nach** einem `CHAT_STREAM_ENDED`-Event (frühester sinnvoller Trigger-Punkt)
3. **`context_fill_percentage >= user_threshold`** (default 0.60, einstellbar)
4. **Keine** Continuous-Voice-Session aktiv für diese Session
   (siehe `usePhase`-State im Frontend, Backend kennt das via Voice-Phase-Events).
   Während Continuous Voice ist Auto-Compact **hart blockiert** — User redet,
   eine 15-s-Compaction-Pause wäre ein UX-Disaster.
5. Idempotenz-Lock im Redis (siehe §5.1) verhindert ohnehin Doppelung
6. Mindest-Größe wie für Manual: `total_messages > 12 AND total_tokens > 4000`

**Cancel-Window-UX**:

- Bei Trigger-Bedingungen erfüllt → Toast unten oder Inline-Hint im Chat:
  `✨ Compacting in 3s — [Cancel]`
- Cancel-Button innerhalb 3 s → Auto-Compaction wird übersprungen, Modus bleibt
  Auto, nächster Trigger-Versuch frühestens nach nächstem Assistant-Turn
- Wenn User in den 3 s anfängt zu tippen → Auto-Compaction abgebrochen
  (Input-non-empty-Detection)
- Sonst: Compaction startet wie bei Manual-Trigger, gleicher Flow ab §5.2

**Wenn Auto fehlschlägt** (z. B. LLM offline): einmaliges Toast „Auto-Compact
fehlgeschlagen — manuell versuchen?", Auto-Mode bleibt aktiv, kein Endlos-Retry.

**Threshold-Klassen** (vereinfacht für Settings-UI):

| Label | Threshold | Wann sinnvoll |
|---|---|---|
| Conservative | 50 % | Sehr lange Sessions, Token-knapp |
| Balanced | 60 % | Default — guter Kompromiss |
| Aggressive | 75 % | Compact möglichst spät, mehr Tail-Tokens für aktuellen Strang |

### 6.6 WebSocket-Subscriptions

In `useChatStream.ts:handleChatEvent()` neue Topics behandeln:

- `CHAT_COMPACTION_STARTED` → Loading-State, Input-Lock
- `CHAT_COMPACTION_COMPLETED` → Checkpoint in Store hinzufügen, MessageList re-rendert
  mit neuem TimelineEntry, Token-Pill aktualisiert sich
- `CHAT_COMPACTION_FAILED` → Toast mit Retry-Button (Compact ist idempotent dank
  Redis-Lock — Retry ist sicher)

## 7. Edge Cases & Open Questions

### 7.1 Geklärt

- **Cache-Prefix-Bruch**: einmaliger Cost, danach neuer Prefix wird wieder warm.
  Akzeptabel.
- **Modell-Wechsel mid-session**: Compact ist Plain-Text → überlebt Modell- und
  Provider-Wechsel anstandslos.
- **User editiert Message vor Compact**: blockieren mit klarer UI-Begründung.
- **Tool-Results im Tail**: bleiben drin (sonst halluziniert das LLM).
- **Tool-Results im Source**: raus (Token-Sparen, in Summary nur erwähnt).

### 7.2 Offen / zu klären

1. **Re-Compaction-Strategie**: Beim zweiten Compact — frisst der neue Compact den
   alten _und_ die dazwischenliegenden Runden (single-checkpoint, alter ist obsolet)?
   Oder Append-only-Stack (alter Compact bleibt, neuer Compact deckt nur den Bereich
   seither ab)? **Vorschlag MVP: alter wird ersetzt** (single rolling checkpoint),
   einfacher und für 95 % der Fälle ausreichend. Stack-Modell als Phase 2 wenn
   Datenverlust spürbar wird.
2. **Soll der User den Compact-Text bearbeiten können?** Das wäre mächtig
   („Korrigiere die KI-Zusammenfassung"), aber riskiert Inkonsistenz.
   **Vorschlag MVP: nein, read-only**, Phase 2 evtl. inline-edit.
3. **Was passiert bei „voice continuous" Sessions?** Lange Voice-Sessions sind nach
   [continuous voice memory](file://...) der primäre Long-Session-Modus. Wir müssen
   prüfen, ob der Compact-Trigger sinnvoll während laufender Voice-Session ist
   (vermutlich nein — User kann nicht klicken). Idee: nach Session-Ende vorschlagen.
4. **Untergrenze für Compact-Trigger**: ab 50 % manuell? Oder schon ab 30 %, damit
   User auch einen „Frischstart-Compact" für ein neues Thema machen kann?
   **Vorschlag**: ab 30 % manuell zugänglich (über Menü), ab 60 % im UI prominent.
5. **Compact-Validation**: was, wenn das LLM ein kaputtes Markdown produziert?
   Ein Retry, dann Fail. Reicht das? Sollte ein zweites Modell als Fallback
   eingeschlagen werden? **Vorschlag MVP**: ein Retry, dann Fail mit `recoverable: true`,
   User kann manuell nochmal triggern.
6. **Tail-Wahl für ganz kurze Sessions**: Was, wenn die ganze Session nur 6 Runden
   hat? → Compact macht keinen Sinn. Mindest-Source-Größe? **Vorschlag**: erst ab
   `total_messages > 12 AND total_tokens > 4000` Trigger anbieten. Sonst Button
   ausgegraut mit Tooltip „Konversation noch zu kurz".
7. **Backwards-compat für bestehende Sessions ohne Field**: Pydantic-Default `[]`
   reicht (siehe 4.1). Verifizieren mit einer alten Session aus Staging.
8. **Auto-Mode + Modell-Wechsel mid-session**: Wenn der User auf ein Modell mit
   _kleinerem_ Kontextfenster wechselt (z. B. von 128k auf 8k), kann die Session
   sofort über Threshold sein. Sollte Auto sofort triggern oder erst nach
   nächstem Turn? **Vorschlag**: erst nach nächstem `CHAT_STREAM_ENDED`, nie
   spontan beim Modell-Wechsel selbst — der User würde sonst „warum compactet
   das jetzt einfach so?" denken.
9. **Auto-Mode in offline-Sessions**: Bei lokalen Ollama-Modellen, die offline
   sind, soll Auto-Mode pausieren (statt den User zu nerven). Detect-Methode?
   `connection_status` aus dem LLM-Modul abfragen.
10. **Persistierter Threshold pro Session vs. pro User**: Vorschlag MVP nur per-User.
    Wenn jemand pro Session andere Schwellen will, ist das später nachrüstbar.

## 8. Manual Verification Plan

(Siehe [manual test sections in specs memory](file://...) — jeder Spec bekommt explizite
manuelle Verifikation am echten Gerät.)

### 8.1 Glücklicher Pfad — Desktop

1. Lange Konversation anlegen (Token-Counter via tiktoken vergrößern bis ~70 %)
2. Sparkly Button erscheint mit pulsierender Animation
3. Klick → Confirm-Card zeigt Token-Vorhersage
4. „Compacten" → Spinner, Input gesperrt
5. Nach 5–20 s: Compacted-Marker erscheint im Chat, Token-Pill springt auf ~10 %
6. Folge-Frage stellen: LLM antwortet kohärent unter Bezug auf Tail _und_ kann auf
   Frage „was haben wir vorhin besprochen?" mit Inhalt aus dem Compact antworten
7. Klick auf Compacted-Pill → Drawer zeigt Compact-Markdown — visuell nachvollziehbar

### 8.2 Edge — Mobile

1. Gleiche Konversation auf Phone
2. Mobile Indicator-Zeile zeigt Compact-Icon-Pill bei orange/red
3. Klick öffnet Bottom-Sheet (statt Confirm-Card)
4. Compact läuft → Mobile-Spinner-Overlay
5. Compacted-Marker korrekt zentriert, mit lesbarem Touch-Target

### 8.3 Edge — Edit vor Compact

1. Compact ausführen
2. Versuch, eine Nachricht aus dem Source-Bereich zu editieren
3. UI lehnt mit klarer Meldung ab — kein crashende Backend-Reaktion

### 8.4 Edge — Re-Compaction

1. Nach erstem Compact die Session weiter füllen, bis erneut 70 %
2. Zweiten Compact triggern
3. Erstes Compacted-Marker verschwindet (oder bleibt? — siehe Open Q1)
4. Neuer Compact-Marker an passender Stelle
5. Beide Compact-Texte sind im Drawer ansehbar

### 8.5 Edge — Provider-Wechsel mit aktivem Compact

1. Session mit Ollama-Modell + Compact
2. Modell-Wechsel auf xAI-Modell mit anderem Token-Budget
3. Folge-Antwort referenziert weiterhin korrekt frühere Punkte aus Compact

### 8.6 Edge — Sehr kurze Konversation

1. Neue Session mit nur 4 Runden
2. Manuell Compact triggern wollen → Button greyed out mit korrektem Tooltip

### 8.7 Edge — Compaction-Fehler

1. LLM-Endpoint absichtlich brechen (Test-Key ungültig)
2. Compact triggern → `CHAT_COMPACTION_FAILED`-Event
3. Toast zeigt Fehlermeldung, Retry-Button funktioniert
4. Lock im Redis ist nach Fehler freigegeben (TTL oder explizites Release)

### 8.8 Auto-Mode — Glücklicher Pfad

1. Auto-Mode in Settings auf „Bei 60 %" stellen
2. Konversation füllen bis 60 %
3. Letzte Assistant-Antwort fertig streamen → Toast erscheint mit
   `✨ Compacting in 3s — [Cancel]`
4. 3 s warten ohne Eingabe → Compaction läuft, Compacted-Marker erscheint,
   Token-Pill springt
5. Folge-Frage stellen — alles funktioniert nahtlos

### 8.9 Auto-Mode — Cancel-Pfad

1. Wie 8.8 Schritte 1–3
2. Innerhalb 3 s den Cancel-Button klicken → Toast verschwindet,
   keine Compaction läuft
3. Nächste Assistant-Antwort wieder über Threshold → Toast erscheint erneut
   (Auto-Mode ist nicht deaktiviert, nur dieser eine Trigger übersprungen)

### 8.10 Auto-Mode — Type-While-Counting-Down

1. Wie 8.8 Schritte 1–3
2. Während des 3-s-Countdowns ins Input-Feld tippen → Toast verschwindet,
   keine Compaction läuft (Input-non-empty-Detection)
3. User kann normal Message senden, kein Compact dazwischen

### 8.11 Auto-Mode — Continuous-Voice-Hard-Block

1. Auto-Mode aktiv, Threshold 60 %
2. Continuous Voice starten, lange Voice-Konversation bis 70 %
3. Verifizieren: **kein** Auto-Compact-Trigger während Voice
4. Voice-Session beenden → erst _danach_ darf Auto-Compact triggern
   (frühestens nach nächstem Text-Assistant-Turn)

### 8.12 Auto-Mode — Modell-Wechsel zu kleinerem Kontext

1. Session bei 30 % Kontext mit 128k-Modell
2. Wechsel zu 8k-Modell → Session jetzt z. B. bei 480 % (Display
   handhabt das wie?)
3. Verifizieren: kein spontaner Auto-Trigger durch den Wechsel selbst
4. Nächste Message senden → Stream endet → _jetzt_ darf Auto-Compact
   triggern (mit dem 8k-Modell als Source-Modell)

### 8.13 Discovery-Dialog

1. Frischer User, Auto-Mode = default (Off/Manual)
2. Manuell ersten Compact erfolgreich durchführen
3. Verifizieren: Discovery-Dialog erscheint genau einmal
4. „Nein, manuell" wählen → Dialog erscheint nie wieder
5. Mit anderem User: „Ja, bei 60 %" wählen → Auto-Mode persistiert,
   Settings reflektieren das, beim zweiten Compact kein Dialog mehr

### 8.14 Backwards-Compat

1. Eine bestehende Session aus dem Staging-Dump laden (vor diesem Feature angelegt)
2. Session lädt ohne Pydantic-Fehler (`compaction_checkpoints: []`)
3. Compact funktioniert auf dieser Session normal

## 9. Implementierungsreihenfolge (Vorschlag)

1. **Shared-Contracts**: DTOs, Events, Topics, JobType — komplett, bevor Code geschrieben wird
2. **Backend-Datenmodell**: `ChatSessionDocument` erweitern, `CompactionCheckpoint` einführen
3. **Job-Handler `_chat_compaction.py`**: kopier-und-anpassen aus `_memory_consolidation.py`
4. **Inference-Slicer in `run_inference`**: Tail-Bestimmung + Compact-Block-Injektion in
   System-Prompt
5. **Edit-Schutz**: kleiner Guard in `handle_chat_edit`
6. **WS-Handler `chat.compaction.request`**: Trigger-Endpoint inkl. Redis-Lock
7. **Frontend-Store**: `compaction_checkpoints` im Session-State
8. **Frontend-Sparkly-Button**: Top-Bar, Confirm-Card, Loading-States
9. **Frontend-Compacted-Marker**: TimelineEntry-`kind: 'compacted'` + Drawer
10. **Manual-Verification-Run** auf Desktop und Mobile

Phase 1 = 1–8. Phase 2 = 9–10. Polish + Edge-Cases = ein zusätzlicher Tag.

## 10. Was wir NICHT bauen (MVP-Scope-Lock)

- Compact-Text-Bearbeitung durch User (read-only im MVP)
- Compact-Stack (single rolling checkpoint im MVP)
- Hierarchical/multi-step Compaction für Mega-Sessions (>70 % Modell-Kontext)
  → MVP: Truncierung mit Warnung
- Cross-Session-Compaction („alle meine Chats zusammenfassen") — eigenes Feature
- Compaction während laufender Continuous-Voice-Session (hart blockiert, siehe §6.5)
- Pro-Session-Override des Auto-Modus (nur per-User-Preference im MVP — wenn ein
  User pro Session andere Einstellungen will, ist das ein Phase-2-Wunsch)

**Im MVP enthalten** (war ursprünglich raus, jetzt drin):

- Auto-Mode + Suggest-Mode mit Hard-Rules nach §6.5
- Discovery-Dialog nach erstem manuellem Compact

Diese Punkte landen ggf. in einem Phase-2-Brief, wenn das MVP belastbare Tester-Signale gibt.

---

## Review-Notizen

_Hier ergänzen wir Notizen, wenn wir den Brief in ein paar Tagen erneut durchgehen,
bevor die Implementierung startet._

- [ ] Open-Question-Liste durchgehen, Entscheidungen treffen
- [ ] Datenmodell-Felder gegen `_models.py` Stil noch einmal abgleichen
- [ ] Token-Schwellen (60/75/90 %) gegen reale Konversations-Nutzung kalibrieren
- [ ] UX-Mock vom Sparkly-Button erstellen, bevor Frontend-Code beginnt
