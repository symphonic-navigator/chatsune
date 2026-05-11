# xAI grok-4.3 first-class & image tier rename — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** xAI-Adapter so anpassen, dass grok-4.3 als einziges first-class-supported xAI-Modell mit nativem `reasoning_effort` Parameter läuft; grok-4.1-fast und grok-4.20 deprecated markieren; Image-Tier-Slug `pro` → `quality` (mit lazy migration).

**Architecture:** `_XaiModelEntry` bekommt das Diskriminantenfeld `reasoning_via` (`slug_switch` für legacy Modelle, `effort_param` für grok-4.3) sowie `first_class_support` und `is_deprecated`. `_build_chat_payload` verzweigt nach diesem Feld. `XaiImagineConfig.tier` Pydantic-Validator akzeptiert `"pro"` als Lazy-Alias auf `"quality"`. Frontend zieht das Tier-Rename nach.

**Tech Stack:** Python 3, Pydantic v2, pytest; React + TypeScript + Vite (pnpm), Vitest.

**Spec:** `devdocs/specs/2026-05-11-xai-grok-4-3-first-class-design.md`

**Branch:** `feature/xai-grok-4-3-first-class` (bereits aktiv, Spec ist auf diesem Branch committet).

**Test-Hinweise (aus CLAUDE.md / memory):**
- Backend-pytest auf Host braucht `PYTHONPATH=/home/chris/workspace/chatsune` Prefix.
- Backend-pytest auf Host muss die 4 Mongo-Test-Files ignorieren. Verwende:
  ```
  PYTHONPATH=/home/chris/workspace/chatsune uv run pytest \
    --ignore=tests/modules/llm/test_service_db.py \
    --ignore=tests/modules/llm/test_connection_repository.py \
    --ignore=tests/modules/llm/test_connection_service_mongo.py \
    --ignore=tests/modules/chat/test_session_repository_mongo.py \
    <weitere targets>
  ```
  Falls Pfade abweichen, vorher `rg -l 'pymongo\|motor\|AsyncIOMotorClient' tests/` zur Bestätigung laufen lassen.
- Frontend Build-Check: `pnpm run build` (nicht nur `tsc --noEmit` — `tsc -b` ist strenger).
- Niemals `--no-verify` oder `--amend` auf bereits committeten Commits.

**Subagent-Konstanten (per memory):** Nicht mergen, nicht pushen, nicht den Branch wechseln. Nur arbeiten, Tests grün halten, committen.

**Commit-Konvention:** Imperative free-form (per global CLAUDE.md), und jede Commit-Message endet mit:
```
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
```
Nutze HEREDOC für Multi-Line-Commits. Die unten in den Tasks gezeigten `git commit -m "..."` Strings sind die Subjekt-Zeile — Co-Authored-By darunter via HEREDOC ergänzen.

---

## File Structure

**Backend:**
- Modify: `shared/dtos/images.py` — `XaiImagineConfig.tier` Literal + Pydantic field_validator
- Modify: `backend/modules/llm/_adapters/_xai_image_groups.py` — Slug-Map (Tier `quality` → `grok-imagine-image-quality`)
- Modify: `backend/modules/llm/_adapters/_xai_http.py` — `_XaiModelEntry` schema, `_XAI_MODELS` Tabelle, `_build_chat_payload` branching, `fetch_models` Felder
- Modify: `backend/modules/llm/data/model_capabilities.yaml` — neuer Eintrag für `xai_http` + `grok-4.3`

**Frontend:**
- Modify: `frontend/src/core/api/images.ts` — TS-Type `tier`
- Modify: `frontend/src/features/images/groups/XaiImagineConfigView.tsx` — TIERS Array

**Tests (neu):**
- Create: `backend/tests/modules/llm/adapters/test_xai_image_groups.py`

**Tests (modify):**
- `tests/shared/dtos/test_images.py`
- `backend/tests/modules/llm/adapters/test_xai_http.py`
- `tests/modules/images/test_service.py`
- `tests/modules/llm/test_service_image_methods.py`
- `tests/modules/images/test_http.py`

---

### Task 1: DTO — `XaiImagineConfig.tier` mit Lazy-Alias `"pro"` → `"quality"`

