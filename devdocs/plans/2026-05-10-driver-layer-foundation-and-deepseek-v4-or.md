# Driver Layer Foundation + DeepSeekV4Driver for OpenRouter — Plan 1

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Establish the driver-layer infrastructure (Driver Protocol, registry, three dispatch hooks) and ship the first concrete driver — `DeepSeekV4Driver` — wired up for OpenRouter only. End state: a real DeepSeek V4 Pro request via an OR Connection flows entirely through the driver (capability resolution, request-body construction, response-chunk parsing).

**Architecture:** A new `_drivers/` subpackage under `backend/modules/llm/` defines a `Driver` Protocol (`capability_spec`, `build_request`, `parse_chunk`). A registry holds Driver classes; `match_driver(model_id)` does basename-fnmatch matching (`slug.rsplit("/", 1)[-1]`). Three integration hooks: `_capabilities.py:resolve_capabilities` consults drivers before yaml; `OpenRouterHttpAdapter.stream_completion` checks the driver registry before building the request body and uses the driver's `parse_chunk` when iterating responses.

**Tech Stack:** Python 3.13, Pydantic v2 (existing), pytest. No new third-party deps.

**Companion documents:**
- Spec: [`devdocs/specs/driver-layer.md`](../specs/driver-layer.md)
- Research: [`devdocs/research/deepseek-v4-wire-shapes.md`](../research/deepseek-v4-wire-shapes.md)
- Insight: [`INSIGHTS.md` INS-040](../../INSIGHTS.md)

**Scope of THIS plan (Plan 1 of 5):**
- Driver-layer foundation (protocol, registry, three integration hooks)
- `DeepSeekV4Driver` — capability + request-body + parse-chunk for OpenRouter only
- Tests for registry, capability dispatch, and the OR-only driver behaviour
- Manual smoke test against live OR

**Out of scope (deferred to Plans 2-5):**
- nano-gpt support including `:thinking` slug suffix (Plan 2)
- Novita support including top-level `thinking.type` field (Plan 3)
- Ollama Cloud support (NDJSON, native protocol, `message.thinking`) (Plan 4)
- `force_default_routing` toggle, provider-metadata-merge polish (Plan 5)

**Test invocation note:** All pytest commands in this plan are prefixed with `PYTHONPATH=/home/chris/workspace/chatsune` because `backend/pyproject.toml` is the pytest configfile (rootdir is `backend/`). Without the prefix, imports of `backend.*` and `shared.*` fail. This is a host-only quirk, not a Docker concern.

---

## File Structure

**New files:**

| Path | Purpose |
|---|---|
| `backend/modules/llm/_drivers/__init__.py` | Exports `DRIVER_REGISTRY`, `match_driver` |
| `backend/modules/llm/_drivers/_protocol.py` | `Driver` Protocol class |
| `backend/modules/llm/_drivers/deepseek_v4/__init__.py` | Exports `DeepSeekV4Driver` |
| `backend/modules/llm/_drivers/deepseek_v4/_capability.py` | DSv4 capability spec |
| `backend/modules/llm/_drivers/deepseek_v4/_builders.py` | OpenAICompatBuilder for OR |
| `backend/modules/llm/_drivers/deepseek_v4/_parsers.py` | OpenRouterCanonicalParser |
| `backend/modules/llm/tests/test_driver_registry.py` | Registry + match_driver tests |
| `backend/modules/llm/tests/test_capabilities_with_drivers.py` | `resolve_capabilities` driver-path tests |
| `backend/modules/llm/tests/test_deepseek_v4_driver.py` | DSv4 capability/body/parse tests |

**Modified files:**

| Path | What changes |
|---|---|
| `backend/modules/llm/_capabilities.py` | `resolve_capabilities` consults driver registry before yaml |
| `backend/modules/llm/_adapters/_openrouter_http.py` | `stream_completion` checks driver before `build_request_body`; uses driver's `parse_chunk` instead of `_chunk_to_events` when driver matched |

---

## Task 1: Driver Protocol skeleton

**Files:**
- Create: `backend/modules/llm/_drivers/_protocol.py`

- [ ] **Step 1: Create the file with the Driver Protocol**

```python
"""Driver Protocol — per-model-family request/response handling.

A Driver matches a model family by slug-basename pattern, returns the
capability spec for the model on a given adapter, and provides the
request-body builder and response-chunk parser appropriate for the
(adapter_type, slug) combination.

See devdocs/specs/driver-layer.md for the architecture.
"""
from __future__ import annotations

from typing import Any, ClassVar, Protocol, runtime_checkable

from backend.modules.llm._adapters._events import ProviderStreamEvent
from backend.modules.llm._capabilities import ResolvedCapabilities
from shared.dtos.inference import CompletionRequest


@runtime_checkable
class Driver(Protocol):
    """Per-model-family driver. See spec for semantics."""

    PATTERNS: ClassVar[list[str]]
    """fnmatch patterns matched against the slug basename
    (slug.rsplit('/', 1)[-1]). Multiple patterns supported so naming-
    convention drift across routers does not multiply driver classes."""

    def capability_spec(
        self,
        *,
        adapter_type: str,
        slug: str,
    ) -> ResolvedCapabilities:
        """Return the capability spec for this (adapter, slug).

        For Plan 1 the driver returns its full spec without merging
        provider metadata. Plan 5 introduces None-overridable fields
        (context_length, pricing) and the merge step.
        """
        ...

    def build_request(
        self,
        *,
        adapter_type: str,
        slug: str,
        request: CompletionRequest,
    ) -> dict[str, Any]:
        """Construct the wire-level request body for this (adapter, slug).

        Returns a dict matching the adapter's transport expectations.
        For openrouter_http this is the OpenAI-compat JSON body shape.
        """
        ...

    def parse_chunk(
        self,
        *,
        adapter_type: str,
        slug: str,
        chunk: dict[str, Any],
    ) -> list[ProviderStreamEvent]:
        """Translate a single decoded chunk into zero or more events.

        For Plan 1 (OR only) chunks are post-SSE-decoded JSON dicts.
        Later plans extend to NDJSON (Ollama Cloud) and additional
        stream-key extraction (delta.reasoning_content, message.thinking).
        """
        ...
```

- [ ] **Step 2: Verify the file compiles**

Run: `uv run python -m py_compile backend/modules/llm/_drivers/_protocol.py`
Expected: no output (zero-exit success).

