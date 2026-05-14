# Mistral Adapter Curation — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Mistral-Adapter so umbauen, dass `fetch_models()` eine kuratierte 3-Modell-Liste liefert (Mistral Small 4, Medium 3.5, Large 3), dass der SSE-Parser Mistrals proprietäres Thinking-Block-Format korrekt verarbeitet, dass `reasoning_effort` als Binary-Toggle (`on→high`/`off→none`) gemappt wird, und dass ein `/test` Sub-Router die Connection-Validierung bereitstellt.

**Architecture:** Hartkodierte `_MistralModelEntry`-Dataclass + `_MISTRAL_MODELS` Tupel (analog `_XAI_MODELS`). `fetch_models()` emittiert nur die Tabelle ohne HTTP-Call. `_build_chat_payload()` mappt `model_id` → `upstream_slug`, setzt `reasoning_effort` bei Reasoning-Modellen je nach `reasoning_mode` toggle, und fällt bei unbekannten `model_id`s auf `mistral-medium-3-5` zurück (Warning gelogged). Neuer `_translate_delta_content()` Helper zerlegt polymorphes `delta.content` (String oder Array typisierter Items) in visible + thinking Text. `_build_adapter_router()` mit einer `/test` Route, analog xAI.

**Tech Stack:** Python 3, Pydantic v2, FastAPI, httpx, pytest.

**Spec:** `devdocs/specs/2026-05-14-mistral-curation-design.md`

**Branch:** `feat/mistral-curation` (bereits aktiv, Spec ist auf diesem Branch committet).

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
- Niemals `--no-verify` oder `--amend` auf bereits committeten Commits.

**Subagent-Konstanten (per memory):** Nicht mergen, nicht pushen, nicht den Branch wechseln. Nur arbeiten, Tests grün halten, committen.

**Commit-Konvention:** Imperative free-form (per global CLAUDE.md). Jede Commit-Message endet mit:
```
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
```
Nutze HEREDOC für Multi-Line-Commits. Die unten in den Tasks gezeigten `git commit -m "..."` Strings sind die Subjekt-Zeile — Co-Authored-By darunter via HEREDOC ergänzen.

---

## File Structure

**Backend (alle Mistral-Adapter-Änderungen in einer einzigen Datei):**
- Modify: `backend/modules/llm/_adapters/_mistral_http.py`
  - File-Header-Kommentar bereinigen (entfernt "Premium-only / not user-creatable"-Sprache)
  - Neue Dataclass `_MistralModelEntry` + Tupel `_MISTRAL_MODELS` + Lookup `_MISTRAL_MODELS_BY_ID`
  - Neue Helper-Funktion `_translate_delta_content()`
  - `_chunk_to_events()` patchen für polymorphes `content`
  - `_build_chat_payload()` umbauen (Slug-Mapping + Reasoning-Toggle + Legacy-Fallback)
  - `fetch_models()` umbauen — kein HTTP mehr, nur Tabellen-Emit
  - Alte `_dedup_models()` Funktion entfernen
  - Neue `capability_hint()` Methode am Adapter
  - Neuer `_mistral_repo_factory()` Helper auf Modul-Ebene
  - Neue `_build_adapter_router()` Funktion am Dateiende
  - Neue `router()` classmethod am Adapter

- Modify: `backend/modules/llm/data/model_capabilities.yaml`
  - Zwei neue Einträge: `(mistral_http, mistral-small-4)` und `(mistral_http, mistral-medium-3-5)`

**Tests:**
- Modify: `backend/tests/modules/llm/adapters/test_mistral_http.py`
  - Entfernen: alle `test_dedup_*` Tests (alte Pipeline weg)
  - Entfernen: `_dedup_models` aus dem Import
  - Anpassen: `test_build_payload_*` Tests an neue Slug-Mapping-Semantik
  - Anpassen: `test_stream_completion_emits_thinking_delta_for_reasoning_content` — neuer thinking-block-Pfad
  - Anpassen: `test_fetch_models_*` Tests auf statische Tabelle
  - Hinzufügen: `test_capability_hint_*` (3 Tests)
  - Hinzufügen: `test_translate_delta_content_*` (4 Tests)
  - Hinzufügen: `test_stream_completion_emits_thinking_delta_for_mistral_thinking_blocks`
  - Hinzufügen: `test_build_payload_*` für Slug-Mapping, Reasoning-Toggle, Legacy-Fallback
  - Hinzufügen: `test_post_test_*` für den Router (analog xAI)

---

## Task 1: Modell-Tabelle + capability_hint + Header-Bereinigung

**Files:**
- Modify: `backend/modules/llm/_adapters/_mistral_http.py` — Header-Kommentar, neue Dataclass, Konstanten, `capability_hint()`
- Test: `backend/tests/modules/llm/adapters/test_mistral_http.py` — neue capability_hint-Tests

- [ ] **Step 1: Tests für Modell-Tabelle und capability_hint schreiben**

In `backend/tests/modules/llm/adapters/test_mistral_http.py` direkt vor dem ersten existierenden `_resolved_conn` Helper folgendes ergänzen:

```python
from backend.modules.llm._adapters._mistral_http import (
    _MISTRAL_MODELS,
    _MISTRAL_MODELS_BY_ID,
    _MistralModelEntry,
)


def test_mistral_models_table_has_exactly_three_entries():
    assert len(_MISTRAL_MODELS) == 3
    ids = {m.model_id for m in _MISTRAL_MODELS}
    assert ids == {"mistral-small-4", "mistral-medium-3-5", "mistral-large-3"}


def test_mistral_models_display_names_are_curated():
    by_id = {m.model_id: m.display_name for m in _MISTRAL_MODELS}
    assert by_id["mistral-small-4"] == "Mistral Small 4"
    assert by_id["mistral-medium-3-5"] == "Mistral Medium 3.5"
    assert by_id["mistral-large-3"] == "Mistral Large 3"


def test_mistral_models_upstream_slugs_match_api_reality():
    by_id = {m.model_id: m.upstream_slug for m in _MISTRAL_MODELS}
    assert by_id["mistral-small-4"] == "mistral-small-latest"
    assert by_id["mistral-medium-3-5"] == "mistral-medium-3-5"
    assert by_id["mistral-large-3"] == "mistral-large-latest"


def test_mistral_models_first_class_only_for_reasoning_models():
    by_id = {m.model_id: m.first_class_support for m in _MISTRAL_MODELS}
    assert by_id["mistral-small-4"] is True
    assert by_id["mistral-medium-3-5"] is True
    assert by_id["mistral-large-3"] is False


def test_mistral_models_large_3_has_no_reasoning():
    entry = _MISTRAL_MODELS_BY_ID["mistral-large-3"]
    assert entry.has_reasoning is False


def test_mistral_models_small_and_medium_have_reasoning():
    assert _MISTRAL_MODELS_BY_ID["mistral-small-4"].has_reasoning is True
    assert _MISTRAL_MODELS_BY_ID["mistral-medium-3-5"].has_reasoning is True


def test_mistral_models_context_window_is_262144_for_all():
    for entry in _MISTRAL_MODELS:
        assert entry.context_window == 262_144


def test_mistral_models_all_support_vision_and_tools():
    for entry in _MISTRAL_MODELS:
        assert entry.supports_vision is True
        assert entry.supports_tool_calls is True


def test_capability_hint_returns_optional_reasoning_for_small_4():
    adapter = MistralHttpAdapter()
    hint = adapter.capability_hint("mistral-small-4")
    assert hint is not None
    assert hint.reasoning.kind == "optional"
    assert hint.reasoning.default_on is True
    assert hint.reasoning.effort is None
    assert hint.tools.supported is True
    assert hint.first_class_support is True


def test_capability_hint_returns_no_reasoning_for_large_3():
    adapter = MistralHttpAdapter()
    hint = adapter.capability_hint("mistral-large-3")
    assert hint is not None
    assert hint.reasoning.kind == "no_reasoning"
    assert hint.reasoning.default_on is False
    assert hint.tools.supported is True
    assert hint.first_class_support is False


def test_capability_hint_returns_none_for_unknown_model_id():
    adapter = MistralHttpAdapter()
    assert adapter.capability_hint("magistral-medium-latest") is None
    assert adapter.capability_hint("totally-made-up") is None
```

- [ ] **Step 2: Tests laufen lassen — müssen failen mit ImportError**

```
PYTHONPATH=/home/chris/workspace/chatsune uv run pytest \
  --ignore=tests/modules/llm/test_service_db.py \
  --ignore=tests/modules/llm/test_connection_repository.py \
  --ignore=tests/modules/llm/test_connection_service_mongo.py \
  --ignore=tests/modules/chat/test_session_repository_mongo.py \
  backend/tests/modules/llm/adapters/test_mistral_http.py::test_mistral_models_table_has_exactly_three_entries -v
```

Expected: `ImportError: cannot import name '_MISTRAL_MODELS' from 'backend.modules.llm._adapters._mistral_http'`.

- [ ] **Step 3: Header-Kommentar bereinigen + Dataclass und Konstanten einführen**

In `backend/modules/llm/_adapters/_mistral_http.py` den File-Docstring (Zeile 1–9) durch folgenden ersetzen:

```python
"""Mistral HTTP adapter — OpenAI-compatible Chat Completions.

Hosts a curated three-model list (Mistral Small 4, Medium 3.5, Large 3)
against the official Mistral Cloud API. Reasoning is a binary toggle
because Mistral only accepts ``reasoning_effort`` values ``high`` and
``none`` for Small 4 / Medium 3.5; Large 3 has no reasoning. Mistral's
SSE stream uses a proprietary ``thinking``-block format inside
``delta.content`` (polymorphic: string or typed-item array) — see
``_translate_delta_content`` for the parser.
"""
```

Dann im Datei-Body — direkt nach `_REFUSAL_REASONS` (vor `_SSE_DONE`) — ergänzen:

```python
from dataclasses import dataclass
from typing import Literal
```

(zu den bestehenden Imports oben ergänzen; nicht doppelt einfügen).

Direkt nach `_SSE_DONE = object()` einfügen:

```python
@dataclass(frozen=True)
class _MistralModelEntry:
    model_id: str            # persona-stable internal ID
    upstream_slug: str       # the slug we send to Mistral
    display_name: str
    context_window: int
    has_reasoning: bool      # True -> reasoning_effort toggle (high/none)
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

- [ ] **Step 4: `capability_hint()` Methode am Adapter ergänzen**

In `class MistralHttpAdapter(BaseAdapter)`: direkt nach `secret_fields = frozenset({"api_key"})` und vor `async def fetch_models(...)` einfügen:

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

- [ ] **Step 5: Tests grün?**

```
PYTHONPATH=/home/chris/workspace/chatsune uv run pytest \
  --ignore=tests/modules/llm/test_service_db.py \
  --ignore=tests/modules/llm/test_connection_repository.py \
  --ignore=tests/modules/llm/test_connection_service_mongo.py \
  --ignore=tests/modules/chat/test_session_repository_mongo.py \
  "backend/tests/modules/llm/adapters/test_mistral_http.py" -v -k "mistral_models or capability_hint"
