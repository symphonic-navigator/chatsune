# DSv4 Flash Capability Fix — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the DSv4 capability spec adapter+slug-aware so OR Flash users no longer see the broken `max` effort bucket (verified 2026-05-10: OR's `xhigh`-mapping halves Flash reasoning instead of expanding it). Add a defensive silent-downgrade in the OR builder for already-saved settings carrying `max`. Add a checked-in drift-detection probe.

**Architecture:** Single helper `_is_or_flash_quirk_applicable(adapter_type, slug)` is the lone branching point — used by both `_capability.py` (to filter buckets) and `_builders.py` (to silent-downgrade). Both call sites carry the same TODO-with-re-probe-date comment. A standalone harness probe under `backend/llm_harness/probes/` runs the empirical comparison and prints a verdict.

**Tech Stack:** Python 3.13, pytest, FastAPI internals (no surface change), httpx for the probe.

---

## Empirical baseline (probed 2026-05-10)

Reasoning-fordernder Prompt: "Finde drei strukturell verschiedene Beweise für die Unendlichkeit der Primzahlen (mindestens einer muss nicht-konstruktiv oder analytisch sein) und vergleiche ihre Eleganz, Stärke und welche Verallgemeinerungen sie nahelegen."

| Adapter | Slug | Wire effort | reasoning_tokens | reasoning_chars | prompt_eval | Verdict |
|---|---|---|---|---|---|---|
| openrouter_http | deepseek/deepseek-v4-flash | high | 4039 | 14023 | 62 | baseline |
| openrouter_http | deepseek/deepseek-v4-flash | xhigh | 2300 | 7898 | 62 | **broken (halved)** |
| ollama_http | deepseek-v4-flash | think:true | 3513 | 7289 | 62 | works |
| ollama_http | deepseek-v4-flash | think:"max" | 9880 | 29681 | 141 | works (4x reasoning, +EN+Markdown — server-side prompt injection visible in prompt_eval jump) |

OR rejects `effort="max"` directly (HTTP 400, accepted set is `{none, minimal, low, medium, high, xhigh}`), so `xhigh` is the only available mapping for our user-bucket "max". The bug is in OR's `xhigh→DSv4 Flash` translation, **not** in our wire shape.

The Ollama Cloud "max" path on Flash works mechanically (4x reasoning, sichtbarer DeepSeek-Server-System-Prompt-Injection durch +79 prompt_eval) but switches the trace language to English with Markdown structure. Per user decision (2026-05-10) this is acceptable — anyone inspecting CoT knows what they're doing. Buckets remain `["high","max"]` for Ollama Cloud.

---

## Capability matrix after this change

| (adapter_type, slug-pattern) | buckets | default |
|---|---|---|
| (`openrouter_http`, `*flash*`) | `["high"]` | `"high"` |
| (`openrouter_http`, anything else) | `["high","max"]` | `"high"` |
| (`ollama_http`, `*flash*`) | `["high","max"]` | `"high"` |
| (`ollama_http`, anything else) | `["high","max"]` | `"high"` |
| (any other adapter, anything) | `["high","max"]` | `"high"` (Plan-3/4 will probe Novita + nano-gpt) |

Slug match is fnmatch-basename (after stripping any `org/` prefix), case-insensitive — covers both `deepseek/deepseek-v4-flash` (OR-style) and `deepseek-v4-flash` (Ollama-style).

---

## File Structure

- `backend/modules/llm/_drivers/deepseek_v4/_capability.py` — extend with adapter+slug branching; import + use shared helper
- `backend/modules/llm/_drivers/deepseek_v4/_quirks.py` — **NEW**, holds `_is_or_flash_quirk_applicable(adapter_type, slug)` + the re-probe-date constant; underscore-prefixed because it's a driver-internal
- `backend/modules/llm/_drivers/deepseek_v4/_builders.py` — silent downgrade for OR+Flash+`max`→`high` with `logger.warning`
- `backend/modules/llm/tests/test_deepseek_v4_driver.py` — extend with capability matrix tests + builder downgrade tests
- `backend/llm_harness/probes/__init__.py` — **NEW**, marker
- `backend/llm_harness/probes/dsv4_flash_or_drift.py` — **NEW**, standalone probe with verdict
- `INSIGHTS.md` — append INS-041