- [ ] **Step 3: Commit**

```bash
git add backend/modules/llm/_drivers/_protocol.py
git commit -m "Add Driver Protocol skeleton for the driver layer"
```

---

## Task 2: Driver Registry + match_driver

**Files:**
- Create: `backend/modules/llm/_drivers/__init__.py`
- Create: `backend/modules/llm/tests/test_driver_registry.py`

- [ ] **Step 1: Write the failing test**

Create `backend/modules/llm/tests/test_driver_registry.py`:

```python
"""Tests for the driver registry and match_driver dispatch."""
from __future__ import annotations

from backend.modules.llm._drivers import DRIVER_REGISTRY, match_driver


class _StubDriver:
    PATTERNS = ["stub-model*"]

    def capability_spec(self, **_):
        raise NotImplementedError

    def build_request(self, **_):
        raise NotImplementedError

    def parse_chunk(self, **_):
        raise NotImplementedError


def test_registry_starts_empty():
    """Plan 1 ships an empty registry until DeepSeekV4Driver is added in Task 8."""
    # NOTE: this test changes after Task 8 — at that point DRIVER_REGISTRY
    # is non-empty. Update the assertion when registering DSv4.
    assert DRIVER_REGISTRY == []


def test_match_driver_returns_none_when_registry_empty():
    assert match_driver("anything/at-all") is None


def test_match_driver_basename_fnmatch(monkeypatch):
    """Driver matching uses the slug basename, not the full slug."""
    monkeypatch.setattr(
        "backend.modules.llm._drivers.DRIVER_REGISTRY",
        [_StubDriver],
    )
    assert match_driver("stub-model-pro") is _StubDriver
    assert match_driver("vendor/stub-model-pro") is _StubDriver
    assert match_driver("vendor/group/stub-model-pro") is _StubDriver
    assert match_driver("stub-model-pro:thinking") is _StubDriver
    assert match_driver("other-model") is None


def test_match_driver_first_match_wins(monkeypatch):
    class _A:
        PATTERNS = ["foo*"]
        def capability_spec(self, **_): raise NotImplementedError
        def build_request(self, **_): raise NotImplementedError
        def parse_chunk(self, **_): raise NotImplementedError

    class _B:
        PATTERNS = ["foo-bar*"]
        def capability_spec(self, **_): raise NotImplementedError
        def build_request(self, **_): raise NotImplementedError
        def parse_chunk(self, **_): raise NotImplementedError

    monkeypatch.setattr(
        "backend.modules.llm._drivers.DRIVER_REGISTRY",
        [_A, _B],
    )
    assert match_driver("foo-bar-baz") is _A
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `PYTHONPATH=/home/chris/workspace/chatsune uv run python -m pytest backend/modules/llm/tests/test_driver_registry.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'backend.modules.llm._drivers'`.

- [ ] **Step 3: Implement the registry**

Create `backend/modules/llm/_drivers/__init__.py`:

```python
"""Driver registry and dispatch.

Plan 1 ships an empty registry; concrete drivers register themselves
into ``DRIVER_REGISTRY`` (see DeepSeekV4Driver in Task 8). Matching is
basename-fnmatch on the slug.

See devdocs/specs/driver-layer.md.
"""
from __future__ import annotations

import fnmatch

from backend.modules.llm._drivers._protocol import Driver

DRIVER_REGISTRY: list[type[Driver]] = []


def match_driver(slug: str) -> type[Driver] | None:
    """Return the first registered driver whose PATTERNS match the slug
    basename, or None.

    The slug basename is everything after the last ``/`` — e.g.
    ``"deepseek/deepseek-v4-pro"`` -> ``"deepseek-v4-pro"``,
    ``"deepseek-v4-pro"`` -> ``"deepseek-v4-pro"``,
    ``"TEE/deepseek-v4-pro"`` -> ``"deepseek-v4-pro"``.

    First match wins, in DRIVER_REGISTRY order.
    """
    basename = slug.rsplit("/", 1)[-1]
    for driver_cls in DRIVER_REGISTRY:
        for pattern in driver_cls.PATTERNS:
            if fnmatch.fnmatch(basename, pattern):
                return driver_cls
    return None
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `PYTHONPATH=/home/chris/workspace/chatsune uv run python -m pytest backend/modules/llm/tests/test_driver_registry.py -v`
Expected: 4 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/modules/llm/_drivers/__init__.py backend/modules/llm/tests/test_driver_registry.py
git commit -m "Add driver registry and match_driver basename-fnmatch dispatch"
```

---

## Task 3: Hook drivers into resolve_capabilities

**Files:**
- Modify: `backend/modules/llm/_capabilities.py:94-112`
- Create: `backend/modules/llm/tests/test_capabilities_with_drivers.py`

- [ ] **Step 1: Write the failing test**

Create `backend/modules/llm/tests/test_capabilities_with_drivers.py`:

```python
"""Tests verifying resolve_capabilities consults the driver registry
before falling through to YAML and adapter heuristics.
"""
from __future__ import annotations

import pytest

from backend.modules.llm._capabilities import (
    DEFAULT_CAPABILITIES,
    ResolvedCapabilities,
    resolve_capabilities,
)
from shared.dtos.llm import (
    ReasoningCapability,
    ReasoningEffortSpec,
    ToolCapability,
)


class _NoOpAdapter:
    """Adapter that gives no capability hint — forces fallthrough."""
    def capability_hint(self, model_id: str):
        return None


_DSv4_DRIVER_SPEC = ResolvedCapabilities(
    reasoning=ReasoningCapability(
        kind="optional",
        effort=ReasoningEffortSpec(buckets=["high", "max"], default_bucket="high"),
        default_on=True,
    ),
    tools=ToolCapability(supported=True, exclusive_with_reasoning=False),
    first_class_support=True,
)


class _StubDSv4Driver:
    PATTERNS = ["deepseek-v4*"]

    def capability_spec(self, *, adapter_type: str, slug: str):
        return _DSv4_DRIVER_SPEC

    def build_request(self, **_):
        raise NotImplementedError

    def parse_chunk(self, **_):
        raise NotImplementedError