```

Expected: alle 11 neuen Tests PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/modules/llm/_adapters/_mistral_http.py \
        backend/tests/modules/llm/adapters/test_mistral_http.py
git commit -m "$(cat <<'EOF'
Introduce curated Mistral model table and capability_hint

Adds _MistralModelEntry + _MISTRAL_MODELS for Small 4, Medium 3.5 and
Large 3, plus capability_hint() following the xAI pattern. Reasoning is
binary (high/none) for the two reasoning-capable models; Large 3 has
none. Header docstring updated to reflect the curated/BYOK reality.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: YAML capability overrides

**Files:**
- Modify: `backend/modules/llm/data/model_capabilities.yaml` — zwei neue Einträge
- Test: `backend/tests/modules/llm/adapters/test_mistral_http.py` — Tests dass resolve_capabilities die richtigen Felder liefert

- [ ] **Step 1: Tests schreiben für resolve_capabilities-Ausgabe**

In `test_mistral_http.py` am Ende der gerade ergänzten capability-Tests anfügen:

```python
def test_resolve_capabilities_small_4_has_no_effort_buckets():
    from backend.modules.llm._capabilities import resolve_capabilities
    adapter = MistralHttpAdapter()
    resolved = resolve_capabilities(
        adapter_type="mistral_http",
        model_id="mistral-small-4",
        adapter=adapter,
    )
    assert resolved.reasoning.kind == "optional"
    assert resolved.reasoning.effort is None
    assert resolved.reasoning.default_on is True
    assert resolved.first_class_support is True


def test_resolve_capabilities_medium_3_5_has_no_effort_buckets():
    from backend.modules.llm._capabilities import resolve_capabilities
    adapter = MistralHttpAdapter()
    resolved = resolve_capabilities(
        adapter_type="mistral_http",
        model_id="mistral-medium-3-5",
        adapter=adapter,
    )
    assert resolved.reasoning.kind == "optional"
    assert resolved.reasoning.effort is None
    assert resolved.first_class_support is True


def test_resolve_capabilities_large_3_has_no_reasoning():
    from backend.modules.llm._capabilities import resolve_capabilities
    adapter = MistralHttpAdapter()
    resolved = resolve_capabilities(
        adapter_type="mistral_http",
        model_id="mistral-large-3",
        adapter=adapter,
    )
    assert resolved.reasoning.kind == "no_reasoning"
    assert resolved.tools.supported is True
```

- [ ] **Step 2: Tests laufen — Large 3 sollte schon passen (capability_hint deckt's), Small/Medium nicht (yaml fehlt)**

```
PYTHONPATH=/home/chris/workspace/chatsune uv run pytest \
  --ignore=tests/modules/llm/test_service_db.py \
  --ignore=tests/modules/llm/test_connection_repository.py \
  --ignore=tests/modules/llm/test_connection_service_mongo.py \
  --ignore=tests/modules/chat/test_session_repository_mongo.py \
  "backend/tests/modules/llm/adapters/test_mistral_http.py" -v -k "resolve_capabilities"
```

Expected: Small 4 / Medium 3.5 Tests passen bereits, weil `capability_hint` korrekt liefert. Sollten alle 3 grün sein.

Anmerkung: die YAML-Einträge dienen primär als Override-Mechanismus, falls wir später für ein Modell von der `capability_hint`-Antwort abweichen wollen (z.B. zukünftiges Modell mit Effort-Buckets). Beide Wege liefern für die aktuellen Mistral-Modelle identische Resultate.

- [ ] **Step 3: YAML-Einträge ergänzen**

In `backend/modules/llm/data/model_capabilities.yaml`, **direkt nach dem `grok-4.3`-Block** (der mit `pattern: "grok-4.3"`), folgendes einfügen:

```yaml
  # Mistral native — Small 4 und Medium 3.5 mit binärem reasoning_effort
  # (Mistral akzeptiert nur high/none, kein low/medium). Der UI-Toggle
  # mappt direkt auf high (an) / none (aus); kein Bucket-Selector.
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

- [ ] **Step 4: Tests bleiben grün**

```
PYTHONPATH=/home/chris/workspace/chatsune uv run pytest \
  --ignore=tests/modules/llm/test_service_db.py \
  --ignore=tests/modules/llm/test_connection_repository.py \
  --ignore=tests/modules/llm/test_connection_service_mongo.py \
  --ignore=tests/modules/chat/test_session_repository_mongo.py \
  "backend/tests/modules/llm/adapters/test_mistral_http.py" -v -k "resolve_capabilities"
```

Expected: 3 PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/modules/llm/data/model_capabilities.yaml \
        backend/tests/modules/llm/adapters/test_mistral_http.py
git commit -m "$(cat <<'EOF'
Add YAML capability overrides for Mistral Small 4 and Medium 3.5

Both reasoning-capable Mistral models get explicit YAML entries with
kind=optional + default_on=true and no effort buckets, reflecting
Mistral's binary high/none constraint. Large 3 stays YAML-free; its
capability_hint already covers the no_reasoning + tools case.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: Neuer `fetch_models()` ohne HTTP-Call + alte `_dedup_models` entfernen

**Files:**
- Modify: `backend/modules/llm/_adapters/_mistral_http.py` — `fetch_models()` und `_dedup_models()`
- Test: `backend/tests/modules/llm/adapters/test_mistral_http.py` — alte dedup-Tests entfernen, neue fetch_models-Tests

- [ ] **Step 1: Alte fetch_models- und dedup-Tests entfernen**

In `test_mistral_http.py` die folgenden Tests vollständig löschen (sie testen die alte Pipeline, die rausfliegt):

- `_cap` (Helper, falls nur noch von dedup-Tests genutzt — vor dem Löschen mit `rg` prüfen)
- `test_dedup_collapses_latest_and_dated_aliases_onto_preferred_id`
- `test_dedup_marks_group_deprecated_when_entries_carry_deprecation`
- `test_dedup_keeps_standalone_entry_without_latest_alias`
- `test_dedup_filters_non_chat_models`
- `test_dedup_full_sample_yields_exactly_three_rows`
- `test_dedup_ignores_unrelated_latest_alias_in_group`
- `test_dedup_ignores_latest_alias_with_different_base_slug`
- `test_dedup_still_picks_matching_latest_alias`
- `test_fetch_models_calls_models_endpoint_with_auth`
- `test_fetch_models_returns_empty_on_auth_failure`
- `test_fetch_models_labels_billing_category_as_pay_per_token`
- `test_premium_adapter_has_no_templates_or_config_schema` (falls noch vorhanden — der bleibt **drin**, wenn er da ist, weil wir bewusst keine templates() hinzufügen)

