# Mistral Adapter — Kuratierte Modellliste, Reasoning-Parser, Test-Endpoint

**Status:** Draft
**Date:** 2026-05-14
**Author:** Chris (with Claude)
**Drives:** Kuration der Mistral-Modellliste (Small 4, Medium 3.5, Large 3),
korrekter Reasoning-Stream-Parser für Mistral-spezifische Thinking-Blocks,
Connection-Validierungs-Endpoint analog xAI.

## Motivation

Wir konsolidieren den Mistral-Adapter im Rahmen unseres Programms "wir
kuratieren, dafür wird alles besser" — analog zu dem, was wir bereits bei xAI
getan haben (siehe `2026-05-11-xai-grok-4-3-first-class-design.md`).

Mistral hat in den letzten Wochen stark konsolidiert:

- **Mistral Small 4** (intern `mistral-small-2603`, slug `mistral-small-latest`)
  ist das aktuelle sparse-MoE Allrounder-Modell und ersetzt die bisherigen
  Linien "Mistral Small Creative", "Devstral", "Codestral", "Magistral" und
  "Ministral". Reasoning-fähig.
- **Mistral Medium 3.5** (intern und slug beide `mistral-medium-3-5`) ist
  "das Gleiche in dense" und ersetzt das alte Mistral Medium 3.4. **Wichtig:**
  `mistral-medium-latest` zeigt aktuell noch die alte Version
  (`mistral-medium-2508`) und ist damit für uns ungeeignet.
- **Mistral Large 3** (intern `mistral-large-2512`, slug `mistral-large-latest`)
  ist das Flagship für lechats Cowork-Modus. Älterer architektonischer Ansatz
  (657B dense), aber kein Reasoning. Bei Mistral ungewöhnlich stark im
  Vision-Bereich — soll daher gezielt als "substitute vision model" erhalten
  bleiben.

Das aktuelle Verhalten — dynamisches Auflisten **aller** Modelle aus
`/v1/models` mit Dedup über das Mistral-`name`-Feld — ist nicht mehr
zeitgemäß: User sehen sonst 30+ Modelle (Magistral, Codestral, Devstral,
Ministral-3b/8b/14b, mehrere Mistral-Medium-Datestamps), von denen die
Mehrzahl entweder verschmolzen wurde oder nicht zu unserem Use-Case passt.
Eine kuratierte 3-Modell-Liste mit gepflegten Display-Namen und korrekten
Reasoning-/Tool-/Vision-Capabilities ist die saubere Lösung.

Zusätzliche Befunde aus der API-Probe (gegen `https://api.mistral.ai/v1`,
2026-05-14):

1. **Reasoning ist binär.** `mistral-small-4` und `mistral-medium-3-5`
   akzeptieren `reasoning_effort` nur in den Stufen `"high"` und `"none"`.
   `"low"`/`"medium"` werden mit HTTP 400 abgelehnt:
   `reasoning_effort='low' is not supported for this model. Must be one of
   (<ReasoningEffort.none: 'none'>, <ReasoningEffort.high: 'high'>)`. Daraus
   folgt: Mistral-Reasoning ist kein Bucket-Selector, sondern ein Toggle.

2. **Reasoning-Stream-Format ist proprietär.** Mistral folgt bei Reasoning
   **nicht** dem OpenAI-Schema (`delta.reasoning_content`), sondern packt
   Thinking-Blocks in `delta.content`, welches in dem Fall ein Array typisierter
   Items ist statt eines Strings:

   ```json
   "delta": {"content": [
     {"type": "thinking",
      "thinking": [{"type": "text", "text": "Okay, der Benutzer fragt …"}],
      "closed": true},
     {"type": "text", "text": "OK"}
   ]}
   ```

   Bei `reasoning_effort="none"` und bei Modellen ohne Reasoning ist
   `delta.content` weiterhin ein einfacher String — `delta.content` ist also
   **polymorph**. Der heute eingecheckte `_chunk_to_events`-Parser im
   Mistral-Adapter erwartet ausschließlich `delta.reasoning_content` und einen
   String-`content`. Damit wird Reasoning bei Small 4 / Medium 3.5 **nicht
   erkannt**: das Thinking-Array würde als String-Content an die UI
   weitergegeben.