def test_no_driver_match_falls_through_to_default(monkeypatch):
    """When no driver matches and no yaml entry matches, behaviour is unchanged."""
    monkeypatch.setattr(
        "backend.modules.llm._drivers.DRIVER_REGISTRY", [],
    )
    result = resolve_capabilities(
        adapter_type="openrouter",
        model_id="some/random-model-no-yaml-match",
        adapter=_NoOpAdapter(),
    )
    assert result == DEFAULT_CAPABILITIES


def test_driver_match_wins_over_yaml(monkeypatch):
    """A matching driver beats a yaml entry that would also match."""
    monkeypatch.setattr(
        "backend.modules.llm._drivers.DRIVER_REGISTRY",
        [_StubDSv4Driver],
    )
    # Even if a yaml entry existed for deepseek-v4, the driver wins.
    result = resolve_capabilities(
        adapter_type="openrouter",
        model_id="deepseek/deepseek-v4-pro",
        adapter=_NoOpAdapter(),
    )
    assert result == _DSv4_DRIVER_SPEC
    assert result.first_class_support is True


def test_driver_basename_match_works_for_unprefixed_slug(monkeypatch):
    """Ollama-Cloud-style unprefixed slugs are matched on the bare basename."""
    monkeypatch.setattr(
        "backend.modules.llm._drivers.DRIVER_REGISTRY",
        [_StubDSv4Driver],
    )
    result = resolve_capabilities(
        adapter_type="ollama_http",
        model_id="deepseek-v4-pro",  # no namespace prefix
        adapter=_NoOpAdapter(),
    )
    assert result == _DSv4_DRIVER_SPEC


def test_driver_passes_adapter_type_and_slug(monkeypatch):
    """The driver receives the adapter_type and slug it was matched against
    (so it can branch internally per-router)."""
    captured = {}

    class _CapturingDriver:
        PATTERNS = ["captured-model*"]
        def capability_spec(self, *, adapter_type: str, slug: str):
            captured["adapter_type"] = adapter_type
            captured["slug"] = slug
            return DEFAULT_CAPABILITIES
        def build_request(self, **_): raise NotImplementedError
        def parse_chunk(self, **_): raise NotImplementedError

    monkeypatch.setattr(
        "backend.modules.llm._drivers.DRIVER_REGISTRY",
        [_CapturingDriver],
    )
    resolve_capabilities(
        adapter_type="some_adapter",
        model_id="vendor/captured-model-x",
        adapter=_NoOpAdapter(),
    )
    assert captured == {
        "adapter_type": "some_adapter",
        "slug": "vendor/captured-model-x",
    }
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `PYTHONPATH=/home/chris/workspace/chatsune uv run python -m pytest backend/modules/llm/tests/test_capabilities_with_drivers.py -v`
Expected: FAIL — `resolve_capabilities` does not consult drivers yet.

- [ ] **Step 3: Modify `resolve_capabilities` to consult drivers first**

Edit `backend/modules/llm/_capabilities.py`. Replace the existing `resolve_capabilities` function (lines 94-112) with the driver-aware version:

```python
def resolve_capabilities(
    *,
    adapter_type: str,
    model_id: str,
    adapter: _AdapterCapabilityProvider,
) -> ResolvedCapabilities:
    # Driver lookup wins — drivers handle premium models with router-
    # specific quirks that the declarative yaml table cannot encode.
    # See devdocs/specs/driver-layer.md and INSIGHTS.md INS-040.
    from backend.modules.llm._drivers import match_driver
    driver_cls = match_driver(model_id)
    if driver_cls is not None:
        return driver_cls().capability_spec(
            adapter_type=adapter_type, slug=model_id,
        )

    # Existing fallback chain: yaml -> adapter heuristic -> default.
    if hint := _yaml_lookup(adapter_type, model_id):
        return ResolvedCapabilities(
            reasoning=hint.reasoning,
            tools=hint.tools,
            first_class_support=True,
        )
    if hint := adapter.capability_hint(model_id):
        return ResolvedCapabilities(
            reasoning=hint.reasoning,
            tools=hint.tools,
            first_class_support=hint.first_class_support,
        )
    return DEFAULT_CAPABILITIES
```

(The local import inside the function avoids an import-cycle: `_drivers/_protocol.py` imports from `_capabilities.py`.)

- [ ] **Step 4: Run the tests to verify they pass**

Run: `PYTHONPATH=/home/chris/workspace/chatsune uv run python -m pytest backend/modules/llm/tests/test_capabilities_with_drivers.py backend/modules/llm/tests/test_driver_registry.py -v`
Expected: all 8 tests PASS (4 from Task 2 + 4 here).

- [ ] **Step 5: Confirm no regression in existing capability behaviour**

Run: `PYTHONPATH=/home/chris/workspace/chatsune uv run python -m pytest backend/modules/llm/tests/ -v`
Expected: all tests PASS, no errors. (If tests fail, the existing capability path was broken — investigate before continuing.)

- [ ] **Step 6: Commit**

```bash
git add backend/modules/llm/_capabilities.py backend/modules/llm/tests/test_capabilities_with_drivers.py
git commit -m "Hook driver registry into resolve_capabilities (driver beats yaml beats default)"
```

---

## Task 4: DeepSeekV4 capability spec

**Files:**
- Create: `backend/modules/llm/_drivers/deepseek_v4/_capability.py`
- Create: `backend/modules/llm/tests/test_deepseek_v4_driver.py`

- [ ] **Step 1: Write the failing test (capability portion only — body/parse added in later tasks)**

Create `backend/modules/llm/tests/test_deepseek_v4_driver.py`:

```python
"""Tests for DeepSeekV4Driver — capability spec, request body, chunk parsing."""
from __future__ import annotations

import pytest

from backend.modules.llm._drivers.deepseek_v4._capability import (
    deepseek_v4_capability_spec,
)


def test_deepseek_v4_capability_spec_for_openrouter():
    spec = deepseek_v4_capability_spec(adapter_type="openrouter_http", slug="deepseek/deepseek-v4-pro")

    assert spec.first_class_support is True
    assert spec.reasoning.kind == "optional"
    assert spec.reasoning.default_on is True
    assert spec.reasoning.effort is not None
    assert spec.reasoning.effort.buckets == ["high", "max"]
    assert spec.reasoning.effort.default_bucket == "high"
    assert spec.tools.supported is True
    assert spec.tools.exclusive_with_reasoning is False


def test_deepseek_v4_capability_spec_is_router_agnostic_for_now():
    """Plan 1 ships only the OR builder; capability spec at this stage is
    identical regardless of (adapter_type, slug). Plans 2-4 may diverge it
    per router (e.g. Novita drops 'max' from effort buckets)."""
    or_spec = deepseek_v4_capability_spec(adapter_type="openrouter_http", slug="deepseek/deepseek-v4-pro")
    nano_spec = deepseek_v4_capability_spec(adapter_type="nano_gpt_http", slug="deepseek/deepseek-v4-pro:thinking")
    assert or_spec == nano_spec
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `PYTHONPATH=/home/chris/workspace/chatsune uv run python -m pytest backend/modules/llm/tests/test_deepseek_v4_driver.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'backend.modules.llm._drivers.deepseek_v4'`.

- [ ] **Step 3: Create the capability module**

Create `backend/modules/llm/_drivers/deepseek_v4/__init__.py` (empty, populated in Task 8):

```python
"""DeepSeek V4 driver (Pro and Flash). Plan 1: OpenRouter only.

See devdocs/specs/driver-layer.md and devdocs/research/deepseek-v4-wire-shapes.md.
"""
```

Create `backend/modules/llm/_drivers/deepseek_v4/_capability.py`:

```python
"""DeepSeek V4 capability spec.

Effort vocabulary is ``[high, max]`` per DeepSeek's official thinking-mode
docs (https://api-docs.deepseek.com/guides/thinking_mode): "low and medium
are mapped to high". We expose those two and only those two — router
extensions (OR's minimal/low/medium, Novita's silent-low) are not exposed
because their behaviour is not specified by DeepSeek.

Plan 1 returns a single capability spec regardless of (adapter_type, slug).
Plans 2-4 may diverge per router (e.g. Novita drops "max" from buckets).
"""
from __future__ import annotations

from backend.modules.llm._capabilities import ResolvedCapabilities
from shared.dtos.llm import (
    ReasoningCapability,
    ReasoningEffortSpec,
    ToolCapability,
)


def deepseek_v4_capability_spec(
    *,
    adapter_type: str,
    slug: str,
) -> ResolvedCapabilities:
    """Return the DeepSeek V4 capability spec for (adapter_type, slug).

    Plan 1: capability is router-agnostic — same spec for OR, nano-gpt,
    Novita, Ollama Cloud. Plans 2+ may branch on adapter_type when the
    Novita "max-rejected" rule lands.
    """
    return ResolvedCapabilities(
        reasoning=ReasoningCapability(
            kind="optional",
            effort=ReasoningEffortSpec(
                buckets=["high", "max"],
                default_bucket="high",
            ),
            default_on=True,
        ),
        tools=ToolCapability(
            supported=True,
            exclusive_with_reasoning=False,
        ),
        first_class_support=True,
    )
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `PYTHONPATH=/home/chris/workspace/chatsune uv run python -m pytest backend/modules/llm/tests/test_deepseek_v4_driver.py -v`
Expected: 2 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/modules/llm/_drivers/deepseek_v4/__init__.py backend/modules/llm/_drivers/deepseek_v4/_capability.py backend/modules/llm/tests/test_deepseek_v4_driver.py
git commit -m "Add DeepSeek V4 capability spec (high/max effort, tools supported)"
```

---

## Task 5: DeepSeekV4 OR-only request body builder

**Files:**
- Create: `backend/modules/llm/_drivers/deepseek_v4/_builders.py`
- Modify: `backend/modules/llm/tests/test_deepseek_v4_driver.py` (append helper + tests)

**Strategy note:** The driver does NOT duplicate the OR adapter's body construction (cache markers, tool translation, temperature handling, ContentPart-to-string conversion). Instead it translates user-facing effort vocabulary (`[high, max]`) into OR's wire vocabulary (`[high, xhigh]`) and delegates to the existing `build_request_body` function in `_openrouter_http.py`. This keeps Plan 1 small and inherits any future improvements to the shared body builder.

- [ ] **Step 1: Append the failing tests + helper fixture**

Append to `backend/modules/llm/tests/test_deepseek_v4_driver.py`:

```python
from shared.dtos.chat import ChatSessionExtras
from shared.dtos.inference import (
    CompletionMessage,
    CompletionRequest,
    ContentPart,
)
from shared.dtos.llm import (
    ReasoningCapability,
    ReasoningEffortSpec,
    ToolCapability,
)

from backend.modules.llm._drivers.deepseek_v4._builders import (
    build_request_for_openrouter,
)


def _make_request(
    *, effort: str | None, reasoning_mode: str = "on",
) -> CompletionRequest:
    """Build a minimal CompletionRequest for builder tests.

    ``effort`` maps to ``extras.reasoning_effort``.
    ``reasoning_mode`` is "on" or "off" — maps to ``extras.reasoning_mode``.
    """
    return CompletionRequest(
        model="deepseek/deepseek-v4-pro",
        messages=[
            CompletionMessage(
                role="user",
                content=[ContentPart(type="text", text="Hello")],
            )
        ],
        reasoning=ReasoningCapability(
            kind="optional",
            effort=ReasoningEffortSpec(
                buckets=["high", "max"], default_bucket="high",
            ),
            default_on=True,
        ),
        tools_capability=ToolCapability(supported=False),
        extras=ChatSessionExtras(
            tools_enabled=False,
            reasoning_mode=reasoning_mode,
            reasoning_effort=effort,
        ),
    )


def test_builder_or_reasoning_off():
    body = build_request_for_openrouter(
        slug="deepseek/deepseek-v4-pro",
        request=_make_request(effort=None, reasoning_mode="off"),
    )
    assert body["model"] == "deepseek/deepseek-v4-pro"
    assert body["stream"] is True
    assert body["reasoning"] == {"enabled": False}


def test_builder_or_reasoning_on_no_effort():
    """Reasoning on without explicit effort: pass through unchanged
    (existing builder emits {"enabled": True} with no effort field;
    OR uses its own default)."""
    body = build_request_for_openrouter(
        slug="deepseek/deepseek-v4-pro",
        request=_make_request(effort=None, reasoning_mode="on"),
    )
    assert body["reasoning"] == {"enabled": True}


def test_builder_or_reasoning_high():
    body = build_request_for_openrouter(
        slug="deepseek/deepseek-v4-pro",
        request=_make_request(effort="high"),
    )
    assert body["reasoning"] == {"enabled": True, "effort": "high"}