Zusätzlich aus dem Modul-Import-Block am Dateianfang `_dedup_models` entfernen.

- [ ] **Step 2: Neue fetch_models-Tests schreiben**

In `test_mistral_http.py`, in einem klar abgegrenzten Block (Kommentar `# --- fetch_models ---`), folgendes einfügen:

```python
@pytest.mark.asyncio
async def test_fetch_models_returns_exactly_three_curated_entries():
    adapter = MistralHttpAdapter()
    metas = await adapter.fetch_models(_resolved_conn())
    ids = {m.model_id for m in metas}
    assert ids == {"mistral-small-4", "mistral-medium-3-5", "mistral-large-3"}
    assert len(metas) == 3


@pytest.mark.asyncio
async def test_fetch_models_carries_curated_display_names():
    adapter = MistralHttpAdapter()
    metas = await adapter.fetch_models(_resolved_conn())
    by_id = {m.model_id: m.display_name for m in metas}
    assert by_id["mistral-small-4"] == "Mistral Small 4"
    assert by_id["mistral-medium-3-5"] == "Mistral Medium 3.5"
    assert by_id["mistral-large-3"] == "Mistral Large 3"


@pytest.mark.asyncio
async def test_fetch_models_billing_category_is_pay_per_token_for_all_entries():
    adapter = MistralHttpAdapter()
    metas = await adapter.fetch_models(_resolved_conn())
    for m in metas:
        assert m.billing_category == "pay_per_token"


@pytest.mark.asyncio
async def test_fetch_models_first_class_only_for_small_and_medium():
    adapter = MistralHttpAdapter()
    metas = await adapter.fetch_models(_resolved_conn())
    by_id = {m.model_id: m.first_class_support for m in metas}
    assert by_id["mistral-small-4"] is True
    assert by_id["mistral-medium-3-5"] is True
    assert by_id["mistral-large-3"] is False


@pytest.mark.asyncio
async def test_fetch_models_makes_no_http_call(monkeypatch):
    """Curated fetch_models must not hit /v1/models — it's a static table."""
    called = False

    async def _boom(*a, **kw):
        nonlocal called
        called = True
        raise AssertionError("fetch_models should not perform HTTP")

    # Patch httpx so any accidental network call would crash loudly.
    monkeypatch.setattr(httpx.AsyncClient, "get", _boom)
    adapter = MistralHttpAdapter()
    metas = await adapter.fetch_models(_resolved_conn())
    assert called is False
    assert len(metas) == 3


@pytest.mark.asyncio
async def test_fetch_models_carries_context_window():
    adapter = MistralHttpAdapter()
    metas = await adapter.fetch_models(_resolved_conn())
    for m in metas:
        assert m.context_window == 262_144


@pytest.mark.asyncio
async def test_fetch_models_carries_vision_and_tool_flags():
    adapter = MistralHttpAdapter()
    metas = await adapter.fetch_models(_resolved_conn())
    for m in metas:
        assert m.supports_vision is True
        assert m.supports_tool_calls is True
```

- [ ] **Step 3: Tests laufen — sollten failen weil fetch_models noch alte HTTP-Variante ist**

```
PYTHONPATH=/home/chris/workspace/chatsune uv run pytest \
  --ignore=tests/modules/llm/test_service_db.py \
  --ignore=tests/modules/llm/test_connection_repository.py \
  --ignore=tests/modules/llm/test_connection_service_mongo.py \
  --ignore=tests/modules/chat/test_session_repository_mongo.py \
  "backend/tests/modules/llm/adapters/test_mistral_http.py" -v -k "fetch_models"
```

Expected: mehrere FAIL (alte fetch_models hängt auf /v1/models statt curated zurückzugeben).

- [ ] **Step 4: `fetch_models()` umbauen + `_dedup_models()` entfernen**

In `backend/modules/llm/_adapters/_mistral_http.py`:

(a) Die gesamte `_dedup_models()` Funktion (Zeile 262 bis ca. Zeile 347) **löschen**.

(b) Die bestehende `fetch_models()` Methode (Zeile 356–392) **ersetzen** durch:

```python
    async def fetch_models(
        self, c: ResolvedConnection,
    ) -> list[ModelMetaDto]:
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

- [ ] **Step 5: Tests grün?**

```
PYTHONPATH=/home/chris/workspace/chatsune uv run pytest \
  --ignore=tests/modules/llm/test_service_db.py \
  --ignore=tests/modules/llm/test_connection_repository.py \
  --ignore=tests/modules/llm/test_connection_service_mongo.py \
  --ignore=tests/modules/chat/test_session_repository_mongo.py \
  "backend/tests/modules/llm/adapters/test_mistral_http.py" -v
```

Expected: alle Tests im File PASS (alte dedup-Tests sind weg, neue fetch_models-Tests grün, sonstige Tests unverändert grün).

- [ ] **Step 6: Commit**

```bash
git add backend/modules/llm/_adapters/_mistral_http.py \
        backend/tests/modules/llm/adapters/test_mistral_http.py
git commit -m "$(cat <<'EOF'
Replace dynamic Mistral fetch_models with curated table

fetch_models now emits the three curated entries directly from
_MISTRAL_MODELS instead of probing /v1/models and deduping over the
'name' field. _dedup_models is removed along with its tests. The
curated path is HTTP-free, faster, and shields users from Mistral's
30+ legacy models (Magistral, Codestral, Devstral, Ministral, etc.).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: `_build_chat_payload()` umbauen — Slug-Mapping, Reasoning-Toggle, Legacy-Fallback

**Files:**
- Modify: `backend/modules/llm/_adapters/_mistral_http.py` — `_build_chat_payload()`
- Test: `backend/tests/modules/llm/adapters/test_mistral_http.py` — neue Tests, alte `test_build_payload_passes_model_slug_through_unchanged` entfernen

- [ ] **Step 1: Alte `test_build_payload_passes_model_slug_through_unchanged` entfernen**