3. **Mistral Large 3 unterstützt Tool-Calls.** Mistrals eigene API-Metadaten
   setzen `function_calling: true`, und Live-Probe bestätigt es: ein einfacher
   Test-Tool-Call (`get_weather`) wird sauber als `finish_reason: "tool_calls"`
   plus `tool_calls[]` zurückgegeben. Eine Model-Card-Behauptung "Large 3
   kann keine Tools" stimmt nicht mit dem realen Verhalten überein.

4. **Mistral-Content-Filter scheint sehr lax.** Eine klar policy-violating
   Probe (vollständige Phishing-E-Mail im Namen einer Bank) wird sowohl von
   Large 3 als auch Small 4 anstandslos generiert, `finish_reason: "stop"`,
   `refusal: null`. In der Praxis wird der `finish_reason in {"content_filter",
   "refusal"}`-Pfad bei Mistral also vermutlich selten bis nie feuern. Wir
   behalten ihn als robusten Default-Pfad.

## Scope

**In Scope:**

- Hartkodierte Modellliste `_MISTRAL_MODELS` mit drei Einträgen
  (`mistral-small-4`, `mistral-medium-3-5`, `mistral-large-3`). Display-Namen
  und Capability-Flags zentral gepflegt.
- `fetch_models()` liefert nicht mehr die dynamische `/v1/models`-Liste,
  sondern emittiert nur die kuratierten Einträge (analog
  `XaiHttpAdapter.fetch_models`). Der bestehende `_dedup_models`-Code wird
  entfernt.
- `_build_chat_payload()` mappt `request.extras.reasoning_mode` auf
  `reasoning_effort` (`"on" → "high"`, `"off" → "none"`) für Small 4 und
  Medium 3.5. Large 3 bekommt keinen Reasoning-Parameter (kein Reasoning).
- Reasoning-Stream-Parser-Fix: neue Helper-Funktion
  `_translate_delta_content(content)` zerlegt polymorphes `delta.content`
  in `(visible_text, thinking_text)`. `_chunk_to_events` emittiert
  entsprechend `ContentDelta` und/oder `ThinkingDelta`.
- Fallback für Legacy-Pins: wenn `_build_chat_payload` ein unbekanntes
  `model_id` bekommt (z.B. `magistral-medium-latest` aus einer alten
  Persona), Warning loggen und auf `mistral-medium-3-5` umlenken — analog
  xAI's grok-4.3-Fallback.
- `model_capabilities.yaml`-Einträge für `(mistral_http, mistral-small-4)`
  und `(mistral_http, mistral-medium-3-5)`: `kind: optional`, `default_on:
  true`, **kein** `effort`-Bucket. `(mistral_http, mistral-large-3)` bleibt
  yaml-frei; `capability_hint` deckt es konservativ ab.
- `capability_hint()`-Methode im Adapter, die für die drei kuratierten
  `model_id`s die korrekten Capabilities liefert (analog xAI).
- Connection-Validierungs-Endpoint: `_build_adapter_router()` mit einer
  einzigen Route `POST /test`, die `GET /v1/models` mit dem Connection-Key
  pingt und Status (`valid` / `failed`) plus optional `error` ins
  Connection-Doc schreibt. `LlmConnectionUpdatedEvent` wird publiziert.
- Tests für die neuen Pfade.

**Explizit nicht in Scope:**

- Keine `templates()` oder `config_schema()` für Mistral. Mistral bleibt
  strukturell wie heute angebunden (BYOK via Premium-Provider-Pfad). Auch
  bei xAI ist heute die User-API-Key-Eingabe der einzige unterstützte Pfad —
  Spec greift den Auth-Flow nicht an.
- Kein Driver-Layer für Mistral. Wire-Format ist (mit Ausnahme der
  thinking-Blocks) Standard-OpenAI-SSE, das im Adapter sauber handhabbar
  ist.
- Keine OpenAI-Compat-SSE-Helper-Extraktion. Das ist eine eigene
  Aufräumaktion nach dem 3. Adapter (siehe Memory
  `project_openai_compat_refactor` — separater Schritt, vermutlich nach
  nano-gpt).
- Keine Erweiterung der Mistral-Modellliste auf "Mistral-Modelle bei anderen
  Anbietern" (OpenRouter, nano-gpt, etc.). Das ist ein gewollter zweiter
  Schritt — Ziel des aktuellen Pakets ist gezielt die direkte
  Mistral-API-Anbindung, um auch in Richtung Mistral selbst Feedback und
  Kooperation zu signalisieren.