def test_builder_or_reasoning_max_translates_to_xhigh():
    """User-effort 'max' maps to OR's 'xhigh' (which OR translates to
    DeepSeek-native max upstream — see research doc)."""
    body = build_request_for_openrouter(
        slug="deepseek/deepseek-v4-pro",
        request=_make_request(effort="max"),
    )
    assert body["reasoning"] == {"enabled": True, "effort": "xhigh"}


def test_builder_or_rejects_unknown_effort():
    with pytest.raises(ValueError, match="effort"):
        build_request_for_openrouter(
            slug="deepseek/deepseek-v4-pro",
            request=_make_request(effort="garbage_xyz"),
        )


def test_builder_or_inherits_message_translation():
    """The builder delegates to build_request_body, so ContentPart-to-string
    message translation is inherited automatically (the existing
    _translate_message helper converts list[ContentPart] to a string)."""
    body = build_request_for_openrouter(
        slug="deepseek/deepseek-v4-pro",
        request=_make_request(effort="high"),
    )
    assert len(body["messages"]) == 1
    assert body["messages"][0]["role"] == "user"
    assert body["messages"][0]["content"] == "Hello"
```

- [ ] **Step 2: Run the appended tests to verify they fail**

Run: `PYTHONPATH=/home/chris/workspace/chatsune uv run python -m pytest backend/modules/llm/tests/test_deepseek_v4_driver.py -v`
Expected: 6 new failures (ImportError for `_builders` module).

- [ ] **Step 3: Implement the OR builder**

Create `backend/modules/llm/_drivers/deepseek_v4/_builders.py`:

```python
"""Request-body builders for DeepSeek V4.

Plan 1 ships only the OpenRouter builder, which delegates to the
existing OpenAI-compat builder in ``_openrouter_http.build_request_body``
after translating user-facing effort vocabulary into OR's wire
vocabulary.

User-facing effort vocabulary (per DeepSeek's thinking-mode docs):
    [high, max]

OR wire vocabulary (per OR's ``reasoning.effort``):
    [none, minimal, low, medium, high, xhigh]

DSv4-specific translation (Plan 1):
    user "high" -> wire "high"
    user "max"  -> wire "xhigh"
                   (OR's xhigh maps to DeepSeek-native max via upstream
                   system-prompt injection — see research doc)
"""
from __future__ import annotations

from typing import Any

from shared.dtos.inference import CompletionRequest


# User-effort -> OR wire effort. ``None`` and reasoning_mode="off" are
# handled separately (no translation, delegate unchanged).
_OR_EFFORT_MAP: dict[str, str] = {
    "high": "high",
    "max": "xhigh",
}


def build_request_for_openrouter(
    *, slug: str, request: CompletionRequest,
) -> dict[str, Any]:
    """Build the OR request body for DeepSeek V4 with effort translation.

    Strategy: translate the user-effort if needed, then delegate to the
    existing ``build_request_body`` so cache-marker, tool, message-content
    handling are inherited automatically.

    Raises ``ValueError`` when ``extras.reasoning_effort`` is set to a
    value outside the DSv4 supported buckets ``[high, max]``. Silent
    degradation is the exact failure mode this driver layer is meant to
    prevent.
    """
    # Local import to avoid a circular dependency at module load time
    # (drivers depend on adapter helpers; adapter consults drivers at
    # call time).
    from backend.modules.llm._adapters._openrouter_http import (
        build_request_body,
    )

    # Reasoning off OR no explicit effort: delegate unchanged.
    if (
        request.extras.reasoning_mode == "off"
        or request.extras.reasoning_effort is None
    ):
        return build_request_body(request)

    # Reasoning on AND effort explicit: translate or reject.
    user_effort = request.extras.reasoning_effort
    if user_effort not in _OR_EFFORT_MAP:
        raise ValueError(
            f"DeepSeek V4 effort {user_effort!r} not in supported "
            f"buckets {list(_OR_EFFORT_MAP.keys())}; cannot translate "
            f"for OpenRouter"
        )

    # Substitute the effort in extras and delegate. Pydantic v2 model_copy.
    translated = request.model_copy(
        update={
            "extras": request.extras.model_copy(
                update={"reasoning_effort": _OR_EFFORT_MAP[user_effort]},
            ),
        },
    )
    return build_request_body(translated)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `PYTHONPATH=/home/chris/workspace/chatsune uv run python -m pytest backend/modules/llm/tests/test_deepseek_v4_driver.py -v`
Expected: 8 tests PASS (2 capability + 6 builder).

- [ ] **Step 5: Commit**

```bash
git add backend/modules/llm/_drivers/deepseek_v4/_builders.py backend/modules/llm/tests/test_deepseek_v4_driver.py
git commit -m "Add DeepSeek V4 request-body builder for OpenRouter (high/max -> high/xhigh)"
```

---

## Task 6: DeepSeekV4 OR-only chunk parser

**Files:**
- Create: `backend/modules/llm/_drivers/deepseek_v4/_parsers.py`
- Modify: `backend/modules/llm/tests/test_deepseek_v4_driver.py` (append tests)

- [ ] **Step 1: Append the failing tests**

Append to `backend/modules/llm/tests/test_deepseek_v4_driver.py`:

```python
from backend.modules.llm._adapters._events import (
    ContentDelta,
    StreamDone,
    ThinkingDelta,
)
from backend.modules.llm._drivers.deepseek_v4._parsers import (
    parse_chunk_openrouter,
)


def test_parser_or_extracts_visible_content():
    chunk = {
        "id": "gen-1", "provider": "DeepInfra",
        "choices": [{"index": 0, "delta": {"content": "Hello", "role": "assistant"}}],
    }
    events = parse_chunk_openrouter(chunk=chunk)
    assert any(isinstance(e, ContentDelta) and e.delta == "Hello" for e in events)


def test_parser_or_extracts_reasoning_from_delta_reasoning():
    """OR's canonical CoT key is delta.reasoning (often paired with reasoning_details).
    The driver maps it to ThinkingDelta (the existing event class name; reasoning
    and thinking are used interchangeably in the codebase — INS-038)."""
    chunk = {
        "id": "gen-1", "provider": "DeepInfra",
        "choices": [{"index": 0, "delta": {
            "content": "",
            "role": "assistant",
            "reasoning": "We need to think...",
            "reasoning_details": [
                {"type": "reasoning.text", "text": "We need to think...", "format": "unknown", "index": 0}
            ],
        }}],
    }
    events = parse_chunk_openrouter(chunk=chunk)
    assert any(
        isinstance(e, ThinkingDelta) and e.delta == "We need to think..."
        for e in events
    )


def test_parser_or_emits_stream_done_with_usage_and_reasoning_tokens():
    chunk = {
        "id": "gen-1", "provider": "DeepInfra",
        "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
        "usage": {
            "prompt_tokens": 19,
            "completion_tokens": 800,
            "total_tokens": 819,
            "completion_tokens_details": {"reasoning_tokens": 360, "image_tokens": 0, "audio_tokens": 0},
        },
    }
    events = parse_chunk_openrouter(chunk=chunk)
    done = next((e for e in events if isinstance(e, StreamDone)), None)
    assert done is not None
    assert done.input_tokens == 19
    assert done.output_tokens == 800
    assert done.reasoning_tokens == 360


def test_parser_or_handles_chunk_with_no_actionable_delta():
    """Chunks with empty delta and no finish_reason produce no events."""
    chunk = {"id": "gen-1", "choices": [{"index": 0, "delta": {}}]}
    events = parse_chunk_openrouter(chunk=chunk)
    assert events == []
```