---

## Important: scope discipline

**Do not** change anything outside the files listed above. In particular:

- Do **not** touch the parsers, the driver class, or any adapter file.
- Do **not** change the `_OR_EFFORT_MAP` or `_OLLAMA_EFFORT_MAP` constants — the silent downgrade happens **before** the map lookup, by replacing the user-effort with `"high"` when the quirk applies.
- Do **not** add inline imports inside functions or test methods. **All imports at the top of each file.** This was a recurring issue in Plan 2 — avoid.
- Do **not** add `_OR_EFFORT_MAP["max"]` or remove the existing `max → xhigh` entry; user-effort `"max"` on Pro slugs continues to map to `xhigh` unchanged.
- Do **not** invent additional capability changes beyond what this plan specifies.

---

## Task 1: Add `_quirks.py` with the shared helper

**Files:**
- Create: `backend/modules/llm/_drivers/deepseek_v4/_quirks.py`
- Test: `backend/modules/llm/tests/test_deepseek_v4_driver.py` (extend existing)

- [ ] **Step 1: Write the failing tests**

Append the following to `test_deepseek_v4_driver.py` (top-level imports already cover `pytest`; add `_is_or_flash_quirk_applicable` to the existing `from backend.modules.llm._drivers.deepseek_v4._quirks import ...` block — create the import line at the top of the file with the other driver imports):

```python
@pytest.mark.parametrize(
    "adapter_type,slug,expected",
    [
        # OR + Flash variants: quirk applies
        ("openrouter_http", "deepseek/deepseek-v4-flash", True),
        ("openrouter_http", "deepseek-v4-flash", True),
        ("openrouter_http", "DEEPSEEK/DEEPSEEK-V4-FLASH", True),
        # OR + non-Flash: quirk does not apply
        ("openrouter_http", "deepseek/deepseek-v4-pro", False),
        ("openrouter_http", "deepseek-v4-pro", False),
        # Ollama + Flash: quirk does not apply (Ollama path works)
        ("ollama_http", "deepseek-v4-flash", False),
        ("ollama_http", "deepseek/deepseek-v4-flash", False),
        # Other adapters + Flash: quirk does not apply
        ("nano_gpt_http", "deepseek/deepseek-v4-flash", False),
        ("novita_http", "deepseek/deepseek-v4-flash", False),
    ],
)
def test_or_flash_quirk_applicable(adapter_type: str, slug: str, expected: bool) -> None:
    assert _is_or_flash_quirk_applicable(adapter_type, slug) is expected
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=/home/chris/workspace/chatsune uv run pytest backend/modules/llm/tests/test_deepseek_v4_driver.py::test_or_flash_quirk_applicable -v`