- Keine Anpassungen am Refusal-Pfad. Mistral schickt heute kein
  `finish_reason: content_filter` (siehe Befund 4 oben); die bestehende
  Logik bleibt als robuster Default drin.
- Keine Image-Generation. Mistral hat das nicht.

## Detailliertes Design

### Kuratierte Modellliste

Analog `_XaiModelEntry` legen wir ein `_MistralModelEntry`-Dataclass an
und eine Modul-Konstante `_MISTRAL_MODELS`:

```python
@dataclass(frozen=True)
class _MistralModelEntry:
    model_id: str            # "schöne" interne ID, persona-stabil
    upstream_slug: str       # was wir tatsächlich an Mistral schicken
    display_name: str
    context_window: int
    has_reasoning: bool      # Toggle high/none
    supports_vision: bool
    supports_tool_calls: bool
    first_class_support: bool


_MISTRAL_MODELS: tuple[_MistralModelEntry, ...] = (
    _MistralModelEntry(
        model_id="mistral-small-4",
        upstream_slug="mistral-small-latest",
        display_name="Mistral Small 4",
        context_window=262_144,
        has_reasoning=True,
        supports_vision=True,
        supports_tool_calls=True,
        first_class_support=True,
    ),
    _MistralModelEntry(
        model_id="mistral-medium-3-5",
        upstream_slug="mistral-medium-3-5",
        display_name="Mistral Medium 3.5",
        context_window=262_144,
        has_reasoning=True,
        supports_vision=True,
        supports_tool_calls=True,
        first_class_support=True,
    ),
    _MistralModelEntry(
        model_id="mistral-large-3",
        upstream_slug="mistral-large-latest",
        display_name="Mistral Large 3",
        context_window=262_144,
        has_reasoning=False,
        supports_vision=True,
        supports_tool_calls=True,
        first_class_support=False,
    ),
)

_MISTRAL_MODELS_BY_ID: dict[str, _MistralModelEntry] = {
    m.model_id: m for m in _MISTRAL_MODELS
}
```

Begründungen:

- **`model_id` vs `upstream_slug`**: Wir entkoppeln den User-stabilen
  Identifier (`mistral-small-4`) vom Mistral-Slug (`mistral-small-latest`).
  Wenn Mistral nächste Saison den Slug auf `mistral-small-5` oder eine
  Variante umstellt, ändern wir nur die `upstream_slug`-Spalte; Personas
  bleiben funktionsfähig. Gleichzeitig liest sich der Persona-Eintrag schön
  als `mistral:mistral-small-4` (Format `<connection_slug>:<model_slug>`,
  siehe INS-019).
- **`first_class_support=True`** nur für Small 4 und Medium 3.5: diese
  sind aktuelle Flagships mit Reasoning und gezielt verifizierter
  Capability-Story. Large 3 ist nach deiner eigenen Einordnung ein
  "altmodisches" Modell und behält den first-class-Badge nicht.
- **`context_window=262_144`**: empirisch über `/v1/models.max_context_length`
  bestätigt. Konsistent für alle drei Modelle.

### `fetch_models()`

```python
async def fetch_models(self, c: ResolvedConnection) -> list[ModelMetaDto]:
    from backend.modules.llm._capabilities import resolve_capabilities
    metas: list[ModelMetaDto] = []
    for entry in _MISTRAL_MODELS:
        resolved = resolve_capabilities(
            adapter_type=self.adapter_type,
            model_id=entry.model_id,
            adapter=self,
        )
        metas.append(ModelMetaDto(
            connection_id=c.id,
            connection_display_name=c.display_name,
            connection_slug=c.slug,
            model_id=entry.model_id,
            display_name=entry.display_name,
            context_window=entry.context_window,
            reasoning=resolved.reasoning,
            tools=resolved.tools,
            first_class_support=resolved.first_class_support,
            supports_vision=entry.supports_vision,
            supports_tool_calls=entry.supports_tool_calls,
            is_deprecated=False,
            billing_category="pay_per_token",
        ))
    return metas
```

Kein HTTP-Call nach `/v1/models` mehr in diesem Pfad. Das alte
`_dedup_models` und der `httpx.get`-Block entfallen.

### `capability_hint()`

