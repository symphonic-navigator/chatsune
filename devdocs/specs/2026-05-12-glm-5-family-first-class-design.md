# z.AI GLM-5 / GLM-5.1 als first-class via Ollama Cloud und Novita

**Status:** Draft
**Date:** 2026-05-12
**Author:** Chris (with Claude)
**Drives:** GLM-5 family aufgenommen in den kuratierten first-class-Katalog.

## Motivation

GLM-5 (756 B) und das nahezu identische post-training-Update GLM-5.1 sind
z.AI's aktueller Flagship-Stand. Reputation: ausgesprochen "personable",
emotional offener als DeepSeek, stark kreativ, exzellente Multilingualität.
Capabilities laut Probe (2026-05-12): Reasoning ja, Tool-Calling ja, kein
Vision (z.AI hat einen separaten V-Branch — `glm-4.6v` etc. — aber für 5/5.1
ist Vision derzeit nicht ausgerollt).

Beide Modelle sind über zwei strikt-westliche Provider verfügbar:

- **Ollama Cloud:** `glm-5`, `glm-5.1`
- **Novita:** `zai-org/glm-5`, `zai-org/glm-5.1`

OpenRouter und nano-gpt werden für GLM-5 **bewusst nicht** als first-class
gepflegt. Hintergrund: nano-gpt routet teilweise nach China und hat
Zuverlässigkeitsprobleme; OpenRouter ist bei unseren Beta-Testern weniger
verbreitet als angenommen. Ollama Cloud und Novita haben sich als die
beiden bevorzugten Provider für Open-Source-Modelle herausgestellt.

## Scope

**In Scope:**

- `model_capabilities.yaml`: vier neue Einträge (2 Modelle × 2 Adapter).
- Unit-Test im YAML-Capability-Loader, parametrisiert über die vier
  (adapter, slug) Kombinationen, der die `ResolvedCapabilities` verifiziert.
- Manuelle Verifikation auf realem Setup.

**Explizit nicht in Scope:**

- Kein Driver-Layer. Die existierenden Adapter `_ollama_http.py` und
  `_novita_http.py` parsen Reasoning-Output bereits sauber (`thinking`-Feld
  bei Ollama, `reasoning_content` bei Novita — verifiziert bei
  `_ollama_http.py:554` und `_novita_http.py:134`). Es fehlt nur die
  Capability-Metadata.
- Keine YAML-Einträge für GLM-5 via OpenRouter oder nano-gpt. Diese
  Adapter-Pfade bleiben über ihre Default-Heuristik erreichbar, aber ohne
  first-class-Badge und ohne kuratierte Capability-Garantien.
- Keine UI-Änderungen. `ThinkingButton.tsx` deckt den on/off-Toggle bereits
  ab; bei `always_on`-Reasoning blendet die existierende UI den Toggle korrekt
  aus (siehe Capability-System-Spec vom 2026-05-09).
- Kein Frontend-Code. First-class-Badges, Tool-Pills, Reasoning-Indikatoren
  funktionieren automatisch über `ResolvedCapabilities`.
- Kein Vision-Support. Falls z.AI später ein `glm-5v` oder `glm-5.1v` ausrollt,
  ist das ein separater Spec.
- Keine Anpassung der Adapter-Wire-Layer. Tool-Call-Akkumulation, SSE-Parsing,
  reasoning-stream-Forwarding sind bereits in beiden Adaptern implementiert.

## Architektur

### Capability-Profile pro Adapter

Die beiden Provider verhalten sich für die GLM-5-Familie unterschiedlich:

| Adapter | Reasoning toggleable? | Tool calls | Vision |
|---|---|---|---|
| `ollama_http` | **Ja** — via `think: true/false` (verifiziert) | Ja | Nein |
| `novita_http` | **Nein** — `reasoning.enabled=false` und `chat_template_kwargs.thinking=false` haben keinen Effekt; `reasoning_content` kommt immer mit | Ja | Nein |

Daher zwei verschiedene `reasoning.kind` Werte: `optional` für Ollama Cloud,
`always_on` für Novita. Beide Provider erlauben Tool-Calls parallel zum
Reasoning (`exclusive_with_reasoning: false`).

### `model_capabilities.yaml` Eintrag

Vier neue Blöcke, einsortiert hinter dem xAI-Block. Bewusst exakte
Patterns (keine Wildcards) — falls z.AI später Varianten wie
`glm-5-thinking` ausrollt, fallen die auf den Adapter-Heuristik-Pfad
zurück anstatt versehentlich unter dieselbe Capability gespannt zu werden.

