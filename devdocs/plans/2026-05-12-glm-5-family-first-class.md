# GLM-5 Family First-Class Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add z.AI's GLM-5 and GLM-5.1 to the curated first-class catalogue via Ollama Cloud and Novita, with capability metadata only (no driver layer).

**Architecture:** Pure additive change to `backend/modules/llm/data/model_capabilities.yaml` — four new entries (two models × two adapters). The capability YAML loader at `backend/modules/llm/_capabilities.py:115` automatically sets `first_class_support=True` on any match. Existing adapters already parse reasoning output (Ollama `thinking` field, Novita `reasoning_content`), so no wire-layer changes are needed.

**Tech Stack:** Python, Pydantic v2, PyYAML, pytest.

**Spec reference:** `devdocs/specs/2026-05-12-glm-5-family-first-class-design.md`

---

## Pre-flight

Confirm we're on the feature branch and the spec commit is in place.

- [ ] **Step 1: Verify branch state**

```bash
git status
git log --oneline -1
```

Expected: clean working tree, HEAD is the spec commit `Add GLM-5 family first-class capabilities spec`. Branch `feat/glm-5-family-first-class`.

---

### Task 1: Add failing tests for the four GLM-5 entries

**Files:**
- Modify: `tests/modules/llm/test_capabilities.py` (append four new test functions after the existing `test_grok_4_3_via_openrouter_has_no_effort_buckets`)

We follow the existing style in this file: one plain test function per scenario, no `pytest.mark.parametrize` (consistent with the eight tests already there).

- [ ] **Step 1: Read the existing test file once to confirm import block and stub adapter shape**

```bash
cat tests/modules/llm/test_capabilities.py
```

Expected: top of file imports `resolve_capabilities`, `ResolvedCapabilities`, `_StubAdapter` is defined near top. No changes needed to the import block.

- [ ] **Step 2: Append four failing tests**

Add the following block at the end of `tests/modules/llm/test_capabilities.py`:

```python
def test_glm_5_ollama_http_is_first_class_optional_reasoning():
    """GLM-5 via Ollama Cloud: reasoning toggleable via think:true/false."""
    res = resolve_capabilities(
        adapter_type="ollama_http",
        model_id="glm-5",
        adapter=_StubAdapter(),
    )
    assert isinstance(res, ResolvedCapabilities)
    assert res.first_class_support is True
    assert res.reasoning.kind == "optional"
    assert res.reasoning.effort is None
    assert res.reasoning.default_on is True
    assert res.tools.supported is True
    assert res.tools.exclusive_with_reasoning is False


def test_glm_5_1_ollama_http_is_first_class_optional_reasoning():
    """GLM-5.1 via Ollama Cloud: same profile as GLM-5."""
    res = resolve_capabilities(
        adapter_type="ollama_http",
        model_id="glm-5.1",
        adapter=_StubAdapter(),
    )
    assert isinstance(res, ResolvedCapabilities)
    assert res.first_class_support is True
    assert res.reasoning.kind == "optional"
    assert res.reasoning.effort is None
    assert res.reasoning.default_on is True
    assert res.tools.supported is True
    assert res.tools.exclusive_with_reasoning is False


def test_glm_5_novita_http_is_first_class_always_on_reasoning():
    """GLM-5 via Novita: reasoning_content cannot be suppressed upstream."""
    res = resolve_capabilities(
        adapter_type="novita_http",
        model_id="zai-org/glm-5",
        adapter=_StubAdapter(),
    )
    assert isinstance(res, ResolvedCapabilities)
    assert res.first_class_support is True
    assert res.reasoning.kind == "always_on"
    assert res.reasoning.effort is None
    assert res.tools.supported is True
    assert res.tools.exclusive_with_reasoning is False


def test_glm_5_1_novita_http_is_first_class_always_on_reasoning():
    """GLM-5.1 via Novita: same profile as GLM-5."""
    res = resolve_capabilities(
        adapter_type="novita_http",
        model_id="zai-org/glm-5.1",
        adapter=_StubAdapter(),
    )
    assert isinstance(res, ResolvedCapabilities)
    assert res.first_class_support is True
    assert res.reasoning.kind == "always_on"
    assert res.reasoning.effort is None
    assert res.tools.supported is True
    assert res.tools.exclusive_with_reasoning is False
```