- [ ] **Step 2: Run the appended tests to verify they fail**

Run: `PYTHONPATH=/home/chris/workspace/chatsune uv run python -m pytest backend/modules/llm/tests/test_deepseek_v4_driver.py -v`
Expected: 4 new failures (ImportError on `_parsers`).

- [ ] **Step 3: Implement the OR parser**

Create `backend/modules/llm/_drivers/deepseek_v4/_parsers.py`:

```python
"""Response-chunk parsers for DeepSeek V4.

Plan 1 ships only the OpenRouter parser, which reads the OR-canonical
CoT key ``delta.reasoning`` (often paired with ``delta.reasoning_details``).
Plans 3-4 add the DeepSeek-native parser for Novita
(``delta.reasoning_content``) and the Ollama-native parser for Ollama
Cloud (``message.thinking`` over NDJSON).

This parser is a thin specialisation: the existing
``_openrouter_http._chunk_to_events`` covers most of what we need; we
duplicate the logic here so the driver fully owns the response shape
without touching the adapter's internal helper. Tool-call accumulation
is intentionally out of scope for Plan 1 — DSv4 + tools is a Plan 2+
concern (covered in the spec's worked example) but not yet wired here.
"""
from __future__ import annotations

from typing import Any

from backend.modules.llm._adapters._events import (
    ContentDelta,
    ProviderStreamEvent,
    StreamDone,
    ThinkingDelta,
)


def parse_chunk_openrouter(*, chunk: dict[str, Any]) -> list[ProviderStreamEvent]:
    """Translate one OR SSE chunk dict into ProviderStreamEvents."""
    events: list[ProviderStreamEvent] = []

    choices = chunk.get("choices") or []
    if choices:
        delta = choices[0].get("delta") or {}

        # Visible content fragment
        content = delta.get("content")
        if content:
            events.append(ContentDelta(delta=content))

        # OR-canonical reasoning fragment (mapped to ThinkingDelta —
        # "reasoning" and "thinking" are used interchangeably in the
        # codebase per INS-038).
        reasoning = delta.get("reasoning")
        if reasoning:
            events.append(ThinkingDelta(delta=reasoning))

    # Terminal usage block (chunk with finish_reason or final usage info)
    usage = chunk.get("usage")
    if usage is not None:
        details = usage.get("completion_tokens_details") or {}
        events.append(StreamDone(
            input_tokens=usage.get("prompt_tokens"),
            output_tokens=usage.get("completion_tokens"),
            reasoning_tokens=details.get("reasoning_tokens"),
        ))

    return events
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `PYTHONPATH=/home/chris/workspace/chatsune uv run python -m pytest backend/modules/llm/tests/test_deepseek_v4_driver.py -v`
Expected: 11 tests PASS (2 capability + 5 builder + 4 parser).

- [ ] **Step 5: Commit**

```bash
git add backend/modules/llm/_drivers/deepseek_v4/_parsers.py backend/modules/llm/tests/test_deepseek_v4_driver.py
git commit -m "Add DeepSeek V4 chunk parser for OpenRouter (delta.reasoning + usage)"
```

---

## Task 7: Wire DeepSeekV4Driver class + register

**Files:**
- Modify: `backend/modules/llm/_drivers/deepseek_v4/__init__.py`
- Modify: `backend/modules/llm/_drivers/__init__.py`
- Modify: `backend/modules/llm/tests/test_driver_registry.py` (one assertion adjusted)
- Modify: `backend/modules/llm/tests/test_deepseek_v4_driver.py` (append integration tests)

- [ ] **Step 1: Append the failing integration tests**

Append to `backend/modules/llm/tests/test_deepseek_v4_driver.py`:

```python
from backend.modules.llm._drivers import match_driver
from backend.modules.llm._drivers.deepseek_v4 import DeepSeekV4Driver


def test_dsv4_driver_class_matches_or_slugs():
    assert match_driver("deepseek/deepseek-v4-pro") is DeepSeekV4Driver
    assert match_driver("deepseek/deepseek-v4-flash") is DeepSeekV4Driver


def test_dsv4_driver_class_matches_unprefixed_ollama_slug():
    assert match_driver("deepseek-v4-pro") is DeepSeekV4Driver


def test_dsv4_driver_capability_spec_via_class():
    d = DeepSeekV4Driver()
    spec = d.capability_spec(adapter_type="openrouter_http", slug="deepseek/deepseek-v4-pro")
    assert spec.reasoning.effort.buckets == ["high", "max"]


def test_dsv4_driver_build_request_via_class_for_or():
    d = DeepSeekV4Driver()
    body = d.build_request(
        adapter_type="openrouter_http",
        slug="deepseek/deepseek-v4-pro",
        request=_make_request(effort="max"),
    )
    assert body["reasoning"] == {"effort": "xhigh"}


def test_dsv4_driver_build_request_for_unsupported_adapter_raises():
    """Plan 1 only supports OR. nano-gpt/Novita/Ollama come in Plans 2-4."""
    d = DeepSeekV4Driver()
    with pytest.raises(NotImplementedError, match="adapter_type"):
        d.build_request(
            adapter_type="nano_gpt_http",
            slug="deepseek/deepseek-v4-pro:thinking",
            request=_make_request(effort="high"),
        )
