# Kimi K2.5 / K2.6 First-Class Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `KimiK2Driver` so Kimi K2.5 and K2.6 are first-class models on Ollama Cloud and Novita AI, with correct per-(adapter, slug) capability surfacing and verified tool-call streaming.

**Architecture:** New driver under `backend/modules/llm/_drivers/kimi_k2/`, directory layout (DSv4-style). Slug-pattern routing via `PATTERNS = ["kimi-k2.5*", "kimi-k2.6*"]`. Capability spec branches on `(adapter_type, slug)`: Ollama K2.5/K2.6 → `optional`; Novita K2.5 → `no_reasoning`; Novita K2.6 → `always_on`. Builders delegate to existing adapter builders (no mutation needed — base builders already handle the three kinds correctly). Parsers mirror DSv4's Ollama and Novita parsers; logic duplicated per driver-layer spec.

**Tech Stack:** Python 3.12, FastAPI, Pydantic v2, pytest. Existing infrastructure: `backend/modules/llm/_drivers/` (driver registry), `backend/modules/llm/_adapters/_ollama_http.py` and `_novita_http.py` (transport adapters with `build_request_body` helpers), `backend/modules/llm/_drivers/_tool_call_accumulator.py` (OpenAI-fragmented tool-call state).

**Spec:** [`devdocs/specs/2026-05-12-kimi-k2-first-class-design.md`](../specs/2026-05-12-kimi-k2-first-class-design.md)
**Research basis:** [`devdocs/research/kimi-k2-wire-shapes.md`](../research/kimi-k2-wire-shapes.md)
**Branch:** `feat/kimi-k2-first-class` (already created)

---

## Pre-flight: discover existing patterns

Read the following before starting, to mirror existing conventions:

- `backend/modules/llm/_drivers/mimo_v25.py` — single-file driver pattern (single adapter)
- `backend/modules/llm/_drivers/deepseek_v4/__init__.py` — multi-adapter driver class
- `backend/modules/llm/_drivers/deepseek_v4/_parsers.py` — reference for ollama and novita parsers
- `backend/modules/llm/_drivers/_protocol.py` — Driver protocol
- `backend/modules/llm/tests/test_mimo_v25_driver.py` — closest test layout (capability + builder + parser)
- `backend/modules/llm/tests/test_driver_registry.py` — registry presence pattern

**Test invocation rule (per memory `feedback_db_tests_on_host`):** these tests do not touch MongoDB, so they run fine on the host. Use the pytest invocation with explicit `PYTHONPATH`:

```bash
PYTHONPATH=/home/chris/workspace/chatsune uv run --project backend pytest backend/modules/llm/tests/test_kimi_k2_driver.py -v
```