```python
def capability_hint(self, model_id: str):
    from backend.modules.llm._capabilities import CapabilityHint
    entry = _MISTRAL_MODELS_BY_ID.get(model_id)
    if entry is None:
        return None
    reasoning_kind: Literal["no_reasoning", "optional"] = (
        "optional" if entry.has_reasoning else "no_reasoning"
    )
    return CapabilityHint(
        reasoning=ReasoningCapability(
            kind=reasoning_kind,
            default_on=entry.has_reasoning,
        ),
        tools=ToolCapability(
            supported=entry.supports_tool_calls,
            exclusive_with_reasoning=False,
        ),
        first_class_support=entry.first_class_support,
    )
```

`model_capabilities.yaml`-Einträge für Small 4 und Medium 3.5 dienen als
**Override** des Hints (gleiches Pattern wie GLM-5 / Claude-via-OR). Large 3
braucht keinen YAML-Eintrag, weil der Hint bereits "no_reasoning + tools"
liefert.

YAML-Einträge:

```yaml
  # Mistral native — Small 4 und Medium 3.5 mit binärem
  # reasoning_effort (high/none). Kein Bucket-Selector — der UI-Toggle
  # mappt direkt auf high/none im Adapter.
  - adapter: mistral_http
    pattern: "mistral-small-4"
    reasoning:
      kind: optional
      default_on: true
    tools: { supported: true, exclusive_with_reasoning: false }

  - adapter: mistral_http
    pattern: "mistral-medium-3-5"
    reasoning:
      kind: optional
      default_on: true
    tools: { supported: true, exclusive_with_reasoning: false }
```

### `_build_chat_payload()`

```python
def _build_chat_payload(request: CompletionRequest) -> dict:
    entry = _MISTRAL_MODELS_BY_ID.get(request.model)
    if entry is None:
        _log.warning(
            "Mistral: unknown model_id=%r in CompletionRequest; "
            "falling back to mistral-medium-3-5",
            request.model,
        )
        entry = _MISTRAL_MODELS_BY_ID["mistral-medium-3-5"]

    payload: dict = {
        "model": entry.upstream_slug,
        "stream": True,
        "stream_options": {"include_usage": True},
        "messages": [_translate_message(m) for m in request.messages],
    }
    if entry.has_reasoning:
        payload["reasoning_effort"] = (
            "high" if request.extras.reasoning_mode == "on" else "none"
        )
    if request.temperature is not None:
        payload["temperature"] = request.temperature
    if request.tools:
        payload["tools"] = [
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description,
                    "parameters": t.parameters,
                },
            }
            for t in request.tools
        ]
    return payload
```

Hinweise:

- **`request.extras.reasoning_effort` wird ignoriert.** Das Feld existiert
  in `CompletionRequest`, ist aber für Mistral irrelevant (kein
  Bucket-Selector). Den UI-Toggle steuert ausschließlich `reasoning_mode`.
- **Legacy-Fallback auf `mistral-medium-3-5`**: ein User mit alter Persona
  (`mistral:magistral-medium-latest`, `mistral:codestral-latest`, etc.) wird
  silent auf Medium 3.5 umgelenkt. Warning ist im Log, kein Crash.

### Reasoning-Stream-Parser

Neue Helper-Funktion:

```python
def _translate_delta_content(content: object) -> tuple[str, str]:
    """Return (visible_text, thinking_text) from Mistral's polymorphic
    delta.content.

    Mistral bricht aus dem OpenAI-Schema aus: bei aktivem Reasoning ist
    delta.content eine Liste typisierter Items, sonst ein String. Wir
    folden visible-text-Fragmente und thinking-text-Fragmente getrennt
    zusammen, sodass _chunk_to_events ContentDelta und ThinkingDelta
    sauber emittieren kann.
    """
    if isinstance(content, str):
        return content, ""
    if not isinstance(content, list):
        return "", ""
    visible: list[str] = []
    thinking: list[str] = []
    for item in content:
        if not isinstance(item, dict):
            continue
        kind = item.get("type")
        if kind == "text":
            text = item.get("text")
            if isinstance(text, str):
                visible.append(text)
        elif kind == "thinking":
            for inner in item.get("thinking") or []:
                if not isinstance(inner, dict):
                    continue
                if inner.get("type") == "text":
                    text = inner.get("text")
                    if isinstance(text, str):
                        thinking.append(text)
        # andere Item-Types (z.B. zukünftige tool-call-Repräsentation) werden
        # bewusst ignoriert — tool_calls kommt bei Mistral als delta.tool_calls
        # separat, nicht inline im content.
    return "".join(visible), "".join(thinking)
```