```

Also adjust the existing assertion in `test_driver_registry.py:test_registry_starts_empty`. Change:

```python
def test_registry_starts_empty():
    """Plan 1 ships an empty registry until DeepSeekV4Driver is added in Task 8."""
    assert DRIVER_REGISTRY == []
```

…to:

```python
def test_registry_contains_dsv4():
    """After Task 7, DRIVER_REGISTRY contains DeepSeekV4Driver."""
    from backend.modules.llm._drivers.deepseek_v4 import DeepSeekV4Driver
    assert DeepSeekV4Driver in DRIVER_REGISTRY
```

- [ ] **Step 2: Run the tests to verify the new ones fail**

Run: `PYTHONPATH=/home/chris/workspace/chatsune uv run python -m pytest backend/modules/llm/tests/test_deepseek_v4_driver.py backend/modules/llm/tests/test_driver_registry.py -v`
Expected: 5 new failures (DeepSeekV4Driver class not yet defined; registry empty).

- [ ] **Step 3: Define DeepSeekV4Driver and register it**

Replace the contents of `backend/modules/llm/_drivers/deepseek_v4/__init__.py` with:

```python
"""DeepSeek V4 driver (Pro and Flash). Plan 1: OpenRouter only.

See devdocs/specs/driver-layer.md and devdocs/research/deepseek-v4-wire-shapes.md.
"""
from __future__ import annotations

from typing import Any

from backend.modules.llm._adapters._events import ProviderStreamEvent
from backend.modules.llm._capabilities import ResolvedCapabilities
from backend.modules.llm._drivers.deepseek_v4._builders import (
    build_request_for_openrouter,
)
from backend.modules.llm._drivers.deepseek_v4._capability import (
    deepseek_v4_capability_spec,
)
from backend.modules.llm._drivers.deepseek_v4._parsers import (
    parse_chunk_openrouter,
)
from shared.dtos.inference import CompletionRequest


class DeepSeekV4Driver:
    """Driver for DeepSeek V4 Pro and DeepSeek V4 Flash.

    Plan 1: OpenRouter only. Plans 2-4 add nano-gpt, Novita, Ollama Cloud.
    """

    PATTERNS: list[str] = [
        "deepseek-v4-pro*",
        "deepseek-v4-flash*",
    ]

    def capability_spec(
        self, *, adapter_type: str, slug: str,
    ) -> ResolvedCapabilities:
        return deepseek_v4_capability_spec(adapter_type=adapter_type, slug=slug)

    def build_request(
        self, *, adapter_type: str, slug: str, request: CompletionRequest,
    ) -> dict[str, Any]:
        if adapter_type == "openrouter_http":
            return build_request_for_openrouter(slug=slug, request=request)
        raise NotImplementedError(
            f"DeepSeekV4Driver: adapter_type={adapter_type!r} not supported "
            f"in Plan 1 (only openrouter_http). See Plans 2-4 for the rest."
        )

    def parse_chunk(
        self, *, adapter_type: str, slug: str, chunk: dict[str, Any],
    ) -> list[ProviderStreamEvent]:
        if adapter_type == "openrouter_http":
            return parse_chunk_openrouter(chunk=chunk)
        raise NotImplementedError(
            f"DeepSeekV4Driver: adapter_type={adapter_type!r} not supported "
            f"in Plan 1 (only openrouter_http). See Plans 2-4 for the rest."
        )
```

Update `backend/modules/llm/_drivers/__init__.py` — replace its contents with:

```python
"""Driver registry and dispatch.

See devdocs/specs/driver-layer.md.
"""
from __future__ import annotations

import fnmatch

from backend.modules.llm._drivers._protocol import Driver
from backend.modules.llm._drivers.deepseek_v4 import DeepSeekV4Driver

DRIVER_REGISTRY: list[type[Driver]] = [
    DeepSeekV4Driver,
]


def match_driver(slug: str) -> type[Driver] | None:
    """Return the first registered driver whose PATTERNS match the slug
    basename, or None.

    See match_driver docstring in Task 2 for the basename semantics.
    """
    basename = slug.rsplit("/", 1)[-1]
    for driver_cls in DRIVER_REGISTRY:
        for pattern in driver_cls.PATTERNS:
            if fnmatch.fnmatch(basename, pattern):
                return driver_cls
    return None
```

- [ ] **Step 4: Run the full driver test suite to verify everything passes**

Run: `PYTHONPATH=/home/chris/workspace/chatsune uv run python -m pytest backend/modules/llm/tests/test_deepseek_v4_driver.py backend/modules/llm/tests/test_driver_registry.py backend/modules/llm/tests/test_capabilities_with_drivers.py -v`
Expected: all tests PASS (4 registry + 4 capability dispatch + 16 dsv4 = 24).

- [ ] **Step 5: Run the full LLM module test suite to confirm no regression**

Run: `PYTHONPATH=/home/chris/workspace/chatsune uv run python -m pytest backend/modules/llm/tests/ -v`
Expected: all tests PASS, no errors.

- [ ] **Step 6: Commit**

```bash
git add backend/modules/llm/_drivers/__init__.py backend/modules/llm/_drivers/deepseek_v4/__init__.py backend/modules/llm/tests/test_deepseek_v4_driver.py backend/modules/llm/tests/test_driver_registry.py
git commit -m "Wire DeepSeekV4Driver class and register in DRIVER_REGISTRY (OR only)"
```

---

## Task 8: Hook driver into OpenRouterHttpAdapter.stream_completion

**Files:**
- Modify: `backend/modules/llm/_adapters/_openrouter_http.py:552-` (`stream_completion`)

**Why this task is invasive but small:** the driver layer needs to intercept two points inside `stream_completion`: (1) before `build_request_body(request)` is called, check whether a driver matches and use its `build_request` instead; (2) inside the chunk loop, when a chunk has been decoded from SSE, ask the driver to parse it instead of `_chunk_to_events`. Everything else (HTTP client, SSE decoding, retry, auth) stays exactly as-is.

- [ ] **Step 1: Read the current stream_completion implementation**

Read: `backend/modules/llm/_adapters/_openrouter_http.py:552-748`. Identify:
- The exact line where `build_request_body(request)` is called.
- The exact line where `_chunk_to_events(...)` is called inside the chunk loop.
- Any local variables passed to `_chunk_to_events` (tool-call accumulator, etc.) — Plan 1's parser does not handle tool calls, so when the driver path is taken, the tool-call accumulator can be skipped (DSv4 + tools is a Plan 2+ concern).

- [ ] **Step 2: Modify `stream_completion` to be driver-aware**

Near the top of `stream_completion` (right after argument unpacking, before the request body is built), add:

```python
from backend.modules.llm._drivers import match_driver  # local import, avoids cycle