```yaml
# z.AI GLM-5 family via Ollama Cloud — reasoning toggleable, tool-call capable,
# no vision. Probed 2026-05-12 via ollama.com/api/chat: `think: false` cleanly
# suppresses thinking output; tool calls work in both reasoning modes.
- adapter: ollama_http
  pattern: "glm-5"
  reasoning:
    kind: optional
    default_on: true
  tools: { supported: true, exclusive_with_reasoning: false }

- adapter: ollama_http
  pattern: "glm-5.1"
  reasoning:
    kind: optional
    default_on: true
  tools: { supported: true, exclusive_with_reasoning: false }

# z.AI GLM-5 family via Novita — reasoning forced on by upstream (no toggle
# parameter found that suppresses `reasoning_content`; probed 2026-05-12 with
# both reasoning.enabled=false and chat_template_kwargs.thinking=false — both
# ignored). Tool-call capable, no vision.
- adapter: novita_http
  pattern: "zai-org/glm-5"
  reasoning:
    kind: always_on
    default_on: true
  tools: { supported: true, exclusive_with_reasoning: false }

- adapter: novita_http
  pattern: "zai-org/glm-5.1"
  reasoning:
    kind: always_on
    default_on: true
  tools: { supported: true, exclusive_with_reasoning: false }
```

`first_class_support: true` wird **nicht** explizit gesetzt — der YAML-Loader
in `_capabilities.py:115` setzt das automatisch bei jedem Match.

`default_on: true` ist bei `kind: always_on` semantisch redundant, aber
konsistent mit allen anderen Einträgen und harmless — das Capability-System
liest `default_on` nur für `optional` aus.

### Patterns-Sortierung

Die Patterns werden zwischen den existierenden xAI-Block und einen
potenziellen späteren Block gelegt. Es gibt im aktuellen YAML keine
breiteren Regeln, die versehentlich `glm-5` oder `zai-org/glm-5` matchen
würden — verifiziert durch Inspektion (alle existierenden Patterns
beginnen mit `anthropic/`, `openai/`, oder `grok-`).

### Wire-Verhalten (keine Änderung, zur Bestätigung)

```
User wählt GLM-5.1 via Ollama-Cloud-Connection, Reasoning aus
  ↓
cockpitStore: extras.reasoning_mode = "off"
  ↓
adapter._ollama_http baut Payload mit "think": false
  ↓
Ollama Cloud antwortet ohne thinking-Feld
  ↓
ContentDelta-Events fließen ungehindert ans Frontend
```

```
User wählt GLM-5.1 via Novita-Connection
  ↓
cockpitStore: extras.reasoning_mode = "on"  (kann auch "off" sein — wird ignoriert)
  ↓
adapter._novita_http baut Standard-OpenAI-compat-Payload
  ↓
Novita liefert reasoning_content + content
  ↓
_novita_http.py:135 emittiert ThinkingDelta, dann ContentDelta
  ↓
UI rendert Thinking-Section und Antwort
```

## Migration

Keine. Reine YAML-Erweiterung, keine Daten-Modelle berührt.

## Tests

### Neue Tests

Parametrisierter Test in `tests/modules/llm/test_capabilities.py` (existiert,
enthält bereits den `_StubAdapter` und die `resolve_capabilities()`-Aufrufe).
Vier Test-Cases:

| adapter_type | model_id | erwartete kind | erwartete first_class |
|---|---|---|---|
| `ollama_http` | `glm-5` | `optional` | `True` |
| `ollama_http` | `glm-5.1` | `optional` | `True` |
| `novita_http` | `zai-org/glm-5` | `always_on` | `True` |
| `novita_http` | `zai-org/glm-5.1` | `always_on` | `True` |

Für jeden Case zusätzlich asserten:
- `tools.supported is True`
- `tools.exclusive_with_reasoning is False`
- `reasoning.effort is None` (keine Buckets bei GLM-5)
- `reasoning.default_on is True`

### Negative Assertions

- `glm-5*` auf einem fremden Adapter (z.B. `openrouter_http`) matched **nicht**
  via YAML. (Smoke test: ein OR-Request für `zai-org/glm-5.1` darf nicht
  fälschlich first-class werden.)
- `glm-4.6` (existierendes Vorgängermodell) bleibt unverändert (kein YAML-Eintrag,
  läuft über Adapter-Heuristik).

### Zu aktualisierende Tests