(`PYTHONPATH` is required because `backend/pyproject.toml` is the configfile so pytest's rootdir is `backend/`, but the source imports use `backend.modules.…` and `shared.…` — see memory `feedback_pytest_rootdir_quirk`.)

---

## File Structure

**Files to create:**

- `backend/modules/llm/_drivers/kimi_k2/__init__.py` — `KimiK2Driver` class, dispatcher across adapters, `_kimi_version` helper, `_unsupported_adapter` helper.
- `backend/modules/llm/_drivers/kimi_k2/_capability.py` — `kimi_k2_capability_spec(*, adapter_type, slug)`.
- `backend/modules/llm/_drivers/kimi_k2/_builders.py` — `build_request_for_ollama_cloud`, `build_request_for_novita`.
- `backend/modules/llm/_drivers/kimi_k2/_parsers.py` — `parse_chunk_ollama_cloud`, `parse_chunk_novita` (logic mirrored from DSv4, NOT imported).
- `backend/modules/llm/tests/test_kimi_k2_driver.py` — full coverage: patterns, capabilities, builders, parsers, registry integration, per-instance state.

**Files to modify:**

- `backend/modules/llm/_drivers/__init__.py` — append `KimiK2Driver` to `DRIVER_REGISTRY` and add import.
- `backend/modules/llm/tests/test_driver_registry.py` — add `test_registry_contains_kimi`.

**Files NOT modified:**

- `backend/modules/llm/data/model_capabilities.yaml` — driver wins over YAML in dispatcher, mirrors MiMo/DSv4.
- Frontend — no UI changes; existing capability surface drives reasoning-toggle visibility.
- `backend/modules/llm/_adapters/_ollama_http.py`, `_novita_http.py` — adapter builders already write `think` (Ollama) or `reasoning` (Novita) correctly per `reasoning.kind`. Driver supplies the kind via capability spec; adapter does the rest.

---

## Task 1: Scaffold driver skeleton, register, match-driver test

**Files:**

- Create: `backend/modules/llm/_drivers/kimi_k2/__init__.py`
- Create: `backend/modules/llm/_drivers/kimi_k2/_capability.py`
- Create: `backend/modules/llm/_drivers/kimi_k2/_builders.py`
- Create: `backend/modules/llm/_drivers/kimi_k2/_parsers.py`
- Create: `backend/modules/llm/tests/test_kimi_k2_driver.py`
- Modify: `backend/modules/llm/_drivers/__init__.py`
- Modify: `backend/modules/llm/tests/test_driver_registry.py`

- [ ] **Step 1: Write the failing match_driver tests**

Create `backend/modules/llm/tests/test_kimi_k2_driver.py` with this content (we add more tests in later tasks, this is the starting skeleton):

```python
"""Tests for KimiK2Driver — capability spec, request body, chunk parsing.

Mirrors the structure of test_mimo_v25_driver.py. Kimi K2 is a
two-adapter (Ollama Cloud + Novita) integration with per-(adapter, slug)
reasoning capability differences:

- Ollama Cloud (k2.5, k2.6): optional reasoning, ``think: true/false``
- Novita k2.5: no_reasoning (provider returns empty reasoning_content)
- Novita k2.6: always_on (provider ignores reasoning toggle)

See devdocs/research/kimi-k2-wire-shapes.md for the wire-shape probes
that motivate this matrix.
"""
from __future__ import annotations

import pytest

from backend.modules.llm._drivers import match_driver
from backend.modules.llm._drivers.kimi_k2 import KimiK2Driver


_OLLAMA_K25 = "kimi-k2.5"
_OLLAMA_K26 = "kimi-k2.6"
_NOVITA_K25 = "moonshotai/kimi-k2.5"
_NOVITA_K26 = "moonshotai/kimi-k2.6"


# --- match_driver ----------------------------------------------------------


def test_match_driver_ollama_k25() -> None:
    assert match_driver(_OLLAMA_K25) is KimiK2Driver


def test_match_driver_ollama_k26() -> None:
    assert match_driver(_OLLAMA_K26) is KimiK2Driver


def test_match_driver_novita_k25_with_publisher_prefix() -> None:
    assert match_driver(_NOVITA_K25) is KimiK2Driver


def test_match_driver_novita_k26_with_publisher_prefix() -> None:
    assert match_driver(_NOVITA_K26) is KimiK2Driver


def test_match_driver_does_not_match_older_kimi() -> None:
    """K2.4 and earlier are not first-class — the driver targets K2.5+."""
    assert match_driver("kimi-k2.4") is None
    assert match_driver("moonshotai/kimi-k2") is None


def test_match_driver_does_not_match_unrelated_moonshot_model() -> None:
    assert match_driver("moonshotai/kimi-vl") is None
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
PYTHONPATH=/home/chris/workspace/chatsune uv run --project backend pytest backend/modules/llm/tests/test_kimi_k2_driver.py -v
```

Expected: ImportError on `from backend.modules.llm._drivers.kimi_k2 import KimiK2Driver` — module does not exist yet.

- [ ] **Step 3: Create empty stubs**

Create `backend/modules/llm/_drivers/kimi_k2/_capability.py`:

```python
"""Capability spec for Kimi K2.5 and K2.6 on Ollama Cloud and Novita.

See devdocs/research/kimi-k2-wire-shapes.md for the wire-shape probes
that produced this matrix.
"""
from __future__ import annotations


def kimi_k2_capability_spec(*, adapter_type: str, slug: str):
    raise NotImplementedError("filled in Task 2")
```

Create `backend/modules/llm/_drivers/kimi_k2/_builders.py`:

```python
"""Request-body builders for Kimi K2.5 / K2.6.

Wire support: Ollama Cloud (``ollama_http``) and Novita (``novita_http``).
Logic: delegate to the existing adapter ``build_request_body`` helpers.
The base builders already handle the three reasoning kinds correctly
(per ``_ollama_http.build_request_body`` and ``_novita_http.build_request_body``
docstrings); the driver's capability spec determines which branch runs.
"""
from __future__ import annotations

from typing import Any

from shared.dtos.inference import CompletionRequest


def build_request_for_ollama_cloud(
    *, slug: str, request: CompletionRequest,
) -> dict[str, Any]:
    raise NotImplementedError("filled in Task 3")


def build_request_for_novita(
    *, slug: str, request: CompletionRequest,
) -> dict[str, Any]:
    raise NotImplementedError("filled in Task 3")
```

Create `backend/modules/llm/_drivers/kimi_k2/_parsers.py`:

```python
"""Response-chunk parsers for Kimi K2.5 / K2.6.

Per the driver-layer spec, each driver fully owns its chunk semantics —
the logic in this file is structurally identical to DSv4's Ollama and
Novita parsers but is intentionally NOT imported from there. Duplication
prevents a Kimi change from accidentally affecting DSv4 (and vice versa).
"""
from __future__ import annotations

import json
from typing import Any
from uuid import uuid4

from backend.modules.llm._adapters._events import (
    ContentDelta,
    ProviderStreamEvent,
    StreamDone,
    StreamRefused,
    ThinkingDelta,
    ToolCallEvent,
)
from backend.modules.llm._drivers._tool_call_accumulator import (
    ToolCallAccumulator,
)


# Local copy of refusal markers — keeps the driver free of adapter
# internals (per the Driver-Layer spec boundary). Same set as MiMo/DSv4.
_REFUSAL_REASONS: frozenset[str] = frozenset({"content_filter", "refusal"})


def parse_chunk_ollama_cloud(*, chunk: dict[str, Any]) -> list[ProviderStreamEvent]:
    raise NotImplementedError("filled in Task 4")


def parse_chunk_novita(
    *, chunk: dict[str, Any], tool_acc: ToolCallAccumulator,
) -> list[ProviderStreamEvent]:
    raise NotImplementedError("filled in Task 5")
```

Create `backend/modules/llm/_drivers/kimi_k2/__init__.py`:

```python
"""Kimi K2 driver (K2.5 + K2.6) on Ollama Cloud and Novita.

Wire support: ``ollama_http``, ``novita_http``. Other adapter_types
raise ``NotImplementedError`` — Kimi is not exposed elsewhere today.

Capability matrix (probed 2026-05-12):

| Slug basename | adapter_type    | reasoning.kind | tools |
|---------------|-----------------|----------------|-------|
| kimi-k2.5*    | ollama_http     | optional       | true  |
| kimi-k2.6*    | ollama_http     | optional       | true  |
| kimi-k2.5*    | novita_http     | no_reasoning   | true  |
| kimi-k2.6*    | novita_http     | always_on      | true  |

Kimi does NOT exhibit the MiMo-on-Novita chat-template bug; tool-call
roundtrip succeeds on every cell.

See devdocs/specs/driver-layer.md and
devdocs/research/kimi-k2-wire-shapes.md.
"""
from __future__ import annotations

from typing import Any

from backend.modules.llm._adapters._events import ProviderStreamEvent
from backend.modules.llm._capabilities import ResolvedCapabilities
from backend.modules.llm._drivers._tool_call_accumulator import (
    ToolCallAccumulator,
)
from backend.modules.llm._drivers.kimi_k2._builders import (
    build_request_for_novita,
    build_request_for_ollama_cloud,
)
from backend.modules.llm._drivers.kimi_k2._capability import (
    kimi_k2_capability_spec,
)
from backend.modules.llm._drivers.kimi_k2._parsers import (
    parse_chunk_novita,
    parse_chunk_ollama_cloud,
)
from shared.dtos.inference import CompletionRequest


_SUPPORTED_ADAPTERS: frozenset[str] = frozenset({"ollama_http", "novita_http"})


def _unsupported_adapter(adapter_type: str) -> NotImplementedError:
    """Build the canonical 'adapter not supported' error.

    Re-used across the three driver methods so the message stays in sync.
    """
    return NotImplementedError(
        f"KimiK2Driver: adapter_type={adapter_type!r} has no driver-level "
        f"support. Kimi K2.5/K2.6 is wired for ollama_http and novita_http "
        f"only; other adapter_types are intentionally unsupported to avoid "
        f"silent capability/wire-shape drift."
    )


def _kimi_version(slug: str) -> str:
    """Return ``'k2.5'`` or ``'k2.6'`` for a Kimi slug, regardless of prefix.

    PATTERNS has already matched ``kimi-k2.5*`` or ``kimi-k2.6*`` against
    the slug basename before this is called, so the slug is guaranteed to
    contain one of those substrings. The publisher prefix
    (``moonshotai/...``) is stripped first for safety.
    """
    basename = slug.rsplit("/", 1)[-1]
    if basename.startswith("kimi-k2.6"):
        return "k2.6"
    if basename.startswith("kimi-k2.5"):
        return "k2.5"
    raise ValueError(
        f"_kimi_version: slug {slug!r} did not start with a known Kimi K2 "
        f"prefix; PATTERNS should have prevented this."
    )


class KimiK2Driver:
    """Driver for Kimi K2.5 and K2.6 on Ollama Cloud and Novita.

    Wire support: ``ollama_http``, ``novita_http``. Other adapter_types
    raise ``NotImplementedError`` from all three driver methods.
    """

    PATTERNS: list[str] = [
        "kimi-k2.5*",
        "kimi-k2.6*",
    ]

    def __init__(self) -> None:
        # Per-stream state: a fresh driver instance is created in the
        # adapter's ``stream_completion`` (``driver = driver_cls()``), so
        # the accumulator is naturally scoped to one inference iteration.
        # Novita streams OpenAI-fragmented tool-calls and needs its own
        # accumulator. The Ollama parser is stateless (atomic tool_calls).
        self._novita_tool_acc = ToolCallAccumulator()

    def capability_spec(
        self, *, adapter_type: str, slug: str,
    ) -> ResolvedCapabilities:
        if adapter_type not in _SUPPORTED_ADAPTERS:
            raise _unsupported_adapter(adapter_type)
        return kimi_k2_capability_spec(adapter_type=adapter_type, slug=slug)

    def build_request(
        self, *, adapter_type: str, slug: str, request: CompletionRequest,
    ) -> dict[str, Any]:
        if adapter_type == "ollama_http":
            return build_request_for_ollama_cloud(slug=slug, request=request)
        if adapter_type == "novita_http":
            return build_request_for_novita(slug=slug, request=request)
        raise _unsupported_adapter(adapter_type)

    def parse_chunk(
        self, *, adapter_type: str, slug: str, chunk: dict[str, Any],
    ) -> list[ProviderStreamEvent]:
        if adapter_type == "ollama_http":
            return parse_chunk_ollama_cloud(chunk=chunk)
        if adapter_type == "novita_http":
            return parse_chunk_novita(
                chunk=chunk, tool_acc=self._novita_tool_acc,
            )
        raise _unsupported_adapter(adapter_type)
```

- [ ] **Step 4: Wire the driver into the registry**

Edit `backend/modules/llm/_drivers/__init__.py` so it reads:

```python
"""Driver registry and dispatch.

See devdocs/specs/driver-layer.md.
"""
from __future__ import annotations

import fnmatch

from backend.modules.llm._drivers._protocol import Driver
from backend.modules.llm._drivers.deepseek_v4 import DeepSeekV4Driver
from backend.modules.llm._drivers.kimi_k2 import KimiK2Driver
from backend.modules.llm._drivers.mimo_v25 import MiMoV25Driver

# Order is cosmetic — DSv4, MiMo, and Kimi PATTERNS do not overlap, so
# the first-match-wins rule never has to break a tie here. New drivers
# append at the bottom unless they need to win over an earlier driver.
DRIVER_REGISTRY: list[type[Driver]] = [
    DeepSeekV4Driver,
    MiMoV25Driver,
    KimiK2Driver,
]


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

- [ ] **Step 5: Run the match-driver tests to verify they pass**

```bash
PYTHONPATH=/home/chris/workspace/chatsune uv run --project backend pytest backend/modules/llm/tests/test_kimi_k2_driver.py -v
```

Expected: all six `test_match_driver_*` tests PASS.

- [ ] **Step 6: Add the registry-presence test**

Edit `backend/modules/llm/tests/test_driver_registry.py` — append this new test after `test_registry_contains_dsv4`:

```python
def test_registry_contains_kimi():
    """After Task 1 of kimi-k2 plan, DRIVER_REGISTRY contains KimiK2Driver."""
    from backend.modules.llm._drivers.kimi_k2 import KimiK2Driver
    assert KimiK2Driver in DRIVER_REGISTRY
```

- [ ] **Step 7: Run the full driver-registry test file**

```bash
PYTHONPATH=/home/chris/workspace/chatsune uv run --project backend pytest backend/modules/llm/tests/test_driver_registry.py -v
```

Expected: all tests PASS, including the new `test_registry_contains_kimi`.

- [ ] **Step 8: Commit**

```bash
git add backend/modules/llm/_drivers/kimi_k2/ \
        backend/modules/llm/_drivers/__init__.py \
        backend/modules/llm/tests/test_kimi_k2_driver.py \
        backend/modules/llm/tests/test_driver_registry.py
git commit -m "$(cat <<'EOF'
Scaffold KimiK2Driver and register in driver registry

Driver class exposes the standard protocol; capability/build_request/
parse_chunk currently raise NotImplementedError(\"filled in Task N\") so
match_driver routing and registry-presence tests can pass on their own.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: Capability spec — 4 cells + unsupported adapters

**Files:**

- Modify: `backend/modules/llm/_drivers/kimi_k2/_capability.py`
- Modify: `backend/modules/llm/tests/test_kimi_k2_driver.py`

- [ ] **Step 1: Write the failing capability tests**

Append to `backend/modules/llm/tests/test_kimi_k2_driver.py`:

```python
# --- capability_spec -------------------------------------------------------


def test_capability_spec_ollama_k25_optional_reasoning() -> None:
    driver = KimiK2Driver()
    spec = driver.capability_spec(adapter_type="ollama_http", slug=_OLLAMA_K25)
    assert spec.first_class_support is True
    assert spec.reasoning.kind == "optional"
    assert spec.reasoning.default_on is True
    assert spec.reasoning.effort is None
    assert spec.tools.supported is True
    assert spec.tools.exclusive_with_reasoning is False


def test_capability_spec_ollama_k26_optional_reasoning() -> None:
    driver = KimiK2Driver()
    spec = driver.capability_spec(adapter_type="ollama_http", slug=_OLLAMA_K26)
    assert spec.first_class_support is True
    assert spec.reasoning.kind == "optional"
    assert spec.reasoning.default_on is True
    assert spec.reasoning.effort is None
    assert spec.tools.supported is True
    assert spec.tools.exclusive_with_reasoning is False


def test_capability_spec_novita_k25_no_reasoning() -> None:
    """Probe 2026-05-12: K2.5 on Novita never returns reasoning_content.
    Surfaced as ``no_reasoning`` so UI hides the toggle entirely."""
    driver = KimiK2Driver()
    spec = driver.capability_spec(adapter_type="novita_http", slug=_NOVITA_K25)
    assert spec.first_class_support is True
    assert spec.reasoning.kind == "no_reasoning"
    assert spec.reasoning.effort is None
    assert spec.tools.supported is True
    assert spec.tools.exclusive_with_reasoning is False


def test_capability_spec_novita_k26_always_on_reasoning() -> None:
    """Probe 2026-05-12: K2.6 on Novita always emits reasoning_content;
    the reasoning toggle is upstream-ignored. Surfaced as ``always_on``
    so UI hides the toggle and shows reasoning by default."""
    driver = KimiK2Driver()
    spec = driver.capability_spec(adapter_type="novita_http", slug=_NOVITA_K26)
    assert spec.first_class_support is True
    assert spec.reasoning.kind == "always_on"
    assert spec.reasoning.effort is None
    assert spec.tools.supported is True
    assert spec.tools.exclusive_with_reasoning is False


@pytest.mark.parametrize(
    "adapter_type",
    ["openrouter_http", "nano_gpt_http", "gmi_http"],
)
def test_capability_spec_unsupported_adapters_raise(adapter_type: str) -> None:
    driver = KimiK2Driver()
    with pytest.raises(NotImplementedError, match="adapter_type"):
        driver.capability_spec(adapter_type=adapter_type, slug=_OLLAMA_K25)
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
PYTHONPATH=/home/chris/workspace/chatsune uv run --project backend pytest backend/modules/llm/tests/test_kimi_k2_driver.py::test_capability_spec_ollama_k25_optional_reasoning -v
```

Expected: FAIL with `NotImplementedError: filled in Task 2`.

- [ ] **Step 3: Implement `kimi_k2_capability_spec`**

Replace `backend/modules/llm/_drivers/kimi_k2/_capability.py` with:

```python
"""Capability spec for Kimi K2.5 and K2.6 on Ollama Cloud and Novita.

See devdocs/research/kimi-k2-wire-shapes.md for the wire-shape probes
that produced this matrix:

| Slug basename | adapter_type    | reasoning.kind | tools |
|---------------|-----------------|----------------|-------|
| kimi-k2.5*    | ollama_http     | optional       | true  |
| kimi-k2.6*    | ollama_http     | optional       | true  |
| kimi-k2.5*    | novita_http     | no_reasoning   | true  |
| kimi-k2.6*    | novita_http     | always_on      | true  |

``first_class_support = true`` and ``tools.supported = true`` on every
cell. ``effort = None`` everywhere — Kimi has no documented effort
buckets and probes did not surface a working knob on either provider.
"""
from __future__ import annotations

from backend.modules.llm._capabilities import ResolvedCapabilities
from shared.dtos.llm import (
    ReasoningCapability,
    ToolCapability,
)


def kimi_k2_capability_spec(
    *, adapter_type: str, slug: str,
) -> ResolvedCapabilities:
    """Return the (adapter, slug)-specific capability spec for Kimi K2."""
    # Local import to keep the driver-package dependency graph one-way.
    from backend.modules.llm._drivers.kimi_k2 import (
        _kimi_version, _unsupported_adapter,
    )

    tools = ToolCapability(supported=True, exclusive_with_reasoning=False)

    if adapter_type == "ollama_http":
        # K2.5 and K2.6 both honour the ``think: true/false`` flag at
        # Ollama Cloud (probe 2026-05-12). Default-on matches the K2
        # family branding as a reasoning model.
        return ResolvedCapabilities(
            reasoning=ReasoningCapability(
                kind="optional", effort=None, default_on=True,
            ),
            tools=tools,
            first_class_support=True,
        )

    if adapter_type == "novita_http":
        version = _kimi_version(slug)
        if version == "k2.5":
            # Novita K2.5 never populates reasoning_content regardless of
            # the ``reasoning.enabled`` flag (probe 2026-05-12). Treat as
            # a non-reasoning model on this provider.
            return ResolvedCapabilities(
                reasoning=ReasoningCapability(
                    kind="no_reasoning", effort=None, default_on=False,
                ),
                tools=tools,
                first_class_support=True,
            )
        # version == "k2.6"
        # Novita K2.6 always emits reasoning_content; the toggle is
        # ignored upstream (probe 2026-05-12). ``always_on`` keeps the
        # UI honest — no toggle shown for a knob that does nothing.
        return ResolvedCapabilities(
            reasoning=ReasoningCapability(
                kind="always_on", effort=None, default_on=True,
            ),
            tools=tools,
            first_class_support=True,
        )

    raise _unsupported_adapter(adapter_type)
```

- [ ] **Step 4: Run the capability tests to verify they pass**

```bash
PYTHONPATH=/home/chris/workspace/chatsune uv run --project backend pytest backend/modules/llm/tests/test_kimi_k2_driver.py -v -k capability_spec
```

Expected: all 5 capability tests PASS (4 cells + 3 unsupported adapters via the parametrised case).

- [ ] **Step 5: Commit**

```bash
git add backend/modules/llm/_drivers/kimi_k2/_capability.py \
        backend/modules/llm/tests/test_kimi_k2_driver.py
git commit -m "$(cat <<'EOF'
Implement KimiK2 capability spec for 4 (adapter, slug) cells

Ollama Cloud K2.5/K2.6: optional + default_on. Novita K2.5:
no_reasoning. Novita K2.6: always_on. tools.supported = true on every
cell; effort = None everywhere.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: Builders — Ollama and Novita

**Files:**

- Modify: `backend/modules/llm/_drivers/kimi_k2/_builders.py`
- Modify: `backend/modules/llm/tests/test_kimi_k2_driver.py`

- [ ] **Step 1: Write the failing builder tests**

Append to `backend/modules/llm/tests/test_kimi_k2_driver.py`:

```python
# --- builder helpers -------------------------------------------------------


from shared.dtos.chat import ChatSessionExtras  # noqa: E402
from shared.dtos.inference import (  # noqa: E402
    CompletionMessage,
    CompletionRequest,
    ContentPart,
    ToolDefinition,
)
from shared.dtos.llm import ReasoningCapability, ToolCapability  # noqa: E402


def _make_request(
    *,
    slug: str,
    kind: str = "optional",
    default_on: bool = True,
    reasoning_mode: str = "on",
    tools_enabled: bool = False,
    tools: list[ToolDefinition] | None = None,
) -> CompletionRequest:
    """Build a CompletionRequest for builder tests.

    The ``kind`` argument lets a test simulate the capability spec the
    resolver would have attached for a given (adapter, slug). For Kimi
    tests we pass:
      - kind='optional' for Ollama K2.5/K2.6
      - kind='no_reasoning' for Novita K2.5
      - kind='always_on' for Novita K2.6
    """
    return CompletionRequest(
        model=slug,
        messages=[
            CompletionMessage(
                role="user",
                content=[ContentPart(type="text", text="Hello")],
            )
        ],
        tools=tools,
        reasoning=ReasoningCapability(
            kind=kind, effort=None, default_on=default_on,
        ),
        tools_capability=ToolCapability(supported=True),
        extras=ChatSessionExtras(
            tools_enabled=tools_enabled,
            reasoning_mode=reasoning_mode,
            reasoning_effort=None,
        ),
    )


# --- build_request: Ollama Cloud -------------------------------------------


def test_build_request_ollama_reasoning_on_writes_think_true() -> None:
    """Optional kind + reasoning_mode='on' -> body['think'] is True.
    The base ``_ollama_http.build_request_body`` already handles this
    when ``reasoning.kind == 'optional'`` — the driver just delegates."""
    driver = KimiK2Driver()
    body = driver.build_request(
        adapter_type="ollama_http",
        slug=_OLLAMA_K25,
        request=_make_request(slug=_OLLAMA_K25, kind="optional", reasoning_mode="on"),
    )
    assert body["think"] is True


def test_build_request_ollama_reasoning_off_writes_think_false() -> None:
    driver = KimiK2Driver()
    body = driver.build_request(
        adapter_type="ollama_http",
        slug=_OLLAMA_K25,
        request=_make_request(slug=_OLLAMA_K25, kind="optional", reasoning_mode="off"),
    )
    assert body["think"] is False


def test_build_request_ollama_k26_reasoning_on_writes_think_true() -> None:
    """K2.6 on Ollama Cloud uses the same wire shape as K2.5."""
    driver = KimiK2Driver()
    body = driver.build_request(
        adapter_type="ollama_http",
        slug=_OLLAMA_K26,
        request=_make_request(slug=_OLLAMA_K26, kind="optional", reasoning_mode="on"),
    )
    assert body["think"] is True


def test_build_request_ollama_includes_tools_when_enabled() -> None:
    driver = KimiK2Driver()
    tools = [
        ToolDefinition(
            name="get_time",
            description="Return the current time",
            parameters={"type": "object", "properties": {}},
        )
    ]
    body = driver.build_request(
        adapter_type="ollama_http",
        slug=_OLLAMA_K25,
        request=_make_request(
            slug=_OLLAMA_K25, kind="optional",
            tools_enabled=True, tools=tools,
        ),
    )
    assert "tools" in body
    assert body["tools"][0]["function"]["name"] == "get_time"


def test_build_request_ollama_omits_tools_when_disabled() -> None:
    driver = KimiK2Driver()
    tools = [
        ToolDefinition(
            name="get_time",
            description="Return the current time",
            parameters={"type": "object", "properties": {}},
        )
    ]
    body = driver.build_request(
        adapter_type="ollama_http",
        slug=_OLLAMA_K25,
        request=_make_request(
            slug=_OLLAMA_K25, kind="optional",
            tools_enabled=False, tools=tools,
        ),
    )
    assert "tools" not in body


# --- build_request: Novita -------------------------------------------------


def test_build_request_novita_k25_omits_reasoning_block() -> None:
    """K2.5 on Novita is no_reasoning — the base Novita builder only adds
    a ``reasoning`` block when kind=='optional', so this should already
    be absent. The driver delegates unchanged.
    """
    driver = KimiK2Driver()
    body = driver.build_request(
        adapter_type="novita_http",
        slug=_NOVITA_K25,
        request=_make_request(
            slug=_NOVITA_K25, kind="no_reasoning", default_on=False,
            reasoning_mode="off",
        ),
    )
    assert "reasoning" not in body
    assert "enable_thinking" not in body


def test_build_request_novita_k26_omits_reasoning_block() -> None:
    """K2.6 on Novita is always_on — the base Novita builder omits the
    reasoning block (only set for kind=='optional'). The provider
    ignores the toggle anyway."""
    driver = KimiK2Driver()
    body = driver.build_request(
        adapter_type="novita_http",
        slug=_NOVITA_K26,
        request=_make_request(
            slug=_NOVITA_K26, kind="always_on", default_on=True,
            reasoning_mode="on",
        ),
    )
    assert "reasoning" not in body
    assert "enable_thinking" not in body


def test_build_request_novita_inherits_message_translation() -> None:
    driver = KimiK2Driver()
    body = driver.build_request(
        adapter_type="novita_http",
        slug=_NOVITA_K25,
        request=_make_request(slug=_NOVITA_K25, kind="no_reasoning"),
    )
    assert len(body["messages"]) == 1
    assert body["messages"][0]["role"] == "user"
    assert body["messages"][0]["content"] == "Hello"


def test_build_request_novita_includes_tools_when_enabled() -> None:
    driver = KimiK2Driver()
    tools = [
        ToolDefinition(
            name="get_time",
            description="Return the current time",
            parameters={"type": "object", "properties": {}},
        )
    ]
    body = driver.build_request(
        adapter_type="novita_http",
        slug=_NOVITA_K26,
        request=_make_request(
            slug=_NOVITA_K26, kind="always_on",
            tools_enabled=True, tools=tools,
        ),
    )
    assert "tools" in body
    assert body["tools"][0]["function"]["name"] == "get_time"


# --- build_request: unsupported adapters -----------------------------------


@pytest.mark.parametrize(
    "adapter_type",
    ["openrouter_http", "nano_gpt_http", "gmi_http"],
)
def test_build_request_unsupported_adapter_raises(adapter_type: str) -> None:
    driver = KimiK2Driver()
    with pytest.raises(NotImplementedError, match="adapter_type"):
        driver.build_request(
            adapter_type=adapter_type,
            slug=_OLLAMA_K25,
            request=_make_request(slug=_OLLAMA_K25, kind="optional"),
        )
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
PYTHONPATH=/home/chris/workspace/chatsune uv run --project backend pytest backend/modules/llm/tests/test_kimi_k2_driver.py -v -k build_request
```

Expected: builder tests FAIL with `NotImplementedError: filled in Task 3` (the parametrised unsupported-adapter test will pass already because the driver's outer dispatch raises before the builder is called).

- [ ] **Step 3: Implement the builders**

Replace `backend/modules/llm/_drivers/kimi_k2/_builders.py` with:

```python
"""Request-body builders for Kimi K2.5 / K2.6.

Wire support: Ollama Cloud (``ollama_http``) and Novita (``novita_http``).

Both builders delegate to the existing adapter ``build_request_body``
helpers and return the result unchanged. The base builders already
produce the correct wire shape for the three reasoning kinds we surface:

- ``optional`` (Ollama K2.5, K2.6) → ``_ollama_http`` writes
  ``think: true/false`` based on ``extras.reasoning_mode``.
- ``no_reasoning`` (Novita K2.5) → ``_novita_http`` omits the
  ``reasoning`` block (only set when kind == ``optional``).
- ``always_on`` (Novita K2.6) → ``_novita_http`` omits the ``reasoning``
  block. The provider ignores the toggle anyway (probe 2026-05-12), so
  there is no working signal to send.

If Kimi later sprouts a working effort knob, slip the override into the
relevant builder rather than mutating the adapter.
"""
from __future__ import annotations

from typing import Any

from shared.dtos.inference import CompletionRequest


def build_request_for_ollama_cloud(
    *, slug: str, request: CompletionRequest,
) -> dict[str, Any]:
    """Build the Ollama Cloud request body for Kimi K2.5 / K2.6.

    Pure delegation — ``_ollama_http.build_request_body`` handles
    everything correctly when ``request.reasoning.kind == 'optional'``
    (which the driver's capability spec guarantees for this adapter).
    """
    # Local import to avoid a circular dependency at module load time
    # (drivers depend on adapter helpers; the adapter consults drivers
    # at call time).
    from backend.modules.llm._adapters._ollama_http import (
        build_request_body as _ollama_build_request_body,
    )

    return _ollama_build_request_body(request)


def build_request_for_novita(
    *, slug: str, request: CompletionRequest,
) -> dict[str, Any]:
    """Build the Novita request body for Kimi K2.5 / K2.6.

    Pure delegation — ``_novita_http.build_request_body`` omits the
    ``reasoning`` block when ``reasoning.kind`` is ``no_reasoning``
    (K2.5) or ``always_on`` (K2.6), which is exactly what we want for
    Kimi on Novita (the provider ignores the toggle for K2.6 and the
    block is meaningless for K2.5).
    """
    from backend.modules.llm._adapters._novita_http import (
        build_request_body as _novita_build_request_body,
    )

    return _novita_build_request_body(request)
```

- [ ] **Step 4: Run the builder tests to verify they pass**

```bash
PYTHONPATH=/home/chris/workspace/chatsune uv run --project backend pytest backend/modules/llm/tests/test_kimi_k2_driver.py -v -k build_request
```

Expected: all builder tests PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/modules/llm/_drivers/kimi_k2/_builders.py \
        backend/modules/llm/tests/test_kimi_k2_driver.py
git commit -m "$(cat <<'EOF'
Implement KimiK2 request builders for Ollama Cloud and Novita

Both builders are pure delegations to the existing adapter
build_request_body helpers — the base builders already produce the
correct wire shape for ``optional`` / ``no_reasoning`` / ``always_on``
reasoning kinds, which the capability spec attaches via the resolver.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: Parser — Ollama Cloud NDJSON

**Files:**

- Modify: `backend/modules/llm/_drivers/kimi_k2/_parsers.py`
- Modify: `backend/modules/llm/tests/test_kimi_k2_driver.py`

- [ ] **Step 1: Write the failing Ollama parser tests**

Append to `backend/modules/llm/tests/test_kimi_k2_driver.py`:

```python
# --- parse_chunk: Ollama Cloud ---------------------------------------------


from backend.modules.llm._adapters._events import (  # noqa: E402
    ContentDelta,
    StreamDone,
    StreamRefused,
    ThinkingDelta,
    ToolCallEvent,
)


def test_parse_chunk_ollama_emits_content_delta() -> None:
    driver = KimiK2Driver()
    chunk = {"message": {"content": "hi"}, "done": False}
    events = driver.parse_chunk(
        adapter_type="ollama_http", slug=_OLLAMA_K25, chunk=chunk,
    )
    assert events == [ContentDelta(delta="hi")]


def test_parse_chunk_ollama_emits_thinking_delta() -> None:
    """Ollama Cloud uses ``message.thinking`` for CoT, mapped to
    ThinkingDelta per INS-038."""
    driver = KimiK2Driver()
    chunk = {"message": {"thinking": "let me think"}, "done": False}
    events = driver.parse_chunk(
        adapter_type="ollama_http", slug=_OLLAMA_K25, chunk=chunk,
    )
    assert events == [ThinkingDelta(delta="let me think")]


def test_parse_chunk_ollama_emits_atomic_tool_call() -> None:
    """Ollama delivers tool_calls atomically (full call per chunk; no
    incremental accumulation). Arguments arrive as an object and must be
    JSON-stringified to match the ToolCallEvent.arguments: str contract."""
    driver = KimiK2Driver()
    chunk = {
        "message": {
            "tool_calls": [
                {
                    "id": "functions.get_weather:0",
                    "function": {
                        "name": "get_weather",
                        "arguments": {"city": "Berlin"},
                    },
                }
            ]
        },
        "done": False,
    }
    events = driver.parse_chunk(
        adapter_type="ollama_http", slug=_OLLAMA_K26, chunk=chunk,
    )
    tool_event = next(e for e in events if isinstance(e, ToolCallEvent))
    assert tool_event.id == "functions.get_weather:0"
    assert tool_event.name == "get_weather"
    # Arguments are JSON-stringified — exact match on the serialised dict
    # is brittle (key order) but the field carries valid JSON.
    import json
    assert json.loads(tool_event.arguments) == {"city": "Berlin"}


def test_parse_chunk_ollama_tool_call_without_id_gets_synthetic_id() -> None:
    """Ollama responses sometimes omit the tool_call id. Fallback is a
    synthetic ``call_<hex>`` id so the continuation turn has something
    to echo. Same logic as the DSv4 Ollama parser."""
    driver = KimiK2Driver()
    chunk = {
        "message": {
            "tool_calls": [{
                "function": {
                    "name": "get_weather",
                    "arguments": {"city": "Berlin"},
                },
            }]
        },
        "done": False,
    }
    events = driver.parse_chunk(
        adapter_type="ollama_http", slug=_OLLAMA_K25, chunk=chunk,
    )
    tool_event = next(e for e in events if isinstance(e, ToolCallEvent))
    assert tool_event.id.startswith("call_")
    assert len(tool_event.id) == 5 + 12  # "call_" + 12 hex chars


def test_parse_chunk_ollama_emits_stream_done_on_terminal() -> None:
    driver = KimiK2Driver()
    chunk = {
        "message": {},
        "done": True,
        "done_reason": "stop",
        "prompt_eval_count": 14,
        "eval_count": 71,
    }
    events = driver.parse_chunk(
        adapter_type="ollama_http", slug=_OLLAMA_K25, chunk=chunk,
    )
    done = next(e for e in events if isinstance(e, StreamDone))
    assert done.input_tokens == 14
    assert done.output_tokens == 71
    # Ollama Cloud bundles reasoning into eval_count — no separate
    # reasoning_tokens field on the wire.
    assert done.reasoning_tokens is None


def test_parse_chunk_ollama_emits_stream_refused_on_content_filter() -> None:
    driver = KimiK2Driver()
    chunk = {
        "message": {"refusal": "I cannot help with that"},
        "done": True,
        "done_reason": "content_filter",
    }
    events = driver.parse_chunk(
        adapter_type="ollama_http", slug=_OLLAMA_K25, chunk=chunk,
    )
    refused = next(e for e in events if isinstance(e, StreamRefused))
    assert refused.reason == "content_filter"
    assert refused.refusal_text == "I cannot help with that"
    # Mutually exclusive: no StreamDone alongside StreamRefused.
    assert not any(isinstance(e, StreamDone) for e in events)
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
PYTHONPATH=/home/chris/workspace/chatsune uv run --project backend pytest backend/modules/llm/tests/test_kimi_k2_driver.py -v -k "parse_chunk_ollama"
```

Expected: tests FAIL with `NotImplementedError: filled in Task 4`.

- [ ] **Step 3: Implement `parse_chunk_ollama_cloud`**

Edit `backend/modules/llm/_drivers/kimi_k2/_parsers.py` — replace the placeholder `parse_chunk_ollama_cloud` with:

```python
def parse_chunk_ollama_cloud(*, chunk: dict[str, Any]) -> list[ProviderStreamEvent]:
    """Translate one Ollama Cloud NDJSON-decoded chunk into events.

    Ollama Cloud uses the native Ollama envelope (no OpenAI ``choices``
    list). Each chunk contains a ``message`` block with ``content`` and
    optional ``thinking``; the final chunk has ``done=True`` plus
    ``prompt_eval_count`` and ``eval_count``. Refusals are signalled via
    ``done_reason in {content_filter, refusal}`` — emit ``StreamRefused``
    instead of ``StreamDone``.

    Tool-calls arrive atomically: a single chunk holds the complete list
    of calls with object-valued ``arguments`` that must be JSON-stringified
    to match ``ToolCallEvent.arguments: str``.

    Logic is structurally identical to ``deepseek_v4._parsers.parse_chunk_ollama_cloud``
    but is intentionally NOT imported from there (per driver-layer spec).
    """
    events: list[ProviderStreamEvent] = []

    message = chunk.get("message") or {}

    # Visible content fragment
    content = message.get("content")
    if content:
        events.append(ContentDelta(delta=content))

    # Ollama-native CoT key. Mapped to ThinkingDelta per INS-038.
    thinking = message.get("thinking")
    if thinking:
        events.append(ThinkingDelta(delta=thinking))

    # Atomic tool-calls (no incremental accumulation across chunks).
    for tc in message.get("tool_calls") or []:
        fn = tc.get("function") or {}
        events.append(ToolCallEvent(
            id=tc.get("id") or f"call_{uuid4().hex[:12]}",
            name=fn.get("name", ""),
            arguments=json.dumps(fn.get("arguments") or {}),
        ))

    # Terminal handling: StreamRefused / StreamDone are mutually exclusive.
    if chunk.get("done"):
        done_reason = chunk.get("done_reason")
        if done_reason and done_reason.lower() in _REFUSAL_REASONS:
            events.append(StreamRefused(
                reason=done_reason,
                refusal_text=message.get("refusal") or None,
            ))
        else:
            events.append(StreamDone(
                input_tokens=chunk.get("prompt_eval_count"),
                output_tokens=chunk.get("eval_count"),
                # Ollama Cloud bundles reasoning into eval_count — no
                # separate reasoning_tokens field. Leave as None.
            ))

    return events
```

- [ ] **Step 4: Run the Ollama parser tests to verify they pass**

```bash
PYTHONPATH=/home/chris/workspace/chatsune uv run --project backend pytest backend/modules/llm/tests/test_kimi_k2_driver.py -v -k "parse_chunk_ollama"
```

Expected: all 6 Ollama parser tests PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/modules/llm/_drivers/kimi_k2/_parsers.py \
        backend/modules/llm/tests/test_kimi_k2_driver.py
git commit -m "$(cat <<'EOF'
Implement KimiK2 Ollama Cloud parser

NDJSON envelope: message.content -> ContentDelta;
message.thinking -> ThinkingDelta; atomic message.tool_calls[] ->
ToolCallEvent with JSON-stringified arguments; done=True with
prompt_eval_count/eval_count -> StreamDone; done_reason in refusal
set -> StreamRefused (mutually exclusive with StreamDone).

Structure mirrors deepseek_v4._parsers.parse_chunk_ollama_cloud per
the driver-layer spec rule that logic is duplicated, not imported.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: Parser — Novita SSE with tool-call accumulation

**Files:**

- Modify: `backend/modules/llm/_drivers/kimi_k2/_parsers.py`
- Modify: `backend/modules/llm/tests/test_kimi_k2_driver.py`

- [ ] **Step 1: Write the failing Novita parser tests**

Append to `backend/modules/llm/tests/test_kimi_k2_driver.py`:

```python
# --- parse_chunk: Novita ---------------------------------------------------


def test_parse_chunk_novita_emits_content_delta() -> None:
    driver = KimiK2Driver()
    chunk = {"choices": [{"delta": {"content": "1,"}, "finish_reason": None}]}
    events = driver.parse_chunk(
        adapter_type="novita_http", slug=_NOVITA_K25, chunk=chunk,
    )
    assert events == [ContentDelta(delta="1,")]


def test_parse_chunk_novita_emits_thinking_delta_from_reasoning_content() -> None:
    """Novita uses DeepSeek-native ``delta.reasoning_content`` (also for K2.6
    — probe 2026-05-12). Mapped to ThinkingDelta per INS-038."""
    driver = KimiK2Driver()
    chunk = {
        "choices": [{
            "delta": {"reasoning_content": "The user"}, "finish_reason": None,
        }]
    }
    events = driver.parse_chunk(
        adapter_type="novita_http", slug=_NOVITA_K26, chunk=chunk,
    )
    assert events == [ThinkingDelta(delta="The user")]


def test_parse_chunk_novita_accumulates_fragmented_tool_call() -> None:
    """Novita streams tool calls OpenAI-style: id+name in the first chunk,
    then string arguments fragments under index:0. Final ``finish_reason:
    tool_calls`` finalises the accumulator into a ToolCallEvent."""
    driver = KimiK2Driver()
    # First chunk: id + name, no args yet
    driver.parse_chunk(
        adapter_type="novita_http",
        slug=_NOVITA_K25,
        chunk={
            "choices": [{"delta": {"tool_calls": [{
                "index": 0, "id": "functions.get_weather:0", "type": "function",
                "function": {"name": "get_weather"},
            }]}, "finish_reason": None}],
        },
    )
    # Args fragments
    for frag in ['{"', 'city', '": ', '"Berlin', '"}']:
        driver.parse_chunk(
            adapter_type="novita_http",
            slug=_NOVITA_K25,
            chunk={
                "choices": [{"delta": {"tool_calls": [{
                    "index": 0, "function": {"arguments": frag},
                }]}, "finish_reason": None}],
            },
        )
    # Terminal: finish_reason=tool_calls + usage block
    events = driver.parse_chunk(
        adapter_type="novita_http",
        slug=_NOVITA_K25,
        chunk={
            "choices": [{"delta": {}, "finish_reason": "tool_calls"}],
            "usage": {
                "prompt_tokens": 80, "completion_tokens": 24,
                "completion_tokens_details": {"reasoning_tokens": 0},
            },
        },
    )
    tool_event = next(e for e in events if isinstance(e, ToolCallEvent))
    assert tool_event.id == "functions.get_weather:0"
    assert tool_event.name == "get_weather"
    assert tool_event.arguments == '{"city": "Berlin"}'
    done = next(e for e in events if isinstance(e, StreamDone))
    assert done.input_tokens == 80
    assert done.output_tokens == 24


def test_parse_chunk_novita_emits_stream_done_with_reasoning_tokens() -> None:
    """K2.6 on Novita populates completion_tokens_details.reasoning_tokens
    (probe 2026-05-12). StreamDone must carry it through."""
    driver = KimiK2Driver()
    chunk = {
        "choices": [{"delta": {}, "finish_reason": "stop"}],
        "usage": {
            "prompt_tokens": 19,
            "completion_tokens": 312,
            "completion_tokens_details": {"reasoning_tokens": 220},
        },
    }
    events = driver.parse_chunk(
        adapter_type="novita_http", slug=_NOVITA_K26, chunk=chunk,
    )
    done = next(e for e in events if isinstance(e, StreamDone))
    assert done.input_tokens == 19
    assert done.output_tokens == 312
    assert done.reasoning_tokens == 220


def test_parse_chunk_novita_emits_stream_refused_on_content_filter() -> None:
    driver = KimiK2Driver()
    chunk = {
        "choices": [{
            "delta": {"refusal": "I cannot help with that"},
            "finish_reason": "content_filter",
        }],
    }
    events = driver.parse_chunk(
        adapter_type="novita_http", slug=_NOVITA_K26, chunk=chunk,
    )
    refused = next(e for e in events if isinstance(e, StreamRefused))
    assert refused.reason == "content_filter"
    assert refused.refusal_text == "I cannot help with that"
    # Mutually exclusive with StreamDone.
    assert not any(isinstance(e, StreamDone) for e in events)
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
PYTHONPATH=/home/chris/workspace/chatsune uv run --project backend pytest backend/modules/llm/tests/test_kimi_k2_driver.py -v -k "parse_chunk_novita"
```

Expected: Novita tests FAIL with `NotImplementedError: filled in Task 5`.

- [ ] **Step 3: Implement `parse_chunk_novita`**

Edit `backend/modules/llm/_drivers/kimi_k2/_parsers.py` — replace the placeholder `parse_chunk_novita` with:

```python
def parse_chunk_novita(
    *, chunk: dict[str, Any], tool_acc: ToolCallAccumulator,
) -> list[ProviderStreamEvent]:
    """Translate one Novita SSE chunk dict into ProviderStreamEvents.

    Wire-shape is OpenAI-compat with the DeepSeek-native CoT key
    ``delta.reasoning_content`` (probe 2026-05-12: K2.6 emits this key;
    K2.5 omits it, which is fine — the .get() returns None). Tool-call
    streaming is OpenAI-fragmented (id+name first, then arguments string
    fragments under the same index); the accumulator handles assembly.

    Logic is structurally identical to ``deepseek_v4._parsers.parse_chunk_novita``
    but is intentionally NOT imported from there (per driver-layer spec).

    ``StreamRefused`` and ``StreamDone`` are mutually exclusive terminal
    states. ``ToolCallEvent`` + ``StreamDone`` CAN co-occur — Novita
    delivers usage in the same chunk as ``finish_reason='tool_calls'``.
    """
    events: list[ProviderStreamEvent] = []

    choices = chunk.get("choices") or []
    if choices:
        choice = choices[0]
        delta = choice.get("delta") or {}

        content = delta.get("content")
        if content:
            events.append(ContentDelta(delta=content))

        reasoning_content = delta.get("reasoning_content")
        if reasoning_content:
            events.append(ThinkingDelta(delta=reasoning_content))

        tool_frags = delta.get("tool_calls") or []
        if tool_frags:
            tool_acc.ingest(tool_frags)

        finish = choice.get("finish_reason")
        if finish and finish.lower() in _REFUSAL_REASONS:
            events.append(StreamRefused(
                reason=finish,
                refusal_text=delta.get("refusal") or None,
            ))
        elif finish == "tool_calls":
            for call in tool_acc.finalised():
                events.append(ToolCallEvent(
                    id=call["id"],
                    name=call["name"],
                    arguments=call["arguments"],
                ))

    usage = chunk.get("usage")
    if usage is not None and not any(isinstance(e, StreamRefused) for e in events):
        details = usage.get("completion_tokens_details") or {}
        events.append(StreamDone(
            input_tokens=usage.get("prompt_tokens"),
            output_tokens=usage.get("completion_tokens"),
            reasoning_tokens=details.get("reasoning_tokens"),
        ))

    return events
```

- [ ] **Step 4: Run the Novita parser tests to verify they pass**

```bash
PYTHONPATH=/home/chris/workspace/chatsune uv run --project backend pytest backend/modules/llm/tests/test_kimi_k2_driver.py -v -k "parse_chunk_novita"
```

Expected: all 5 Novita parser tests PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/modules/llm/_drivers/kimi_k2/_parsers.py \
        backend/modules/llm/tests/test_kimi_k2_driver.py
git commit -m "$(cat <<'EOF'
Implement KimiK2 Novita SSE parser with tool-call accumulator

OpenAI-compat SSE: delta.content -> ContentDelta;
delta.reasoning_content -> ThinkingDelta (DeepSeek-native CoT key);
fragmented delta.tool_calls fed into ToolCallAccumulator and finalised
on finish_reason='tool_calls'; terminal usage block ->
StreamDone(reasoning_tokens=completion_tokens_details.reasoning_tokens);
content_filter / refusal finish_reason -> StreamRefused (mutually
exclusive with StreamDone).

Structure mirrors deepseek_v4._parsers.parse_chunk_novita per the
driver-layer spec rule that logic is duplicated, not imported.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: Integration — resolve_capabilities + per-instance state

**Files:**

- Modify: `backend/modules/llm/tests/test_kimi_k2_driver.py`

These tests verify the driver actually fires through the public capability resolver and that accumulator state is per-instance (not shared across concurrent streams).

- [ ] **Step 1: Write the integration tests**

Append to `backend/modules/llm/tests/test_kimi_k2_driver.py`:

```python
# --- integration with resolve_capabilities ---------------------------------


from backend.modules.llm._capabilities import (  # noqa: E402
    DEFAULT_CAPABILITIES,
    resolve_capabilities,
)


class _NoOpAdapter:
    """Adapter that gives no capability hint — forces fallthrough."""

    def capability_hint(self, model_id: str):
        return None


def test_resolve_capabilities_returns_driver_spec_for_ollama_k25() -> None:
    spec = resolve_capabilities(
        adapter_type="ollama_http",
        model_id=_OLLAMA_K25,
        adapter=_NoOpAdapter(),
    )
    assert spec.first_class_support is True
    assert spec.reasoning.kind == "optional"
    assert spec.reasoning.default_on is True
    assert spec.tools.supported is True
    # Sanity: this is NOT the universal default — proves the driver fired.
    assert spec != DEFAULT_CAPABILITIES


def test_resolve_capabilities_returns_driver_spec_for_ollama_k26() -> None:
    spec = resolve_capabilities(
        adapter_type="ollama_http",
        model_id=_OLLAMA_K26,
        adapter=_NoOpAdapter(),
    )
    assert spec.reasoning.kind == "optional"
    assert spec.first_class_support is True


def test_resolve_capabilities_returns_driver_spec_for_novita_k25() -> None:
    spec = resolve_capabilities(
        adapter_type="novita_http",
        model_id=_NOVITA_K25,
        adapter=_NoOpAdapter(),
    )
    assert spec.reasoning.kind == "no_reasoning"
    assert spec.first_class_support is True


def test_resolve_capabilities_returns_driver_spec_for_novita_k26() -> None:
    spec = resolve_capabilities(
        adapter_type="novita_http",
        model_id=_NOVITA_K26,
        adapter=_NoOpAdapter(),
    )
    assert spec.reasoning.kind == "always_on"
    assert spec.first_class_support is True


# --- per-instance state ----------------------------------------------------


def test_driver_novita_accumulator_is_per_instance() -> None:
    """Each KimiK2Driver instance owns a private Novita accumulator so
    concurrent streams don't cross-contaminate."""
    a = KimiK2Driver()
    b = KimiK2Driver()
    assert a._novita_tool_acc is not b._novita_tool_acc
```

- [ ] **Step 2: Run the integration tests**

```bash
PYTHONPATH=/home/chris/workspace/chatsune uv run --project backend pytest backend/modules/llm/tests/test_kimi_k2_driver.py -v -k "resolve_capabilities or accumulator_is_per_instance"
```

Expected: all 5 tests PASS — these need no further implementation; they verify already-implemented behaviour.

- [ ] **Step 3: Run the entire Kimi test file**

```bash
PYTHONPATH=/home/chris/workspace/chatsune uv run --project backend pytest backend/modules/llm/tests/test_kimi_k2_driver.py -v
```

Expected: every test PASSES. Count: 6 match_driver + 5 capability + 11 build_request + 6 parse_chunk_ollama + 5 parse_chunk_novita + 5 integration = ~38 tests.

- [ ] **Step 4: Run the broader driver test suite to catch regressions**

```bash
PYTHONPATH=/home/chris/workspace/chatsune uv run --project backend pytest backend/modules/llm/tests/test_driver_registry.py backend/modules/llm/tests/test_deepseek_v4_driver.py backend/modules/llm/tests/test_mimo_v25_driver.py backend/modules/llm/tests/test_capabilities_with_drivers.py -v
```

Expected: every test PASSES — no regression in DSv4, MiMo, registry, or generic capabilities tests.

- [ ] **Step 5: Commit**

```bash
git add backend/modules/llm/tests/test_kimi_k2_driver.py
git commit -m "$(cat <<'EOF'
Add resolve_capabilities and per-instance accumulator tests for KimiK2

Verifies the driver actually fires through resolve_capabilities (not
shadowed by YAML or adapter heuristic) for all 4 (adapter, slug)
cells, and that each KimiK2Driver instance owns a private Novita
tool-call accumulator.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: Backend-wide sanity check

This task is a safety net — no new tests or code. We run a broader pytest sweep over the LLM module to ensure no incidental breakage.

**Files:** none modified — verification only.

- [ ] **Step 1: Run the full backend/modules/llm test suite**

```bash
PYTHONPATH=/home/chris/workspace/chatsune uv run --project backend pytest backend/modules/llm/ -v --ignore=backend/modules/llm/tests/test_resolve_models_integration.py
```

The ignore is conservative — `test_resolve_models_integration.py` historically wants live API keys for some adapters. Re-include it if it now runs offline; otherwise stay with the ignore.

Expected: every test PASSES (or skips for adapter live-key reasons that pre-date this branch).

- [ ] **Step 2: Backend compile check on touched files**

```bash
uv run python -m py_compile \
  backend/modules/llm/_drivers/__init__.py \
  backend/modules/llm/_drivers/kimi_k2/__init__.py \
  backend/modules/llm/_drivers/kimi_k2/_capability.py \
  backend/modules/llm/_drivers/kimi_k2/_builders.py \
  backend/modules/llm/_drivers/kimi_k2/_parsers.py
```

Expected: silent success (no output, exit 0).

- [ ] **Step 3: Report the final commit log to the user**

```bash
git log --oneline master..HEAD
```

Expected output should be 5 commits (one per Task 1 → Task 5; Task 6 is a single commit; Task 7 has no commit). If it isn't, double-check that each task's commit step ran.

**Do NOT merge to master. Do NOT push. Do NOT switch branches.** The main session handles the merge after a final manual-verification pass with the user.

---

## Manual verification checklist (run by Chris after merge)

These cannot be automated — they need a live Chatsune instance with Ollama Cloud and Novita connections configured. From the spec's "Manual verification" section, condensed:

- [ ] In the Chatsune UI, the models list for an Ollama Cloud connection includes `kimi-k2.5` and `kimi-k2.6` (selectable, first-class badge).
- [ ] Same for a Novita AI connection with `moonshotai/*` prefix.
- [ ] Ollama Cloud K2.5: reasoning toggle visible, defaults to ON, can be toggled OFF.
- [ ] Ollama Cloud K2.6: reasoning toggle visible, defaults to ON, can be toggled OFF.
- [ ] Novita K2.5: reasoning toggle hidden (`no_reasoning`); no reasoning rendered.
- [ ] Novita K2.6: reasoning toggle hidden (`always_on`); reasoning rendered by default.
- [ ] Tool roundtrip (websearch or similar) succeeds on every cell — most importantly Novita K2.5 and K2.6 (the MiMo failure mode).

---

## Self-review checklist (for the human running the plan)

- Spec coverage: each capability matrix cell has a test; each requirement in the spec maps to a Task above. ✓
- Placeholders: no TBD / TODO / "implement later". ✓
- Type consistency: `kimi_k2_capability_spec`, `_kimi_version`, `_unsupported_adapter`, `parse_chunk_ollama_cloud`, `parse_chunk_novita`, `build_request_for_ollama_cloud`, `build_request_for_novita`, `KimiK2Driver._novita_tool_acc` — all names match across tasks. ✓
- Pytest invocation: every test step uses `PYTHONPATH=/home/chris/workspace/chatsune uv run --project backend pytest` per memory `feedback_pytest_rootdir_quirk`. ✓
- No subagent-merge: Task 7 Step 3 explicitly forbids merge/push/branch-switch. ✓