**Files:**
- Modify: `shared/dtos/images.py:11-16` (XaiImagineConfig)
- Modify: `tests/shared/dtos/test_images.py`

- [ ] **Step 1.1: Failing-Tests in `tests/shared/dtos/test_images.py` hinzufügen**

Anhängen ans Datei-Ende:

```python
def test_xai_imagine_config_tier_default_is_normal():
    cfg = XaiImagineConfig()
    assert cfg.tier == "normal"


def test_xai_imagine_config_accepts_quality_tier():
    cfg = XaiImagineConfig(tier="quality")
    assert cfg.tier == "quality"


def test_xai_imagine_config_pro_tier_alias_to_quality():
    """Backwards-compat: legacy 'pro' input deserialises as 'quality'."""
    cfg = XaiImagineConfig(tier="pro")
    assert cfg.tier == "quality"


def test_xai_imagine_config_rejects_unknown_tier():
    with pytest.raises(ValidationError):
        XaiImagineConfig(tier="ultra")
```

Außerdem den existierenden `test_image_group_config_discriminated_union_parses_xai` (Zeile 32-42) anpassen — der setzt `tier: "pro"` und prüft `parsed.tier == "pro"`. Nach unserer Änderung wäre der Test inkonsistent. Diesen Test zu folgender Form ändern:

```python
def test_image_group_config_discriminated_union_parses_xai():
    adapter = TypeAdapter(ImageGroupConfig)
    parsed = adapter.validate_python({
        "group_id": "xai_imagine",
        "tier": "quality",
        "resolution": "2k",
        "aspect": "16:9",
        "n": 2,
    })
    assert isinstance(parsed, XaiImagineConfig)
    assert parsed.tier == "quality"
```

- [ ] **Step 1.2: Tests laufen lassen, müssen failen**

```bash
PYTHONPATH=/home/chris/workspace/chatsune uv run pytest \
  tests/shared/dtos/test_images.py -v
```

Erwartet: Mehrere Failures — bestehender Code lehnt `"quality"` ab (Literal nur `"normal"` und `"pro"`), und `"pro"` wird nicht zu `"quality"` aliased.

- [ ] **Step 1.3: `shared/dtos/images.py` updaten**

Importe ergänzen (oben in der Datei):

```python
from pydantic import BaseModel, Field, field_validator
```

`XaiImagineConfig` Klasse ersetzen:

```python
class XaiImagineConfig(BaseModel):
    group_id: Literal["xai_imagine"] = "xai_imagine"
    tier: Literal["normal", "quality"] = "normal"
    resolution: Literal["1k", "2k"] = "1k"
    aspect: Literal["1:1", "16:9", "9:16", "4:3", "3:4"] = "1:1"
    n: int = Field(4, ge=1, le=10)

    @field_validator("tier", mode="before")
    @classmethod
    def _alias_pro_to_quality(cls, v):
        # Lazy migration for legacy persisted configs (xAI deprecated
        # the "pro" image slug on 2026-05-15).
        return "quality" if v == "pro" else v
```

- [ ] **Step 1.4: Tests laufen lassen, müssen grün sein**

```bash
PYTHONPATH=/home/chris/workspace/chatsune uv run pytest \
  tests/shared/dtos/test_images.py -v
```

Erwartet: alle grün.

- [ ] **Step 1.5: Commit**

```bash
git add shared/dtos/images.py tests/shared/dtos/test_images.py
git commit -m "Alias legacy XaiImagineConfig tier='pro' to 'quality'"
```

---

### Task 2: Image-Group Slug-Mapping aktualisieren

**Files:**
- Modify: `backend/modules/llm/_adapters/_xai_image_groups.py:11-15`
- Create: `backend/tests/modules/llm/adapters/test_xai_image_groups.py`

- [ ] **Step 2.1: Failing-Test-Datei anlegen**

`backend/tests/modules/llm/adapters/test_xai_image_groups.py`:

```python
"""Tests for the xAI imagine image-group slug map."""

from backend.modules.llm._adapters._xai_image_groups import (
    GROUP_ID,
    aspect_to_payload,
    model_id_for_tier,
    resolution_to_payload,
)


def test_group_id_is_xai_imagine():
    assert GROUP_ID == "xai_imagine"


def test_model_id_for_tier_quality_returns_quality_slug():
    assert model_id_for_tier("quality") == "grok-imagine-image-quality"


def test_model_id_for_tier_normal_returns_base_slug():
    assert model_id_for_tier("normal") == "grok-imagine-image"


def test_model_id_for_tier_unknown_falls_back_to_base():
    assert model_id_for_tier("something-else") == "grok-imagine-image"


def test_aspect_passthrough():
    assert aspect_to_payload("16:9") == "16:9"


def test_resolution_passthrough():
    assert resolution_to_payload("2k") == "2k"
```

- [ ] **Step 2.2: Test laufen lassen, muss failen**

```bash
PYTHONPATH=/home/chris/workspace/chatsune uv run pytest \
  backend/tests/modules/llm/adapters/test_xai_image_groups.py -v
```

Erwartet: `test_model_id_for_tier_quality_returns_quality_slug` failt (Code mapped noch `"pro"` → `grok-imagine-image-pro`, nicht `"quality"` → `grok-imagine-image-quality`).

- [ ] **Step 2.3: `_xai_image_groups.py` updaten**

`model_id_for_tier` (Zeilen 11-15) ersetzen:

```python
def model_id_for_tier(tier: str) -> str:
    """Map config tier to xAI's model id.

    Verified against the live xAI API; ``grok-imagine-image-pro`` was
    deprecated on 2026-05-15 in favour of ``grok-imagine-image-quality``.
    Docs: https://docs.x.ai/developers/model-capabilities/images/generation
    """
    if tier == "quality":
        return "grok-imagine-image-quality"
    return "grok-imagine-image"
```

- [ ] **Step 2.4: Test laufen lassen, muss grün sein**

```bash
PYTHONPATH=/home/chris/workspace/chatsune uv run pytest \
  backend/tests/modules/llm/adapters/test_xai_image_groups.py -v
```

Erwartet: alle grün.

- [ ] **Step 2.5: Commit**

```bash
git add backend/modules/llm/_adapters/_xai_image_groups.py \
        backend/tests/modules/llm/adapters/test_xai_image_groups.py
git commit -m "Map xAI image tier 'quality' to grok-imagine-image-quality"
```

---

### Task 3: Bestehende `tier="pro"` Fixtures auf `"quality"` umstellen

Mechanisches Update aller Stellen, an denen `tier="pro"` in Test-Setups verwendet wird. Eine explizite Backwards-Compat-Stelle wurde in Task 1 (`test_xai_imagine_config_pro_tier_alias_to_quality`) bereits eingerichtet.

**Files:**
- Modify: `tests/modules/images/test_service.py`
- Modify: `tests/modules/llm/test_service_image_methods.py`
- Modify: `tests/modules/images/test_http.py`

- [ ] **Step 3.1: Vorkommen finden**

```bash
rg -n 'tier.*=.*"pro"|tier="pro"|"tier":\s*"pro"' tests/
```

Erwartete Treffer (Stand heute):
- `tests/modules/images/test_service.py` (mehrere Zeilen)
- `tests/modules/llm/test_service_image_methods.py`
- `tests/modules/images/test_http.py`

- [ ] **Step 3.2: Jeden Treffer von `"pro"` auf `"quality"` umstellen**

Wichtig: Falls in einer Datei ein Test explizit "legacy 'pro' input" testen sollte (statt das xAI-Bild-Generierungs-Tier zu prüfen), den intakt lassen. Bei reinen Setup-Fixtures: durch `"quality"` ersetzen.

Falls eine Assertion wie `assert config["tier"] == "pro"` direkt auf den persistierten String prüft, ebenfalls auf `"quality"` umstellen — die DTO-Validation transformiert ja.

- [ ] **Step 3.3: Tests laufen lassen, müssen grün sein**

```bash
PYTHONPATH=/home/chris/workspace/chatsune uv run pytest \
  tests/modules/images/ \
  tests/modules/llm/test_service_image_methods.py \
  -v
```

Erwartet: alle grün.

- [ ] **Step 3.4: Commit**

```bash
git add tests/modules/images/ tests/modules/llm/test_service_image_methods.py
git commit -m "Update image-tier test fixtures from 'pro' to 'quality'"
```

---

### Task 4: Frontend — Tier-Type und TIERS-Array anpassen