Keine erwartet. Bei Snapshot-Drift in `tests/test_capabilities_yaml.py` (falls
das File bereits eine Liste aller YAML-Patterns asserted) nachziehen.

## Manual Verification

Auf realem Setup gegen Live-Provider (Ksena-Test-Account oder Beta-Discord-Ankündigung):

1. **Ollama Cloud — glm-5.1 mit Reasoning aus:**
   - Connection für Ollama Cloud anlegen, GLM-5.1 in Persona auswählen.
   - `ThinkingButton` zeigt einfachen on/off-Toggle (keine Buckets).
   - Reasoning ausschalten, Test-Inferenz fahren.
   - Backend-Log: Outbound-Payload enthält `"think": false`.
   - Response: keine Thinking-Section in der UI, direkter Content-Stream.

2. **Ollama Cloud — glm-5.1 mit Reasoning an:**
   - Toggle umstellen, dieselbe Persona testen.
   - Thinking-Section sichtbar in der UI, danach reguläre Antwort.
   - Bei längeren Prompts: deutlich tiefere Antwort als ohne Reasoning.

3. **Novita — zai-org/glm-5.1:**
   - Novita-Connection (sollte als Premium-Provider verfügbar sein),
     GLM-5.1 auswählen.
   - `ThinkingButton` ist **ausgeblendet** oder zeigt "always on" (Verhalten
     der existierenden `always_on`-UI-Logik prüfen — falls die UI den
     Toggle versteckt, ist das korrekt).
   - Test-Inferenz: Thinking-Section sichtbar (kommt immer), Antwort folgt.
   - Backend-Log: kein `reasoning.enabled`-Feld im Outbound-Payload nötig.

4. **First-class-Badge im Model-Browser:**
   - Beide Provider-Pfade zeigen den GLM-5/5.1-Eintrag mit first-class-Badge.
   - Falls der User zusätzlich eine OpenRouter-Connection mit `zai-org/glm-5.1`
     hat, trägt **dieser** Eintrag **keinen** Badge.

5. **Tool-Calling:**
   - Persona mit aktiviertem Web-Search-Tool, GLM-5.1 via Ollama Cloud:
     Tool-Call-Pill erscheint, Suchergebnis fließt zurück, finale Antwort
     baut darauf auf.
   - Selbe Persona mit GLM-5.1 via Novita: Tool-Call funktioniert ebenfalls,
     Thinking-Section + Tool-Pill + finale Antwort.

6. **Multilingualität (informeller Smoke-Check):**
   - Deutsches Prompt → deutsche Antwort, idiomatisch.
   - Japanisches Prompt → japanische Antwort.
   - (GLM-5 ist laut Reputation hier stark; nur ein grober Sanity-Check.)

7. **Regression — nicht-GLM-Modelle:**
   - Bestehende Personas mit Claude / Grok / DeepSeek funktionieren
     unverändert, kein Capability-Drift sichtbar.

## Offene Punkte / Follow-ups

- **Novita-Reasoning-Toggle re-probe:** Sollte Novita irgendwann einen
  Off-Switch nachschieben (z.B. via `chat_template_kwargs` Format-Variante
  oder neuem Top-Level-Parameter), den YAML-Eintrag auf `kind: optional`
  flippen. Heute (2026-05-12) keine Spur eines solchen Parameters.
- **GLM-5V:** Wenn z.AI eine V-Variante für 5/5.1 ausrollt, separater Spec —
  Vision-Capability ist im aktuellen Capability-Schema nicht abgebildet
  und müsste zuerst hinzugefügt werden.
- **GLM-5.2 / GLM-6:** Bei nächster z.AI-Release: exakte Patterns hinzufügen
  (analog zu hier), keine Wildcards.

## Referenzen

- z.AI GLM-5 model card: <https://huggingface.co/zai-org/GLM-5>
- z.AI GLM-5.1 model card: <https://huggingface.co/zai-org/GLM-5.1>
- LLM Reasoning/Tools Capabilities Spec (Capability-Schema-Basis):
  `devdocs/specs/2026-05-09-llm-reasoning-tools-capabilities-design.md`
- Novita Premium Provider Spec:
  `devdocs/specs/2026-05-08-novita-premium-provider-design.md`
- xAI grok-4.3 first-class Spec (Strukturvorlage, deutlich größer als hier):
  `devdocs/specs/2026-05-11-xai-grok-4-3-first-class-design.md`
- Probe-Datum für beide Provider: 2026-05-12, via `.llm-test-key` und
  `.novita-test-key` im Repo-Root.