Diesen einen Test in `test_mistral_http.py` löschen (er erwartet das alte Pass-Through-Verhalten, das wir gerade brechen).

- [ ] **Step 2: Neue Tests schreiben für Slug-Mapping + Reasoning + Fallback**

In `test_mistral_http.py`, in einem Block `# --- build_chat_payload ---` (vor den stream tests), folgendes ergänzen:

```python
def test_build_payload_maps_small_4_to_mistral_small_latest():
    req = _simple_request(model="mistral-small-4")
    payload = _build_chat_payload(req)
    assert payload["model"] == "mistral-small-latest"


def test_build_payload_maps_medium_3_5_to_dated_slug():
    req = _simple_request(model="mistral-medium-3-5")
    payload = _build_chat_payload(req)
    assert payload["model"] == "mistral-medium-3-5"


def test_build_payload_maps_large_3_to_mistral_large_latest():
    req = _simple_request(model="mistral-large-3")
    payload = _build_chat_payload(req)
    assert payload["model"] == "mistral-large-latest"


def test_build_payload_reasoning_on_sends_high():
    req = _simple_request(
        model="mistral-small-4",
        extras=ChatSessionExtras(
            tools_enabled=False, reasoning_mode="on", reasoning_effort=None,
        ),
    )
    payload = _build_chat_payload(req)
    assert payload["reasoning_effort"] == "high"


def test_build_payload_reasoning_off_sends_none():
    req = _simple_request(
        model="mistral-small-4",
        extras=ChatSessionExtras(
            tools_enabled=False, reasoning_mode="off", reasoning_effort=None,
        ),
    )
    payload = _build_chat_payload(req)
    assert payload["reasoning_effort"] == "none"


def test_build_payload_ignores_persisted_effort_bucket():
    # Stale persona may carry e.g. reasoning_effort="medium" from a different
    # adapter — Mistral rejects medium with HTTP 400. We must drop it entirely
    # and always send the high/none binary derived from reasoning_mode.
    req = _simple_request(
        model="mistral-medium-3-5",
        extras=ChatSessionExtras(
            tools_enabled=False, reasoning_mode="on", reasoning_effort="medium",
        ),
    )
    payload = _build_chat_payload(req)
    assert payload["reasoning_effort"] == "high"


def test_build_payload_large_3_omits_reasoning_effort():
    req = _simple_request(
        model="mistral-large-3",
        extras=ChatSessionExtras(
            tools_enabled=False, reasoning_mode="on", reasoning_effort=None,
        ),
    )
    payload = _build_chat_payload(req)
    assert "reasoning_effort" not in payload


def test_build_payload_unknown_model_falls_back_to_medium_3_5(caplog):
    import logging
    req = _simple_request(model="magistral-medium-latest")
    with caplog.at_level(logging.WARNING):
        payload = _build_chat_payload(req)
    assert payload["model"] == "mistral-medium-3-5"
    assert any(
        "unknown model_id" in r.message and "magistral-medium-latest" in r.message
        for r in caplog.records
    )


def test_build_payload_stream_options_included():
    req = _simple_request(model="mistral-small-4")
    payload = _build_chat_payload(req)
    assert payload["stream"] is True
    assert payload["stream_options"] == {"include_usage": True}


def test_build_payload_tools_translated_to_openai_schema():
    req = _simple_request(
        model="mistral-large-3",
        tools=[ToolDefinition(
            name="get_weather",
            description="Get weather",
            parameters={"type": "object", "properties": {"city": {"type": "string"}}},
        )],
    )
    payload = _build_chat_payload(req)
    assert payload["tools"] == [{
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": "Get weather",
            "parameters": {"type": "object", "properties": {"city": {"type": "string"}}},
        },
    }]
```

If `_simple_request` does not accept a `model` keyword today, locate it in the test file and ensure it supports `model="..."` plus `extras=...` plus `tools=...`. The xAI test file's `_simple_request` is the reference implementation.

- [ ] **Step 3: Tests laufen — Slug-Mapping- und Reasoning-Tests müssen failen**

```
PYTHONPATH=/home/chris/workspace/chatsune uv run pytest \
  --ignore=tests/modules/llm/test_service_db.py \
  --ignore=tests/modules/llm/test_connection_repository.py \
  --ignore=tests/modules/llm/test_connection_service_mongo.py \
  --ignore=tests/modules/chat/test_session_repository_mongo.py \
  "backend/tests/modules/llm/adapters/test_mistral_http.py" -v -k "build_payload"
```

Expected: mehrere FAIL für die neuen Slug-Mapping- und Reasoning-Tests.

- [ ] **Step 4: `_build_chat_payload()` umbauen**

Bestehende Funktion in `_mistral_http.py` (Zeile 231–259) **ersetzen** durch:

```python
def _build_chat_payload(request: CompletionRequest) -> dict:
    """Build a Mistral chat/completions payload.

    Maps our internal model_id to Mistral's upstream slug, applies the
    binary reasoning toggle (on -> "high", off -> "none") for reasoning
    models, and falls back to mistral-medium-3-5 when a stale persona
    references a model we no longer expose.
    """
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

- [ ] **Step 5: Tests grün?**

```
PYTHONPATH=/home/chris/workspace/chatsune uv run pytest \
  --ignore=tests/modules/llm/test_service_db.py \
  --ignore=tests/modules/llm/test_connection_repository.py \
  --ignore=tests/modules/llm/test_connection_service_mongo.py \
  --ignore=tests/modules/chat/test_session_repository_mongo.py \
  "backend/tests/modules/llm/adapters/test_mistral_http.py" -v -k "build_payload"