**Files:**
- Modify: `frontend/src/core/api/images.ts:12` (`tier` Typ)
- Modify: `frontend/src/features/images/groups/XaiImagineConfigView.tsx:4` (TIERS Array)

- [ ] **Step 4.1: `images.ts` updaten**

Aktuelle Zeile (12):
```ts
  tier: 'normal' | 'pro'
```
Ersetzen durch:
```ts
  tier: 'normal' | 'quality'
```

- [ ] **Step 4.2: `XaiImagineConfigView.tsx` updaten**

Aktuelle Zeile (4):
```ts
const TIERS: XaiImagineConfig['tier'][] = ['normal', 'pro']
```
Ersetzen durch:
```ts
const TIERS: XaiImagineConfig['tier'][] = ['normal', 'quality']
```

Restliche Komponente bleibt unverändert — die Segmented-Buttons rendern den Tier-Wert direkt.

- [ ] **Step 4.3: Falls Frontend-Snapshot-Tests existieren, prüfen**

```bash
cd frontend && pnpm test --run -- XaiImagine 2>&1 | tail -30
```

Wenn keine Tests existieren oder alle grün: weiter. Bei Snapshot-Drift gegen `"pro"`-Werte: Snapshot aktualisieren oder Erwartungen anpassen.

- [ ] **Step 4.4: Frontend bauen**

```bash
cd frontend && pnpm run build 2>&1 | tail -40
```

Erwartet: Build grün, keine TS-Errors.

- [ ] **Step 4.5: Commit**

```bash
git add frontend/src/core/api/images.ts frontend/src/features/images/groups/XaiImagineConfigView.tsx
git commit -m "Rename frontend xAI image tier 'pro' to 'quality'"
```

---

### Task 5: `_XaiModelEntry` Schema und `_XAI_MODELS` Tabelle erweitern

**Files:**
- Modify: `backend/modules/llm/_adapters/_xai_http.py:270-310` (Dataclass + Tabelle)
- Modify: `backend/modules/llm/_adapters/_xai_http.py:400-429` (`fetch_models`)
- Modify: `backend/tests/modules/llm/adapters/test_xai_http.py`

- [ ] **Step 5.1: Failing-Tests in `test_xai_http.py` ergänzen / anpassen**

Den existierenden Test `test_fetch_models_returns_three_grok_entries` (Zeilen ~58-88) anpassen. Die alte Assertion `g43.remarks == "Falls back to Grok 4.20..."` wird auf `g43.remarks is None` geändert.

Zusätzlich ans Datei-Ende anhängen:

```python
@pytest.mark.asyncio
async def test_fetch_models_first_class_support_only_for_grok_4_3():
    adapter = XaiHttpAdapter()
    metas = await adapter.fetch_models(_resolved_conn())
    by_id = {m.model_id: m for m in metas}
    assert by_id["grok-4.3"].first_class_support is True
    assert by_id["grok-4.1-fast"].first_class_support is False
    assert by_id["grok-4.20"].first_class_support is False


@pytest.mark.asyncio
async def test_fetch_models_deprecated_for_legacy_models():
    adapter = XaiHttpAdapter()
    metas = await adapter.fetch_models(_resolved_conn())
    by_id = {m.model_id: m for m in metas}
    assert by_id["grok-4.1-fast"].is_deprecated is True
    assert by_id["grok-4.20"].is_deprecated is True
    assert by_id["grok-4.3"].is_deprecated is False
```

- [ ] **Step 5.2: Tests laufen, müssen failen**

```bash
PYTHONPATH=/home/chris/workspace/chatsune uv run pytest \
  backend/tests/modules/llm/adapters/test_xai_http.py -v -k "fetch_models or first_class or deprecated"
```

Erwartet: drei der gerade berührten Tests failen — Adapter setzt `first_class_support` heute hart auf False, `is_deprecated` ist im DTO False per default, der alte remarks-String steht noch im grok-4.3-Eintrag.

- [ ] **Step 5.3: `_XaiModelEntry` Dataclass erweitern**

In `_xai_http.py:270-277` ersetzen:

```python
@dataclass(frozen=True)
class _XaiModelEntry:
    model_id: str
    display_name: str
    context_window: int
    reasoning_via: Literal["slug_switch", "effort_param"]
    reasoning_slug: str | None = None
    non_reasoning_slug: str | None = None
    first_class_support: bool = False
    is_deprecated: bool = False
    remarks: str | None = None
```