- [ ] **Step 3: Run the four new tests, verify all four fail**

Run from the repository root (per memory: PYTHONPATH must point at the repo when running backend tests from the host):

```bash
PYTHONPATH=/home/chris/workspace/chatsune uv run pytest tests/modules/llm/test_capabilities.py -v -k "glm_5"
```

Expected: 4 failures. All four tests fail at `assert res.first_class_support is True` with `assert False is True`, because no YAML entry matches yet and the resolver falls through to `DEFAULT_CAPABILITIES` (which has `first_class_support=False`).

- [ ] **Step 4: Commit the failing tests**

```bash
git add tests/modules/llm/test_capabilities.py
git commit -m "Add failing tests for GLM-5 family first-class capabilities"
```

---

### Task 2: Add the four YAML entries to make the tests pass

**Files:**
- Modify: `backend/modules/llm/data/model_capabilities.yaml` (append four new blocks after the xAI grok-4.3 block)

- [ ] **Step 1: Append the four YAML entries at the end of the `models:` list**

Open `backend/modules/llm/data/model_capabilities.yaml`. The file currently ends with the grok-4.3 block (line 128). Append the following directly after line 128 (i.e. at end of file), keeping the existing two-space indent for the list items:

```yaml

  # z.AI GLM-5 family via Ollama Cloud — reasoning toggleable via think:
  # true/false (probed 2026-05-12 against ollama.com/api/chat). Tool calls
  # work in both reasoning modes. No vision support in this family.
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

  # z.AI GLM-5 family via Novita — reasoning is forced on upstream
  # (probed 2026-05-12: neither reasoning.enabled=false nor
  # chat_template_kwargs.thinking=false suppress reasoning_content).
  # Tool calls work. No vision support in this family.
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

- [ ] **Step 2: Run the four GLM tests, verify they now pass**

```bash
PYTHONPATH=/home/chris/workspace/chatsune uv run pytest tests/modules/llm/test_capabilities.py -v -k "glm_5"
```

Expected: 4 passed.

- [ ] **Step 3: Run the full capabilities test file to catch regressions**

```bash
PYTHONPATH=/home/chris/workspace/chatsune uv run pytest tests/modules/llm/test_capabilities.py -v
```

Expected: 12 passed (8 existing + 4 new). Specifically the existing `test_universal_fallback_when_nothing_matches` must still pass — i.e. our new entries don't accidentally widen any wildcard.

- [ ] **Step 4: Run the driver-integrated capabilities test for the driver-path regression check**

```bash
PYTHONPATH=/home/chris/workspace/chatsune uv run pytest backend/modules/llm/tests/test_capabilities_with_drivers.py -v
```

Expected: all pre-existing tests pass. The DeepSeek V4 driver pattern (`deepseek-v4-pro*`, `deepseek-v4-flash*`) does not overlap with `glm-5*` so no driver-path regression is plausible — this run is the safety check.

- [ ] **Step 5: Quick syntax check on the YAML file**

```bash
PYTHONPATH=/home/chris/workspace/chatsune uv run python -c "import yaml; yaml.safe_load(open('backend/modules/llm/data/model_capabilities.yaml'))"
```

Expected: no output (clean parse).

- [ ] **Step 6: Commit**

```bash
git add backend/modules/llm/data/model_capabilities.yaml
git commit -m "Add YAML capability entries for GLM-5 family (Ollama Cloud, Novita)"
```

---

### Task 3: Verify backend imports cleanly and run wider LLM test suite

**Files:** None modified. Pure verification.

- [ ] **Step 1: Smoke-import the capability module**

```bash
PYTHONPATH=/home/chris/workspace/chatsune uv run python -c "from backend.modules.llm._capabilities import resolve_capabilities, DEFAULT_CAPABILITIES; print('ok')"
```

Expected: `ok`. Confirms no YAML parse error breaks the loader at import-time (relevant because `_capabilities.py` re-reads the YAML on every call but a malformed file would surface here on first use).

- [ ] **Step 2: Run the broader LLM module tests, excluding the four DB-touching files (per memory)**

DB-dependent tests need Docker. From host, exclude them:

```bash
PYTHONPATH=/home/chris/workspace/chatsune uv run pytest backend/modules/llm/tests/ tests/modules/llm/ \
  --ignore=backend/modules/llm/tests/test_homelab_tokens.py \
  --ignore=backend/modules/llm/tests/test_homelab_repository.py \
  --ignore=backend/modules/llm/tests/test_connections_repository.py \
  --ignore=backend/modules/llm/tests/test_migration_connections_refactor.py \
  -v 2>&1 | tail -40