```

Expected: alle build_payload-Tests PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/modules/llm/_adapters/_mistral_http.py \
        backend/tests/modules/llm/adapters/test_mistral_http.py
git commit -m "$(cat <<'EOF'
Rewire _build_chat_payload for curated Mistral models

Maps internal model_id to upstream slug, applies binary reasoning toggle
(on -> high, off -> none) for Small 4 and Medium 3.5, omits the
reasoning_effort field entirely for Large 3, and falls back to
mistral-medium-3-5 with a warning when a persona references a model
that's no longer in the curated list.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: Stream-Parser-Fix für Mistral's `thinking`-Block-Format

**Files:**
- Modify: `backend/modules/llm/_adapters/_mistral_http.py` — `_translate_delta_content()` Helper + `_chunk_to_events()` patchen
- Test: `backend/tests/modules/llm/adapters/test_mistral_http.py` — neue Parser-Tests

- [ ] **Step 1: Tests für `_translate_delta_content` schreiben**

In `test_mistral_http.py`, in einem Block `# --- translate_delta_content (thinking-blocks) ---`, folgendes ergänzen:

```python
from backend.modules.llm._adapters._mistral_http import _translate_delta_content


def test_translate_delta_content_string_input_passes_through():
    visible, thinking = _translate_delta_content("hello")
    assert visible == "hello"
    assert thinking == ""


def test_translate_delta_content_empty_string():
    visible, thinking = _translate_delta_content("")
    assert visible == ""
    assert thinking == ""


def test_translate_delta_content_none_returns_empty_pair():
    visible, thinking = _translate_delta_content(None)
    assert visible == ""
    assert thinking == ""


def test_translate_delta_content_array_with_only_thinking():
    arr = [{
        "type": "thinking",
        "thinking": [{"type": "text", "text": "Okay, let me think"}],
        "closed": True,
    }]
    visible, thinking = _translate_delta_content(arr)
    assert visible == ""
    assert thinking == "Okay, let me think"


def test_translate_delta_content_array_with_only_text():
    arr = [{"type": "text", "text": "Result is 4"}]
    visible, thinking = _translate_delta_content(arr)
    assert visible == "Result is 4"
    assert thinking == ""


def test_translate_delta_content_array_with_mixed_items():
    arr = [
        {"type": "thinking",
         "thinking": [{"type": "text", "text": "Hmm "}, {"type": "text", "text": "let me see."}]},
        {"type": "text", "text": "The answer "},
        {"type": "text", "text": "is 4."},
    ]
    visible, thinking = _translate_delta_content(arr)
    assert visible == "The answer is 4."
    assert thinking == "Hmm let me see."


def test_translate_delta_content_ignores_unknown_item_types():
    arr = [
        {"type": "future_unknown_type", "data": "..."},
        {"type": "text", "text": "Hello"},
    ]
    visible, thinking = _translate_delta_content(arr)
    assert visible == "Hello"
    assert thinking == ""


def test_translate_delta_content_robust_against_malformed_items():
    arr = [
        "not a dict",  # malformed item
        {"type": "thinking"},  # missing thinking-field
        {"type": "text"},  # missing text-field
        {"type": "text", "text": "ok"},
    ]
    visible, thinking = _translate_delta_content(arr)
    assert visible == "ok"
    assert thinking == ""
```

Außerdem den existierenden Stream-Test
`test_stream_completion_emits_thinking_delta_for_reasoning_content` durch
einen umbenannten Test ergänzen (alten lassen oder umbenennen — der alte
OpenAI-Style-`reasoning_content`-Pfad bleibt ja als Fallback erhalten):

```python
@pytest.mark.asyncio
async def test_stream_completion_emits_thinking_delta_for_mistral_thinking_blocks(monkeypatch):
    """Mistral's proprietary format: delta.content as array with
    thinking-typed items.
    """
    def handler(request):
        return _sse_response([
            'data: {"choices":[{"delta":{"content":'
            '[{"type":"thinking","thinking":[{"type":"text","text":"hmm"}]}]}}]}',
            'data: {"choices":[{"delta":{"content":'
            '[{"type":"text","text":"42"}]}}]}',
            'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}',
            'data: {"choices":[],"usage":{"prompt_tokens":5,"completion_tokens":3}}',
            'data: [DONE]',
        ])

    _install_mock_transport(monkeypatch, handler)
    adapter = MistralHttpAdapter()
    events = await _collect(adapter.stream_completion(_resolved_conn(), _simple_request()))
    thinking = [e for e in events if isinstance(e, ThinkingDelta)]
    content = [e for e in events if isinstance(e, ContentDelta)]
    assert [t.delta for t in thinking] == ["hmm"]
    assert [c.delta for c in content] == ["42"]
```

- [ ] **Step 2: Tests laufen — Helper und neuer Stream-Test sollten failen**

```
PYTHONPATH=/home/chris/workspace/chatsune uv run pytest \
  --ignore=tests/modules/llm/test_service_db.py \
  --ignore=tests/modules/llm/test_connection_repository.py \
  --ignore=tests/modules/llm/test_connection_service_mongo.py \
  --ignore=tests/modules/chat/test_session_repository_mongo.py \
  "backend/tests/modules/llm/adapters/test_mistral_http.py" -v -k "translate_delta_content or mistral_thinking_blocks"
```

Expected: ImportError für `_translate_delta_content`, alle neuen Tests FAIL.

- [ ] **Step 3: `_translate_delta_content` Helper hinzufügen**

In `backend/modules/llm/_adapters/_mistral_http.py`, **vor** der `_chunk_to_events()`-Funktion, einfügen:

```python
def _translate_delta_content(content: object) -> tuple[str, str]:
    """Return (visible_text, thinking_text) from Mistral's polymorphic delta.content.

    Mistral breaks from OpenAI's schema when reasoning is active: delta.content
    becomes a list of typed items {"type": "thinking" | "text", ...} rather
    than a plain string. We fold visible-text fragments and thinking-text
    fragments separately so _chunk_to_events can emit ContentDelta and
    ThinkingDelta cleanly.

    When reasoning_effort="none" (or for models without reasoning) Mistral
    keeps delta.content as a plain string — handled identically to the
    OpenAI path.
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
        # other item types (e.g. future tool-call representation) are
        # ignored intentionally — tool_calls arrive on delta.tool_calls,
        # not inline in content.
    return "".join(visible), "".join(thinking)
```