Sicherstellen, dass `Literal` aus `typing` importiert ist (am Datei-Anfang). Falls noch nicht: ergänzen.

- [ ] **Step 5.4: `_XAI_MODELS` Tabelle anpassen**

In `_xai_http.py:280-310` ersetzen:

```python
_XAI_MODELS: tuple[_XaiModelEntry, ...] = (
    _XaiModelEntry(
        model_id="grok-4.1-fast",
        display_name="Grok 4.1 Fast",
        context_window=128_000,
        reasoning_via="slug_switch",
        reasoning_slug="grok-4-1-fast-reasoning",
        non_reasoning_slug="grok-4-1-fast-non-reasoning",
        is_deprecated=True,
    ),
    _XaiModelEntry(
        model_id="grok-4.20",
        display_name="Grok 4.20",
        context_window=200_000,
        reasoning_via="slug_switch",
        reasoning_slug="grok-4.20-0309-reasoning",
        non_reasoning_slug="grok-4.20-0309-non-reasoning",
        is_deprecated=True,
    ),
    _XaiModelEntry(
        model_id="grok-4.3",
        display_name="Grok 4.3",
        context_window=200_000,
        reasoning_via="effort_param",
        first_class_support=True,
    ),
)
```

Der bisherige Remarks-String und die `non_reasoning_slug="grok-4.20-0309-non-reasoning"` Fallback-Krücke für grok-4.3 sind weg.

- [ ] **Step 5.5: `fetch_models` Felder durchreichen**

`_xai_http.py:408-427` — innerhalb des `ModelMetaDto(...)` Konstruktors die hartcodierte `first_class_support=False` durch `first_class_support=entry.first_class_support` ersetzen und ein neues Feld `is_deprecated=entry.is_deprecated` ergänzen. Auch den Kommentarblock (`# All Grok entries currently in _XAI_MODELS expose a reasoning toggle...`) auf den neuen Stand bringen.

Beispiel:

```python
async def fetch_models(
    self, c: ResolvedConnection,
) -> list[ModelMetaDto]:
    # Reasoning UX is now per-entry: legacy entries use slug switching
    # (reasoning_mode on/off), grok-4.3 uses the native reasoning_effort
    # parameter. See _build_chat_payload for the dispatch.
    return [
        ModelMetaDto(
            connection_id=c.id,
            connection_display_name=c.display_name,
            connection_slug=c.slug,
            model_id=entry.model_id,
            display_name=entry.display_name,
            context_window=entry.context_window,
            reasoning=ReasoningCapability(
                kind="optional", default_on=True,
            ),
            tools=ToolCapability(
                supported=True, exclusive_with_reasoning=False,
            ),
            first_class_support=entry.first_class_support,
            is_deprecated=entry.is_deprecated,
            supports_vision=True,
            supports_tool_calls=True,
            billing_category="pay_per_token",
            remarks=entry.remarks,
        )
        for entry in _XAI_MODELS
    ]
```

**Falls `ModelMetaDto` kein `is_deprecated` Feld besitzt:** Per Spec-Sektion 2 ist es vorhanden (`ModelBrowser.tsx:386-392` rendert den Badge). Wenn nicht: prüfen in `shared/dtos/llm.py`, ggf. dort `is_deprecated: bool = False` ergänzen und commiten — das ist eine echte Voraussetzung dieser Task, nicht Out-of-Scope.

- [ ] **Step 5.6: Tests laufen, müssen grün sein**

```bash
PYTHONPATH=/home/chris/workspace/chatsune uv run pytest \
  backend/tests/modules/llm/adapters/test_xai_http.py -v
```

Erwartet: alles grün. Wenn `_build_chat_payload`-Tests aus der Datei jetzt failen (weil `reasoning_slug`/`non_reasoning_slug` Optional sind und der alte Builder sie noch ohne None-Check liest), das in Task 6 fixen — bei Bedarf hier nur sicherstellen, dass die `fetch_models`/`is_deprecated`/`first_class_support` Tests grün sind und die anderen Failures klar als "von Task 6 zu adressieren" identifiziert sind.

- [ ] **Step 5.7: Commit**

