# xAI Premium Adapter — grok-4.3 als first-class, Deprecations, Image-Tier-Rename

**Status:** Draft
**Date:** 2026-05-11
**Author:** Chris (with Claude)
**Drives:** Anpassungen am xAI-Adapter an angekündigte xAI-Änderungen (Stand 2026-05-11)

## Motivation

xAI hat für die kommenden Tage drei Änderungen angekündigt, die unseren Adapter
betreffen:

1. **Grok 4.1 Fast** wird komplett abgeschaltet, **Grok 4.20** ist offiziell
   legacy. Beide brauchen Deprecation-Markierungen, bleiben aber bis zur echten
   Abschaltung funktional (per CLAUDE.md "no more wipes" und "disabled statt
   versteckt").
2. **`grok-imagine-image-pro`** wird zum 2026-05-15 deprecated und durch
   **`grok-imagine-image-quality`** ersetzt (Quelle:
   <https://docs.x.ai/developers/model-capabilities/images/generation>).
3. **Grok 4.3** bekommt nativen `reasoning_effort` Parameter mit Werten
   `none`/`low`/`medium`/`high` (Quelle:
   <https://docs.x.ai/developers/model-capabilities/text/reasoning#the-reasoning_effort-parameter>).
   Damit entfällt die bisherige Fallback-Krücke "grok-4.3 fällt auf
   grok-4.20-non-reasoning zurück wenn Reasoning aus".

Wir nutzen die Gelegenheit, **grok-4.3** als einziges Modell im xAI-Adapter zu
einem "first-class-supported" Modell hochzustufen. Begründung: xAI-API-Keys
sind bei unseren Beta-Testern verbreitet (wegen STT/TTS), die Preise sind
niedrig, und grok-4.3 ist nach den Änderungen das einzige Grok-Modell, das
mittelfristig überlebt.

**Wichtig zur Abgrenzung:** grok-4.3 kommt auch über die Router-Adapter
nano-gpt und OpenRouter rein (über deren dynamische Model-Listen). Diese
Einträge sind **kein** first-class — sie zeigen im Model-Browser keinen
first-class-Badge und keinen Effort-Bucket-Picker. First-class und der
configurable `reasoning_effort` Picker sind strikt auf den xAI-Adapter-Pfad
für grok-4.3 begrenzt.

## Scope

**In Scope:**

- `_XaiModelEntry` um Diskriminantenfeld `reasoning_via`, sowie
  `first_class_support` und `is_deprecated` erweitern.
- `_build_chat_payload` verzweigt nach `reasoning_via`. Für grok-4.3 wird
  `reasoning_effort` aus `request.extras.reasoning_effort` als top-level Feld
  in den Outbound-Payload geschrieben.
- `fetch_models()` reicht die neuen Entry-Felder ins `ModelMetaDto` durch.
- `model_capabilities.yaml` bekommt einen `xai_http` + `grok-4.3` Eintrag mit
  Effort-Buckets `[none, low, medium, high]`, default `low`.
- `_xai_image_groups.py`: Slug `grok-imagine-image-pro` → `grok-imagine-image-quality`.
- `XaiImagineConfig.tier`: Literal wird `["normal", "quality"]`. Pydantic
  validator akzeptiert eingehendes `"pro"` als Alias (lazy migration on read).
- Frontend: `XaiImagineConfig` TS-Type und `XaiImagineConfigView` TIERS-Array
  parallel angepasst.
- Tests für die neuen Pfade, Updates der existierenden Test-Fixtures.

**Explizit nicht in Scope:**

- Kein Driver-Layer für grok-4.3 (Adapter reicht — Wire-Format ist Standard-xAI).
- Keine Änderungen an OpenRouter/nano-gpt/Mistral-Adaptern.
- Kein UI-Redesign der Effort-Buckets — `ThinkingButton.tsx` und
  `ReasoningToolsCluster.tsx` decken die Buckets bereits ab.
- Keine Migration weg von `reasoning_mode` für 4.1 Fast / 4.20 — die sterben
  eh bald.
- Kein One-Shot-Migrations-Skript für `XaiImagineConfig` mit `tier="pro"`. Lazy
  read genügt.
- Keine "premium"/"first-class" Ausweitung auf andere Modelle.
- **Keine YAML-Capability-Einträge für grok-4.3 via nano-gpt / OpenRouter.**
  Die Router-Adapter-Pfade für grok-4.3 nutzen ihre Default-Capabilities
  (kein Effort-Bucket-Picker, kein first-class-Badge). Wer den Bucket-Picker
  will, nimmt den xAI-Connection-Pfad.
- Keine Verifikation des `grok-imagine-image` (normal-tier) Slugs gegen die
  Live-API jetzt — wenn xAI ihn stilllegt, reagieren wir reaktiv.
- Keine Persona-Auto-Migration für User, die noch grok-4.1-fast oder grok-4.20
  konfiguriert haben — sie sehen den Deprecated-Badge, das Modell funktioniert
  bis zur Abschaltung. Discord-Ansage übernimmt den Rest.

## Architektur

### Backend: `_XaiModelEntry` als selbstbeschreibendes Modell

Das Diskriminantenfeld `reasoning_via` macht das Reasoning-Verhalten jedes
Eintrags explizit. Heute existiert nur slug-switching; mit grok-4.3 kommt
parameter-passing dazu.

```python
@dataclass(frozen=True)
class _XaiModelEntry:
    model_id: str
    display_name: str
    context_window: int
    reasoning_via: Literal["slug_switch", "effort_param"]
    reasoning_slug: str | None = None       # nur bei slug_switch
    non_reasoning_slug: str | None = None   # nur bei slug_switch
    first_class_support: bool = False
    is_deprecated: bool = False
    remarks: str | None = None
```

`_XAI_MODELS` Tupel nach der Änderung:

| model_id | reasoning_via | first_class | deprecated | remarks |
|---|---|---|---|---|
| grok-4.1-fast | slug_switch | False | True | nichts |
| grok-4.20 | slug_switch | False | True | nichts |
| grok-4.3 | effort_param | True | False | nichts |

Der bisherige Remarks-String für grok-4.3 ("Falls back to Grok 4.20…") wird
entfernt — die Fallback-Krücke entfällt vollständig.

### Backend: `_build_chat_payload` verzweigt nach `reasoning_via`

```text
entry = _XAI_MODELS_BY_ID[request.model]  # mit Fallback wie bisher
if entry.reasoning_via == "slug_switch":
    model_slug = entry.reasoning_slug if extras.reasoning_mode == "on"
                 else entry.non_reasoning_slug
    payload["model"] = model_slug
    # extras.reasoning_effort wird ignoriert
elif entry.reasoning_via == "effort_param":
    payload["model"] = entry.model_id  # z.B. "grok-4.3"
    if extras.reasoning_effort:
        payload["reasoning_effort"] = extras.reasoning_effort
    # extras.reasoning_mode wird ignoriert
```

Wenn `reasoning_effort` nicht gesetzt ist, omitten wir das Feld — xAI default
ist serverseitig `"low"`. Damit landet ein User, der gerade von einem alten
Grok-Modell auf grok-4.3 umgestellt hat und keine Effort gewählt hat, auf
einem sinnvollen Default.

### Backend: `fetch_models()` reicht neue Felder durch

```text
ModelMetaDto(
    ...,
    first_class_support=entry.first_class_support,
    is_deprecated=entry.is_deprecated,
    remarks=entry.remarks,
    ...
)
```

`reasoning.kind` bleibt für alle Einträge `"optional"`. Die Effort-Buckets
für grok-4.3 kommen über `model_capabilities.yaml`, nicht über Heuristik im
Adapter — konsistent mit GPT-5.

### Backend: `model_capabilities.yaml`

Neuer Eintrag, einsortiert in den xAI-Block:

```yaml
- adapter: xai_http
  pattern: "grok-4.3"
  reasoning:
    kind: optional
    effort: { buckets: [none, low, medium, high], default_bucket: low }
    default_on: true
  tools: { supported: true, exclusive_with_reasoning: false }
```

`adapter: xai_http` ist hier kein Detail, sondern essentiell: damit wirkt die
Effort-Capability nur auf xAI-Connection-Pfade. Vor dem Hinzufügen prüfen,
dass keine existierende, breiter formulierte YAML-Regel (z.B. ein generisches
`pattern: "grok*"`) bereits auf andere Adapter zugreift und unbeabsichtigt
Buckets ausspielt.

### Backend: Image-Tier-Slug

```python
# _xai_image_groups.py
def model_id_for_tier(tier: str) -> str:
    if tier == "quality":
        return "grok-imagine-image-quality"
    return "grok-imagine-image"
```

### DTO: `XaiImagineConfig.tier` lazy migration

```python
# shared/dtos/images.py
class XaiImagineConfig(BaseModel):
    ...
    tier: Literal["normal", "quality"] = "normal"
    ...

    @field_validator("tier", mode="before")
    @classmethod
    def _alias_pro_to_quality(cls, v):
        return "quality" if v == "pro" else v
```

Wirkung: Mongo-Dokumente mit `tier: "pro"` deserialisieren transparent als
`"quality"`. Schreibwege gehen ausschließlich mit `"quality"` raus. Configs
heilen sich beim nächsten Save organisch.

### Frontend

```ts
// frontend/src/core/api/images.ts
export interface XaiImagineConfig {
  ...
  tier: 'normal' | 'quality'
  ...
}
```

```tsx
// frontend/src/features/images/groups/XaiImagineConfigView.tsx
const TIERS: XaiImagineConfig['tier'][] = ['normal', 'quality']
```

Keine zusätzliche UI-Anpassung — die Segmented-Buttons rendern den Wert direkt
als Label.

Effort-Bucket-Picker für grok-4.3 entsteht automatisch durch den existierenden
`ThinkingButton` + `ReasoningToolsCluster`, sobald die YAML-Capability geladen ist.

### Cross-Adapter-Verhalten für grok-4.3

grok-4.3 kann von einem User über drei Wege erreicht werden:

| Adapter-Pfad | first_class_support | Effort-Picker | Reasoning-UX |
|---|---|---|---|
| xAI-Connection (`xai_http`) | True | Ja, 4 Buckets | Native `reasoning_effort` Parameter |
| OpenRouter-Connection | False | Nein | OR-default (on/off, ggf. nested `reasoning.effort` passthrough wenn extras gesetzt) |
| nano-gpt-Connection | False | Nein | nano-gpt-default |

Im Model-Browser sieht der User pro Connection einen separaten Eintrag (das
ist das existierende Verhalten — model unique ID ist `<connection_id>:<slug>`).
Der xAI-Eintrag trägt zusätzlich den first-class-Badge, die anderen nicht.
Das ist explizit so gewollt: Effort-Buckets sind eine xAI-API-Detail-Capability
und werden nur dort ausgespielt, wo wir den Wire-Vertrag direkt kennen.

## Datenfluss (grok-4.3 mit reasoning_effort)

```
User wählt grok-4.3 + Bucket "medium"
  ↓
cockpitStore: extras.reasoning_effort = "medium"
  ↓
WebSocket → backend ChatService
  ↓
LLM-Service ruft adapter.stream_completion(request)
  ↓
_build_chat_payload sieht entry.reasoning_via == "effort_param"
  ↓
Outbound xAI Request: {"model": "grok-4.3", "reasoning_effort": "medium", ...}
  ↓
xAI streamt Antwort mit Thinking-Tokens
```

## Migration

**Image-Tier `"pro"` → `"quality"`:** Lazy read via Pydantic-Validator (siehe
oben). Keine `backend/migrations/` Skripte. Folgt CLAUDE.md Variante 1.

**Grok 4.1 Fast / 4.20:** Keine Datenmigration. Persona-Configs, die diese
Modelle referenzieren, funktionieren weiter bis xAI den jeweiligen Slug zieht.
Sobald xAI einen Slug serverseitig abdreht, antwortet die API auf
betroffene Requests mit 4xx — der User sieht den `ErrorEvent` im UI. Aufräumen
(Entry aus `_XAI_MODELS` entfernen, eventuell Default-Fallback im
`_build_chat_payload` mit anpassen) erfolgt in einem separaten Follow-up,
sobald die Slugs tatsächlich tot sind. Out of Scope hier.

**Deprecation-Sichtbarkeit:** Wenn die Modelle aus `fetch_models()` mit
`is_deprecated=True` zurückkommen, rendert das Frontend bereits den Badge im
Model-Browser (`ModelBrowser.tsx:386-392`).

## Tests

### Neue Tests

- `tests/shared/dtos/test_images.py`: `XaiImagineConfig(tier="pro")` ergibt
  `tier == "quality"` nach Validation. Default bleibt `"normal"`.
- `backend/tests/modules/llm/adapters/test_xai_http.py`:
  - grok-4.3 + `reasoning_effort="medium"` → Payload enthält
    `"reasoning_effort": "medium"`, slug ist `"grok-4.3"`, kein
    Slug-Switching.
  - grok-4.3 + `reasoning_effort="none"` → Payload enthält
    `"reasoning_effort": "none"`.
  - grok-4.3 + `reasoning_effort=None` → Feld nicht im Payload.
  - grok-4.3 + `reasoning_mode="off"` → Feld nicht im Payload (mode wird
    ignoriert für effort_param Modelle).
  - grok-4.1-fast + `reasoning_mode="on"` → alte Slug-Switching-Logik
    weiterhin grün (Regression-Schutz).
  - `fetch_models()`: grok-4.3 hat `first_class_support=True`,
    `is_deprecated=False`. 4.1 Fast und 4.20 haben `is_deprecated=True`,
    `first_class_support=False`.
- Test für `model_id_for_tier`: `"quality"` →
  `"grok-imagine-image-quality"`, `"normal"` → `"grok-imagine-image"`. Falls
  noch kein Modul-Test existiert, neu anlegen (kurzes File).

### Zu aktualisierende Tests

- Alle `XaiImagineConfig(..., tier="pro")` Vorkommen in Tests werden auf
  `"quality"` umgestellt, **mit Ausnahme** eines expliziten
  Backwards-Compat-Tests, der `"pro"` als Input drin behält.
- `tests/llm/test_resolver_premium.py`: prüfen, dass der grok-4.3
  first-class Pfad weiterhin grün ist (vermutlich keine Änderung nötig).
- Frontend: `CockpitBar.test.tsx` und `ModelBrowser.test.tsx` werden
  überprüft, ob sich durch die neuen ModelMetaDto-Felder Snapshot-Drift
  ergibt; bei Bedarf nachziehen.

## Manual Verification

Auf realem Setup gegen die Live-xAI-API (Beta-Discord ankündigen):

1. **grok-4.3 + Effort-Bucket-Picker:**
   - Persona mit grok-4.3 anlegen.
   - ThinkingButton öffnet 4-Bucket-Picker (`none` / `low` / `medium` /
     `high`), default `low`.
   - Für jeden Bucket eine Test-Inferenz fahren.
   - Backend-Log prüfen: `reasoning_effort` korrekt im Outbound-Payload.
   - `none` → keine Thinking-Tokens in der Response.
   - `high` → sichtbar tiefere Antwort, längere Antwortzeit.

2. **Deprecation-Badges:**
   - Im Model-Browser: grok-4.1-fast und grok-4.20 zeigen den
     Deprecated-Badge.
   - grok-4.3 zeigt den first-class-Badge.
   - Alle drei sind weiterhin auswählbar.

3. **Reasoning bei alten Modellen unverändert:**
   - Persona auf grok-4.1-fast umstellen.
   - Bucket-Picker verschwindet (UI fällt auf simplen On/Off-Toggle zurück).
   - Reasoning on/off funktioniert wie bisher.

4. **Image-Tier-Migration:**
   - Image-Tool mit Tier `"quality"` generiert ein Bild.
   - Manuell via `mongosh` einen Persona-Image-Config-Eintrag auf
     `tier: "pro"` setzen.
   - Persona laden → UI zeigt Tier `"quality"` (alias greift).
   - Einmal speichern → Mongo-Dokument enthält nun `tier: "quality"`.

5. **Slug-Cutover am 2026-05-15:**
   - Nach xAIs Pro-Slug-Abschaltung Test wiederholen: Tier `"quality"`
     muss weiterhin funktionieren, Tier `"normal"` (Slug
     `grok-imagine-image`) wird beobachtet.

6. **Cross-Adapter-Abgrenzung:**
   - Wenn der Test-User auch eine OpenRouter- oder nano-gpt-Connection mit
     einem grok-4.3-fähigen Slug aktiv hat, im Model-Browser prüfen: jene
     Einträge zeigen **keinen** first-class-Badge und **keinen**
     Effort-Bucket-Picker im ThinkingButton.
   - Nur der xAI-Connection-Pfad für grok-4.3 trägt den Badge und liefert
     die 4-Bucket-UI.

## Offene Punkte / Follow-ups

- **`grok-imagine-image` Lebensdauer:** Die xAI-Docs erwähnen nur noch
  `grok-imagine-image-quality`. Falls der base-Slug `grok-imagine-image`
  ebenfalls abgeschaltet wird, brauchen wir ein zweites Tier-Re-Mapping
  (vermutlich Tier-Picker komplett entfernen). Reaktiv adressieren wenn das
  passiert.
- **Final cleanup von 4.1 Fast / 4.20:** Wenn xAI die Modelle wirklich abdreht,
  Einträge aus `_XAI_MODELS` entfernen und Fallback-Logik in
  `_build_chat_payload` aufräumen. Eigener kleiner Follow-up-Task.

## Referenzen

- xAI Reasoning Docs: <https://docs.x.ai/developers/model-capabilities/text/reasoning>
- xAI Image Generation Docs: <https://docs.x.ai/developers/model-capabilities/images/generation>
- Vorgänger-Spec mit Fallback-Logik (wird obsolet):
  `devdocs/specs/2026-05-01-grok-4.3-with-4.20-fallback-design.md`
- TTI-Spec mit Imagine-Slug-Verifikation:
  `devdocs/specs/2026-04-26-tti-xai-imagine-design.md`
- LLM Reasoning/Tools Capabilities (effort-Bucket-System):
  `devdocs/specs/2026-05-09-llm-reasoning-tools-capabilities-design.md`
