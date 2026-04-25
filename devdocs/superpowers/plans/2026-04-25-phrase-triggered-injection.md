# Phrase Triggered Injection (PTI) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add deterministic, phrase-triggered Knowledge Base document injection into user messages, coexisting with the existing embedding-based `knowledge_search` tool.

**Architecture:** Trigger phrases are matched as Unicode-normalised substrings against an in-RAM per-session index, invalidated via existing event-bus patterns. Hits inject the full document into the user message's `knowledge_context` (reused field, extended with a `source` discriminator). Cooldown and per-message caps protect token budgets.

**Tech Stack:** Python 3.12 / FastAPI / Pydantic v2 / Motor (MongoDB), TypeScript / React / Vite / Vitest, pytest-asyncio, existing Chatsune event-bus.

**Spec:** `devdocs/superpowers/specs/2026-04-25-phrase-triggered-injection-design.md`

---

## Conventions used throughout this plan

- **Backend tests** live in `backend/tests/...` (mirror module path), use `pytest-asyncio`, fixture `test_db`.
- **Frontend tests** colocated as `*.test.tsx` next to the component, use `vitest`.
- **Commit cadence:** one commit per task, message in imperative form (per CLAUDE.md).
- **Build verification at task end:** for backend changes run `uv run python -m py_compile <file>`; for frontend run `pnpm tsc --noEmit` from `frontend/`.
- **British English** in all code, comments, identifiers, and docs.
- **No new dependencies** introduced by this plan — everything uses existing libraries.

## File-structure overview

**New backend files:**

- `backend/modules/knowledge/_pti_normalisation.py` — `normalise()` function
- `backend/modules/knowledge/_pti_index.py` — `TriggerIndex`, `PtiIndexCache`, match logic
- `backend/modules/knowledge/_pti_service.py` — orchestration: cooldown, caps, public function
- `backend/tests/modules/knowledge/test_pti_normalisation.py`
- `backend/tests/modules/knowledge/test_pti_index.py`
- `backend/tests/modules/knowledge/test_pti_service.py`
- `backend/tests/modules/knowledge/test_pti_validation.py`
- `backend/tests/modules/chat/test_pti_lifecycle.py`

**New frontend files:**

- `frontend/src/features/knowledge/normalisePhrase.ts`
- `frontend/src/features/knowledge/normalisePhrase.test.ts`
- `frontend/src/features/knowledge/TriggerPhraseEditor.tsx`
- `frontend/src/features/knowledge/TriggerPhraseEditor.test.tsx`
- `frontend/src/features/knowledge/RefreshFrequencySelect.tsx`

**Modified backend files:**

- `shared/dtos/knowledge.py` — extend Document and Library DTOs
- `shared/dtos/chat.py` — type `knowledge_context` items with `source`, add `pti_overflow`
- `shared/topics.py` — add 4 library-attach/detach topics
- `backend/ws/event_bus.py` — add `_FANOUT` entries for new topics
- `backend/modules/knowledge/__init__.py` — export new public API
- `backend/modules/knowledge/_handlers.py` — content-size validation on document save
- `backend/modules/knowledge/_export.py` — round-trip new fields
- `backend/modules/knowledge/_import.py` — round-trip new fields
- `backend/modules/chat/_handlers.py` — publish `LIBRARY_ATTACHED/DETACHED_TO_SESSION` on diff
- `backend/modules/chat/_handlers_ws.py` — pre-persist PTI hook around `save_message`
- `backend/modules/chat/_repository.py` — accept `pti_overflow` parameter on `save_message`
- `backend/modules/chat/_models.py` — extend `ChatSessionDocument`, `ChatMessageDocument`
- `backend/modules/persona/_handlers.py` — publish `LIBRARY_ATTACHED/DETACHED_TO_PERSONA` on diff
- `backend/main.py` — wire PTI cache to event-bus

**Modified frontend files:**

- `frontend/src/app/components/user-modal/DocumentEditorModal.tsx` — embed `TriggerPhraseEditor` + `RefreshFrequencySelect`
- `frontend/src/app/components/user-modal/LibraryEditorModal.tsx` — embed `RefreshFrequencySelect` for default
- `frontend/src/features/chat/KnowledgePills.tsx` — source-aware icon + tooltip + overflow pill
- `INSIGHTS.md` — add normalisation-sync entry

---

# Phase A — Foundation: DTOs, Topics, FANOUT

These tasks touch only contracts. Once they land, every later task can depend on the new fields existing.

---

### Task 1: Extend Knowledge DTOs

**Files:**
- Modify: `shared/dtos/knowledge.py`
- Test: `backend/tests/test_knowledge_dtos.py` (NEW)

- [ ] **Step 1: Read the current DTO file** to find exact insertion points

```bash
cat shared/dtos/knowledge.py
```

- [ ] **Step 2: Add a `RefreshFrequency` type alias** at the top of the file (after imports)

```python
from typing import Literal

RefreshFrequency = Literal["rarely", "standard", "often"]
```

- [ ] **Step 3: Extend `KnowledgeDocumentDto` and `KnowledgeDocumentDetailDto`** with PTI fields

Add to both classes (these have shared fields — both need it):

```python
trigger_phrases: list[str] = Field(default_factory=list)
refresh: RefreshFrequency | None = None  # None = inherit from library
```

- [ ] **Step 4: Extend `KnowledgeLibraryDto`** with default refresh

Add field:

```python
default_refresh: RefreshFrequency = "standard"
```

- [ ] **Step 5: Write a smoke test** for the new fields

`backend/tests/test_knowledge_dtos.py`:

```python
from shared.dtos.knowledge import (
    KnowledgeDocumentDetailDto,
    KnowledgeDocumentDto,
    KnowledgeLibraryDto,
)


def test_document_dto_defaults_pti_fields():
    """Existing documents (no PTI fields in DB) deserialize cleanly."""
    dto = KnowledgeDocumentDto(
        id="d1",
        library_id="l1",
        title="Test",
        media_type="text/markdown",
        size_bytes=100,
        chunk_count=1,
        embedding_status="completed",
        embedding_error=None,
        created_at="2026-04-25T10:00:00Z",
        updated_at="2026-04-25T10:00:00Z",
    )
    assert dto.trigger_phrases == []
    assert dto.refresh is None


def test_library_dto_default_refresh():
    dto = KnowledgeLibraryDto(
        id="l1",
        name="Lore",
        description=None,
        nsfw=False,
        document_count=0,
        created_at="2026-04-25T10:00:00Z",
        updated_at="2026-04-25T10:00:00Z",
    )
    assert dto.default_refresh == "standard"


def test_document_dto_refresh_explicit_value():
    dto = KnowledgeDocumentDetailDto(
        id="d1", library_id="l1", title="T",
        media_type="text/markdown", size_bytes=0, chunk_count=0,
        embedding_status="completed", embedding_error=None,
        created_at="2026-04-25T10:00:00Z",
        updated_at="2026-04-25T10:00:00Z",
        content="hello",
        trigger_phrases=["andromedagalaxie"],
        refresh="often",
    )
    assert dto.refresh == "often"
    assert dto.trigger_phrases == ["andromedagalaxie"]
```

- [ ] **Step 6: Run tests**

```bash
cd /home/chris/workspace/chatsune
uv run pytest backend/tests/test_knowledge_dtos.py -v
```

Expected: 3 PASS

- [ ] **Step 7: Compile-check the modified DTO file**

```bash
uv run python -m py_compile shared/dtos/knowledge.py
```

- [ ] **Step 8: Commit**

```bash
git add shared/dtos/knowledge.py backend/tests/test_knowledge_dtos.py
git commit -m "Extend Knowledge DTOs with PTI fields (trigger_phrases, refresh, default_refresh)"
```

---

### Task 2: Extend Chat DTOs with typed knowledge_context and pti_overflow

**Files:**
- Modify: `shared/dtos/chat.py`
- Test: `backend/tests/test_chat_dtos_pti.py` (NEW)

- [ ] **Step 1: Inspect current `ChatMessageDto`** to find insertion points

```bash
grep -n "class ChatMessageDto\|knowledge_context\|web_search_context" shared/dtos/chat.py
```

- [ ] **Step 2: Add a `KnowledgeContextItem` typed model** above `ChatMessageDto`

```python
from typing import Literal


class KnowledgeContextItem(BaseModel):
    library_name: str
    document_title: str
    heading_path: list[str] = Field(default_factory=list)
    preroll_text: str | None = None
    content: str
    score: float | None = None
    source: Literal["search", "trigger"] = "search"
    triggered_by: str | None = None  # phrase, only when source="trigger"


class PtiOverflow(BaseModel):
    dropped_count: int
    dropped_titles: list[str]
```

- [ ] **Step 3: Change `knowledge_context` field type** on `ChatMessageDto` from `list[dict] | None` to `list[KnowledgeContextItem] | None`. Keep the default `None`.

- [ ] **Step 4: Add `pti_overflow` field** to `ChatMessageDto`

```python
pti_overflow: PtiOverflow | None = None
```

- [ ] **Step 5: Write smoke tests**

`backend/tests/test_chat_dtos_pti.py`:

```python
from shared.dtos.chat import KnowledgeContextItem, PtiOverflow


def test_knowledge_context_default_source_is_search():
    item = KnowledgeContextItem(
        library_name="Lore",
        document_title="Andromeda",
        content="…",
    )
    assert item.source == "search"
    assert item.triggered_by is None


def test_knowledge_context_trigger_source():
    item = KnowledgeContextItem(
        library_name="Lore",
        document_title="Andromeda",
        content="…",
        source="trigger",
        triggered_by="andromedagalaxie",
    )
    assert item.source == "trigger"
    assert item.triggered_by == "andromedagalaxie"


def test_pti_overflow_basic():
    o = PtiOverflow(dropped_count=2, dropped_titles=["A", "B"])
    assert o.dropped_count == 2
    assert o.dropped_titles == ["A", "B"]
```

- [ ] **Step 6: Run tests**

```bash
uv run pytest backend/tests/test_chat_dtos_pti.py -v
```

Expected: 3 PASS

- [ ] **Step 7: Build-check downstream**

The frontend consumes `ChatMessageDto`. Run TypeScript compile to confirm nothing breaks (since TS types are generated/aligned manually):

```bash
cd frontend && pnpm tsc --noEmit
```

If this surfaces TS-side type mismatches, **do not fix them in this task** — note the failure, the frontend pill task (Task 19) will address it. Document the failure in the commit message.

- [ ] **Step 8: Commit**

```bash
git add shared/dtos/chat.py backend/tests/test_chat_dtos_pti.py
git commit -m "Add KnowledgeContextItem and PtiOverflow DTOs to ChatMessageDto"
```

---

### Task 3: Add new Topics and FANOUT mappings

**Files:**
- Modify: `shared/topics.py`
- Modify: `backend/ws/event_bus.py`

- [ ] **Step 1: Inspect current Topics class**

```bash
grep -n "KNOWLEDGE_\|class Topics" shared/topics.py
```

- [ ] **Step 2: Add 4 new library-attach/detach topics** to `shared/topics.py` in the knowledge section

```python
class Topics:
    # … existing knowledge topics …
    LIBRARY_ATTACHED_TO_SESSION = "knowledge.library.attached_to_session"
    LIBRARY_DETACHED_FROM_SESSION = "knowledge.library.detached_from_session"
    LIBRARY_ATTACHED_TO_PERSONA = "knowledge.library.attached_to_persona"
    LIBRARY_DETACHED_FROM_PERSONA = "knowledge.library.detached_from_persona"
```

- [ ] **Step 3: Inspect `_FANOUT` structure**

```bash
sed -n '20,80p' backend/ws/event_bus.py
```

- [ ] **Step 4: Add `_FANOUT` entries** for the 4 new topics and any existing knowledge topics that are missing

In `backend/ws/event_bus.py`, add to `_FANOUT`:

```python
Topics.LIBRARY_ATTACHED_TO_SESSION:    ([], True),
Topics.LIBRARY_DETACHED_FROM_SESSION:  ([], True),
Topics.LIBRARY_ATTACHED_TO_PERSONA:    ([], True),
Topics.LIBRARY_DETACHED_FROM_PERSONA:  ([], True),
```

Also verify and (if missing) add the existing knowledge topics — these are required by Section 7.4 of the spec:

```python
Topics.KNOWLEDGE_DOCUMENT_CREATED: ([], True),
Topics.KNOWLEDGE_DOCUMENT_UPDATED: ([], True),
Topics.KNOWLEDGE_DOCUMENT_DELETED: ([], True),
```

If these are already present, leave them alone.

- [ ] **Step 5: Compile-check**

```bash
uv run python -m py_compile shared/topics.py backend/ws/event_bus.py
```

- [ ] **Step 6: Commit**

```bash
git add shared/topics.py backend/ws/event_bus.py
git commit -m "Add library-attach/detach topics and PTI-relevant FANOUT entries"
```

---

# Phase B — Backend Core PTI Logic

Pure logic, easily unit-tested. No DB, no event-bus.

---

### Task 4: Normalisation function

**Files:**
- Create: `backend/modules/knowledge/_pti_normalisation.py`
- Test: `backend/tests/modules/knowledge/test_pti_normalisation.py`

- [ ] **Step 1: Write the failing test file**

`backend/tests/modules/knowledge/test_pti_normalisation.py`:

```python
import pytest

from backend.modules.knowledge._pti_normalisation import normalise


def test_lowercase():
    assert normalise("Andromeda") == "andromeda"


def test_collapse_whitespace():
    assert normalise("dragon  ball   z") == "dragon ball z"


def test_trim():
    assert normalise("  hello  ") == "hello"


def test_unicode_casefold_ss():
    # German ß → ss under casefold
    assert normalise("Straße") == "strasse"


def test_unicode_nfc():
    # decomposed é (e + combining acute) → composed é
    decomposed = "café"
    composed = "café"
    assert normalise(decomposed) == normalise(composed) == "café"


def test_keeps_punctuation():
    assert normalise("Andromeda-Galaxie!") == "andromeda-galaxie!"


def test_keeps_emoji():
    assert normalise("🐉 dragon") == "🐉 dragon"


def test_keeps_cjk():
    assert normalise("アンドロメダ銀河") == "アンドロメダ銀河"


def test_keeps_cyrillic():
    assert normalise("  Андромеда   Галактика  ") == "андромеда галактика"


def test_idempotent():
    s = "  Foo BAR  baz!  "
    once = normalise(s)
    twice = normalise(once)
    assert once == twice


def test_various_whitespace_classes_collapse():
    # tab, NBSP, ideographic space → all become a single ASCII space
    s = "a\tb c　d"
    assert normalise(s) == "a b c d"


def test_empty_input():
    assert normalise("") == ""
    assert normalise("   ") == ""
```

- [ ] **Step 2: Run tests to confirm failure**

```bash
uv run pytest backend/tests/modules/knowledge/test_pti_normalisation.py -v
```

Expected: ImportError or all FAIL — module doesn't exist yet.

- [ ] **Step 3: Implement the module**

`backend/modules/knowledge/_pti_normalisation.py`:

```python
"""Unicode normalisation for PTI trigger phrases and user messages.

Three steps, applied identically to phrases on save and to messages on match:

1. Unicode NFC composition — makes visually identical strings byte-identical.
2. casefold() — Unicode-aware lowercasing (handles ß→ss, Turkish dotted I, etc.).
3. Whitespace collapse — any whitespace class run becomes one ASCII space, trimmed.

The function is idempotent: normalise(normalise(s)) == normalise(s).

NOTE: A TypeScript mirror lives at frontend/src/features/knowledge/normalisePhrase.ts.
The two implementations MUST stay in sync — see INSIGHTS.md.
"""

from __future__ import annotations

import unicodedata


def normalise(s: str) -> str:
    """Normalise a string for PTI matching."""
    s = unicodedata.normalize("NFC", s)
    s = s.casefold()
    # str.split() with no args splits on any Unicode whitespace and drops empties
    s = " ".join(s.split())
    return s
```

- [ ] **Step 4: Run tests, expect all pass**

```bash
uv run pytest backend/tests/modules/knowledge/test_pti_normalisation.py -v
```

Expected: 12 PASS

- [ ] **Step 5: Compile-check**

```bash
uv run python -m py_compile backend/modules/knowledge/_pti_normalisation.py
```

- [ ] **Step 6: Commit**

```bash
git add backend/modules/knowledge/_pti_normalisation.py backend/tests/modules/knowledge/test_pti_normalisation.py
git commit -m "Add PTI normalisation function (NFC + casefold + whitespace collapse)"
```

---

### Task 5: TriggerIndex and PtiIndexCache

**Files:**
- Create: `backend/modules/knowledge/_pti_index.py`
- Test: `backend/tests/modules/knowledge/test_pti_index.py`

- [ ] **Step 1: Write the failing test**

`backend/tests/modules/knowledge/test_pti_index.py`:

```python
import pytest

from backend.modules.knowledge._pti_index import (
    PtiIndexCache,
    TriggerIndex,
)


def test_trigger_index_add_phrase():
    idx = TriggerIndex()
    idx.add("andromedagalaxie", "doc1")
    assert idx.phrase_to_docs == {"andromedagalaxie": ["doc1"]}


def test_trigger_index_multiple_docs_same_phrase():
    idx = TriggerIndex()
    idx.add("andromedagalaxie", "doc1")
    idx.add("andromedagalaxie", "doc2")
    assert idx.phrase_to_docs == {"andromedagalaxie": ["doc1", "doc2"]}


def test_trigger_index_remove_doc():
    idx = TriggerIndex()
    idx.add("a", "doc1")
    idx.add("a", "doc2")
    idx.add("b", "doc1")
    idx.remove_doc("doc1")
    assert idx.phrase_to_docs == {"a": ["doc2"]}


def test_trigger_index_remove_doc_keeps_other_phrase():
    idx = TriggerIndex()
    idx.add("a", "doc1")
    idx.add("b", "doc1")
    idx.remove_doc("doc1")
    assert idx.phrase_to_docs == {}


def test_cache_lookup_initially_none():
    cache = PtiIndexCache()
    assert cache.get("session1") is None


def test_cache_set_and_get():
    cache = PtiIndexCache()
    idx = TriggerIndex()
    idx.add("foo", "d1")
    cache.set("session1", idx)
    assert cache.get("session1") is idx


def test_cache_invalidate():
    cache = PtiIndexCache()
    cache.set("s1", TriggerIndex())
    cache.invalidate("s1")
    assert cache.get("s1") is None


def test_cache_invalidate_unknown_session_is_noop():
    cache = PtiIndexCache()
    cache.invalidate("nonexistent")  # should not raise


def test_cache_drop_session():
    cache = PtiIndexCache()
    cache.set("s1", TriggerIndex())
    cache.drop_session("s1")
    assert cache.get("s1") is None
```

- [ ] **Step 2: Run, confirm failure (ImportError)**

```bash
uv run pytest backend/tests/modules/knowledge/test_pti_index.py -v
```

- [ ] **Step 3: Implement `_pti_index.py`**

`backend/modules/knowledge/_pti_index.py`:

```python
"""In-RAM trigger index for PTI matching.

`TriggerIndex` is a per-session structure mapping normalised phrases to
the document IDs they trigger. `PtiIndexCache` is a process-wide cache
keyed by session_id.

The cache holds plain-text trigger phrases. Future E2EE work will treat
this cache as the decryption boundary: phrases are encrypted at rest and
only ever decrypted into this in-memory structure for matching.
"""

from __future__ import annotations

from threading import RLock


class TriggerIndex:
    """A per-session phrase → doc_ids map.

    A single phrase may map to multiple documents (multiple library docs
    sharing the same trigger). Order within the doc list is preserved
    (insertion order) but is not relied upon for correctness.
    """

    def __init__(self) -> None:
        self.phrase_to_docs: dict[str, list[str]] = {}

    def add(self, phrase: str, doc_id: str) -> None:
        bucket = self.phrase_to_docs.setdefault(phrase, [])
        if doc_id not in bucket:
            bucket.append(doc_id)

    def remove_doc(self, doc_id: str) -> None:
        """Remove all phrase entries for the given document."""
        empty_phrases: list[str] = []
        for phrase, docs in self.phrase_to_docs.items():
            if doc_id in docs:
                docs.remove(doc_id)
                if not docs:
                    empty_phrases.append(phrase)
        for p in empty_phrases:
            del self.phrase_to_docs[p]


class PtiIndexCache:
    """Process-wide cache of TriggerIndex per session.

    Thread-safe via an internal lock. Each session_id has at most one
    TriggerIndex; absence means "not loaded yet — load on next access".
    """

    def __init__(self) -> None:
        self._per_session: dict[str, TriggerIndex] = {}
        self._lock = RLock()

    def get(self, session_id: str) -> TriggerIndex | None:
        with self._lock:
            return self._per_session.get(session_id)

    def set(self, session_id: str, index: TriggerIndex) -> None:
        with self._lock:
            self._per_session[session_id] = index

    def invalidate(self, session_id: str) -> None:
        with self._lock:
            self._per_session.pop(session_id, None)

    def drop_session(self, session_id: str) -> None:
        """Alias for invalidate — used when a session ends."""
        self.invalidate(session_id)

    def all_session_ids(self) -> list[str]:
        with self._lock:
            return list(self._per_session.keys())
```

- [ ] **Step 4: Run tests, expect all pass**

```bash
uv run pytest backend/tests/modules/knowledge/test_pti_index.py -v
```

Expected: 9 PASS

- [ ] **Step 5: Commit**

```bash
git add backend/modules/knowledge/_pti_index.py backend/tests/modules/knowledge/test_pti_index.py
git commit -m "Add TriggerIndex and PtiIndexCache for PTI matching"
```

---

### Task 6: Match algorithm

**Files:**
- Modify: `backend/modules/knowledge/_pti_index.py` (add `match` function)
- Modify: `backend/tests/modules/knowledge/test_pti_index.py` (add match tests)

- [ ] **Step 1: Add failing match tests** to `test_pti_index.py`

```python
from backend.modules.knowledge._pti_index import match_phrases


def _idx(*pairs: tuple[str, str]) -> TriggerIndex:
    idx = TriggerIndex()
    for phrase, doc_id in pairs:
        idx.add(phrase, doc_id)
    return idx


def test_match_no_hits():
    idx = _idx(("andromedagalaxie", "d1"))
    hits = match_phrases("hello world", idx)
    assert hits == []


def test_match_single_hit():
    idx = _idx(("andromedagalaxie", "d1"))
    hits = match_phrases("Lass uns über die Andromedagalaxie reden", idx)
    assert hits == [("d1", "andromedagalaxie", 19)]


def test_match_multi_word_phrase():
    idx = _idx(("dragon ball z", "d1"))
    hits = match_phrases("Ich liebe Dragon Ball Z einfach.", idx)
    # position depends on normalisation; just check the doc and phrase
    assert len(hits) == 1
    assert hits[0][0] == "d1"
    assert hits[0][1] == "dragon ball z"


def test_match_whitespace_robust():
    idx = _idx(("dragon ball z", "d1"))
    # double space in source — should still match because of normalisation
    hits = match_phrases("hey dragon  ball  z fans", idx)
    assert len(hits) == 1
    assert hits[0][0] == "d1"


def test_match_emoji():
    idx = _idx(("🐉", "d1"))
    hits = match_phrases("rar 🐉 fly", idx)
    assert len(hits) == 1
    assert hits[0][0] == "d1"


def test_match_returns_position_sorted():
    idx = _idx(
        ("sigma-sektor", "d2"),
        ("andromedagalaxie", "d1"),
        ("maartje voss", "d3"),
    )
    msg = "Lass uns über die Andromedagalaxie und den Sigma-Sektor diskutieren, vor allem die Rolle von Maartje Voss"
    hits = match_phrases(msg, idx)
    # Andromeda first, then Sigma, then Maartje
    assert [h[0] for h in hits] == ["d1", "d2", "d3"]


def test_match_one_phrase_multi_docs():
    idx = _idx(
        ("andromedagalaxie", "d1"),
        ("andromedagalaxie", "d2"),
    )
    hits = match_phrases("die Andromedagalaxie ist schön", idx)
    # Both docs returned, same position
    assert sorted(h[0] for h in hits) == ["d1", "d2"]
    assert all(h[1] == "andromedagalaxie" and h[2] == 4 for h in hits)
```

- [ ] **Step 2: Run, confirm import error**

```bash
uv run pytest backend/tests/modules/knowledge/test_pti_index.py::test_match_single_hit -v
```

- [ ] **Step 3: Append `match_phrases` to `_pti_index.py`**

```python
from backend.modules.knowledge._pti_normalisation import normalise


def match_phrases(
    message: str, index: TriggerIndex
) -> list[tuple[str, str, int]]:
    """Find all phrase hits in `message`.

    Returns a list of (doc_id, matched_phrase, position) tuples sorted
    by position of first occurrence in the normalised message. If a
    phrase maps to multiple docs, every doc is emitted at the same
    position.
    """
    norm = normalise(message)
    hits: list[tuple[str, str, int]] = []
    for phrase, doc_ids in index.phrase_to_docs.items():
        pos = norm.find(phrase)
        if pos >= 0:
            for doc_id in doc_ids:
                hits.append((doc_id, phrase, pos))
    hits.sort(key=lambda x: x[2])
    return hits
```

- [ ] **Step 4: Run all tests**

```bash
uv run pytest backend/tests/modules/knowledge/test_pti_index.py -v
```

Expected: 16 PASS (9 original + 7 new)

- [ ] **Step 5: Commit**

```bash
git add backend/modules/knowledge/_pti_index.py backend/tests/modules/knowledge/test_pti_index.py
git commit -m "Add PTI match_phrases function with position-sorted hits"
```

---

### Task 7: Cooldown and caps logic

**Files:**
- Create: `backend/modules/knowledge/_pti_service.py`
- Test: `backend/tests/modules/knowledge/test_pti_service.py`

This task contains the cooldown filter, the duplicate-doc dedupe, and the cap-enforcement logic. The "wire it to the chat lifecycle" task comes later.

- [ ] **Step 1: Write failing tests**

`backend/tests/modules/knowledge/test_pti_service.py`:

```python
"""Unit tests for PTI cooldown / cap logic.

These tests pass in plain Python objects — no DB, no event bus.
"""
from __future__ import annotations

import pytest

from backend.modules.knowledge._pti_service import (
    REFRESH_TO_N,
    DocumentCandidate,
    apply_cooldown_and_caps,
)


def _doc(
    doc_id: str,
    title: str,
    phrase: str,
    position: int,
    content: str = "x",
    refresh: str | None = None,
    library_default: str = "standard",
    token_count: int = 100,
) -> DocumentCandidate:
    return DocumentCandidate(
        doc_id=doc_id,
        title=title,
        library_name="lib",
        triggered_by=phrase,
        position=position,
        content=content,
        token_count=token_count,
        refresh=refresh,
        library_default_refresh=library_default,
    )


def test_refresh_to_n():
    assert REFRESH_TO_N["rarely"] == 10
    assert REFRESH_TO_N["standard"] == 7
    assert REFRESH_TO_N["often"] == 5


def test_no_candidates_returns_empty():
    items, overflow = apply_cooldown_and_caps(
        candidates=[],
        pti_last_inject={},
        user_msg_index=10,
        token_cap=8000,
        doc_cap=10,
    )
    assert items == []
    assert overflow is None


def test_single_hit_passes_through():
    cand = _doc("d1", "Andromeda", "andromedagalaxie", position=5)
    items, overflow = apply_cooldown_and_caps(
        candidates=[cand],
        pti_last_inject={},
        user_msg_index=10,
        token_cap=8000,
        doc_cap=10,
    )
    assert len(items) == 1
    assert items[0].doc_id == "d1"
    assert overflow is None


def test_duplicate_doc_id_only_injected_once():
    # Two phrases triggering the same doc
    c1 = _doc("d1", "T", "phrase-a", position=5)
    c2 = _doc("d1", "T", "phrase-b", position=15)
    items, _ = apply_cooldown_and_caps(
        candidates=[c1, c2],
        pti_last_inject={},
        user_msg_index=10,
        token_cap=8000,
        doc_cap=10,
    )
    assert len(items) == 1
    # First-hit wins (position-sorted)
    assert items[0].triggered_by == "phrase-a"


def test_cooldown_blocks_within_window():
    # standard refresh = 7. Last inject was at index 5; current is 10.
    # 10 - 5 = 5 < 7 → blocked.
    cand = _doc("d1", "T", "p", position=0)
    items, overflow = apply_cooldown_and_caps(
        candidates=[cand],
        pti_last_inject={"d1": 5},
        user_msg_index=10,
        token_cap=8000,
        doc_cap=10,
    )
    assert items == []
    assert overflow is None  # cooldown is silent — not overflow


def test_cooldown_passes_after_window():
    # 12 - 5 = 7 >= 7 → passes
    cand = _doc("d1", "T", "p", position=0)
    items, _ = apply_cooldown_and_caps(
        candidates=[cand],
        pti_last_inject={"d1": 5},
        user_msg_index=12,
        token_cap=8000,
        doc_cap=10,
    )
    assert len(items) == 1


def test_cooldown_uses_document_refresh_override():
    # often = 5. last=10, current=14 → 14-10=4 < 5 → blocked
    cand = _doc("d1", "T", "p", position=0, refresh="often")
    items, _ = apply_cooldown_and_caps(
        candidates=[cand],
        pti_last_inject={"d1": 10},
        user_msg_index=14,
        token_cap=8000,
        doc_cap=10,
    )
    assert items == []


def test_cooldown_uses_library_default_when_doc_refresh_none():
    # rarely = 10. last=0, current=8 → 8 < 10 → blocked
    cand = _doc("d1", "T", "p", position=0, refresh=None, library_default="rarely")
    items, _ = apply_cooldown_and_caps(
        candidates=[cand],
        pti_last_inject={"d1": 0},
        user_msg_index=8,
        token_cap=8000,
        doc_cap=10,
    )
    assert items == []


def test_doc_cap_enforced_with_overflow():
    candidates = [
        _doc(f"d{i}", f"Title{i}", f"phrase{i}", position=i, token_count=100)
        for i in range(15)
    ]
    items, overflow = apply_cooldown_and_caps(
        candidates=candidates,
        pti_last_inject={},
        user_msg_index=0,
        token_cap=10_000,
        doc_cap=10,
    )
    assert len(items) == 10
    assert overflow is not None
    assert overflow.dropped_count == 5
    assert overflow.dropped_titles == [f"Title{i}" for i in range(10, 15)]


def test_token_cap_enforced_with_overflow():
    candidates = [
        _doc(f"d{i}", f"T{i}", f"p{i}", position=i, token_count=3000)
        for i in range(5)
    ]
    items, overflow = apply_cooldown_and_caps(
        candidates=candidates,
        pti_last_inject={},
        user_msg_index=0,
        token_cap=8000,
        doc_cap=10,
    )
    # 3000 + 3000 = 6000 (ok), 6000+3000=9000 > 8000 → stop after 2
    assert len(items) == 2
    assert overflow is not None
    assert overflow.dropped_count == 3


def test_caps_count_only_emitted_documents():
    # First 5 docs blocked by cooldown, next 12 hit cap of 10
    cooldown = {f"cool{i}": 0 for i in range(5)}
    candidates = [
        _doc(f"cool{i}", f"C{i}", "p", position=i, token_count=100)
        for i in range(5)
    ] + [
        _doc(f"hot{i}", f"H{i}", "p", position=i + 100, token_count=100)
        for i in range(12)
    ]
    items, overflow = apply_cooldown_and_caps(
        candidates=candidates,
        pti_last_inject=cooldown,
        user_msg_index=1,  # 1-0=1 < 7 → cooldown blocks the 5 cool docs
        token_cap=10_000,
        doc_cap=10,
    )
    # 10 hot docs emitted, 2 hot dropped
    assert len(items) == 10
    assert all(i.doc_id.startswith("hot") for i in items)
    assert overflow is not None
    assert overflow.dropped_count == 2
```

- [ ] **Step 2: Run, confirm ImportError**

```bash
uv run pytest backend/tests/modules/knowledge/test_pti_service.py -v
```

- [ ] **Step 3: Implement `_pti_service.py`** (skeleton with cooldown + caps; the public `get_pti_injections` orchestrator comes in Task 9)

`backend/modules/knowledge/_pti_service.py`:

```python
"""PTI service-level logic: cooldown filtering, dedupe, cap enforcement.

Pure functions over plain dataclasses — no DB or event-bus dependencies.
The orchestrator that loads the index, runs the match, calls these
functions, and persists results lives in `_pti_orchestrator.py` (Task 9).
"""

from __future__ import annotations

from dataclasses import dataclass

from shared.dtos.chat import KnowledgeContextItem, PtiOverflow

REFRESH_TO_N: dict[str, int] = {
    "rarely": 10,
    "standard": 7,
    "often": 5,
}


@dataclass
class DocumentCandidate:
    """A trigger hit that still needs cooldown/cap filtering."""

    doc_id: str
    title: str
    library_name: str
    triggered_by: str
    position: int
    content: str
    token_count: int
    refresh: str | None  # "rarely" | "standard" | "often" | None
    library_default_refresh: str  # "rarely" | "standard" | "often"


def _effective_n(candidate: DocumentCandidate) -> int:
    setting = candidate.refresh or candidate.library_default_refresh
    return REFRESH_TO_N[setting]


def apply_cooldown_and_caps(
    candidates: list[DocumentCandidate],
    pti_last_inject: dict[str, int],
    user_msg_index: int,
    token_cap: int,
    doc_cap: int,
) -> tuple[list[KnowledgeContextItem], PtiOverflow | None]:
    """Apply dedupe → cooldown filter → caps.

    Args:
        candidates: position-sorted hits from match_phrases.
        pti_last_inject: session.pti_last_inject map.
        user_msg_index: current session.user_message_counter value.
        token_cap: max hidden-context tokens for this message.
        doc_cap: max documents for this message.

    Returns:
        (items, overflow) where items are the survivors as DTOs ready
        to attach to the message's knowledge_context, and overflow is
        None unless caps were hit.
    """
    seen_doc_ids: set[str] = set()
    eligible: list[DocumentCandidate] = []
    for c in candidates:
        if c.doc_id in seen_doc_ids:
            continue
        seen_doc_ids.add(c.doc_id)
        n = _effective_n(c)
        last = pti_last_inject.get(c.doc_id)
        if last is not None and (user_msg_index - last) < n:
            continue
        eligible.append(c)

    items: list[KnowledgeContextItem] = []
    dropped_titles: list[str] = []
    running_tokens = 0
    for c in eligible:
        if len(items) >= doc_cap or running_tokens + c.token_count > token_cap:
            dropped_titles.append(c.title)
            continue
        items.append(
            KnowledgeContextItem(
                library_name=c.library_name,
                document_title=c.title,
                heading_path=[],
                preroll_text=None,
                content=c.content,
                score=None,
                source="trigger",
                triggered_by=c.triggered_by,
            )
        )
        running_tokens += c.token_count

    overflow = (
        PtiOverflow(dropped_count=len(dropped_titles), dropped_titles=dropped_titles)
        if dropped_titles
        else None
    )
    return items, overflow
```

- [ ] **Step 4: Run tests, all pass**

```bash
uv run pytest backend/tests/modules/knowledge/test_pti_service.py -v
```

Expected: 11 PASS

- [ ] **Step 5: Commit**

```bash
git add backend/modules/knowledge/_pti_service.py backend/tests/modules/knowledge/test_pti_service.py
git commit -m "Add PTI cooldown and caps logic with deterministic dropout reporting"
```

---

### Task 8: Document content size validation

**Files:**
- Modify: `backend/modules/knowledge/_pti_service.py` (add validation function)
- Modify: `backend/tests/modules/knowledge/test_pti_service.py` (add validation tests)

- [ ] **Step 1: Append failing validation tests**

```python
from backend.modules.knowledge._pti_service import (
    PTI_DOC_MAX_TOKENS,
    PTI_DOC_MAX_CHARS,
    PtiContentTooLargeError,
    validate_pti_eligibility,
)


def test_validate_no_triggers_passes_any_size():
    # 50_000 chars, but no triggers — should pass without checking
    long = "x" * 50_000
    validate_pti_eligibility(content=long, trigger_phrases=[])  # no error


def test_validate_with_triggers_under_char_limit_passes():
    # Under 20_000 chars and under 5_000 tokens → ok
    validate_pti_eligibility(content="hi" * 100, trigger_phrases=["foo"])


def test_validate_rejects_over_char_limit():
    long = "x" * 25_000  # 25k chars > 20k
    with pytest.raises(PtiContentTooLargeError) as ei:
        validate_pti_eligibility(content=long, trigger_phrases=["foo"])
    assert "5,000 tokens" in str(ei.value) or "20,000 characters" in str(ei.value)


def test_validate_constants():
    assert PTI_DOC_MAX_TOKENS == 5_000
    assert PTI_DOC_MAX_CHARS == 20_000
```

- [ ] **Step 2: Run, confirm failure**

```bash
uv run pytest backend/tests/modules/knowledge/test_pti_service.py::test_validate_constants -v
```

- [ ] **Step 3: Append validation logic** to `_pti_service.py`

```python
PTI_DOC_MAX_TOKENS = 5_000
PTI_DOC_MAX_CHARS = 20_000  # cheap pre-check before invoking tokeniser


class PtiContentTooLargeError(ValueError):
    """Raised when a PTI-eligible document exceeds size caps."""


def validate_pti_eligibility(content: str, trigger_phrases: list[str]) -> None:
    """Reject documents that have trigger phrases but exceed size caps.

    Documents WITHOUT trigger phrases are not size-capped — they remain
    available for embedding-search retrieval at any size.

    Cheap char-length check first; falls through to exact token count
    only if char count is borderline.
    """
    if not trigger_phrases:
        return
    if len(content) > PTI_DOC_MAX_CHARS:
        raise PtiContentTooLargeError(
            "PTI documents must stay under 5,000 tokens "
            "(~20,000 characters). Split this document into smaller, "
            "focused entries."
        )
    # Char count is within limits. For Phase 1, treat the char cap as
    # authoritative (sufficient since 20k chars ≈ 5k tokens for most
    # languages and tokenisers). If we ever need exact-token enforcement,
    # plug count_tokens(content) here.
```

- [ ] **Step 4: Run all tests in file**

```bash
uv run pytest backend/tests/modules/knowledge/test_pti_service.py -v
```

Expected: all PASS (15 total)

- [ ] **Step 5: Commit**

```bash
git add backend/modules/knowledge/_pti_service.py backend/tests/modules/knowledge/test_pti_service.py
git commit -m "Add PTI document size validation (5000 tokens / 20000 chars cap)"
```

---

# Phase C — Backend Integration

Now we wire the pure logic to the database, the event bus, and the chat lifecycle.

---

### Task 9: PTI orchestrator (load index, get injections)

**Files:**
- Create: `backend/modules/knowledge/_pti_orchestrator.py`
- Modify: `backend/modules/knowledge/__init__.py`
- Test: `backend/tests/modules/knowledge/test_pti_orchestrator.py`

This task introduces the **public API**: a top-level `get_pti_injections` function that the chat module will call.

- [ ] **Step 1: Write the failing integration test**

`backend/tests/modules/knowledge/test_pti_orchestrator.py`:

```python
"""Integration test for PTI orchestrator.

Hits MongoDB via the test_db fixture; uses an in-memory PtiIndexCache.
"""
from __future__ import annotations

import pytest

from backend.modules.knowledge import get_pti_injections
from backend.modules.knowledge._pti_index import PtiIndexCache


@pytest.fixture
def cache() -> PtiIndexCache:
    return PtiIndexCache()


@pytest.mark.asyncio
async def test_orchestrator_no_attached_libraries_returns_empty(test_db, cache):
    # Set up a session with no libraries attached
    sess_id = "session-1"
    await test_db.chat_sessions.insert_one({
        "_id": sess_id,
        "user_id": "u1",
        "persona_id": "p1",
        "knowledge_library_ids": [],
        "user_message_counter": 0,
        "pti_last_inject": {},
    })
    items, overflow = await get_pti_injections(
        db=test_db,
        cache=cache,
        session_id=sess_id,
        message="andromedagalaxie",
        persona_library_ids=[],
    )
    assert items == []
    assert overflow is None


@pytest.mark.asyncio
async def test_orchestrator_full_path(test_db, cache):
    """End-to-end: library + doc with phrase, message matches, doc injected."""
    # Library
    await test_db.knowledge_libraries.insert_one({
        "_id": "lib1",
        "user_id": "u1",
        "name": "Lore",
        "default_refresh": "standard",
    })
    # Document
    await test_db.knowledge_documents.insert_one({
        "_id": "doc1",
        "library_id": "lib1",
        "title": "Andromeda Mythos",
        "content": "Andromeda is far away.",
        "media_type": "text/markdown",
        "trigger_phrases": ["andromedagalaxie"],
        "refresh": None,
    })
    # Session attaching the library
    await test_db.chat_sessions.insert_one({
        "_id": "s1",
        "user_id": "u1",
        "persona_id": "p1",
        "knowledge_library_ids": ["lib1"],
        "user_message_counter": 0,
        "pti_last_inject": {},
    })

    items, overflow = await get_pti_injections(
        db=test_db,
        cache=cache,
        session_id="s1",
        message="erzähl mir von der Andromedagalaxie",
        persona_library_ids=[],
    )
    assert len(items) == 1
    assert items[0].source == "trigger"
    assert items[0].triggered_by == "andromedagalaxie"
    assert items[0].document_title == "Andromeda Mythos"
    assert overflow is None

    # Verify cooldown was recorded
    sess = await test_db.chat_sessions.find_one({"_id": "s1"})
    assert sess["pti_last_inject"]["doc1"] == 1  # counter was incremented
    assert sess["user_message_counter"] == 1


@pytest.mark.asyncio
async def test_orchestrator_cooldown_blocks_second_call(test_db, cache):
    await test_db.knowledge_libraries.insert_one({
        "_id": "lib1", "user_id": "u1", "name": "Lore", "default_refresh": "often"
    })
    await test_db.knowledge_documents.insert_one({
        "_id": "doc1", "library_id": "lib1", "title": "T",
        "content": "c", "media_type": "text/markdown",
        "trigger_phrases": ["foo"], "refresh": None,
    })
    await test_db.chat_sessions.insert_one({
        "_id": "s1", "user_id": "u1", "persona_id": "p1",
        "knowledge_library_ids": ["lib1"],
        "user_message_counter": 0, "pti_last_inject": {},
    })

    # First call: hit
    items1, _ = await get_pti_injections(
        db=test_db, cache=cache, session_id="s1",
        message="foo", persona_library_ids=[],
    )
    assert len(items1) == 1

    # Second call (next user message, counter now 2): should be blocked by
    # cooldown (often = 5)
    items2, _ = await get_pti_injections(
        db=test_db, cache=cache, session_id="s1",
        message="foo again", persona_library_ids=[],
    )
    assert items2 == []
```

- [ ] **Step 2: Run, confirm ImportError on `get_pti_injections`**

```bash
uv run pytest backend/tests/modules/knowledge/test_pti_orchestrator.py -v
```

- [ ] **Step 3: Implement `_pti_orchestrator.py`**

`backend/modules/knowledge/_pti_orchestrator.py`:

```python
"""PTI orchestrator: load index, match, apply cooldown/caps, persist counter.

This is the public-API entry-point called by the chat module just before
persisting a user message. It mutates session state (counter +
pti_last_inject) atomically.
"""

from __future__ import annotations

from motor.motor_asyncio import AsyncIOMotorDatabase

from backend.modules.knowledge._pti_index import (
    PtiIndexCache,
    TriggerIndex,
    match_phrases,
)
from backend.modules.knowledge._pti_normalisation import normalise
from backend.modules.knowledge._pti_service import (
    DocumentCandidate,
    apply_cooldown_and_caps,
)
from shared.dtos.chat import KnowledgeContextItem, PtiOverflow

# Per-message caps, see Spec Section 6.4
MESSAGE_TOKEN_CAP = 8_000
MESSAGE_DOC_CAP = 10


async def get_pti_injections(
    db: AsyncIOMotorDatabase,
    cache: PtiIndexCache,
    session_id: str,
    message: str,
    persona_library_ids: list[str],
) -> tuple[list[KnowledgeContextItem], PtiOverflow | None]:
    """Match + filter + persist. Atomically updates session state."""
    session = await db.chat_sessions.find_one({"_id": session_id})
    if session is None:
        return [], None

    session_lib_ids = session.get("knowledge_library_ids") or []
    all_lib_ids = list({*persona_library_ids, *session_lib_ids})
    if not all_lib_ids:
        return [], None

    # Build / fetch the index
    index = cache.get(session_id)
    if index is None:
        index = await _build_index(db, all_lib_ids)
        cache.set(session_id, index)

    # Match
    hits = match_phrases(message, index)
    if not hits:
        # Even with no hits, we still increment the user-message counter
        # so cooldowns advance correctly.
        await db.chat_sessions.update_one(
            {"_id": session_id},
            {"$inc": {"user_message_counter": 1}},
        )
        return [], None

    # Resolve candidates against documents
    hit_doc_ids = list({h[0] for h in hits})
    docs_cur = db.knowledge_documents.find({"_id": {"$in": hit_doc_ids}})
    docs_by_id = {d["_id"]: d async for d in docs_cur}

    libs_cur = db.knowledge_libraries.find({"_id": {"$in": all_lib_ids}})
    libs_by_id = {l["_id"]: l async for l in libs_cur}

    candidates: list[DocumentCandidate] = []
    for doc_id, phrase, position in hits:
        doc = docs_by_id.get(doc_id)
        if doc is None:
            continue
        lib = libs_by_id.get(doc.get("library_id"))
        candidates.append(
            DocumentCandidate(
                doc_id=doc_id,
                title=doc.get("title", ""),
                library_name=(lib or {}).get("name", ""),
                triggered_by=phrase,
                position=position,
                content=doc.get("content", ""),
                token_count=_estimate_tokens(doc.get("content", "")),
                refresh=doc.get("refresh"),
                library_default_refresh=(lib or {}).get(
                    "default_refresh", "standard"
                ),
            )
        )

    # Atomically increment the counter, fetch the new value
    new_counter = await _increment_counter(db, session_id)
    pti_last_inject = session.get("pti_last_inject") or {}

    items, overflow = apply_cooldown_and_caps(
        candidates=candidates,
        pti_last_inject=pti_last_inject,
        user_msg_index=new_counter,
        token_cap=MESSAGE_TOKEN_CAP,
        doc_cap=MESSAGE_DOC_CAP,
    )

    # Persist updated cooldown map
    if items:
        injected_ids = [
            c.doc_id
            for c in candidates
            if any(
                i.document_title == c.title and i.triggered_by == c.triggered_by
                for i in items
            )
        ]
        update_fields = {
            f"pti_last_inject.{doc_id}": new_counter
            for doc_id in injected_ids
        }
        await db.chat_sessions.update_one(
            {"_id": session_id},
            {"$set": update_fields},
        )

    return items, overflow


async def _build_index(
    db: AsyncIOMotorDatabase, library_ids: list[str]
) -> TriggerIndex:
    """Load all trigger phrases of all documents in `library_ids`."""
    index = TriggerIndex()
    cur = db.knowledge_documents.find(
        {"library_id": {"$in": library_ids}, "trigger_phrases": {"$ne": []}},
        projection={"_id": 1, "trigger_phrases": 1},
    )
    async for doc in cur:
        for phrase in doc.get("trigger_phrases", []):
            normalised = normalise(phrase)
            if normalised:
                index.add(normalised, doc["_id"])
    return index


async def _increment_counter(db: AsyncIOMotorDatabase, session_id: str) -> int:
    """Atomically ++ user_message_counter and return the new value."""
    res = await db.chat_sessions.find_one_and_update(
        {"_id": session_id},
        {"$inc": {"user_message_counter": 1}},
        return_document=True,
    )
    return (res or {}).get("user_message_counter", 1)


def _estimate_tokens(content: str) -> int:
    """Cheap token estimate: 4 chars per token. Good enough for caps."""
    return max(1, len(content) // 4)
```

- [ ] **Step 4: Wire public export** — modify `backend/modules/knowledge/__init__.py`

Add to the `__all__` list:

```python
__all__ = [
    # … existing entries …
    "get_pti_injections",
    "pti_index_cache",  # singleton, exported for event-handlers
]
```

And at module level:

```python
from backend.modules.knowledge._pti_index import PtiIndexCache
from backend.modules.knowledge._pti_orchestrator import get_pti_injections

# Process-wide singleton — created at import time, lives for process lifetime.
pti_index_cache = PtiIndexCache()
```

- [ ] **Step 5: Run integration tests, all pass**

```bash
uv run pytest backend/tests/modules/knowledge/test_pti_orchestrator.py -v
```

Expected: 3 PASS

- [ ] **Step 6: Compile-check**

```bash
uv run python -m py_compile backend/modules/knowledge/_pti_orchestrator.py backend/modules/knowledge/__init__.py
```

- [ ] **Step 7: Commit**

```bash
git add backend/modules/knowledge/_pti_orchestrator.py backend/modules/knowledge/__init__.py backend/tests/modules/knowledge/test_pti_orchestrator.py
git commit -m "Add PTI orchestrator and expose get_pti_injections public API"
```

---

### Task 10: Publish library-attach/detach events on session and persona updates

**Files:**
- Modify: `backend/modules/chat/_handlers.py` (around line 181 — `update_session_knowledge_library_ids` call)
- Modify: `backend/modules/persona/_handlers.py` (around line 229 — persona library update)

The frontend already calls these endpoints; we need to publish events on the **diff** between old and new library lists.

- [ ] **Step 1: Inspect chat handler structure**

```bash
sed -n '160,200p' backend/modules/chat/_handlers.py
```

- [ ] **Step 2: Add diff-and-publish helper** — modify `backend/modules/chat/_handlers.py` near the existing endpoint

After fetching the existing session library_ids (or before calling the update), compute attach/detach diffs and publish events:

```python
from shared.topics import Topics

# Inside the PUT /sessions/{id}/knowledge handler, after authentication:
existing = await repo.get_session(session_id, user_id=user["sub"])
if existing is None:
    raise HTTPException(404)
old_ids = set(existing.get("knowledge_library_ids") or [])
new_ids = set(body.library_ids)

await repo.update_session_knowledge_library_ids(session_id, body.library_ids)

attached = new_ids - old_ids
detached = old_ids - new_ids
for lib_id in attached:
    await event_bus.publish(
        Topics.LIBRARY_ATTACHED_TO_SESSION,
        scope=f"session:{session_id}",
        target_user_ids=[user["sub"]],
        payload={"session_id": session_id, "library_id": lib_id},
    )
for lib_id in detached:
    await event_bus.publish(
        Topics.LIBRARY_DETACHED_FROM_SESSION,
        scope=f"session:{session_id}",
        target_user_ids=[user["sub"]],
        payload={"session_id": session_id, "library_id": lib_id},
    )
```

(Adjust the `event_bus.publish` signature to match the actual one used elsewhere in this file — verify by grepping for an existing `event_bus.publish(` call in the same handlers file.)

- [ ] **Step 3: Mirror in persona handlers**

In `backend/modules/persona/_handlers.py` around line 229 (the `PUT /api/personas/{id}/knowledge` handler):

```python
existing = await repo.find_by_id(persona_id, user["sub"])
if existing is None:
    raise HTTPException(404)
old_ids = set(existing.get("knowledge_library_ids") or [])
new_ids = set(body.library_ids)

await repo.update(
    persona_id, user["sub"], {"knowledge_library_ids": body.library_ids},
)

attached = new_ids - old_ids
detached = old_ids - new_ids
for lib_id in attached:
    await event_bus.publish(
        Topics.LIBRARY_ATTACHED_TO_PERSONA,
        scope=f"persona:{persona_id}",
        target_user_ids=[user["sub"]],
        payload={"persona_id": persona_id, "library_id": lib_id},
    )
for lib_id in detached:
    await event_bus.publish(
        Topics.LIBRARY_DETACHED_FROM_PERSONA,
        scope=f"persona:{persona_id}",
        target_user_ids=[user["sub"]],
        payload={"persona_id": persona_id, "library_id": lib_id},
    )
```

- [ ] **Step 4: Add a smoke test** for the chat handler

`backend/tests/test_chat_library_attach_events.py`:

```python
"""Verify LIBRARY_ATTACHED/DETACHED_TO_SESSION events are published on diff."""
import pytest

from shared.topics import Topics


@pytest.mark.asyncio
async def test_attach_event_on_new_library(client, user, session, monkeypatch):
    published: list[tuple[str, dict]] = []

    async def fake_publish(topic, **kwargs):
        published.append((topic, kwargs))

    monkeypatch.setattr("backend.ws.event_bus.publish", fake_publish)

    res = await client.put(
        f"/api/chat/sessions/{session['_id']}/knowledge",
        json={"library_ids": ["lib-new"]},
        headers={"Authorization": f"Bearer {user['token']}"},
    )
    assert res.status_code == 200
    topics = [t for t, _ in published]
    assert Topics.LIBRARY_ATTACHED_TO_SESSION in topics


@pytest.mark.asyncio
async def test_detach_event_on_removed_library(client, user, session, monkeypatch):
    # Pre-attach
    await client.put(
        f"/api/chat/sessions/{session['_id']}/knowledge",
        json={"library_ids": ["lib-old"]},
        headers={"Authorization": f"Bearer {user['token']}"},
    )
    published: list[tuple[str, dict]] = []
    async def fake_publish(topic, **kwargs):
        published.append((topic, kwargs))
    monkeypatch.setattr("backend.ws.event_bus.publish", fake_publish)

    res = await client.put(
        f"/api/chat/sessions/{session['_id']}/knowledge",
        json={"library_ids": []},
        headers={"Authorization": f"Bearer {user['token']}"},
    )
    assert res.status_code == 200
    topics = [t for t, _ in published]
    assert Topics.LIBRARY_DETACHED_FROM_SESSION in topics
```