```bash
git add backend/modules/llm/_adapters/_xai_http.py \
        backend/tests/modules/llm/adapters/test_xai_http.py \
        shared/dtos/llm.py   # falls Step 5.5 das Feld dort ergänzt hat
git commit -m "Add reasoning_via and deprecation/first-class flags to xAI model entries"
```

---

### Task 6: `_build_chat_payload` verzweigt nach `reasoning_via`

**Files:**
- Modify: `backend/modules/llm/_adapters/_xai_http.py:315-353`
- Modify: `backend/tests/modules/llm/adapters/test_xai_http.py`

- [ ] **Step 6.1: Failing-Tests in `test_xai_http.py` ergänzen**

`_build_chat_payload` wird intern aufgerufen (Prefix-Unterstrich). Import direkt aus dem Modul. Importe ggf. ergänzen:

```python
from backend.modules.llm._adapters._xai_http import (
    XaiHttpAdapter,
    _build_chat_payload,
    _translate_message,
)
from shared.dtos.inference import (
    CompletionMessage,
    CompletionRequest,
    ChatSessionExtras,
)
```

Ans Datei-Ende anhängen:

```python
def _basic_request(model: str, extras: ChatSessionExtras) -> CompletionRequest:
    return CompletionRequest(
        model=model,
        messages=[CompletionMessage(role="user", content="hi")],
        tools=[],
        temperature=None,
        extras=extras,
    )


def test_build_payload_grok_4_3_uses_native_slug_and_effort_medium():
    extras = ChatSessionExtras(
        tools_enabled=True, reasoning_mode="on", reasoning_effort="medium",
    )
    payload = _build_chat_payload(_basic_request("grok-4.3", extras))
    assert payload["model"] == "grok-4.3"
    assert payload["reasoning_effort"] == "medium"


def test_build_payload_grok_4_3_passes_effort_none_through():
    extras = ChatSessionExtras(
        tools_enabled=True, reasoning_mode="on", reasoning_effort="none",
    )
    payload = _build_chat_payload(_basic_request("grok-4.3", extras))
    assert payload["model"] == "grok-4.3"
    assert payload["reasoning_effort"] == "none"


def test_build_payload_grok_4_3_omits_effort_when_unset():
    extras = ChatSessionExtras(
        tools_enabled=True, reasoning_mode="on", reasoning_effort=None,
    )
    payload = _build_chat_payload(_basic_request("grok-4.3", extras))
    assert payload["model"] == "grok-4.3"
    assert "reasoning_effort" not in payload


def test_build_payload_grok_4_3_ignores_reasoning_mode():
    """For effort_param models the legacy on/off mode flag is ignored."""
    extras = ChatSessionExtras(
        tools_enabled=True, reasoning_mode="off", reasoning_effort="low",
    )
    payload = _build_chat_payload(_basic_request("grok-4.3", extras))
    assert payload["model"] == "grok-4.3"
    assert payload["reasoning_effort"] == "low"


def test_build_payload_grok_4_1_fast_still_slug_switches():
    """Regression: legacy slug-switch path stays intact."""
    on = ChatSessionExtras(
        tools_enabled=True, reasoning_mode="on", reasoning_effort=None,
    )
    off = ChatSessionExtras(
        tools_enabled=True, reasoning_mode="off", reasoning_effort=None,
    )
    p_on = _build_chat_payload(_basic_request("grok-4.1-fast", on))
    p_off = _build_chat_payload(_basic_request("grok-4.1-fast", off))
    assert p_on["model"] == "grok-4-1-fast-reasoning"
    assert p_off["model"] == "grok-4-1-fast-non-reasoning"
    assert "reasoning_effort" not in p_on
    assert "reasoning_effort" not in p_off


def test_build_payload_slug_switch_ignores_reasoning_effort():
    """For slug_switch models, reasoning_effort is not forwarded."""
    extras = ChatSessionExtras(
        tools_enabled=True, reasoning_mode="on", reasoning_effort="medium",
    )
    payload = _build_chat_payload(_basic_request("grok-4.20", extras))
    assert payload["model"] == "grok-4.20-0309-reasoning"
    assert "reasoning_effort" not in payload
```

- [ ] **Step 6.2: Tests laufen, müssen failen**