`_chunk_to_events` wird angepasst:

```python
visible, thinking = _translate_delta_content(delta.get("content"))
if thinking:
    events.append(ThinkingDelta(delta=thinking))
if visible:
    events.append(ContentDelta(delta=visible))

# Bestehender reasoning_content-Pfad bleibt als Fallback, falls Mistral
# dieses OpenAI-Feld in einer zukünftigen API-Version doch noch einführt:
oai_reasoning = delta.get("reasoning_content") or ""
if oai_reasoning:
    events.append(ThinkingDelta(delta=oai_reasoning))
```

`delta.tool_calls` bleibt unverändert (gleicher Code wie heute, gleiches
Format wie xAI/OpenAI). `usage`-Chunk und `finish_reason`-Logik
unverändert.

### Test-Endpoint

Vorbild ist `XaiHttpAdapter._build_adapter_router()`. Wir kopieren das
Muster minimal angepasst — keine Image-Generation-Route, nur `/test`:

```python
@classmethod
def router(cls) -> APIRouter:
    return _build_adapter_router()


def _mistral_repo_factory():
    """Default factory — returns a ConnectionRepository backed by the live DB.
    Defined at module level so tests can monkeypatch it.
    """
    from backend.database import get_db
    from backend.modules.llm._connections import ConnectionRepository
    return ConnectionRepository(get_db())


def _build_adapter_router() -> APIRouter:
    from datetime import UTC, datetime

    import backend.modules.llm._adapters._mistral_http as _self
    from backend.modules.llm._connections import ConnectionRepository
    from backend.modules.llm._resolver import resolve_connection_for_user
    from backend.ws.event_bus import EventBus, get_event_bus
    from shared.events.llm import LlmConnectionUpdatedEvent
    from shared.topics import Topics

    router = APIRouter()

    @router.post("/test")
    async def test_connection(
        c: ResolvedConnection = Depends(resolve_connection_for_user),
        event_bus: EventBus = Depends(get_event_bus),
        repo=Depends(lambda: _self._mistral_repo_factory()),
    ) -> dict:
        url = c.config["url"].rstrip("/")
        api_key = c.config.get("api_key") or ""
        valid = False
        error: str | None = None
        try:
            async with httpx.AsyncClient(timeout=_PROBE_TIMEOUT) as client:
                resp = await client.get(
                    f"{url}/models",
                    headers={"Authorization": f"Bearer {api_key}"},
                )
                if resp.status_code in (401, 403):
                    error = "API key rejected by Mistral"
                elif resp.status_code != 200:
                    error = f"Mistral returned {resp.status_code}"
                else:
                    valid = True
        except Exception as exc:  # noqa: BLE001
            error = str(exc)

        updated = await repo.update_test_status(
            c.user_id, c.id,
            status="valid" if valid else "failed",
            error=error,
        )
        if updated is not None:
            await event_bus.publish(
                Topics.LLM_CONNECTION_UPDATED,
                LlmConnectionUpdatedEvent(
                    connection=ConnectionRepository.to_dto(updated),
                    timestamp=datetime.now(UTC),
                ),
            )
        return {"valid": valid, "error": error}

    return router
```

Mistrals `/v1/models` verlangt einen Authorization-Header — das ist
empirisch bestätigt. Die Probe ist deshalb ein guter Validierungs-Hammer:
`200 → valid`, `401/403 → bad key`, Rest → upstream-Fehler.

### Bereinigung des File-Header-Kommentars

Der heute eingecheckte Header-Kommentar im Mistral-Adapter spricht von
"Premium-only adapter: not user-creatable" und impliziert eine
Admin-Konfiguration. Das ist missverständlich — bei uns ist alles BYOK
(per-User encrypted credential, kein admin-shared key). Wir ersetzen den
Kommentar durch eine kurze Beschreibung des aktuellen Anbindungspfads
ohne irreführende Begriffe.

## Migration

- **Datenbank:** keine Schema-Änderungen. `Connection`-Dokumente bleiben
  unverändert. `model_id`-Strings in Personas werden _silent migriert_
  durch den Legacy-Fallback in `_build_chat_payload` — kein Backfill nötig.