- [ ] **Step 4: `_chunk_to_events()` patchen**

In `_mistral_http.py` die folgenden Zeilen in `_chunk_to_events()`:

```python
    reasoning = delta.get("reasoning_content") or ""
    if reasoning:
        events.append(ThinkingDelta(delta=reasoning))

    content = delta.get("content") or ""
    if content:
        events.append(ContentDelta(delta=content))
```

ersetzen durch:

```python
    # Mistral packs thinking blocks inside delta.content (polymorphic:
    # string or typed-item list). The OpenAI-style reasoning_content
    # field is kept as a fallback in case Mistral converges to OpenAI's
    # schema in a future API revision.
    visible, thinking_from_content = _translate_delta_content(delta.get("content"))
    if thinking_from_content:
        events.append(ThinkingDelta(delta=thinking_from_content))
    if visible:
        events.append(ContentDelta(delta=visible))

    oai_reasoning = delta.get("reasoning_content") or ""
    if oai_reasoning:
        events.append(ThinkingDelta(delta=oai_reasoning))
```

- [ ] **Step 5: Tests grün?**

```
PYTHONPATH=/home/chris/workspace/chatsune uv run pytest \
  --ignore=tests/modules/llm/test_service_db.py \
  --ignore=tests/modules/llm/test_connection_repository.py \
  --ignore=tests/modules/llm/test_connection_service_mongo.py \
  --ignore=tests/modules/chat/test_session_repository_mongo.py \
  "backend/tests/modules/llm/adapters/test_mistral_http.py" -v
```

Expected: alle Tests im File PASS (inkl. der existierenden Stream-Tests, die unverändert mit String-Content arbeiten und weiterhin grün sind).

- [ ] **Step 6: Commit**

```bash
git add backend/modules/llm/_adapters/_mistral_http.py \
        backend/tests/modules/llm/adapters/test_mistral_http.py
git commit -m "$(cat <<'EOF'
Parse Mistral's proprietary thinking-block stream format

When reasoning is active, Mistral packs thinking content into
delta.content as a typed-item array rather than using OpenAI's
delta.reasoning_content. Introduces _translate_delta_content() to
fold the polymorphic string-or-array shape into (visible, thinking)
and routes the parts to ContentDelta / ThinkingDelta. The OpenAI-style
reasoning_content path stays as a fallback for future API revisions.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: Test-Endpoint Sub-Router

**Files:**
- Modify: `backend/modules/llm/_adapters/_mistral_http.py` — `_mistral_repo_factory()`, `_build_adapter_router()`, `MistralHttpAdapter.router()`
- Test: `backend/tests/modules/llm/adapters/test_mistral_http.py` — Router-Tests (valid, invalid key, upstream error)

- [ ] **Step 1: Router-Tests schreiben**

In `test_mistral_http.py` am Dateiende einen neuen Block ergänzen:

```python
# ---------------------------------------------------------------------------
# Sub-router POST /test
# ---------------------------------------------------------------------------

from fastapi import FastAPI
from fastapi.testclient import TestClient


def _app_with_mistral_router(monkeypatch, handler) -> TestClient:
    from backend.modules.llm._adapters import _mistral_http
    from backend.modules.llm._resolver import resolve_connection_for_user

    class _PatchedClient(httpx.AsyncClient):
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = httpx.MockTransport(handler)
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(_mistral_http.httpx, "AsyncClient", _PatchedClient)

    router = MistralHttpAdapter.router()
    app = FastAPI()
    app.include_router(router, prefix="/adapter")
    app.dependency_overrides[resolve_connection_for_user] = lambda: _resolved_conn()

    from backend.ws.event_bus import get_event_bus

    class _FakeRepo:
        async def update_test_status(self, *a, **kw):
            return None

    class _FakeBus:
        async def publish(self, *a, **kw):
            return None

    monkeypatch.setattr(_mistral_http, "_mistral_repo_factory",
                        lambda: _FakeRepo(), raising=False)
    app.dependency_overrides[get_event_bus] = lambda: _FakeBus()
    return TestClient(app)


def test_post_test_valid_key_returns_true(monkeypatch):
    def handler(request):
        assert request.url.path.endswith("/models")
        assert request.headers["authorization"] == "Bearer mistral-test-key"
        return httpx.Response(200, json={"data": [{"id": "mistral-small-latest"}]})

    client = _app_with_mistral_router(monkeypatch, handler)
    resp = client.post("/adapter/test")
    assert resp.status_code == 200
    body = resp.json()
    assert body["valid"] is True
    assert body["error"] is None


def test_post_test_invalid_key_returns_false_with_clear_error(monkeypatch):
    def handler(request):
        return httpx.Response(401, json={"error": "unauthorised"})

    client = _app_with_mistral_router(monkeypatch, handler)
    resp = client.post("/adapter/test")
    assert resp.status_code == 200
    body = resp.json()
    assert body["valid"] is False
    assert "key" in body["error"].lower() and "mistral" in body["error"].lower()


def test_post_test_upstream_error_returns_false(monkeypatch):
    def handler(request):
        return httpx.Response(503, json={"error": "down"})

    client = _app_with_mistral_router(monkeypatch, handler)
    resp = client.post("/adapter/test")
    assert resp.status_code == 200
    body = resp.json()
    assert body["valid"] is False
    assert "503" in body["error"]
```

- [ ] **Step 2: Tests laufen — alle drei sollten failen**

```
PYTHONPATH=/home/chris/workspace/chatsune uv run pytest \
  --ignore=tests/modules/llm/test_service_db.py \
  --ignore=tests/modules/llm/test_connection_repository.py \
  --ignore=tests/modules/llm/test_connection_service_mongo.py \
  --ignore=tests/modules/chat/test_session_repository_mongo.py \
  "backend/tests/modules/llm/adapters/test_mistral_http.py" -v -k "post_test"