```bash
PYTHONPATH=/home/chris/workspace/chatsune uv run pytest \
  backend/tests/modules/llm/adapters/test_xai_http.py -v \
  -k "build_payload"
```

Erwartet: Failures, weil der Payload-Builder weder `reasoning_effort` durchreicht noch nach `reasoning_via` verzweigt. Möglicherweise auch AttributeError, weil `entry.reasoning_slug` für grok-4.3 jetzt `None` ist und der Builder das blind als String verwendet.

- [ ] **Step 6.3: `_build_chat_payload` aktualisieren**

`_xai_http.py:315-353` ersetzen:

```python
def _build_chat_payload(request: CompletionRequest) -> dict:
    entry = _XAI_MODELS_BY_ID.get(request.model)
    if entry is None:
        # Stale persona reference (e.g. legacy `xai:grok-4`) — fall back
        # to Grok 4.1 Fast so the request stays routable. Logged as a
        # warning so it shows up in Claude-oriented logs without
        # raising.
        _log.warning(
            "xAI: unknown model_id=%r in CompletionRequest; "
            "falling back to grok-4.1-fast",
            request.model,
        )
        entry = _XAI_MODELS_BY_ID["grok-4.1-fast"]

    if entry.reasoning_via == "effort_param":
        model_slug = entry.model_id
    else:
        # slug_switch
        model_slug = (
            entry.reasoning_slug if request.extras.reasoning_mode == "on"
            else entry.non_reasoning_slug
        )

    payload: dict = {
        "model": model_slug,
        "stream": True,
        "stream_options": {"include_usage": True},
        "messages": [_translate_message(m) for m in request.messages],
    }
    if entry.reasoning_via == "effort_param" and request.extras.reasoning_effort:
        payload["reasoning_effort"] = request.extras.reasoning_effort
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

- [ ] **Step 6.4: Tests laufen, müssen grün sein**

```bash
PYTHONPATH=/home/chris/workspace/chatsune uv run pytest \
  backend/tests/modules/llm/adapters/test_xai_http.py -v
```

Erwartet: gesamte xAI-Adapter-Test-Suite grün.

- [ ] **Step 6.5: Commit**

```bash
git add backend/modules/llm/_adapters/_xai_http.py \
        backend/tests/modules/llm/adapters/test_xai_http.py
git commit -m "Branch xAI chat payload by reasoning_via; pass reasoning_effort for grok-4.3"
```

---

### Task 7: `model_capabilities.yaml` Eintrag für grok-4.3

**Files:**
- Modify: `backend/modules/llm/data/model_capabilities.yaml`

- [ ] **Step 7.1: Prüfen, dass keine breitere xAI/Grok-Regel existiert**

```bash
rg -n 'grok|xai_http' backend/modules/llm/data/model_capabilities.yaml
```

Falls eine Regel mit `pattern: "grok*"` oder ohne `adapter:`-Filter existiert, die `effort` setzt: STOP, mit Chris klären. Andernfalls weiter.

- [ ] **Step 7.2: YAML-Eintrag ergänzen**

Im xAI-Block (oder, falls noch keiner existiert, an semantisch passender Stelle, z.B. nach den OpenRouter/nano-gpt-Einträgen für GPT-5):

```yaml
  # xAI native — grok-4.3 with configurable reasoning_effort
  - adapter: xai_http
    pattern: "grok-4.3"
    reasoning:
      kind: optional
      effort: { buckets: [none, low, medium, high], default_bucket: low }
      default_on: true
    tools: { supported: true, exclusive_with_reasoning: false }
```

- [ ] **Step 7.3: Capabilities-Tests laufen**

```bash
PYTHONPATH=/home/chris/workspace/chatsune uv run pytest \
  tests/modules/llm/test_capabilities.py \
  tests/modules/llm/test_capability_dtos.py \
  -v