Expected: ImportError on `_is_or_flash_quirk_applicable` (module doesn't exist yet).

- [ ] **Step 3: Create `_quirks.py`**

Create `backend/modules/llm/_drivers/deepseek_v4/_quirks.py`:

```python
"""DeepSeek V4 router-specific quirks.

Single source of truth for empirically-verified upstream bugs that the
driver layer has to work around. Each quirk has:
- a precise applicability check (adapter_type + slug pattern)
- a date when it was last probed
- a re-probe instruction (see ``backend/llm_harness/probes/``)

When a probe shows a quirk has been fixed upstream, drop the relevant
branch from this module and from any call site that consults it.
"""
from __future__ import annotations

from fnmatch import fnmatchcase

# OR-quirk: DSv4 Flash + reasoning.effort=xhigh halves the reasoning
# budget instead of expanding it. Probed 2026-05-10 with the prime-
# infinitude prompt: high=4039 reasoning_tokens, xhigh=2300 (ratio 0.57).
# OR rejects effort="max" (HTTP 400) so xhigh is the only available
# mapping; there is no other path to try.
#
# Re-probe quarterly via:
#   uv run python -m backend.llm_harness.probes.dsv4_flash_or_drift
# Next due: 2026-08-10. Drop the branch (and the override in
# ``_capability.py`` and ``_builders.py``) when the probe verdict flips
# to FIXED.
OR_FLASH_QUIRK_PROBED_AT = "2026-05-10"


def _is_or_flash_quirk_applicable(adapter_type: str, slug: str) -> bool:
    """Return True iff the OR-Flash xhigh-broken quirk applies here.

    Slug match is fnmatch-basename, case-insensitive — covers both the
    OR-prefixed form ``deepseek/deepseek-v4-flash`` and the un-prefixed
    Ollama form ``deepseek-v4-flash``.
    """
    if adapter_type != "openrouter_http":
        return False
    basename = slug.split("/", 1)[-1].lower()
    return fnmatchcase(basename, "*flash*")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=/home/chris/workspace/chatsune uv run pytest backend/modules/llm/tests/test_deepseek_v4_driver.py::test_or_flash_quirk_applicable -v`

Expected: 9/9 PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/modules/llm/_drivers/deepseek_v4/_quirks.py backend/modules/llm/tests/test_deepseek_v4_driver.py
git commit -m "Add DSv4 OR-Flash quirk helper for capability + builder branching"
```

---

## Task 2: Make `deepseek_v4_capability_spec` adapter+slug-aware

**Files:**
- Modify: `backend/modules/llm/_drivers/deepseek_v4/_capability.py`
- Test: `backend/modules/llm/tests/test_deepseek_v4_driver.py` (extend)

- [ ] **Step 1: Write the failing tests**

Append to `test_deepseek_v4_driver.py`:

```python
@pytest.mark.parametrize(
    "adapter_type,slug,expected_buckets",
    [
        # OR + Flash: only "high" (xhigh broken)
        ("openrouter_http", "deepseek/deepseek-v4-flash", ["high"]),
        ("openrouter_http", "deepseek-v4-flash", ["high"]),
        # OR + Pro: both
        ("openrouter_http", "deepseek/deepseek-v4-pro", ["high", "max"]),
        # Ollama + Flash: both work (per probe 2026-05-10)
        ("ollama_http", "deepseek-v4-flash", ["high", "max"]),
        # Ollama + Pro: both
        ("ollama_http", "deepseek-v4-pro", ["high", "max"]),
        # Future adapters keep the default until probed
        ("nano_gpt_http", "deepseek/deepseek-v4-flash", ["high", "max"]),
        ("novita_http", "deepseek/deepseek-v4-pro", ["high", "max"]),
    ],
)
def test_capability_spec_buckets(
    adapter_type: str, slug: str, expected_buckets: list[str],
) -> None:
    spec = deepseek_v4_capability_spec(adapter_type=adapter_type, slug=slug)
    assert spec.reasoning is not None
    assert spec.reasoning.effort.buckets == expected_buckets
    assert spec.reasoning.effort.default_bucket == "high"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=/home/chris/workspace/chatsune uv run pytest backend/modules/llm/tests/test_deepseek_v4_driver.py::test_capability_spec_buckets -v`

Expected: 2/7 FAIL — the two OR+Flash cases return `["high","max"]` instead of `["high"]`.

- [ ] **Step 3: Update `_capability.py`**

Replace the body of `deepseek_v4_capability_spec` so that when the OR-Flash quirk applies, the buckets list is `["high"]`. The rest of the spec (default_bucket, default_on, ToolCapability, first_class_support) stays identical. Add a TODO-with-date comment at the override pointing at the probe.

The new file:

```python
"""DeepSeek V4 capability spec.

Effort vocabulary is ``[high, max]`` per DeepSeek's official thinking-mode
docs (https://api-docs.deepseek.com/guides/thinking_mode): "low and medium
are mapped to high". We expose those two and only those two — router
extensions (OR's minimal/low/medium, Novita's silent-low) are not exposed
because their behaviour is not specified by DeepSeek.

Per-adapter override: see ``_quirks.py``. As of probe 2026-05-10, the
OR-Flash xhigh path halves reasoning instead of expanding it, so we
drop "max" from the buckets list for that combination only.
"""
from __future__ import annotations

from backend.modules.llm._capabilities import ResolvedCapabilities
from backend.modules.llm._drivers.deepseek_v4._quirks import (
    _is_or_flash_quirk_applicable,
)
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

    Default: ``buckets=["high","max"]``. Override: when the OR-Flash
    quirk applies (see ``_quirks.py``), drop ``"max"`` from the buckets
    list. Re-probe quarterly; drop the override branch when fixed.
    """
    if _is_or_flash_quirk_applicable(adapter_type, slug):
        # OR-quirk override (probed 2026-05-10): xhigh halves Flash
        # reasoning. Re-probe via dsv4_flash_or_drift.py; next due
        # 2026-08-10. Drop this branch when the probe flips to FIXED.
        buckets = ["high"]
    else:
        buckets = ["high", "max"]

    return ResolvedCapabilities(
        reasoning=ReasoningCapability(
            kind="optional",
            effort=ReasoningEffortSpec(
                buckets=buckets,
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

- [ ] **Step 4: Run all DSv4 driver tests to verify they pass**

Run: `PYTHONPATH=/home/chris/workspace/chatsune uv run pytest backend/modules/llm/tests/test_deepseek_v4_driver.py -v`

Expected: ALL pass (existing tests + the new capability_spec parametrise + the quirk-helper parametrise).

- [ ] **Step 5: Commit**

```bash
git add backend/modules/llm/_drivers/deepseek_v4/_capability.py backend/modules/llm/tests/test_deepseek_v4_driver.py
git commit -m "Make DSv4 capability_spec drop 'max' bucket for OR Flash"
```

---

## Task 3: Silent-downgrade in the OR builder for stale stored settings

**Why:** Capability filtering in the resolver is not the only path that can carry an effort value to the builder — a saved persona-default or model-config may still hold `"max"` from before this change. Per Memory `Defaults over delete`: silent-downgrade with a single `logger.warning`, never raise. (The builder already raises `ValueError` for **unknown** values; that path stays untouched. The new branch only handles the now-known-but-not-applicable `"max"` for Flash.)

**Files:**
- Modify: `backend/modules/llm/_drivers/deepseek_v4/_builders.py`
- Test: `backend/modules/llm/tests/test_deepseek_v4_driver.py` (extend)

- [ ] **Step 1: Write the failing tests**

Append to `test_deepseek_v4_driver.py`:

```python
def test_builder_silent_downgrade_or_flash_max(caplog) -> None:
    """OR + Flash + user-effort 'max' must downgrade to 'high' silently
    and emit one logger.warning. The wire body must show effort='high',
    not 'xhigh'."""
    request = _make_request(effort="max")
    with caplog.at_level("WARNING"):
        body = build_request_for_openrouter(
            slug="deepseek/deepseek-v4-flash", request=request,
        )
    assert body["reasoning"]["effort"] == "high"
    assert any(
        "DSv4 OR-Flash quirk" in rec.message and "downgraded" in rec.message
        for rec in caplog.records
    ), f"expected downgrade warning, got: {[r.message for r in caplog.records]}"


def test_builder_no_downgrade_or_pro_max(caplog) -> None:
    """OR + Pro + user-effort 'max' continues to map to wire 'xhigh',
    no warning."""
    request = _make_request(effort="max")
    with caplog.at_level("WARNING"):
        body = build_request_for_openrouter(
            slug="deepseek/deepseek-v4-pro", request=request,
        )
    assert body["reasoning"]["effort"] == "xhigh"
    assert not any(
        "DSv4 OR-Flash quirk" in rec.message for rec in caplog.records
    )


def test_builder_no_downgrade_or_flash_high(caplog) -> None:
    """OR + Flash + user-effort 'high' is unaffected, no warning."""
    request = _make_request(effort="high")
    with caplog.at_level("WARNING"):
        body = build_request_for_openrouter(
            slug="deepseek/deepseek-v4-flash", request=request,
        )
    assert body["reasoning"]["effort"] == "high"
    assert not any(
        "DSv4 OR-Flash quirk" in rec.message for rec in caplog.records
    )
```

Use the **existing** `_make_request(*, effort, reasoning_mode="on")` helper at line 64 of the test file. The helper hard-codes the request `model` field to `"deepseek/deepseek-v4-pro"` — this is fine, because `build_request_for_openrouter` takes the model from its own `slug` parameter (not from `request.model`); the request body's `model` field is overwritten by the OR builder. Do not modify the helper signature.

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=/home/chris/workspace/chatsune uv run pytest backend/modules/llm/tests/test_deepseek_v4_driver.py::test_builder_silent_downgrade_or_flash_max backend/modules/llm/tests/test_deepseek_v4_driver.py::test_builder_no_downgrade_or_pro_max backend/modules/llm/tests/test_deepseek_v4_driver.py::test_builder_no_downgrade_or_flash_high -v`

Expected: 1 FAIL (the downgrade test — wire emits `xhigh` not `high`), 2 PASS.

- [ ] **Step 3: Add the silent downgrade in `_builders.py`**

In `build_request_for_openrouter`, after the "Reasoning off OR no explicit effort" early-return and **before** the `_OR_EFFORT_MAP` lookup, add a quirk-aware downgrade. Add a module-level `logger = logging.getLogger(__name__)` at the top of the file (after imports) if it does not exist.

New top-of-file imports section (after the existing `from __future__` line):

```python
import logging
from typing import Any

from shared.dtos.inference import CompletionRequest
from backend.modules.llm._drivers.deepseek_v4._quirks import (
    _is_or_flash_quirk_applicable,
)


logger = logging.getLogger(__name__)
```

Inside `build_request_for_openrouter`, replace the section that begins
`# Reasoning on AND effort explicit: translate or reject.` with:

```python
    # Reasoning on AND effort explicit: translate or reject.
    user_effort = request.extras.reasoning_effort

    # OR-quirk silent downgrade: DSv4 Flash + xhigh halves reasoning
    # (probed 2026-05-10). When a stale stored setting carries "max"
    # for an OR-Flash slug, downgrade to "high" instead of routing to
    # the broken xhigh path. Capability filter normally prevents this
    # combination at the UI; the downgrade is defence-in-depth for
    # already-saved values. Re-probe quarterly (next due 2026-08-10);
    # drop this branch when the probe flips to FIXED.
    if user_effort == "max" and _is_or_flash_quirk_applicable(
        adapter_type="openrouter_http", slug=slug,
    ):
        logger.warning(
            "DSv4 OR-Flash quirk: effort='max' downgraded to 'high' "
            "for slug=%s — OR's xhigh path halves Flash reasoning.",
            slug,
        )
        user_effort = "high"

    if user_effort not in _OR_EFFORT_MAP:
        raise ValueError(
            f"DeepSeek V4 effort {user_effort!r} not in supported "
            f"buckets {list(_OR_EFFORT_MAP.keys())}; cannot translate "
            f"for OpenRouter"
        )
```

- [ ] **Step 4: Run the new tests to verify they pass**

Run: `PYTHONPATH=/home/chris/workspace/chatsune uv run pytest backend/modules/llm/tests/test_deepseek_v4_driver.py -v`

Expected: ALL pass.

- [ ] **Step 5: Commit**

```bash
git add backend/modules/llm/_drivers/deepseek_v4/_builders.py backend/modules/llm/tests/test_deepseek_v4_driver.py
git commit -m "Silent-downgrade DSv4 OR-Flash 'max' → 'high' with logger.warning"
```

---

## Task 4: Standalone drift-detection probe

**Files:**
- Create: `backend/llm_harness/probes/__init__.py` (empty marker)
- Create: `backend/llm_harness/probes/dsv4_flash_or_drift.py`

- [ ] **Step 1: Create the probe module marker**

Create `backend/llm_harness/probes/__init__.py` (empty file).

- [ ] **Step 2: Create the drift probe**

Create `backend/llm_harness/probes/dsv4_flash_or_drift.py`:

```python
"""Drift probe for the OR-Flash xhigh quirk (see ``_quirks.py``).

Run quarterly:
    uv run python -m backend.llm_harness.probes.dsv4_flash_or_drift

Reads the OR API key from ``.or-test-key`` in the project root.

Verdict logic: ratio = xhigh_reasoning_tokens / high_reasoning_tokens.
- ratio < 0.85 → STILL BROKEN (OR's xhigh halves Flash reasoning)
- ratio > 1.15 → FIXED (or different bug — investigate before relying)
- otherwise   → INCONCLUSIVE (ratio in noise band; re-run with a different prompt)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import httpx


_OR_URL = "https://openrouter.ai/api/v1/chat/completions"
_MODEL = "deepseek/deepseek-v4-flash"
_PROMPT = (
    "Finde drei strukturell verschiedene Beweise für die Unendlichkeit "
    "der Primzahlen (mindestens einer muss nicht-konstruktiv oder "
    "analytisch sein) und vergleiche ihre Eleganz, Stärke und welche "
    "Verallgemeinerungen sie nahelegen."
)


def _load_key() -> str:
    candidates = [
        Path(__file__).resolve().parents[3] / ".or-test-key",  # repo root
        Path.cwd() / ".or-test-key",
    ]
    for path in candidates:
        if path.is_file():
            return path.read_text().strip()
    raise SystemExit(
        "could not locate .or-test-key — looked in: "
        + ", ".join(str(p) for p in candidates)
    )


def _probe(client: httpx.Client, api_key: str, effort: str) -> dict[str, Any]:
    body = {
        "model": _MODEL,
        "messages": [{"role": "user", "content": _PROMPT}],
        "stream": False,
        "reasoning": {"effort": effort},
    }
    response = client.post(
        _OR_URL,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        content=json.dumps(body),
        timeout=120.0,
    )
    response.raise_for_status()
    return response.json()


def _reasoning_tokens(payload: dict[str, Any]) -> int:
    usage = payload.get("usage") or {}
    details = usage.get("completion_tokens_details") or {}
    tokens = details.get("reasoning_tokens")
    if tokens is None:
        raise SystemExit(
            f"no reasoning_tokens in payload: {json.dumps(payload)[:300]}"
        )
    return int(tokens)


def main() -> int:
    api_key = _load_key()
    with httpx.Client() as client:
        print(f"probing {_MODEL} @ openrouter, effort=high (baseline)…", flush=True)
        high_payload = _probe(client, api_key, "high")
        high_tokens = _reasoning_tokens(high_payload)
        print(f"  reasoning_tokens={high_tokens}", flush=True)

        print(f"probing {_MODEL} @ openrouter, effort=xhigh (test)…", flush=True)
        xhigh_payload = _probe(client, api_key, "xhigh")
        xhigh_tokens = _reasoning_tokens(xhigh_payload)
        print(f"  reasoning_tokens={xhigh_tokens}", flush=True)

    if high_tokens == 0:
        print("\nERROR: baseline returned zero reasoning_tokens — probe inconclusive")
        return 2

    ratio = xhigh_tokens / high_tokens
    print()
    print(f"ratio (xhigh / high) = {ratio:.2f}")
    if ratio < 0.85:
        print("verdict: STILL BROKEN — keep capability override + builder downgrade")
        return 1
    if ratio > 1.15:
        print("verdict: FIXED (or different bug — investigate)")
        print("  → drop the override in _capability.py and _builders.py")
        print("  → drop _is_or_flash_quirk_applicable from _quirks.py")
        return 0
    print("verdict: INCONCLUSIVE (ratio in noise band)")
    print("  → re-run with a different reasoning-demanding prompt")
    return 3


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 3: Smoke-run the probe**

Run: `uv run python -m backend.llm_harness.probes.dsv4_flash_or_drift`

Expected: ratio ≈ 0.55–0.65 (matches the 2026-05-10 baseline of 0.57), verdict `STILL BROKEN`, exit 1.

If exit 0 or 3 unexpectedly: do not change the capability override — flag to the controller for re-evaluation. Single-shot variance can rarely produce a near-1.0 ratio; re-run twice before concluding FIXED.

- [ ] **Step 4: Commit**

```bash
git add backend/llm_harness/probes/__init__.py backend/llm_harness/probes/dsv4_flash_or_drift.py
git commit -m "Add quarterly drift probe for OR-Flash xhigh quirk"
```

---

## Task 5: INSIGHTS.md entry

**Files:**
- Modify: `INSIGHTS.md` (append)

- [ ] **Step 1: Append the entry**

Append after INS-040:

```markdown
## INS-041 — OR's `xhigh` halves DSv4 Flash reasoning instead of expanding it (2026-05-10)

OpenRouter's `reasoning.effort: "xhigh"` for `deepseek/deepseek-v4-flash`
returns roughly **half** the reasoning tokens of `effort: "high"` on the
same prompt (probed 2026-05-10: 2300 vs 4039 reasoning_tokens, ratio
0.57). OR rejects `effort: "max"` directly (HTTP 400 — accepted set is
`{none, minimal, low, medium, high, xhigh}`), so `xhigh` is the only
mapping path for the user-bucket "max"; we cannot work around it by
sending a different value.

The same model on the same prompt via Ollama Cloud with `think: "max"`
returns **4×** the reasoning of `think: true` (9880 vs 3513 eval tokens)
and triggers a server-side system-prompt injection (prompt_eval jumps
from 62 to 141), so the upstream "max" mode itself works — the bug is
in OR's `xhigh → DeepSeek-Flash` translation.

DSv4 Pro on OR is unaffected: `xhigh` produces measurably more reasoning
than `high` as expected.

**Action:** For (`openrouter_http`, `*flash*`) we expose only
`effort.buckets = ["high"]`. The OR-Pro and Ollama-Cloud paths keep
`["high", "max"]`. A defensive silent-downgrade in the OR builder
catches stale stored settings still carrying `"max"`. Re-probe quarterly
via `backend/llm_harness/probes/dsv4_flash_or_drift.py`.

When the OR-side fix lands (verdict flips to FIXED), drop the override
in `_capability.py` and `_builders.py` and remove
`_is_or_flash_quirk_applicable` from `_quirks.py`.
```

- [ ] **Step 2: Commit**

```bash
git add INSIGHTS.md
git commit -m "INSIGHTS INS-041: OR xhigh halves DSv4 Flash reasoning"
```

---

## Task 6: Full DSv4 driver test sweep

**Files:**
- (verification only)

- [ ] **Step 1: Run the full DSv4 driver test file**

Run: `PYTHONPATH=/home/chris/workspace/chatsune uv run pytest backend/modules/llm/tests/test_deepseek_v4_driver.py -v`

Expected: all tests pass (the original 46 plus the new ones added in Tasks 1–3).

- [ ] **Step 2: Run the capabilities-with-drivers integration test**

Run: `PYTHONPATH=/home/chris/workspace/chatsune uv run pytest backend/modules/llm/tests/test_capabilities_with_drivers.py -v`

Expected: all tests pass (or, if a test asserts a specific bucket list for OR+Flash that no longer matches, update its expected value to `["high"]` — but **only** that one assertion, do not invent additional changes; leave a note in the commit message if you had to change a test).

- [ ] **Step 3: Commit any required test updates**

If Step 2 required test changes:

```bash
git add backend/modules/llm/tests/test_capabilities_with_drivers.py
git commit -m "Update capabilities-with-drivers test for OR-Flash bucket override"
```

---

## Manual verification (controller runs after subagents complete; do not do this in the subagent)

These steps are for the human controller after all tasks are merged into the branch and before merging the branch to master. Do not execute them in any subagent.

1. Restart backend (the auto-reload picks up the branch).
2. Open the Connections / Models UI in the frontend.
3. Pick a connection of type **OpenRouter** with DSv4 **Pro** as the active model. The reasoning-effort selector should show both **high** and **max**.
4. Switch the active model to DSv4 **Flash**. The selector should now show **only high** (the **max** option must be absent or disabled with a tooltip per Memory `Disabled-Buttons statt Verstecken` — verify which the existing UI does for reduced bucket lists).
5. Switch the connection to **Ollama Cloud** with DSv4 **Flash**. The selector should show **both high and max** again.
6. (Optional) Run the drift probe: `uv run python -m backend.llm_harness.probes.dsv4_flash_or_drift`. Expected: verdict `STILL BROKEN`, ratio ≈ 0.57.

---

## Done conditions

- All tasks 1–6 complete with green tests
- Manual verification 1–6 confirmed by the human controller
- Branch has 5 commits (one per task that touches code; INSIGHTS-only commit + test-fix commit are optional 6th and 7th)
- No untracked files left behind by the subagents
- The subagent must not merge to master, must not push, must not switch branches