```

Expected: AttributeError oder ähnliches, weil `MistralHttpAdapter.router()` und `_mistral_repo_factory()` noch nicht existieren.

- [ ] **Step 3: `_mistral_repo_factory()`, `_build_adapter_router()` und `router()` ergänzen**

In `backend/modules/llm/_adapters/_mistral_http.py`:

(a) Den Import-Block oben ergänzen — falls noch nicht vorhanden:

```python
from fastapi import APIRouter, Depends
```

(b) **Vor** der `class MistralHttpAdapter(...)` Definition, eine Helper-Funktion einfügen:

```python
def _mistral_repo_factory():
    """Default factory — returns a ConnectionRepository backed by the live DB.

    Defined at module level so tests can monkeypatch it:
        monkeypatch.setattr(_mistral_http, "_mistral_repo_factory", lambda: _FakeRepo())
    """
    from backend.database import get_db
    from backend.modules.llm._connections import ConnectionRepository
    return ConnectionRepository(get_db())
```

(c) **Innerhalb** `class MistralHttpAdapter(BaseAdapter):` direkt nach den class-level attributes (`adapter_type`, `display_name`, `view_id`, `secret_fields`) und vor `capability_hint()`, eine `router()` classmethod ergänzen:

```python
    @classmethod
    def router(cls) -> APIRouter:
        return _build_adapter_router()
```

(d) **Am Dateiende**, eine `_build_adapter_router()` Funktion einfügen:

```python
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
        except Exception as exc:  # noqa: BLE001 — surface to frontend
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

- [ ] **Step 4: Tests grün?**

```
PYTHONPATH=/home/chris/workspace/chatsune uv run pytest \
  --ignore=tests/modules/llm/test_service_db.py \
  --ignore=tests/modules/llm/test_connection_repository.py \
  --ignore=tests/modules/llm/test_connection_service_mongo.py \
  --ignore=tests/modules/chat/test_session_repository_mongo.py \
  "backend/tests/modules/llm/adapters/test_mistral_http.py" -v -k "post_test"
```

Expected: alle drei Router-Tests PASS.

- [ ] **Step 5: Full-Suite-Lauf**

```
PYTHONPATH=/home/chris/workspace/chatsune uv run pytest \
  --ignore=tests/modules/llm/test_service_db.py \
  --ignore=tests/modules/llm/test_connection_repository.py \
  --ignore=tests/modules/llm/test_connection_service_mongo.py \
  --ignore=tests/modules/chat/test_session_repository_mongo.py \
  "backend/tests/modules/llm/" -v
```

Expected: alle Tests im llm-Verzeichnis PASS — sanity check, dass wir nichts anderes gebrochen haben (z.B. Capability-Resolution, Driver-Tests).

- [ ] **Step 6: Commit**

```bash
git add backend/modules/llm/_adapters/_mistral_http.py \
        backend/tests/modules/llm/adapters/test_mistral_http.py
git commit -m "$(cat <<'EOF'
Add Mistral /test sub-router for connection validation

Mirrors xAI's adapter router pattern: POST /api/llm/connections/{id}/
adapter/test pings GET /v1/models with the connection key and writes
valid/failed (plus optional error) into the connection document.
Publishes LlmConnectionUpdatedEvent so the frontend reflects the new
status without a separate fetch.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: Manual verification gegen Mistral-API

Diese Task wird **nicht von einem Subagent ausgeführt**. Chris läuft sie manuell durch, mit einem Beta-Build und einer echten Mistral-Connection (oder dem `.mistral-test-key`).

- [ ] **Modell-Picker zeigt genau drei Mistral-Einträge:** Mistral Small 4, Mistral Medium 3.5, Mistral Large 3 — keine Magistral/Codestral/Devstral/Ministral mehr im Picker.

- [ ] **Connection-Test:** Mistral-Connection in den Settings öffnen, "Verbindung testen" klicken. Status wechselt auf "valid". Anschließend Key absichtlich verfälschen → Status wechselt auf "failed" mit lesbarer Fehlermeldung.

- [ ] **Reasoning ein, Small 4:** Persona mit Mistral Small 4 + Reasoning=on. Prompt "Was ist 2+2? Denke kurz nach." → Thinking-Pill erscheint im Chat mit lesbarem Reasoning-Text. Antwort darunter ist kurz wie "4". Token-Anzeige zeigt Input- und Reasoning-Tokens.

- [ ] **Reasoning aus, Small 4:** gleiche Persona, Reasoning=off, gleicher Prompt. Antwort kommt ohne Thinking-Pill — keine leere Thinking-Pille in der UI.

- [ ] **Reasoning ein, Medium 3.5:** Persona mit Mistral Medium 3.5 + Reasoning=on. Beliebiger Prompt, Thinking-Pill mit lesbarem Reasoning erscheint.

- [ ] **Tool-Call, Large 3:** Persona mit Mistral Large 3 + Tool-Group "Web/Search" aktiv. Prompt "Wie ist das Wetter in Wien?". Tool-Call wird ausgelöst, Antwort kommt nach Tool-Roundtrip.

- [ ] **Vision, Large 3:** Persona mit Mistral Large 3, Bild hochladen + "Was siehst du?". Bild-Beschreibung kommt zurück.

- [ ] **Legacy-Persona (optional):** Falls eine Persona existiert, die ein altes Mistral-Modell (z.B. `magistral-medium-latest`) gepinnt hat — Chat senden, prüfen dass Antwort kommt und im Backend-Log eine Warning `Mistral: unknown model_id=…; falling back to mistral-medium-3-5` steht. Wenn keine solche Persona existiert: Test überspringen, Discord-Hinweis bei Beta-Release reicht.

---

## Done

Wenn alle Tasks abgehakt sind, ist die Mistral-Kuration komplett. Subagent meldet zurück; Chris merged Branch nach Master (per Implementation-Defaults in CLAUDE.md "Please always merge to master after implementation").