```

Erwartet: alle grün. Falls bestehende Tests die Capabilities von grok-4.3 implizit oder explizit prüfen, sollten sie jetzt korrekt die `effort`-Buckets reflektieren.

- [ ] **Step 7.4: Optional — neuen Capabilities-Test ergänzen**

Wenn die existierende Test-Datei `tests/modules/llm/test_capabilities.py` einen klaren YAML-Lookup-Test pro Adapter/Modell-Kombination hat (Pattern erkennen aus 1-2 vorhandenen Tests), eine Assertion anhängen:

```python
def test_grok_4_3_xai_http_has_effort_buckets():
    from backend.modules.llm._capabilities import resolve_capabilities
    caps = resolve_capabilities(
        adapter_type="xai_http",
        model_id="grok-4.3",
        adapter=None,
    )
    assert caps.reasoning.kind == "optional"
    assert caps.reasoning.effort is not None
    assert caps.reasoning.effort.buckets == ["none", "low", "medium", "high"]
    assert caps.reasoning.effort.default_bucket == "low"


def test_grok_4_3_via_openrouter_has_no_effort_buckets():
    """Cross-adapter scope: effort buckets only via xai_http."""
    from backend.modules.llm._capabilities import resolve_capabilities
    caps = resolve_capabilities(
        adapter_type="openrouter_http",
        model_id="grok-4.3",  # OR might advertise as e.g. "x-ai/grok-4.3" instead
        adapter=None,
    )
    # OR-side: either kind != "optional with effort", or effort is None.
    assert caps.reasoning.effort is None
```

Wenn die exakte `resolve_capabilities`-Signatur abweicht (Adapter-Argument, Rückgabe-Type), aus bestehenden Tests in derselben Datei adaptieren. Die Tests sind optional — beim Auffinden eines abweichenden Patterns weglassen, statt blind zu implementieren.

- [ ] **Step 7.5: Tests laufen, müssen grün sein**

```bash
PYTHONPATH=/home/chris/workspace/chatsune uv run pytest \
  tests/modules/llm/test_capabilities.py -v
```

- [ ] **Step 7.6: Commit**

```bash
git add backend/modules/llm/data/model_capabilities.yaml tests/modules/llm/test_capabilities.py
git commit -m "Declare grok-4.3 reasoning_effort buckets in xAI model capabilities YAML"
```

---

### Task 8: End-to-End Verifikation und Branch-Status

- [ ] **Step 8.1: Backend-Test-Suite (host) laufen**

```bash
PYTHONPATH=/home/chris/workspace/chatsune uv run pytest \
  --ignore=tests/modules/llm/test_service_db.py \
  --ignore=tests/modules/llm/test_connection_repository.py \
  --ignore=tests/modules/llm/test_connection_service_mongo.py \
  --ignore=tests/modules/chat/test_session_repository_mongo.py \
  -q
```

Erwartet: alles grün. Falls einzelne nicht-Mongo-Tests scheitern, ursachenbezogen fixen (keine Test-Wipes ohne Verständnis).

Hinweis: Falls die obigen Ignore-Pfade nicht alle existieren, kurz vorher verifizieren:
```bash
ls tests/modules/llm/test_*db*.py tests/modules/llm/test_*mongo*.py tests/modules/chat/*mongo* 2>/dev/null
```
und die Ignore-Liste entsprechend anpassen.

- [ ] **Step 8.2: Frontend-Build + Type-Check**

```bash
cd frontend && pnpm run build 2>&1 | tail -50
```

Erwartet: Build grün, keine Type-Errors.

- [ ] **Step 8.3: Existierende Frontend-Tests (Cockpit, Model-Browser)**

```bash
cd frontend && pnpm test --run -- CockpitBar ModelBrowser ThinkingButton 2>&1 | tail -40
```

Falls Snapshot-Drift durch neue `is_deprecated`/`first_class_support` Pfade auftritt, Snapshots überprüfen und ggf. aktualisieren. Bei Unsicherheit nicht blind die Snapshots überschreiben, sondern den Drift im Diff begutachten.

- [ ] **Step 8.4: Manual-Verification-Block markieren**

Dieser Plan endet hier. Die Spec listet unter "Manual Verification" 6 Schritte, die Chris an einer realen xAI-Connection durchführt — diese sind **nicht** Subagent-Scope und müssen nicht automatisiert werden.

- [ ] **Step 8.5: Branch-Status verifizieren**

```bash
git status
git log --oneline feature/xai-grok-4-3-first-class
```

Erwartet: clean tree, alle Commits aus Tasks 1-7 sichtbar. **Nicht** mergen, **nicht** pushen — Chris übernimmt das nach manueller Verifikation.