- [ ] **Step 5: Run the test**

```bash
uv run pytest backend/tests/test_chat_library_attach_events.py -v
```

If the existing fixtures (`client`, `user`, `session`) don't match the actual `conftest.py`, adjust to use whichever fixtures the codebase provides. Adapt the `monkeypatch.setattr` target to whichever module exposes `event_bus.publish` — grep for a working test that already mocks it as a reference.

- [ ] **Step 6: Compile-check both handlers files**

```bash
uv run python -m py_compile backend/modules/chat/_handlers.py backend/modules/persona/_handlers.py
```

- [ ] **Step 7: Commit**

```bash
git add backend/modules/chat/_handlers.py backend/modules/persona/_handlers.py backend/tests/test_chat_library_attach_events.py
git commit -m "Publish library attach/detach events on persona and session updates"
```

---

### Task 11: PTI cache invalidation event subscriptions

**Files:**
- Create: `backend/modules/knowledge/_pti_invalidation.py`
- Modify: `backend/main.py` (wire subscriptions at startup)
- Test: `backend/tests/modules/knowledge/test_pti_invalidation.py`

- [ ] **Step 1: Write failing test**

`backend/tests/modules/knowledge/test_pti_invalidation.py`:

```python
"""Test PTI cache invalidation on relevant events."""
from __future__ import annotations

import pytest

from backend.modules.knowledge._pti_index import PtiIndexCache, TriggerIndex
from backend.modules.knowledge._pti_invalidation import (
    on_document_created,
    on_document_deleted,
    on_document_updated,
    on_library_attached_to_session,
    on_library_detached_from_session,
)


def _seed(cache: PtiIndexCache, session_id: str, doc_id: str, phrase: str):
    idx = TriggerIndex()
    idx.add(phrase, doc_id)
    cache.set(session_id, idx)


@pytest.mark.asyncio
async def test_document_deleted_removes_from_all_session_indices(test_db):
    cache = PtiIndexCache()
    _seed(cache, "s1", "doc1", "phr")
    _seed(cache, "s2", "doc1", "phr")
    await on_document_deleted(cache=cache, db=test_db, payload={"document_id": "doc1"})
    # Both indices invalidated (lazy-reload on next access is fine)
    assert cache.get("s1") is None
    assert cache.get("s2") is None


@pytest.mark.asyncio
async def test_document_updated_invalidates_index(test_db):
    cache = PtiIndexCache()
    _seed(cache, "s1", "doc1", "phr")
    await on_document_updated(cache=cache, db=test_db, payload={"document_id": "doc1"})
    assert cache.get("s1") is None


@pytest.mark.asyncio
async def test_document_created_invalidates_for_attached_sessions(test_db):
    # Set up a session that has lib1 attached, and a doc going into lib1
    await test_db.chat_sessions.insert_one({
        "_id": "s1", "user_id": "u1", "persona_id": "p1",
        "knowledge_library_ids": ["lib1"],
    })
    cache = PtiIndexCache()
    _seed(cache, "s1", "old", "p")
    await on_document_created(
        cache=cache, db=test_db,
        payload={"document_id": "doc-new", "library_id": "lib1"},
    )
    assert cache.get("s1") is None


@pytest.mark.asyncio
async def test_library_attached_invalidates_session(test_db):
    cache = PtiIndexCache()
    _seed(cache, "s1", "old", "p")
    await on_library_attached_to_session(
        cache=cache, db=test_db,
        payload={"session_id": "s1", "library_id": "lib1"},
    )
    assert cache.get("s1") is None


@pytest.mark.asyncio
async def test_library_detached_invalidates_session(test_db):
    cache = PtiIndexCache()
    _seed(cache, "s1", "old", "p")
    await on_library_detached_from_session(
        cache=cache, db=test_db,
        payload={"session_id": "s1", "library_id": "lib1"},
    )
    assert cache.get("s1") is None
```

- [ ] **Step 2: Run, confirm ImportError**

```bash
uv run pytest backend/tests/modules/knowledge/test_pti_invalidation.py -v
```

- [ ] **Step 3: Implement `_pti_invalidation.py`**

`backend/modules/knowledge/_pti_invalidation.py`:

```python
"""Event handlers that invalidate the PTI index cache.

These are pure async functions: take cache + db + payload, mutate cache.
Wiring to the event bus happens in `backend/main.py`.

Strategy: invalidate-on-event, lazy-reload on next match. We don't
pre-build the new index here — the orchestrator will rebuild on next
user message. Cheap, correct, and avoids a stale-index race.
"""

from __future__ import annotations

from motor.motor_asyncio import AsyncIOMotorDatabase

from backend.modules.knowledge._pti_index import PtiIndexCache


async def on_document_created(
    *, cache: PtiIndexCache, db: AsyncIOMotorDatabase, payload: dict
) -> None:
    library_id = payload.get("library_id")
    if not library_id:
        return
    await _invalidate_sessions_with_library(cache, db, library_id)


async def on_document_updated(
    *, cache: PtiIndexCache, db: AsyncIOMotorDatabase, payload: dict
) -> None:
    document_id = payload.get("document_id")
    if not document_id:
        return
    doc = await db.knowledge_documents.find_one(
        {"_id": document_id}, projection={"library_id": 1}
    )
    if doc is None:
        # Already deleted — fall through to broad invalidation
        await _invalidate_all(cache)
        return
    await _invalidate_sessions_with_library(cache, db, doc["library_id"])


async def on_document_deleted(
    *, cache: PtiIndexCache, db: AsyncIOMotorDatabase, payload: dict
) -> None:
    # We can't look the document up any more; broad invalidate.
    # Acceptable cost: next user message rebuilds the index.
    await _invalidate_all(cache)


async def on_library_attached_to_session(
    *, cache: PtiIndexCache, db: AsyncIOMotorDatabase, payload: dict
) -> None:
    session_id = payload.get("session_id")
    if session_id:
        cache.invalidate(session_id)


async def on_library_detached_from_session(
    *, cache: PtiIndexCache, db: AsyncIOMotorDatabase, payload: dict
) -> None:
    session_id = payload.get("session_id")
    if session_id:
        cache.invalidate(session_id)


async def on_library_attached_to_persona(
    *, cache: PtiIndexCache, db: AsyncIOMotorDatabase, payload: dict
) -> None:
    persona_id = payload.get("persona_id")
    if not persona_id:
        return
    await _invalidate_sessions_with_persona(cache, db, persona_id)


async def on_library_detached_from_persona(
    *, cache: PtiIndexCache, db: AsyncIOMotorDatabase, payload: dict
) -> None:
    persona_id = payload.get("persona_id")
    if not persona_id:
        return
    await _invalidate_sessions_with_persona(cache, db, persona_id)


async def _invalidate_sessions_with_library(
    cache: PtiIndexCache, db: AsyncIOMotorDatabase, library_id: str
) -> None:
    cur = db.chat_sessions.find(
        {"knowledge_library_ids": library_id}, projection={"_id": 1}
    )
    async for sess in cur:
        cache.invalidate(sess["_id"])


async def _invalidate_sessions_with_persona(
    cache: PtiIndexCache, db: AsyncIOMotorDatabase, persona_id: str
) -> None:
    cur = db.chat_sessions.find(
        {"persona_id": persona_id}, projection={"_id": 1}
    )
    async for sess in cur:
        cache.invalidate(sess["_id"])


async def _invalidate_all(cache: PtiIndexCache) -> None:
    for sess_id in cache.all_session_ids():
        cache.invalidate(sess_id)
```

- [ ] **Step 4: Wire subscriptions in `backend/main.py`**

Add at startup (find the existing event-bus subscription section, e.g. via `grep -n "event_bus\.subscribe\|on_event" backend/main.py`):

```python
from backend.modules.knowledge import pti_index_cache
from backend.modules.knowledge._pti_invalidation import (
    on_document_created,
    on_document_deleted,
    on_document_updated,
    on_library_attached_to_persona,
    on_library_attached_to_session,
    on_library_detached_from_persona,
    on_library_detached_from_session,
)
from shared.topics import Topics


def _wire_pti_invalidation(event_bus, db) -> None:
    """Subscribe PTI cache to invalidation events. Called from startup."""
    handlers = {
        Topics.KNOWLEDGE_DOCUMENT_CREATED: on_document_created,
        Topics.KNOWLEDGE_DOCUMENT_UPDATED: on_document_updated,
        Topics.KNOWLEDGE_DOCUMENT_DELETED: on_document_deleted,
        Topics.LIBRARY_ATTACHED_TO_SESSION: on_library_attached_to_session,
        Topics.LIBRARY_DETACHED_FROM_SESSION: on_library_detached_from_session,
        Topics.LIBRARY_ATTACHED_TO_PERSONA: on_library_attached_to_persona,
        Topics.LIBRARY_DETACHED_FROM_PERSONA: on_library_detached_from_persona,
    }
    for topic, handler in handlers.items():
        async def _wrap(payload, _h=handler):
            await _h(cache=pti_index_cache, db=db, payload=payload)
        event_bus.subscribe(topic, _wrap)
```

Call `_wire_pti_invalidation(event_bus, db)` from the existing startup hook (typically inside the FastAPI `lifespan` context manager). Find the right spot via:

```bash
grep -n "event_bus\|lifespan\|startup" backend/main.py | head
```

If the actual subscription mechanism differs (e.g. `event_bus.on()` instead of `subscribe()`), match the existing pattern.

- [ ] **Step 5: Run tests**

```bash
uv run pytest backend/tests/modules/knowledge/test_pti_invalidation.py -v
```

Expected: 5 PASS

- [ ] **Step 6: Compile-check**

```bash
uv run python -m py_compile backend/modules/knowledge/_pti_invalidation.py backend/main.py
```

- [ ] **Step 7: Commit**

```bash
git add backend/modules/knowledge/_pti_invalidation.py backend/main.py backend/tests/modules/knowledge/test_pti_invalidation.py
git commit -m "Wire PTI cache invalidation handlers to event bus"
```

---

### Task 12: Chat lifecycle integration — pre-persist PTI hook

**Files:**
- Modify: `backend/modules/chat/_handlers_ws.py` (around line 186)
- Modify: `backend/modules/chat/_repository.py` (extend `save_message`)
- Test: `backend/tests/modules/chat/test_pti_lifecycle.py`

- [ ] **Step 1: Extend `save_message` signature** in `_repository.py` — add `pti_overflow` parameter

Find the existing function (~ ln. 376):

```python
async def save_message(
    self,
    session_id: str,
    role: str,
    content: str,
    token_count: int,
    knowledge_context: list[dict] | None = None,
    pti_overflow: dict | None = None,  # NEW
    # … other existing params …
) -> dict:
```

Then in the body, ensure `pti_overflow` is added to the persisted document:

```python
doc = {
    "session_id": session_id,
    "role": role,
    "content": content,
    "token_count": token_count,
    "knowledge_context": knowledge_context,
    "pti_overflow": pti_overflow,  # NEW
    # … etc …
}
```

- [ ] **Step 2: Inject PTI call** in `_handlers_ws.py` around line 186

Locate the `save_message` call inside `handle_chat_send`. Just before it:

```python
from backend.modules.knowledge import get_pti_injections, pti_index_cache

# Determine persona library ids from the loaded persona/session context
persona_library_ids = (persona or {}).get("knowledge_library_ids") or []

pti_items, pti_overflow = await get_pti_injections(
    db=db,
    cache=pti_index_cache,
    session_id=session_id,
    message=text,
    persona_library_ids=persona_library_ids,
)
```

Pass them into `save_message`:

```python
saved_msg = await repo.save_message(
    session_id=session_id,
    role="user",
    content=text,
    token_count=token_count,
    knowledge_context=[i.model_dump() for i in pti_items] if pti_items else None,
    pti_overflow=pti_overflow.model_dump() if pti_overflow else None,
    correlation_id=correlation_id,
)
```