```

Expected: all selected tests pass. If a test file is missing from the ignore list and surfaces a `pymongo` connection error, add it to the ignore list and re-run — don't try to fix DB connectivity from the host.

- [ ] **Step 3: (Optional sanity) frontend type-check is not impacted**

This change is backend-only and frontend reads `first_class_support` via the existing `ModelMetaDto` field. No frontend build run needed for this plan.

---

### Task 4: Final review, merge, and clean up

**Files:** None modified.

- [ ] **Step 1: Review the diff**

```bash
git diff master --stat
git log master..HEAD --oneline
```

Expected: three commits on the branch — spec, failing tests, YAML implementation. Two files changed: the YAML file and `tests/modules/llm/test_capabilities.py`, plus the spec document.

- [ ] **Step 2: Wait for Chris's manual verification before merging**

Per the spec's "Manual Verification" section, Chris will exercise:
1. Ollama Cloud GLM-5.1 with reasoning off → no thinking section, direct content stream.
2. Ollama Cloud GLM-5.1 with reasoning on → thinking section appears.
3. Novita zai-org/glm-5.1 → thinking section appears always; UI hides the toggle (or shows "always on").
4. First-class badge visible on both provider paths in the model browser.
5. Tool-calling works on both provider paths.
6. Brief multilingual sanity check (German + Japanese prompts).
7. Regression: existing Claude/Grok/DeepSeek personas behave unchanged.

Subagents must **not** merge or push or switch branches (per memory). The merge to master happens after Chris confirms the manual verification.

- [ ] **Step 3: Once Chris has confirmed, merge to master**

```bash
git checkout master
git merge --no-ff feat/glm-5-family-first-class -m "Merge branch 'feat/glm-5-family-first-class'"
```

- [ ] **Step 4: Optional — delete the feature branch locally**

```bash
git branch -d feat/glm-5-family-first-class
```

---

## Notes for the implementer

- **Memory: DB tests on host.** Four test files in `backend/modules/llm/tests/` connect to MongoDB. They are listed in Task 3 Step 2's `--ignore` flags. Never run the "full backend suite" without these flags from the host.
- **Memory: PYTHONPATH quirk.** The backend's `pyproject.toml` lives in `backend/`, so pytest's `rootdir` becomes `backend/`. Prepending `PYTHONPATH=/home/chris/workspace/chatsune` ensures top-level `tests/` and `shared/` resolve as imports.
- **No driver layer.** The original spec investigation confirmed that both `_ollama_http.py` and `_novita_http.py` already emit `ThinkingDelta` events for the upstream reasoning channels. The YAML entry is the entire wiring required — there is no second file to touch.
- **Patterns are exact**, not wildcards. If z.AI releases a `glm-5-thinking` slug or similar, that will fall through to the adapter heuristic. Future variants get their own explicit entries; see the spec's "Offene Punkte" section.