- **Frontend:** der Modell-Picker zeigt nur noch drei Mistral-Einträge.
  Personas, die heute auf z.B. `mistral:magistral-medium-latest` zeigen,
  laufen weiter (Fallback auf `mistral-medium-3-5`), erscheinen aber im
  Picker als "Unbekanntes Modell — bei Bearbeitung wird auf Mistral
  Medium 3.5 umgestellt". Das ist konsistent mit `feedback_no_rube_goldberg_for_legacy_data`
  — wir fixen das Problem über User-Workflow (Persona neu auswählen),
  nicht über eine Cleanup-Wave.
- **Redis-Cache:** Model-Listen-TTL ist 30 Min. Innerhalb dieses Fensters
  zeigen Caches die alte 30+-Modell-Liste. Akzeptabel — nach maximal 30
  Minuten ist die Liste reorganisiert.

## Open Questions

Keine.

## Manual verification

Vor dem Mergen auf realem Mistral-API-Key auf einem Beta-Build verifizieren
(siehe `feedback_manual_test_sections_in_specs`):

1. **Modell-Picker zeigt genau drei Mistral-Einträge:** Mistral Small 4,
   Mistral Medium 3.5, Mistral Large 3 — keine Magistral/Codestral/Devstral/
   Ministral mehr.
2. **Connection-Test:** Mistral-Connection in den Settings öffnen, "Verbindung
   testen" klicken. Status muss auf "valid" wechseln. Mit absichtlich
   ungültigem Key wechselt er auf "failed" mit lesbarer Fehlermeldung.
3. **Reasoning ein, Small 4:** Persona mit Mistral Small 4 + Reasoning=on,
   Prompt "Was ist 2+2? Denke kurz nach." → Thinking-Pill erscheint im Chat
   mit lesbarem Reasoning-Text, Antwort darunter ist eine kurze Antwort
   wie "4". Token-Anzeige zeigt sowohl Input- als auch Reasoning-Tokens.
4. **Reasoning aus, Small 4:** gleiche Persona, Reasoning=off, gleicher
   Prompt. Antwort kommt ohne Thinking-Pill — kein leerer Thinking-Block
   in der UI.
5. **Tool-Call, Large 3:** Persona mit Mistral Large 3 + Tool-Group
   "Web/Search" aktiv, Prompt "Wie ist das Wetter in Wien?". Tool-Call
   wird ausgelöst, Antwort kommt nach Tool-Roundtrip.
6. **Vision, Large 3:** Persona mit Mistral Large 3, Bild hochladen +
   "Was siehst du?". Bild-Beschreibung kommt zurück.
7. **Legacy-Persona:** Falls noch eine Persona existiert, die ein altes
   Mistral-Modell (z.B. `magistral-medium-latest`) gepinnt hat — Chat
   senden, prüfen dass Antwort kommt und im Backend-Log eine Warning
   `Mistral: unknown model_id=…; falling back to mistral-medium-3-5`
   steht. Wenn keine solche Persona existiert, manuell eine bauen,
   indem ein Mongo-Doc gepatcht wird, oder den Test überspringen.

## Risks

- **Mistral ändert das Reasoning-Format.** Das proprietäre
  thinking-Block-Format ist nicht dokumentiert in `/api/endpoint/chat` —
  Mistral könnte es jederzeit ändern. Unser Parser ist defensiv (akzeptiert
  Listen, Strings und ignoriert unbekannte Item-Types ohne Crash), aber
  ein Schemawechsel würde Reasoning lautlos verstummen lassen. Mitigation:
  der bestehende `delta.reasoning_content`-Fallback fängt eine OpenAI-Style-Umstellung
  ab.
- **Mistral benennt `mistral-medium-3-5` um.** Sobald Mistral
  `mistral-medium-latest` auf 3.5 weiterdreht, wäre `mistral-medium-3-5`
  möglicherweise obsolet (oder bleibt parallel verfügbar). Wir folgen
  Mistral's Slug-Verlauf in einer Folge-Anpassung; der Adapter ist auf
  diese Art von Slug-Wechsel vorbereitet (nur eine String-Konstante
  ändern).
- **Mistral-Large-3-Tool-Call kann inoffiziell sein.** Wir verlassen uns
  auf empirisches Verhalten, das den Model-Card-Behauptungen widerspricht.
  Mistral könnte das in einer Update-Runde "fixen" und Large 3
  Tool-Calls explizit blockieren. Unwahrscheinlich (Mistral würde damit
  ihre eigenen API-Metadaten widerlegen), aber möglich. Mitigation:
  wenn das passiert, drehen wir `supports_tool_calls=False` im Eintrag um —
  trivialer Hotfix.