(Adjust to match the existing call's exact parameter style — keyword vs positional.)

- [ ] **Step 3: Write integration test**

`backend/tests/modules/chat/test_pti_lifecycle.py`:

```python
"""End-to-end test of PTI hook in chat lifecycle.

Sends a chat message via the WS handler path, verifies the persisted
ChatMessage has knowledge_context with source=trigger.
"""
import pytest

# This test exercises the complete pipeline. If a full WS test harness
# isn't readily available, fall back to calling handle_chat_send directly
# with a stub websocket.


@pytest.mark.asyncio
async def test_pti_injection_persists_to_message(
    test_db, monkeypatch
):
    # Seed library + doc + session
    await test_db.knowledge_libraries.insert_one({
        "_id": "lib1", "user_id": "u1", "name": "Lore",
        "default_refresh": "standard",
    })
    await test_db.knowledge_documents.insert_one({
        "_id": "doc1", "library_id": "lib1", "title": "Andromeda",
        "content": "Andromeda lore here.", "media_type": "text/markdown",
        "trigger_phrases": ["andromedagalaxie"], "refresh": None,
    })
    await test_db.chat_sessions.insert_one({
        "_id": "s1", "user_id": "u1", "persona_id": "p1",
        "knowledge_library_ids": ["lib1"],
        "user_message_counter": 0, "pti_last_inject": {},
    })
    await test_db.personas.insert_one({
        "_id": "p1", "user_id": "u1", "name": "Test",
        "knowledge_library_ids": [],
    })

    from backend.modules.chat._handlers_ws import handle_chat_send

    # Build a minimal stub for the inputs handle_chat_send needs.
    # Adapt this to the actual signature found via grep.
    sent_events: list[dict] = []

    class StubWs:
        async def send_json(self, data): sent_events.append(data)

    # Call handle_chat_send with a message containing the trigger.
    # The exact call shape depends on existing signatures — check
    # backend/modules/chat/_handlers_ws.py and adapt.
    await handle_chat_send(
        user_id="u1",
        data={
            "session_id": "s1",
            "content": "Erzähl mir von der Andromedagalaxie",
        },
        # … other required arguments per actual signature …
    )

    msg = await test_db.chat_messages.find_one(
        {"session_id": "s1", "role": "user"}
    )
    assert msg is not None
    kc = msg.get("knowledge_context") or []
    assert any(item.get("source") == "trigger" for item in kc)
```

> If `handle_chat_send`'s signature requires more setup than this stub can provide easily, mark this test as `@pytest.mark.skip(reason="needs full WS test harness — covered by manual smoke test")` and lean on the manual e2e test in Task 21.

- [ ] **Step 4: Run test**

```bash
uv run pytest backend/tests/modules/chat/test_pti_lifecycle.py -v
```

If skipped, note in the commit message.

- [ ] **Step 5: Compile-check**

```bash
uv run python -m py_compile backend/modules/chat/_handlers_ws.py backend/modules/chat/_repository.py
```

- [ ] **Step 6: Commit**

```bash
git add backend/modules/chat/_handlers_ws.py backend/modules/chat/_repository.py backend/tests/modules/chat/test_pti_lifecycle.py
git commit -m "Integrate PTI injection into chat user-message lifecycle"
```

---

### Task 13: Document save validation hook

**Files:**
- Modify: `backend/modules/knowledge/_handlers.py` (the document update / create endpoints)
- Test: `backend/tests/modules/knowledge/test_pti_validation.py`

- [ ] **Step 1: Write failing test**

`backend/tests/modules/knowledge/test_pti_validation.py`:

```python
"""Test the size cap on PTI-eligible documents at the API layer."""
import pytest


@pytest.mark.asyncio
async def test_create_document_with_triggers_within_limit(client, user, library):
    res = await client.post(
        f"/api/knowledge/libraries/{library['_id']}/documents",
        json={
            "title": "Small Lore",
            "content": "x" * 100,
            "media_type": "text/markdown",
            "trigger_phrases": ["foo"],
        },
        headers={"Authorization": f"Bearer {user['token']}"},
    )
    assert res.status_code == 201


@pytest.mark.asyncio
async def test_create_document_with_triggers_over_limit_rejected(client, user, library):
    res = await client.post(
        f"/api/knowledge/libraries/{library['_id']}/documents",
        json={
            "title": "Huge Lore",
            "content": "x" * 25_000,
            "media_type": "text/markdown",
            "trigger_phrases": ["foo"],
        },
        headers={"Authorization": f"Bearer {user['token']}"},
    )
    assert res.status_code == 400
    assert "5,000 tokens" in res.text or "20,000 characters" in res.text


@pytest.mark.asyncio
async def test_create_document_no_triggers_any_size_ok(client, user, library):
    res = await client.post(
        f"/api/knowledge/libraries/{library['_id']}/documents",
        json={
            "title": "Reference Doc",
            "content": "x" * 50_000,
            "media_type": "text/markdown",
            "trigger_phrases": [],
        },
        headers={"Authorization": f"Bearer {user['token']}"},
    )
    assert res.status_code == 201


@pytest.mark.asyncio
async def test_update_document_add_triggers_then_oversize_rejected(client, user, library):
    """Update path: add trigger phrases to an existing too-large document → reject."""
    create = await client.post(
        f"/api/knowledge/libraries/{library['_id']}/documents",
        json={"title": "Big", "content": "x" * 30_000,
              "media_type": "text/markdown", "trigger_phrases": []},
        headers={"Authorization": f"Bearer {user['token']}"},
    )
    doc_id = create.json()["id"]
    res = await client.put(
        f"/api/knowledge/libraries/{library['_id']}/documents/{doc_id}",
        json={"trigger_phrases": ["whatever"]},
        headers={"Authorization": f"Bearer {user['token']}"},
    )
    assert res.status_code == 400
```

- [ ] **Step 2: Run, confirm failures**

```bash
uv run pytest backend/tests/modules/knowledge/test_pti_validation.py -v
```

- [ ] **Step 3: Add validation in `_handlers.py`**

Inside the document create / update endpoints, after parsing the request body and before persisting:

```python
from backend.modules.knowledge._pti_normalisation import normalise
from backend.modules.knowledge._pti_service import (
    PtiContentTooLargeError,
    validate_pti_eligibility,
)

# … inside the create-document handler …
trigger_phrases_raw = body.trigger_phrases or []
trigger_phrases = [n for n in (normalise(p) for p in trigger_phrases_raw) if n]
try:
    validate_pti_eligibility(content=body.content, trigger_phrases=trigger_phrases)
except PtiContentTooLargeError as e:
    raise HTTPException(status_code=400, detail=str(e))
# Persist `trigger_phrases` (already normalised) on the document.
```

For the **update** path, when the request mutates either `content` or `trigger_phrases`, fetch the current state, compute the resulting (post-update) values, then call `validate_pti_eligibility` on those:

```python
existing = await repo.get_document(doc_id, library_id, user_id=user["sub"])
new_content = body.content if body.content is not None else existing["content"]
if body.trigger_phrases is not None:
    new_phrases = [n for n in (normalise(p) for p in body.trigger_phrases) if n]
else:
    new_phrases = existing.get("trigger_phrases", [])
try:
    validate_pti_eligibility(content=new_content, trigger_phrases=new_phrases)
except PtiContentTooLargeError as e:
    raise HTTPException(status_code=400, detail=str(e))
```

Then proceed with the existing update logic, persisting normalised phrases.

- [ ] **Step 4: Add the `trigger_phrases` and `refresh` fields** to the request models that handlers parse (likely Pydantic models defined either in `_handlers.py` or `shared/dtos/knowledge.py` — check first, may already be picked up via the DTO change in Task 1).

- [ ] **Step 5: Run tests**

```bash
uv run pytest backend/tests/modules/knowledge/test_pti_validation.py -v
```

Expected: 4 PASS

- [ ] **Step 6: Commit**

```bash
git add backend/modules/knowledge/_handlers.py backend/tests/modules/knowledge/test_pti_validation.py
git commit -m "Validate PTI document size and normalise trigger phrases on save"
```

---

### Task 14: Library export/import round-trip for PTI fields

**Files:**
- Modify: `backend/modules/knowledge/_export.py` (line ~39 — `_DOCUMENT_FIELDS`, `_LIBRARY_FIELDS`)
- Modify: `backend/modules/knowledge/_import.py` — accept and persist new fields
- Test: `backend/tests/modules/knowledge/test_pti_export_import.py`

- [ ] **Step 1: Write failing test**

`backend/tests/modules/knowledge/test_pti_export_import.py`:

```python
"""Round-trip PTI fields through library export/import."""
import pytest

from backend.modules.knowledge._export import export_library
from backend.modules.knowledge._import import import_library


@pytest.mark.asyncio
async def test_export_includes_pti_fields(test_db):
    await test_db.knowledge_libraries.insert_one({
        "_id": "lib1", "user_id": "u1", "name": "Lore",
        "description": "d", "nsfw": False,
        "default_refresh": "often",
    })
    await test_db.knowledge_documents.insert_one({
        "_id": "doc1", "library_id": "lib1", "title": "Andromeda",
        "content": "c", "media_type": "text/markdown",
        "trigger_phrases": ["andromedagalaxie"],
        "refresh": "rarely",
    })
    payload = await export_library(test_db, library_id="lib1", user_id="u1")
    assert payload["library"]["default_refresh"] == "often"
    docs = payload["documents"]
    assert len(docs) == 1
    assert docs[0]["trigger_phrases"] == ["andromedagalaxie"]
    assert docs[0]["refresh"] == "rarely"


@pytest.mark.asyncio
async def test_import_restores_pti_fields(test_db):
    payload = {
        "library": {
            "name": "Imported", "description": None, "nsfw": False,
            "default_refresh": "often",
        },
        "documents": [
            {
                "title": "Andromeda", "content": "c",
                "media_type": "text/markdown",
                "trigger_phrases": ["andromedagalaxie"],
                "refresh": "rarely",
            }
        ],
    }
    new_lib_id = await import_library(test_db, user_id="u1", payload=payload)
    lib = await test_db.knowledge_libraries.find_one({"_id": new_lib_id})
    assert lib["default_refresh"] == "often"
    docs = await test_db.knowledge_documents.find(
        {"library_id": new_lib_id}
    ).to_list(None)
    assert len(docs) == 1
    assert docs[0]["trigger_phrases"] == ["andromedagalaxie"]
    assert docs[0]["refresh"] == "rarely"
```

- [ ] **Step 2: Run, confirm test failure** (likely a missing field assertion)

```bash
uv run pytest backend/tests/modules/knowledge/test_pti_export_import.py -v
```

- [ ] **Step 3: Modify `_export.py`** — extend the field tuples

```python
_DOCUMENT_FIELDS: tuple[str, ...] = (
    "title", "content", "media_type",
    "trigger_phrases", "refresh",  # NEW
)
_LIBRARY_FIELDS: tuple[str, ...] = (
    "name", "description", "nsfw",
    "default_refresh",  # NEW
)
```

- [ ] **Step 4: Modify `_import.py`** — ensure new fields are read and persisted with sensible defaults if missing in older payloads

```python
# When constructing the import doc:
trigger_phrases = src_doc.get("trigger_phrases") or []
refresh = src_doc.get("refresh")  # None means inherit
default_refresh = src_lib.get("default_refresh", "standard")

# Normalise trigger phrases on import (defensive; old exports may have raw strings)
from backend.modules.knowledge._pti_normalisation import normalise

trigger_phrases = [n for n in (normalise(p) for p in trigger_phrases) if n]
```

Wire these into the existing insertion code in `_import.py`.

- [ ] **Step 5: Run tests**

```bash
uv run pytest backend/tests/modules/knowledge/test_pti_export_import.py -v
```

Expected: 2 PASS

- [ ] **Step 6: Compile-check**

```bash
uv run python -m py_compile backend/modules/knowledge/_export.py backend/modules/knowledge/_import.py
```

- [ ] **Step 7: Commit**

```bash
git add backend/modules/knowledge/_export.py backend/modules/knowledge/_import.py backend/tests/modules/knowledge/test_pti_export_import.py
git commit -m "Round-trip PTI fields through library export and import"
```

---

# Phase D — Frontend

---

### Task 15: TypeScript normalisation mirror

**Files:**
- Create: `frontend/src/features/knowledge/normalisePhrase.ts`
- Test: `frontend/src/features/knowledge/normalisePhrase.test.ts`

- [ ] **Step 1: Write failing test**

`frontend/src/features/knowledge/normalisePhrase.test.ts`:

```typescript
import { describe, expect, it } from "vitest"
import { normalisePhrase } from "./normalisePhrase"

describe("normalisePhrase", () => {
  it("lowercases", () => {
    expect(normalisePhrase("Andromeda")).toBe("andromeda")
  })

  it("collapses whitespace", () => {
    expect(normalisePhrase("dragon  ball   z")).toBe("dragon ball z")
  })

  it("trims", () => {
    expect(normalisePhrase("  hello  ")).toBe("hello")
  })

  it("casefolds German ß", () => {
    expect(normalisePhrase("Straße")).toBe("strasse")
  })

  it("composes Unicode (NFC)", () => {
    const decomposed = "café"
    const composed = "café"
    expect(normalisePhrase(decomposed)).toBe(normalisePhrase(composed))
    expect(normalisePhrase(decomposed)).toBe("café")
  })

  it("keeps punctuation", () => {
    expect(normalisePhrase("Andromeda-Galaxie!")).toBe("andromeda-galaxie!")
  })

  it("keeps emoji", () => {
    expect(normalisePhrase("🐉 dragon")).toBe("🐉 dragon")
  })

  it("keeps CJK", () => {
    expect(normalisePhrase("アンドロメダ銀河")).toBe("アンドロメダ銀河")
  })

  it("is idempotent", () => {
    const s = "  Foo BAR  baz!  "
    expect(normalisePhrase(normalisePhrase(s))).toBe(normalisePhrase(s))
  })

  it("collapses various whitespace classes", () => {
    expect(normalisePhrase("a\tb c　d")).toBe("a b c d")
  })

  it("returns empty string for blank input", () => {
    expect(normalisePhrase("")).toBe("")
    expect(normalisePhrase("   ")).toBe("")
  })
})
```

- [ ] **Step 2: Run test, confirm fail**

```bash
cd frontend && pnpm vitest run src/features/knowledge/normalisePhrase.test.ts
```

- [ ] **Step 3: Implement `normalisePhrase.ts`**

`frontend/src/features/knowledge/normalisePhrase.ts`:

```typescript
/**
 * Unicode normalisation for PTI trigger phrases and user messages.
 *
 * MIRROR of backend/modules/knowledge/_pti_normalisation.py — these
 * MUST stay in sync. See INSIGHTS.md.
 *
 * Three steps applied identically to phrases on save and to messages:
 *   1. Unicode NFC composition
 *   2. Locale-aware lowercase (toLocaleLowerCase("en"))
 *   3. Whitespace runs collapsed to single ASCII space, trimmed
 */

const WHITESPACE_RUN = /\s+/gu

export function normalisePhrase(input: string): string {
  let s = input.normalize("NFC")
  // Note: JS has no exact equivalent of Python's str.casefold(). For ASCII
  // and most cases toLocaleLowerCase is sufficient. The backend is the
  // authoritative normaliser — frontend is only used for live UI preview.
  // The single known divergence (German ß) is corrected explicitly below.
  s = s.toLocaleLowerCase("en")
  // Casefold approximation: handle ß explicitly to match Python casefold().
  s = s.replace(/ß/g, "ss")
  s = s.replace(WHITESPACE_RUN, " ").trim()
  return s
}
```

- [ ] **Step 4: Run tests, all pass**

```bash
cd frontend && pnpm vitest run src/features/knowledge/normalisePhrase.test.ts
```

Expected: 11 PASS

- [ ] **Step 5: TS-compile check**

```bash
cd frontend && pnpm tsc --noEmit
```

- [ ] **Step 6: Commit**

```bash
git add frontend/src/features/knowledge/normalisePhrase.ts frontend/src/features/knowledge/normalisePhrase.test.ts
git commit -m "Add TypeScript normalisePhrase mirror of backend PTI normalisation"
```

---

### Task 16: TriggerPhraseEditor component

**Files:**
- Create: `frontend/src/features/knowledge/TriggerPhraseEditor.tsx`
- Test: `frontend/src/features/knowledge/TriggerPhraseEditor.test.tsx`

- [ ] **Step 1: Write failing tests**

`frontend/src/features/knowledge/TriggerPhraseEditor.test.tsx`:

```tsx
import { fireEvent, render, screen } from "@testing-library/react"
import { describe, expect, it, vi } from "vitest"
import { TriggerPhraseEditor } from "./TriggerPhraseEditor"

describe("TriggerPhraseEditor", () => {
  it("renders existing phrases as tags", () => {
    render(
      <TriggerPhraseEditor
        value={["andromedagalaxie", "sigma-sektor"]}
        onChange={() => {}}
      />,
    )
    expect(screen.getByText("andromedagalaxie")).toBeInTheDocument()
    expect(screen.getByText("sigma-sektor")).toBeInTheDocument()
  })

  it("shows normalisation preview while typing", () => {
    render(<TriggerPhraseEditor value={[]} onChange={() => {}} />)
    const input = screen.getByPlaceholderText(/add phrase/i) as HTMLInputElement
    fireEvent.change(input, { target: { value: "  Andromeda  Galaxie  " } })
    expect(screen.getByText(/will be saved as/i)).toHaveTextContent(
      "andromeda galaxie",
    )
  })

  it("adds normalised phrase on Enter", () => {
    const onChange = vi.fn()
    render(<TriggerPhraseEditor value={[]} onChange={onChange} />)
    const input = screen.getByPlaceholderText(/add phrase/i)
    fireEvent.change(input, { target: { value: "Andromedagalaxie" } })
    fireEvent.keyDown(input, { key: "Enter" })
    expect(onChange).toHaveBeenCalledWith(["andromedagalaxie"])
  })

  it("removes a phrase when × is clicked", () => {
    const onChange = vi.fn()
    render(<TriggerPhraseEditor value={["foo", "bar"]} onChange={onChange} />)
    const removeButtons = screen.getAllByRole("button", { name: /remove/i })
    fireEvent.click(removeButtons[0])
    expect(onChange).toHaveBeenCalledWith(["bar"])
  })

  it("does not add duplicate phrases", () => {
    const onChange = vi.fn()
    render(<TriggerPhraseEditor value={["foo"]} onChange={onChange} />)
    const input = screen.getByPlaceholderText(/add phrase/i)
    fireEvent.change(input, { target: { value: "FOO" } })
    fireEvent.keyDown(input, { key: "Enter" })
    // FOO normalises to foo → already present → onChange called with same array
    expect(onChange).toHaveBeenCalledWith(["foo"])
  })

  it("ignores empty input on Enter", () => {
    const onChange = vi.fn()
    render(<TriggerPhraseEditor value={["foo"]} onChange={onChange} />)
    const input = screen.getByPlaceholderText(/add phrase/i)
    fireEvent.change(input, { target: { value: "   " } })
    fireEvent.keyDown(input, { key: "Enter" })
    expect(onChange).not.toHaveBeenCalled()
  })
})
```

- [ ] **Step 2: Run, confirm fail**

```bash
cd frontend && pnpm vitest run src/features/knowledge/TriggerPhraseEditor.test.tsx
```

- [ ] **Step 3: Implement the component**

`frontend/src/features/knowledge/TriggerPhraseEditor.tsx`:

```tsx
import { useState } from "react"
import { normalisePhrase } from "./normalisePhrase"

interface Props {
  value: string[]
  onChange: (next: string[]) => void
  disabled?: boolean
}

export function TriggerPhraseEditor({ value, onChange, disabled }: Props) {
  const [input, setInput] = useState("")
  const preview = normalisePhrase(input)

  const addPhrase = () => {
    if (!preview) return
    if (value.includes(preview)) {
      // Normalised duplicate — emit unchanged for parent to update field state
      onChange(value)
      setInput("")
      return
    }
    onChange([...value, preview])
    setInput("")
  }

  const removePhrase = (idx: number) => {
    const next = value.filter((_, i) => i !== idx)
    onChange(next)
  }

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap gap-2">
        {value.map((phrase, i) => (
          <span
            key={`${phrase}-${i}`}
            className="inline-flex items-center gap-1 rounded-full bg-white/5 px-3 py-1 text-sm"
          >
            <span className="font-mono">{phrase}</span>
            <button
              type="button"
              aria-label={`Remove ${phrase}`}
              onClick={() => removePhrase(i)}
              disabled={disabled}
              className="opacity-60 hover:opacity-100"
            >
              ×
            </button>
          </span>
        ))}
      </div>
      <div>
        <input
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" || e.key === ",") {
              e.preventDefault()
              addPhrase()
            }
          }}
          disabled={disabled}
          placeholder="add phrase…"
          className="w-full rounded border border-white/10 bg-transparent px-3 py-2 text-sm"
        />
        {input.trim() !== "" && preview !== input && (
          <p className="mt-1 text-xs text-white/50">
            Will be saved as: <span className="font-mono">{preview}</span>
          </p>
        )}
      </div>
      <p className="text-xs text-white/40">
        Add words or short phrases that should trigger this document. International
        characters and emoji are supported. Choose phrases specific enough not to
        match accidentally inside other words.
      </p>
    </div>
  )
}
```

- [ ] **Step 4: Run tests, all pass**

```bash
cd frontend && pnpm vitest run src/features/knowledge/TriggerPhraseEditor.test.tsx
```

Expected: 6 PASS

- [ ] **Step 5: TS-compile check**

```bash
cd frontend && pnpm tsc --noEmit
```

- [ ] **Step 6: Commit**

```bash
git add frontend/src/features/knowledge/TriggerPhraseEditor.tsx frontend/src/features/knowledge/TriggerPhraseEditor.test.tsx
git commit -m "Add TriggerPhraseEditor component with live normalisation preview"
```

---

### Task 17: RefreshFrequencySelect component

**Files:**
- Create: `frontend/src/features/knowledge/RefreshFrequencySelect.tsx`

(Single small component, used in both Library and Document editors. No separate test file — tests live in the editor modal tests.)

- [ ] **Step 1: Implement the component**

`frontend/src/features/knowledge/RefreshFrequencySelect.tsx`:

```tsx
export type RefreshFrequency = "rarely" | "standard" | "often"

interface Props {
  /** Current value. `null` means inherit (only valid when `inheritFrom` is provided). */
  value: RefreshFrequency | null
  onChange: (next: RefreshFrequency | null) => void
  /** When given, allow a "(inherit: X)" option that maps to value=null. */
  inheritFrom?: RefreshFrequency
  disabled?: boolean
  label?: string
}

const OPTION_STYLE: React.CSSProperties = {
  background: "#0f0d16",
  color: "rgba(255,255,255,0.85)",
}

const LABELS: Record<RefreshFrequency, string> = {
  rarely: "Rarely (every 10+ messages)",
  standard: "Standard (every 7+ messages)",
  often: "Often (every 5+ messages)",
}

export function RefreshFrequencySelect({
  value,
  onChange,
  inheritFrom,
  disabled,
  label,
}: Props) {
  const selectValue = value === null ? "__inherit__" : value
  return (
    <label className="flex flex-col gap-1 text-sm">
      {label && <span className="text-white/70">{label}</span>}
      <select
        value={selectValue}
        disabled={disabled}
        onChange={(e) => {
          const v = e.target.value
          onChange(v === "__inherit__" ? null : (v as RefreshFrequency))
        }}
        className="rounded border border-white/10 bg-transparent px-3 py-2 text-sm"
      >
        {inheritFrom && (
          <option value="__inherit__" style={OPTION_STYLE}>
            Inherit ({LABELS[inheritFrom].split(" ")[0]})
          </option>
        )}
        {(["rarely", "standard", "often"] as const).map((k) => (
          <option key={k} value={k} style={OPTION_STYLE}>
            {LABELS[k]}
          </option>
        ))}
      </select>
    </label>
  )
}
```

- [ ] **Step 2: TS-compile check**

```bash
cd frontend && pnpm tsc --noEmit
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/features/knowledge/RefreshFrequencySelect.tsx
git commit -m "Add RefreshFrequencySelect component"
```

---

### Task 18: Wire editors to TriggerPhraseEditor + RefreshFrequencySelect

**Files:**
- Modify: `frontend/src/app/components/user-modal/DocumentEditorModal.tsx`
- Modify: `frontend/src/app/components/user-modal/LibraryEditorModal.tsx`
- Modify: `frontend/src/core/api/knowledge.ts` (extend create/update payloads)

- [ ] **Step 1: Inspect DocumentEditorModal current structure**

```bash
cat frontend/src/app/components/user-modal/DocumentEditorModal.tsx
```

- [ ] **Step 2: Add state and UI for trigger_phrases + refresh** in `DocumentEditorModal.tsx`

In the component body, alongside the existing `title` and `content` state:

```tsx
import { TriggerPhraseEditor } from "@/features/knowledge/TriggerPhraseEditor"
import { RefreshFrequencySelect, type RefreshFrequency } from "@/features/knowledge/RefreshFrequencySelect"

// In state:
const [triggerPhrases, setTriggerPhrases] = useState<string[]>(
  initial?.trigger_phrases ?? [],
)
const [refresh, setRefresh] = useState<RefreshFrequency | null>(
  initial?.refresh ?? null,
)
```

In the JSX (between content textarea and save button):

```tsx
<div className="space-y-1">
  <label className="text-sm text-white/70">Trigger phrases</label>
  <TriggerPhraseEditor value={triggerPhrases} onChange={setTriggerPhrases} />
</div>

<RefreshFrequencySelect
  label="Refresh frequency"
  value={refresh}
  onChange={setRefresh}
  inheritFrom={libraryDefaultRefresh /* prop or derived */}
/>
```

`libraryDefaultRefresh` must come in as a prop on `DocumentEditorModalProps`. Add it to the interface and pass it from the call site (look for where DocumentEditorModal is currently rendered — `LibraryEditorModal` or a parent — and feed it the library's `default_refresh`).

In the save handler, include the new fields:

```tsx
await onSave({
  title,
  content,
  media_type: mediaType,
  trigger_phrases: triggerPhrases,
  refresh,
})
```

- [ ] **Step 3: Add `default_refresh` UI** to `LibraryEditorModal.tsx`

```tsx
import {
  RefreshFrequencySelect,
  type RefreshFrequency,
} from "@/features/knowledge/RefreshFrequencySelect"

// In state:
const [defaultRefresh, setDefaultRefresh] = useState<RefreshFrequency>(
  initial?.default_refresh ?? "standard",
)

// In JSX:
<RefreshFrequencySelect
  label="Default refresh frequency for documents"
  value={defaultRefresh}
  onChange={(v) => v && setDefaultRefresh(v)}
/>
// Pass to onSave / API call:
await onSave({ ...existingFields, default_refresh: defaultRefresh })
```

- [ ] **Step 4: Update API client types** in `frontend/src/core/api/knowledge.ts`

Where the `createDocument` / `updateDocument` request bodies are typed, add:

```typescript
trigger_phrases?: string[]
refresh?: "rarely" | "standard" | "often" | null
```

For `createLibrary` / `updateLibrary`:

```typescript
default_refresh?: "rarely" | "standard" | "often"
```

Existing function bodies don't need changes if they already pass-through arbitrary fields, but if they enumerate explicitly, extend them.

- [ ] **Step 5: TS-compile check**

```bash
cd frontend && pnpm tsc --noEmit
```

- [ ] **Step 6: Build check**

```bash
cd frontend && pnpm run build
```

- [ ] **Step 7: Smoke-test manually** by booting the dev server and:
  1. Opening Library Editor → set Default Refresh to "Often" → save → reopen → value persisted
  2. Opening Document Editor on a document in that library → see "Inherit (Often)" option in dropdown
  3. Adding a trigger phrase "Andromedagalaxie!" → tag shows `andromedagalaxie!`
  4. Trying to save a 25k-character document with a trigger phrase → 400 error surfaced in UI

(Document the manual smoke result in commit message.)

- [ ] **Step 8: Commit**

```bash
git add frontend/src/app/components/user-modal/DocumentEditorModal.tsx \
        frontend/src/app/components/user-modal/LibraryEditorModal.tsx \
        frontend/src/core/api/knowledge.ts
git commit -m "Wire trigger phrases and refresh-frequency selectors into editor modals"
```

---

### Task 19: KnowledgePills source-aware rendering and overflow pill

**Files:**
- Modify: `frontend/src/features/chat/KnowledgePills.tsx`
- Test: `frontend/src/features/chat/__tests__/KnowledgePills.test.tsx` (NEW — likely doesn't exist yet)

- [ ] **Step 1: Read current `KnowledgePills.tsx` in full**

```bash
cat frontend/src/features/chat/KnowledgePills.tsx
```

- [ ] **Step 2: Write failing tests**

`frontend/src/features/chat/__tests__/KnowledgePills.test.tsx`:

```tsx
import { fireEvent, render, screen } from "@testing-library/react"
import { describe, expect, it } from "vitest"
import { KnowledgePills } from "../KnowledgePills"

describe("KnowledgePills", () => {
  it("renders search-source pill with book icon", () => {
    render(
      <KnowledgePills
        items={[
          {
            library_name: "Lore",
            document_title: "Andromeda",
            content: "…",
            score: 0.8,
            source: "search",
          },
        ]}
        overflow={null}
      />,
    )
    const pill = screen.getByText("Andromeda")
    expect(pill).toBeInTheDocument()
    expect(pill.closest("[data-source]")).toHaveAttribute("data-source", "search")
  })

  it("renders trigger-source pill with sparkles icon and triggered_by tooltip", () => {
    render(
      <KnowledgePills
        items={[
          {
            library_name: "Lore",
            document_title: "Andromeda",
            content: "…",
            source: "trigger",
            triggered_by: "andromedagalaxie",
          },
        ]}
        overflow={null}
      />,
    )
    const pill = screen.getByText("Andromeda")
    expect(pill.closest("[data-source]")).toHaveAttribute("data-source", "trigger")
    fireEvent.click(pill)
    expect(screen.getByText(/triggered by/i)).toHaveTextContent(
      "andromedagalaxie",
    )
  })

  it("renders overflow pill when caps were applied", () => {
    render(
      <KnowledgePills
        items={[]}
        overflow={{ dropped_count: 3, dropped_titles: ["A", "B", "C"] }}
      />,
    )
    const overflowPill = screen.getByText(/\+3 limited/i)
    expect(overflowPill).toBeInTheDocument()
    fireEvent.click(overflowPill)
    expect(screen.getByText("A")).toBeInTheDocument()
    expect(screen.getByText("B")).toBeInTheDocument()
    expect(screen.getByText("C")).toBeInTheDocument()
  })
})
```

- [ ] **Step 3: Run tests, expect failure** (component signature is different)

```bash
cd frontend && pnpm vitest run src/features/chat/__tests__/KnowledgePills.test.tsx
```

- [ ] **Step 4: Refactor `KnowledgePills.tsx`** — accept the new shape, render source-aware pills + overflow pill

Replace the existing component with:

```tsx
import { useState } from "react"

export interface KnowledgeContextItem {
  library_name: string
  document_title: string
  heading_path?: string[]
  preroll_text?: string | null
  content: string
  score?: number | null
  source: "search" | "trigger"
  triggered_by?: string | null
}

export interface PtiOverflow {
  dropped_count: number
  dropped_titles: string[]
}

interface Props {
  items: KnowledgeContextItem[]
  overflow: PtiOverflow | null
}

export function KnowledgePills({ items, overflow }: Props) {
  const [expandedIdx, setExpandedIdx] = useState<number | null>(null)
  const [overflowOpen, setOverflowOpen] = useState(false)

  if (items.length === 0 && !overflow) return null

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap gap-2">
        {items.map((item, i) => (
          <Pill
            key={i}
            item={item}
            expanded={expandedIdx === i}
            onToggle={() => setExpandedIdx(expandedIdx === i ? null : i)}
          />
        ))}
        {overflow && (
          <button
            type="button"
            onClick={() => setOverflowOpen((v) => !v)}
            className="inline-flex items-center gap-1 rounded-full bg-white/5 px-3 py-1 text-xs text-white/50"
          >
            +{overflow.dropped_count} limited
          </button>
        )}
      </div>
      {overflow && overflowOpen && (
        <div className="rounded-md border border-white/10 bg-white/5 p-2 text-xs text-white/70">
          <p className="mb-1">Documents not injected (cap reached):</p>
          <ul className="list-disc pl-5">
            {overflow.dropped_titles.map((t, i) => (
              <li key={i}>{t}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}

function Pill({
  item,
  expanded,
  onToggle,
}: {
  item: KnowledgeContextItem
  expanded: boolean
  onToggle: () => void
}) {
  const Icon = item.source === "trigger" ? SparklesIcon : BookIcon
  return (
    <div data-source={item.source}>
      <button
        type="button"
        onClick={onToggle}
        className="inline-flex items-center gap-2 rounded-full bg-white/5 px-3 py-1 text-sm hover:bg-white/10"
      >
        <Icon className="h-3.5 w-3.5" />
        <span className="max-w-[14rem] truncate">{item.document_title}</span>
        {item.score != null && (
          <span className="text-xs text-white/40">
            {item.score.toFixed(2)}
          </span>
        )}
      </button>
      {expanded && (
        <div className="mt-2 rounded-md border border-white/10 bg-white/5 p-2 text-xs text-white/80">
          <p>
            <span className="text-white/40">Library:</span> {item.library_name}
          </p>
          {item.heading_path && item.heading_path.length > 0 && (
            <p>
              <span className="text-white/40">Path:</span>{" "}
              {item.heading_path.join(" › ")}
            </p>
          )}
          {item.source === "trigger" && item.triggered_by && (
            <p>
              <span className="text-white/40">Triggered by:</span>{" "}
              <span className="font-mono">{item.triggered_by}</span>
            </p>
          )}
          {item.preroll_text && (
            <p className="mt-2 text-white/50">{item.preroll_text}</p>
          )}
          <pre className="mt-2 max-h-40 overflow-auto whitespace-pre-wrap text-white/70">
            {item.content}
          </pre>
        </div>
      )}
    </div>
  )
}

function BookIcon(props: React.SVGProps<SVGSVGElement>) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" {...props}>
      <path d="M4 4h12a4 4 0 0 1 4 4v12H8a4 4 0 0 1-4-4V4z" />
      <path d="M4 16a4 4 0 0 1 4-4h12" />
    </svg>
  )
}

function SparklesIcon(props: React.SVGProps<SVGSVGElement>) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" {...props}>
      <path d="M12 2v4M12 18v4M2 12h4M18 12h4M5 5l3 3M16 16l3 3M5 19l3-3M16 8l3-3" />
    </svg>
  )
}
```

- [ ] **Step 5: Update call sites** to pass the new `overflow` prop. Find them:

```bash
grep -rn "KnowledgePills" frontend/src --include="*.tsx"
```

The MessageList (or whichever component currently renders pills from `message.knowledge_context`) needs to also pass `message.pti_overflow`:

```tsx
<KnowledgePills
  items={message.knowledge_context ?? []}
  overflow={message.pti_overflow ?? null}
/>
```

Also update the message store/types so `pti_overflow` is part of the message DTO interface. Look at `frontend/src/core/types/` and add the field.

- [ ] **Step 6: Run tests**

```bash
cd frontend && pnpm vitest run src/features/chat/__tests__/KnowledgePills.test.tsx
```

Expected: 3 PASS

- [ ] **Step 7: Build check**

```bash
cd frontend && pnpm tsc --noEmit && pnpm run build
```

- [ ] **Step 8: Commit**

```bash
git add frontend/src/features/chat/KnowledgePills.tsx \
        frontend/src/features/chat/__tests__/KnowledgePills.test.tsx
# also any call sites and types updated:
git add -u
git commit -m "Render PTI source discriminator and overflow pill in chat history"
```

---

# Phase E — Documentation and end-to-end smoke

---

### Task 20: INSIGHTS.md entry for normalisation sync

**Files:**
- Modify: `INSIGHTS.md`

- [ ] **Step 1: Read current INSIGHTS.md** to find the right insertion point

```bash
grep -n "INS-" INSIGHTS.md | tail -10
```

Find the next free INS-NNN number.

- [ ] **Step 2: Append a new entry**

```markdown
### INS-NNN — PTI normalisation lives in two languages

The PTI trigger-phrase / message normalisation function lives in two
files that must be kept manually in sync:

- `backend/modules/knowledge/_pti_normalisation.py` — Python authority,
  used at save time and during runtime matching.
- `frontend/src/features/knowledge/normalisePhrase.ts` — used for live
  preview in the trigger-phrase editor.

There is no runtime drift check. When changing the normalisation
algorithm — adding a step, changing an unicode behaviour, etc. — both
files must be updated together. Pattern is identical to the xAI
voice-expression-tags duplication (see CLAUDE.md and the existing
`backend/modules/integrations/_voice_expression_tags.py`).

Symptom of drift: tag shown in the editor differs from what the backend
matches against. Test via the existing parametrised tests on each side;
any diff in expected outputs is the smoking gun.
```

- [ ] **Step 3: Commit**

```bash
git add INSIGHTS.md
git commit -m "Add INSIGHTS entry for PTI normalisation backend/frontend sync"
```

---

### Task 21: End-to-end manual smoke test

**Files:** none — checklist only.

This is a non-automated test step. Execute manually, document outcome in commit message. Do **not** mark the task complete unless the checklist passes.

- [ ] **Step 1: Boot the stack**

```bash
docker compose up -d mongo redis
cd /home/chris/workspace/chatsune
uv run uvicorn backend.main:app --reload &
cd frontend && pnpm run dev
```

- [ ] **Step 2: Run the smoke checklist**

Open the dev frontend in a browser, log in, then verify:

- [ ] Create a Library named "Sci-Fi" with `default_refresh = often`
- [ ] Create three documents in that library:
  - "Andromeda Mythos", trigger `Andromedagalaxie`, refresh inherit, content ~500 chars
  - "Sigma Sektor", trigger `Sigma-Sektor`, refresh `rarely`, content ~500 chars
  - "Maartje Voss", trigger `Maartje Voss`, refresh inherit, content ~500 chars
- [ ] Try to save a 25k-character document with trigger `foo` → 400 error visible in UI
- [ ] Same document without trigger → saves fine
- [ ] Open a chat session, attach the Sci-Fi library
- [ ] Send: "Erzähl mir bitte von der Andromedagalaxie." → Pill with sparkles icon for "Andromeda Mythos" appears on the user message; tooltip shows `Triggered by: andromedagalaxie`
- [ ] Send next message that does NOT mention any trigger → no PTI pills (cooldown irrelevant since no match)
- [ ] Send a message mentioning ALL THREE triggers → all three pills appear, in mention-order
- [ ] Send 6 more messages without the Andromedagalaxie trigger
- [ ] On message 7 with trigger `Andromedagalaxie` → pill appears again (cooldown 5 expired since last inject was message 1)
- [ ] Edit "Andromeda Mythos", add another phrase. In a NEW message in the same session: trigger via the new phrase → pill appears (index invalidated correctly)
- [ ] Detach the library from the session in the chat sidebar → next message with `Andromedagalaxie` → no pill
- [ ] Re-attach via persona-level library setting → next message → pill appears (persona-attach event invalidated cache)
- [ ] Library export → check exported JSON contains `default_refresh`, `trigger_phrases`, `refresh`
- [ ] Library import the same JSON as a new library → fields preserved

- [ ] **Step 3: Document outcome**

If everything passed, commit a marker (no code change needed):

```bash
git commit --allow-empty -m "Smoke-test PTI end-to-end on local stack — all checklist items pass"
```

If anything failed, file follow-up tasks rather than marking the plan complete. Each failure becomes a TodoWrite entry with concrete reproduction steps and expected fix area.

---

# Self-Review Notes

This section is for the plan-author to verify completeness before handing off.

**Spec coverage check:**

| Spec section | Implementing task(s) |
|---|---|
| 4.1 Authoring | 16 (editor), 18 (modal integration) |
| 4.2 Refresh frequency | 17 (component), 18 (modal integration), 1 (DTOs) |
| 4.3 Match and injection | 4–9, 12 |
| 4.4 Pills | 19 |
| 5.1 New fields | 1, 2, 12 |
| 5.2 Removed fields | covered by absence — no task adds them |
| 6.1 Normalisation | 4 (Python), 15 (TS) |
| 6.2 Match algorithm | 6 |
| 6.3 Cooldown | 7 |
| 6.4 Caps | 7 |
| 6.5 Conflict (both inject) | 6, 7 (test_match_one_phrase_multi_docs + test in service) |
| 6.6 Per-doc cap | 8, 13 |
| 7.1 Module boundaries | 9 (orchestrator + public export) |
| 7.2 Lifecycle | 12 |
| 7.3 Events | 3 (topics + FANOUT) |
| 7.4 Cache invalidation | 11 |
| 7.5 Logging | (lightweight — added inline as part of Task 9; expand later if needed) |
| 8 Migration | None — Pydantic defaults handle it (covered in Task 1 tests) |
| 9 E2EE constraints | Architecture honours all 6 (in-RAM only, no FT-index, etc.) |
| 11 Acceptance Criteria | All covered across tasks; final smoke in 21 |

**Type consistency check:**

- `KnowledgeContextItem` (Pydantic in `shared/dtos/chat.py`, Task 2) ↔ `KnowledgeContextItem` (TS interface in `KnowledgePills.tsx`, Task 19) — same field names. ✅
- `PtiOverflow` (Pydantic, Task 2) ↔ `PtiOverflow` (TS, Task 19) — same fields. ✅
- `RefreshFrequency` literal `"rarely" | "standard" | "often"` consistent across DTOs (Task 1), service (Task 7), TS component (Task 17). ✅
- `pti_last_inject` map of `doc_id → int` consistent across orchestrator (Task 9) and tests (Task 7, 9). ✅

**Placeholder scan:** No "TBD", "TODO" strings in plan. A couple of "verify by greppping for existing pattern X" notes — these are precise and bounded, not vague placeholders.

---

**End of plan.**