driver_cls = match_driver(request.model)
driver = driver_cls() if driver_cls is not None else None
```

Then where `build_request_body(request)` is called, replace it with:

```python
if driver is not None:
    body = driver.build_request(
        adapter_type=self.adapter_type,
        slug=request.model,
        request=request,
    )
else:
    body = build_request_body(request)
```

The existing call site (currently `_openrouter_http.py:707`) reads:

```python
for event in _chunk_to_events(parsed, acc):
    ...
```

where `acc` is the local `_ToolCallAccumulator` instance. Replace that single line with:

```python
chunk_events = (
    driver.parse_chunk(
        adapter_type=self.adapter_type,
        slug=request.model,
        chunk=parsed,
    )
    if driver is not None
    else _chunk_to_events(parsed, acc)
)
for event in chunk_events:
    ...
```

Keep the rest of `stream_completion` — auth headers, HTTP transport, SSE decoding, retry logic, exception handling — exactly as-is.

**Tool-call handling note:** `_ToolCallAccumulator` is built up inside `_chunk_to_events` for the non-driver path. The driver's `parse_chunk` does not currently emit `ToolCallEvent`s for DSv4 + tools (out of scope for Plan 1; addressed in Plans 2-4 if/when DSv4 tool-call paths are exercised). For Plan 1 the driver path bypasses the tool accumulator — DSv4 requests in this plan do not exercise tools.

- [ ] **Step 3: Verify the file compiles**

Run: `uv run python -m py_compile backend/modules/llm/_adapters/_openrouter_http.py`
Expected: no output (zero-exit success).

- [ ] **Step 4: Run the full LLM test suite to verify no regression**

Run: `PYTHONPATH=/home/chris/workspace/chatsune uv run python -m pytest backend/modules/llm/tests/ -v`
Expected: all tests still PASS. (Existing OR adapter tests, if any, must not break — the driver path is additive.)

- [ ] **Step 5: Commit**

```bash
git add backend/modules/llm/_adapters/_openrouter_http.py
git commit -m "Hook driver layer into OpenRouter adapter stream_completion"
```

---

## Task 9: Manual smoke test against live OpenRouter

**Files:**
- No code changes — pure manual verification step.

This task validates the full end-to-end path against the real OR API. The test key is at `.or-test-key` in the repo root (gitignored, plain text).

- [ ] **Step 1: Confirm the dev backend is running**

The implementing agent should NOT start the backend. Ask the user to confirm the backend is running, or to start it via `pnpm dev` (or whatever the project's dev command is). The backend must be reachable at the standard port.

- [ ] **Step 2: Configure an OR Connection with DS V4 Pro**

In the running app:
1. Add a new LLM Connection of type "OpenRouter".
2. Use `cat .or-test-key` to grab the API key into the Connection config.
3. Save the Connection.
4. Open the model picker and select `deepseek/deepseek-v4-pro`.

- [ ] **Step 3: Enable reasoning at user effort = "max"**

Send a reasoning-triggering prompt. Suggested:

> Why are there infinitely many prime numbers? Give a step-by-step proof.

- [ ] **Step 4: Verify backend logs show driver routing**

In the backend log (the JSON-structured Claude-oriented log per CLAUDE.md), look for log lines that confirm:

1. **Capability resolution**: a line indicating the capability spec for `deepseek/deepseek-v4-pro` was resolved (the existing log infra should show first_class_support=True).
2. **Reasoning tokens at stream end**: per INS-038, the inference summary line should now include `reasoning_tokens=…` with a non-zero value.

If no driver-specific log lines exist yet (Plan 1 doesn't add new logs), at minimum verify the request body sent to OR contains `reasoning.effort=xhigh` (not `high`). Use the existing LLM_TRACE log if available, or add a one-shot debug print in `stream_completion` after `body = ...`.

- [ ] **Step 5: Verify reasoning content is rendered in the UI**

The chat UI should show the reasoning trace (per INS-034 toggle / capability_hint affordances) and the final visible answer. The reasoning trace should be substantive (~hundreds of chars, not empty).

- [ ] **Step 6: Toggle reasoning OFF and re-send**

Disable reasoning via the UI toggle. Re-send the same prompt. Backend log should now show the request body had `reasoning.enabled=false` and the response stream contained no `reasoning` delta.

- [ ] **Step 7: Document any deviations**

If anything unexpected happens (unexpected effort vocabulary, body shape mismatch, parse errors), capture the deviation in `devdocs/research/deepseek-v4-wire-shapes.md` as a follow-up note dated today, and either:

- Fix in this plan (extend the relevant task) if the fix is small, or
- Open a follow-up note in INSIGHTS.md for Plan 2+ to address.

- [ ] **Step 8: Commit any verification notes**

If you wrote follow-up notes:

```bash
git add devdocs/research/deepseek-v4-wire-shapes.md INSIGHTS.md
git commit -m "Plan 1 smoke test: verification notes for DeepSeekV4Driver via OR"
```

If no notes were needed, no commit is necessary for this task.

---

## Self-review checklist (run before declaring Plan 1 complete)

- [ ] All tests pass: `PYTHONPATH=/home/chris/workspace/chatsune uv run python -m pytest backend/modules/llm/tests/ -v`
- [ ] No untracked files left in `backend/modules/llm/_drivers/`
- [ ] All commits are present (Tasks 1, 2, 3, 4, 5, 6, 7, 8 each produced at least one commit)
- [ ] `INSIGHTS.md`, `devdocs/specs/driver-layer.md`, `devdocs/research/deepseek-v4-wire-shapes.md` are unchanged unless Task 9 deviation notes were added
- [ ] No changes outside the in-scope files listed in the **File Structure** section (no surprise edits to chat module, frontend, etc.)
- [ ] `nano.json` (the user's curl-output dump) is still untracked and was NOT committed
- [ ] Manual smoke test (Task 9) was either completed by the user or explicitly scheduled by them as a follow-up
