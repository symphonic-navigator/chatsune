# Knowledge Base System Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a knowledge base system where users manage libraries of documents, embed them for semantic search, assign them to personas/sessions, and retrieve relevant chunks via an LLM tool call.

**Architecture:** New `backend/modules/knowledge/` module following the existing Modular Monolith pattern. Owns 3 MongoDB collections (`knowledge_libraries`, `knowledge_documents`, `knowledge_chunks`). Integrates with the existing embedding module (fire-and-forget for bulk, blocking for queries). Frontend extends existing User Modal and Persona Overlay with Knowledge tabs, adds ad-hoc assignment dropdown to chat topbar, and displays retrieval results as lila pills.

**Tech Stack:** Python/FastAPI (backend), Pydantic v2 (models), Motor (MongoDB), MongoDB Vector Search (similarity), tiktoken (token counting), React/TSX/Zustand/Tailwind (frontend)

**Spec:** `docs/superpowers/specs/2026-04-06-knowledge-base-design.md`

---

## File Map

### New Files — Backend

| File | Responsibility |
|------|---------------|
| `shared/dtos/knowledge.py` | All knowledge DTOs (library, document, chunk, requests) |
| `shared/events/knowledge.py` | All knowledge event payloads |
| `backend/modules/knowledge/__init__.py` | Public API, router export, init_indexes |
| `backend/modules/knowledge/_repository.py` | MongoDB CRUD for 3 collections |
| `backend/modules/knowledge/_chunker.py` | Document chunking algorithm (port from Prototype 2) |
| `backend/modules/knowledge/_retrieval.py` | Vector search + knowledge_search tool executor |
| `backend/modules/knowledge/_handlers.py` | FastAPI REST endpoints |
| `tests/test_chunker.py` | Chunker unit tests |

### New Files — Frontend

| File | Responsibility |
|------|---------------|
| `frontend/src/core/api/knowledge.ts` | REST API client for knowledge endpoints |
| `frontend/src/core/store/knowledgeStore.ts` | Zustand store for libraries, documents, assignments |
| `frontend/src/core/types/knowledge.ts` | TypeScript interfaces matching backend DTOs |
| `frontend/src/features/chat/KnowledgePills.tsx` | Retrieved chunk pills in chat (lila) |
| `frontend/src/features/chat/KnowledgeDropdown.tsx` | Ad-hoc library assignment dropdown for topbar |
| `frontend/src/app/components/user-modal/DocumentEditorModal.tsx` | Markdown document editor modal |
| `frontend/src/app/components/user-modal/LibraryEditorModal.tsx` | Library create/edit modal |

### Modified Files — Backend

| File | Change |
|------|--------|
| `shared/topics.py` | Add 10 knowledge topic constants |
| `backend/main.py` | Add knowledge router, init_indexes, embedding event subscription |
| `backend/ws/event_bus.py` | Add knowledge topics to `_FANOUT` dict |
| `backend/modules/tools/_registry.py` | Register `knowledge_search` tool group |
| `backend/modules/tools/_executors.py` | Add `KnowledgeSearchExecutor` class |

### Modified Files — Frontend

| File | Change |
|------|--------|
| `frontend/src/app/components/user-modal/KnowledgeTab.tsx` | Replace placeholder with full library/document management |
| `frontend/src/app/components/persona-overlay/KnowledgeTab.tsx` | Replace placeholder with library assignment UI |
| `frontend/src/app/components/topbar/Topbar.tsx` | Add knowledge dropdown icon + component |
| `frontend/src/features/chat/ToolCallActivity.tsx` | Add `knowledge_search` to TOOL_LABELS |
| `frontend/src/features/chat/ChatView.tsx` | Render KnowledgePills, subscribe to knowledge events |
| `frontend/src/core/store/chatStore.ts` | Add `streamingKnowledgeContext` state |
| `frontend/src/core/api/chat.ts` | Add `ChatSessionDto.knowledge_library_ids` field |

---

## Task 1: Shared Contracts — Topics, DTOs, Events

**Files:**
- Modify: `shared/topics.py`
- Create: `shared/dtos/knowledge.py`
- Create: `shared/events/knowledge.py`

- [ ] **Step 1: Add knowledge topics to `shared/topics.py`**

Add at the end of the `Topics` class, before the closing of the class:

```python
    # Knowledge
    KNOWLEDGE_LIBRARY_CREATED = "knowledge.library.created"
    KNOWLEDGE_LIBRARY_UPDATED = "knowledge.library.updated"
    KNOWLEDGE_LIBRARY_DELETED = "knowledge.library.deleted"
    KNOWLEDGE_DOCUMENT_CREATED = "knowledge.document.created"
    KNOWLEDGE_DOCUMENT_UPDATED = "knowledge.document.updated"
    KNOWLEDGE_DOCUMENT_DELETED = "knowledge.document.deleted"
    KNOWLEDGE_DOCUMENT_EMBEDDING = "knowledge.document.embedding"
    KNOWLEDGE_DOCUMENT_EMBEDDED = "knowledge.document.embedded"
    KNOWLEDGE_DOCUMENT_EMBED_FAILED = "knowledge.document.embed_failed"
    KNOWLEDGE_SEARCH_COMPLETED = "knowledge.search.completed"
```

- [ ] **Step 2: Create `shared/dtos/knowledge.py`**

```python
from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class KnowledgeLibraryDto(BaseModel):
    id: str
    name: str
    description: str | None = None
    nsfw: bool = False
    document_count: int = 0
    created_at: datetime
    updated_at: datetime


class KnowledgeDocumentDto(BaseModel):
    id: str
    library_id: str
    title: str
    media_type: Literal["text/markdown", "text/plain"]
    size_bytes: int
    chunk_count: int = 0
    embedding_status: Literal["pending", "processing", "completed", "failed"]
    embedding_error: str | None = None
    created_at: datetime
    updated_at: datetime


class KnowledgeDocumentDetailDto(KnowledgeDocumentDto):
    content: str


class CreateLibraryRequest(BaseModel):
    name: str
    description: str | None = None
    nsfw: bool = False


class UpdateLibraryRequest(BaseModel):
    name: str | None = None
    description: str | None = None
    nsfw: bool | None = None


class CreateDocumentRequest(BaseModel):
    title: str
    content: str
    media_type: Literal["text/markdown", "text/plain"] = "text/markdown"


class UpdateDocumentRequest(BaseModel):
    title: str | None = None
    content: str | None = None
    media_type: Literal["text/markdown", "text/plain"] | None = None


class RetrievedChunkDto(BaseModel):
    library_name: str
    document_title: str
    heading_path: list[str]
    preroll_text: str
    content: str
    score: float


class SetKnowledgeLibrariesRequest(BaseModel):
    library_ids: list[str]
```

- [ ] **Step 3: Create `shared/events/knowledge.py`**

```python
from datetime import datetime

from pydantic import BaseModel

from shared.dtos.knowledge import KnowledgeDocumentDto, KnowledgeLibraryDto, RetrievedChunkDto


class KnowledgeLibraryCreatedEvent(BaseModel):
    type: str = "knowledge.library.created"
    library: KnowledgeLibraryDto
    correlation_id: str
    timestamp: datetime


class KnowledgeLibraryUpdatedEvent(BaseModel):
    type: str = "knowledge.library.updated"
    library: KnowledgeLibraryDto
    correlation_id: str
    timestamp: datetime


class KnowledgeLibraryDeletedEvent(BaseModel):
    type: str = "knowledge.library.deleted"
    library_id: str
    correlation_id: str
    timestamp: datetime


class KnowledgeDocumentCreatedEvent(BaseModel):
    type: str = "knowledge.document.created"
    document: KnowledgeDocumentDto
    correlation_id: str
    timestamp: datetime


class KnowledgeDocumentUpdatedEvent(BaseModel):
    type: str = "knowledge.document.updated"
    document: KnowledgeDocumentDto
    correlation_id: str
    timestamp: datetime


class KnowledgeDocumentDeletedEvent(BaseModel):
    type: str = "knowledge.document.deleted"
    library_id: str
    document_id: str
    correlation_id: str
    timestamp: datetime


class KnowledgeDocumentEmbeddingEvent(BaseModel):
    type: str = "knowledge.document.embedding"
    document_id: str
    chunk_count: int
    retry_count: int
    correlation_id: str
    timestamp: datetime


class KnowledgeDocumentEmbeddedEvent(BaseModel):
    type: str = "knowledge.document.embedded"
    document_id: str
    chunk_count: int
    correlation_id: str
    timestamp: datetime


class KnowledgeDocumentEmbedFailedEvent(BaseModel):
    type: str = "knowledge.document.embed_failed"
    document_id: str
    error: str
    retry_count: int
    recoverable: bool
    correlation_id: str
    timestamp: datetime


class KnowledgeSearchCompletedEvent(BaseModel):
    type: str = "knowledge.search.completed"
    session_id: str
    results: list[RetrievedChunkDto]
    correlation_id: str
    timestamp: datetime
```

- [ ] **Step 4: Verify syntax**

Run: `uv run python -m py_compile shared/dtos/knowledge.py && uv run python -m py_compile shared/events/knowledge.py && uv run python -c "from shared.topics import Topics; print(Topics.KNOWLEDGE_LIBRARY_CREATED)"`

Expected: `knowledge.library.created`

- [ ] **Step 5: Commit**

```bash
git add shared/topics.py shared/dtos/knowledge.py shared/events/knowledge.py
git commit -m "Add knowledge base shared contracts — topics, DTOs, events"
```

---

## Task 2: Document Chunker with TDD

**Files:**
- Create: `backend/modules/knowledge/_chunker.py`
- Create: `tests/test_chunker.py`

- [ ] **Step 1: Write chunker tests**

```python
"""Tests for the document chunker — ported from Prototype 2."""

import pytest

from backend.modules.knowledge._chunker import DocumentChunk, chunk_document


class TestChunkerBasics:
    def test_empty_content_returns_empty(self):
        assert chunk_document("") == []
        assert chunk_document("   ") == []

    def test_single_paragraph_under_limit(self):
        text = "This is a short paragraph."
        chunks = chunk_document(text, max_tokens=512)
        assert len(chunks) == 1
        assert chunks[0].text.strip() == text
        assert chunks[0].chunk_index == 0
        assert chunks[0].heading_path == []
        assert chunks[0].preroll_text == ""

    def test_heading_path_tracked(self):
        text = "# Top\n\nSome text\n\n## Sub\n\nMore text"
        chunks = chunk_document(text, max_tokens=512)
        # At least 2 chunks (one per heading section)
        assert len(chunks) >= 1
        # Find the chunk with "More text"
        sub_chunk = [c for c in chunks if "More text" in c.text]
        assert len(sub_chunk) == 1
        assert sub_chunk[0].heading_path == ["# Top", "## Sub"]
        assert sub_chunk[0].preroll_text == "# Top > ## Sub"

    def test_heading_hierarchy_pops_correctly(self):
        text = "# A\n\nText A\n\n## B\n\nText B\n\n# C\n\nText C"
        chunks = chunk_document(text, max_tokens=512)
        c_chunk = [c for c in chunks if "Text C" in c.text]
        assert len(c_chunk) == 1
        # C is a new H1 — B should be popped from the stack
        assert c_chunk[0].heading_path == ["# C"]


class TestOversizedSplitting:
    def test_splits_by_paragraphs(self):
        paras = ["Paragraph number " + str(i) + ". " * 20 for i in range(10)]
        text = "\n\n".join(paras)
        chunks = chunk_document(text, max_tokens=50)
        assert len(chunks) > 1
        # Every chunk should be under the limit (with some tolerance for preroll)
        for c in chunks:
            assert c.token_count <= 60  # tolerance for preroll addition

    def test_splits_by_sentences_when_paragraph_too_large(self):
        # One giant paragraph of many sentences
        sentences = ["This is sentence number " + str(i) + "." for i in range(50)]
        text = " ".join(sentences)
        chunks = chunk_document(text, max_tokens=50)
        assert len(chunks) > 1

    def test_hard_split_as_last_resort(self):
        # One long "word" repeated — no sentence or paragraph boundaries
        text = "word " * 200
        chunks = chunk_document(text, max_tokens=30)
        assert len(chunks) > 1


class TestSmallChunkMerging:
    def test_tiny_chunks_merged(self):
        text = "# Section\n\nA.\n\nB.\n\nC."
        chunks = chunk_document(text, max_tokens=512, merge_threshold=100)
        # A, B, C are tiny — should be merged into fewer chunks
        assert len(chunks) <= 2

    def test_different_heading_parents_not_merged(self):
        text = "# A\n\nTiny A.\n\n# B\n\nTiny B."
        chunks = chunk_document(text, max_tokens=512, merge_threshold=100)
        a_chunks = [c for c in chunks if "Tiny A" in c.text]
        b_chunks = [c for c in chunks if "Tiny B" in c.text]
        # They should not be in the same chunk (different heading parents)
        assert len(a_chunks) == 1
        assert len(b_chunks) == 1
        assert a_chunks[0].chunk_index != b_chunks[0].chunk_index


class TestPrerollGeneration:
    def test_mid_section_split_gets_preroll_context(self):
        # Create a section large enough to split
        lines = [f"Line {i} with some extra text to pad it out a bit." for i in range(30)]
        text = "# My Section\n\n" + "\n\n".join(lines)
        chunks = chunk_document(text, max_tokens=50, preroll_lines=3)
        # Second chunk onwards should contain preroll from the section start
        if len(chunks) > 1:
            for c in chunks[1:]:
                if not c.text.startswith("# My Section"):
                    # Should have preroll context prepended
                    assert "Line 0" in c.text or c.heading_path == ["# My Section"]


class TestChunkIndexing:
    def test_chunk_indexes_are_sequential(self):
        text = "# A\n\nText A\n\n# B\n\nText B\n\n# C\n\nText C"
        chunks = chunk_document(text, max_tokens=512)
        for i, c in enumerate(chunks):
            assert c.chunk_index == i

    def test_token_counts_are_positive(self):
        text = "Some text with a few words in it."
        chunks = chunk_document(text, max_tokens=512)
        for c in chunks:
            assert c.token_count > 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/chris/workspace/chatsune && uv run pytest tests/test_chunker.py -v`

Expected: ImportError — `_chunker` module does not exist yet.

- [ ] **Step 3: Implement the chunker**

```python
"""Document chunking algorithm — ported from Prototype 2's DocumentChunker.cs.

Splits documents by heading structure, then by paragraphs, sentences, and
finally hard word boundaries. Merges tiny adjacent chunks. Prepends preroll
context from the parent section for mid-section splits.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import tiktoken

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+)$", re.MULTILINE)
_PARAGRAPH_RE = re.compile(r"\n\s*\n")
_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")

_enc = tiktoken.get_encoding("cl100k_base")

_DEFAULT_MAX_TOKENS = 512
_DEFAULT_MERGE_THRESHOLD = 64
_DEFAULT_PREROLL_LINES = 3


def _count_tokens(text: str) -> int:
    if not text:
        return 0
    return len(_enc.encode(text))


@dataclass(frozen=True)
class DocumentChunk:
    chunk_index: int
    text: str
    heading_path: list[str]
    preroll_text: str
    token_count: int


@dataclass
class _SectionCandidate:
    text: str
    heading_path: list[str]
    first_lines: list[str]
    is_heading_boundary: bool


@dataclass
class _ChunkCandidate:
    text: str
    heading_path: list[str]
    first_lines: list[str]
    token_count: int
    is_heading_boundary: bool


def chunk_document(
    content: str,
    max_tokens: int = _DEFAULT_MAX_TOKENS,
    merge_threshold: int = _DEFAULT_MERGE_THRESHOLD,
    preroll_lines: int = _DEFAULT_PREROLL_LINES,
) -> list[DocumentChunk]:
    """Chunk a document into embedding-sized pieces.

    Args:
        content: Full document text (Markdown or plain).
        max_tokens: Maximum tokens per chunk (default 512).
        merge_threshold: Chunks smaller than this are merged with neighbours (default 64).
        preroll_lines: Number of context lines prepended to mid-section splits (default 3).

    Returns:
        List of DocumentChunk with sequential chunk_index values.
    """
    if not content or not content.strip():
        return []

    # Step 1: Split by headings
    sections = _split_by_headings(content)

    # Step 2: Split oversized sections
    candidates: list[_ChunkCandidate] = []
    for section in sections:
        token_count = _count_tokens(section.text)
        if token_count <= max_tokens:
            candidates.append(_ChunkCandidate(
                text=section.text,
                heading_path=section.heading_path,
                first_lines=section.first_lines,
                token_count=token_count,
                is_heading_boundary=section.is_heading_boundary,
            ))
        else:
            candidates.extend(_split_oversized(section, max_tokens))

    # Step 3: Merge small chunks
    candidates = _merge_small(candidates, max_tokens, merge_threshold)

    # Step 4: Build final chunks with preroll
    result: list[DocumentChunk] = []
    for i, c in enumerate(candidates):
        preroll_text = _build_preroll(c.heading_path)
        text = c.text

        # Mid-section splits get context from the section start
        if not c.is_heading_boundary and c.first_lines:
            preroll_content = "\n".join(c.first_lines[:preroll_lines])
            if preroll_content.strip() and not text.startswith(preroll_content):
                text = preroll_content + "\n\n" + text

        result.append(DocumentChunk(
            chunk_index=i,
            text=text,
            heading_path=list(c.heading_path),
            preroll_text=preroll_text,
            token_count=_count_tokens(text),
        ))

    return result


def _split_by_headings(content: str) -> list[_SectionCandidate]:
    sections: list[_SectionCandidate] = []
    lines = content.split("\n")
    current_lines: list[str] = []
    current_heading_path: list[str] = []
    heading_stack: list[tuple[int, str]] = []
    first_lines: list[str] = []
    line_count = 0

    for line in lines:
        match = _HEADING_RE.match(line)
        if match:
            # Flush previous section
            if current_lines:
                text = "\n".join(current_lines).strip()
                if text:
                    sections.append(_SectionCandidate(
                        text=text,
                        heading_path=list(current_heading_path),
                        first_lines=list(first_lines),
                        is_heading_boundary=True,
                    ))
                current_lines = []
                first_lines = []
                line_count = 0

            level = len(match.group(1))
            heading = line.strip()

            # Pop headings at same or deeper level
            while heading_stack and heading_stack[-1][0] >= level:
                heading_stack.pop()

            heading_stack.append((level, heading))
            current_heading_path = [h[1] for h in heading_stack]

        current_lines.append(line)
        if line_count < 5:
            trimmed = line.strip()
            if trimmed:
                first_lines.append(trimmed)
        line_count += 1

    # Flush last section
    if current_lines:
        text = "\n".join(current_lines).strip()
        if text:
            sections.append(_SectionCandidate(
                text=text,
                heading_path=list(current_heading_path),
                first_lines=list(first_lines),
                is_heading_boundary=len(sections) == 0 or len(current_heading_path) > 0,
            ))

    # If no sections at all, treat entire content as one section
    if not sections and content.strip():
        fl = [l.strip() for l in content.split("\n")[:5] if l.strip()]
        sections.append(_SectionCandidate(
            text=content.strip(),
            heading_path=[],
            first_lines=fl,
            is_heading_boundary=True,
        ))

    return sections


def _split_oversized(section: _SectionCandidate, max_tokens: int) -> list[_ChunkCandidate]:
    # Try paragraph boundaries first
    paragraphs = [p.strip() for p in _PARAGRAPH_RE.split(section.text) if p.strip()]

    if len(paragraphs) > 1:
        results: list[_ChunkCandidate] = []
        accumulated: list[str] = []
        acc_tokens = 0
        is_first = True

        for para in paragraphs:
            para_tokens = _count_tokens(para)

            if acc_tokens + para_tokens > max_tokens and accumulated:
                text = "\n\n".join(accumulated)
                results.append(_ChunkCandidate(
                    text=text,
                    heading_path=section.heading_path,
                    first_lines=section.first_lines,
                    token_count=acc_tokens,
                    is_heading_boundary=is_first and section.is_heading_boundary,
                ))
                accumulated = []
                acc_tokens = 0
                is_first = False

            accumulated.append(para)
            acc_tokens += para_tokens

        if accumulated:
            text = "\n\n".join(accumulated)
            tokens = _count_tokens(text)
            if tokens <= max_tokens:
                results.append(_ChunkCandidate(
                    text=text,
                    heading_path=section.heading_path,
                    first_lines=section.first_lines,
                    token_count=tokens,
                    is_heading_boundary=is_first and section.is_heading_boundary,
                ))
            else:
                results.extend(_split_by_sentences(
                    text, section.heading_path, section.first_lines, max_tokens,
                ))

        return results

    # Fall through to sentence splitting
    return _split_by_sentences(
        section.text, section.heading_path, section.first_lines, max_tokens,
    )


def _split_by_sentences(
    text: str,
    heading_path: list[str],
    first_lines: list[str],
    max_tokens: int,
) -> list[_ChunkCandidate]:
    sentences = [s for s in _SENTENCE_RE.split(text) if s.strip()]

    if len(sentences) <= 1:
        return _hard_split(text, heading_path, first_lines, max_tokens)

    results: list[_ChunkCandidate] = []
    accumulated: list[str] = []
    acc_tokens = 0
    is_first = True

    for sentence in sentences:
        sent_tokens = _count_tokens(sentence)

        if acc_tokens + sent_tokens > max_tokens and accumulated:
            results.append(_ChunkCandidate(
                text=" ".join(accumulated),
                heading_path=heading_path,
                first_lines=first_lines,
                token_count=acc_tokens,
                is_heading_boundary=is_first,
            ))
            accumulated = []
            acc_tokens = 0
            is_first = False

        accumulated.append(sentence)
        acc_tokens += sent_tokens

    if accumulated:
        joined = " ".join(accumulated)
        results.append(_ChunkCandidate(
            text=joined,
            heading_path=heading_path,
            first_lines=first_lines,
            token_count=_count_tokens(joined),
            is_heading_boundary=is_first,
        ))

    return results


def _hard_split(
    text: str,
    heading_path: list[str],
    first_lines: list[str],
    max_tokens: int,
) -> list[_ChunkCandidate]:
    words = text.split()
    results: list[_ChunkCandidate] = []
    accumulated: list[str] = []
    acc_tokens = 0
    is_first = True

    for word in words:
        word_tokens = _count_tokens(word)

        if acc_tokens + word_tokens > max_tokens and accumulated:
            joined = " ".join(accumulated)
            results.append(_ChunkCandidate(
                text=joined,
                heading_path=heading_path,
                first_lines=first_lines,
                token_count=acc_tokens,
                is_heading_boundary=is_first,
            ))
            accumulated = []
            acc_tokens = 0
            is_first = False

        accumulated.append(word)
        acc_tokens += word_tokens

    if accumulated:
        joined = " ".join(accumulated)
        results.append(_ChunkCandidate(
            text=joined,
            heading_path=heading_path,
            first_lines=first_lines,
            token_count=_count_tokens(joined),
            is_heading_boundary=is_first,
        ))

    return results


def _merge_small(
    candidates: list[_ChunkCandidate],
    max_tokens: int,
    merge_threshold: int,
) -> list[_ChunkCandidate]:
    if len(candidates) <= 1:
        return candidates

    merged: list[_ChunkCandidate] = []
    pending: _ChunkCandidate | None = None

    for candidate in candidates:
        if pending is None:
            pending = candidate
            continue

        same_parent = pending.heading_path == candidate.heading_path
        can_merge = (
            same_parent
            and (candidate.token_count < merge_threshold or pending.token_count < merge_threshold)
            and pending.token_count + candidate.token_count <= max_tokens
        )

        if can_merge:
            pending = _ChunkCandidate(
                text=pending.text + "\n\n" + candidate.text,
                heading_path=pending.heading_path,
                first_lines=pending.first_lines,
                token_count=pending.token_count + candidate.token_count,
                is_heading_boundary=pending.is_heading_boundary,
            )
        else:
            merged.append(pending)
            pending = candidate

    if pending is not None:
        merged.append(pending)

    return merged


def _build_preroll(heading_path: list[str]) -> str:
    if not heading_path:
        return ""
    return " > ".join(heading_path)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /home/chris/workspace/chatsune && uv run pytest tests/test_chunker.py -v`

Expected: All tests PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/modules/knowledge/_chunker.py tests/test_chunker.py
git commit -m "Add document chunker with TDD — port from Prototype 2"
```

---

## Task 3: Knowledge Repository

**Files:**
- Create: `backend/modules/knowledge/_repository.py`

- [ ] **Step 1: Create the repository**

```python
"""MongoDB repository for knowledge libraries, documents, and chunks."""

from datetime import UTC, datetime
from uuid import uuid4

from motor.motor_asyncio import AsyncIOMotorDatabase

from shared.dtos.knowledge import (
    KnowledgeDocumentDetailDto,
    KnowledgeDocumentDto,
    KnowledgeLibraryDto,
)


class KnowledgeRepository:
    def __init__(self, db: AsyncIOMotorDatabase) -> None:
        self._libraries = db["knowledge_libraries"]
        self._documents = db["knowledge_documents"]
        self._chunks = db["knowledge_chunks"]

    # ── Indexes ──────────────────────────────────────────────

    async def create_indexes(self) -> None:
        await self._libraries.create_index("user_id")
        await self._libraries.create_index([("user_id", 1), ("nsfw", 1)])

        await self._documents.create_index([("user_id", 1), ("library_id", 1)])
        await self._documents.create_index([("user_id", 1), ("embedding_status", 1)])

        await self._chunks.create_index([("user_id", 1), ("document_id", 1)])
        # Note: MongoDB Vector Search index must be created via Atlas CLI or
        # mongosh — it cannot be created via the driver. See INSIGHTS.md.

    # ── Libraries ────────────────────────────────────────────

    async def create_library(
        self, user_id: str, name: str, description: str | None, nsfw: bool,
    ) -> dict:
        now = datetime.now(UTC)
        doc = {
            "_id": str(uuid4()),
            "user_id": user_id,
            "name": name,
            "description": description,
            "nsfw": nsfw,
            "document_count": 0,
            "created_at": now,
            "updated_at": now,
        }
        await self._libraries.insert_one(doc)
        return doc

    async def get_library(self, library_id: str, user_id: str) -> dict | None:
        return await self._libraries.find_one({"_id": library_id, "user_id": user_id})

    async def list_libraries(self, user_id: str) -> list[dict]:
        cursor = self._libraries.find({"user_id": user_id}).sort("created_at", 1)
        return await cursor.to_list(length=500)

    async def update_library(self, library_id: str, user_id: str, updates: dict) -> dict | None:
        updates["updated_at"] = datetime.now(UTC)
        return await self._libraries.find_one_and_update(
            {"_id": library_id, "user_id": user_id},
            {"$set": updates},
            return_document=True,
        )

    async def delete_library(self, library_id: str, user_id: str) -> bool:
        result = await self._libraries.delete_one({"_id": library_id, "user_id": user_id})
        if result.deleted_count > 0:
            await self._documents.delete_many({"library_id": library_id, "user_id": user_id})
            await self._chunks.delete_many({"library_id": library_id, "user_id": user_id})
            return True
        return False

    async def increment_document_count(self, library_id: str, user_id: str, delta: int) -> None:
        await self._libraries.update_one(
            {"_id": library_id, "user_id": user_id},
            {"$inc": {"document_count": delta}, "$set": {"updated_at": datetime.now(UTC)}},
        )

    # ── Documents ────────────────────────────────────────────

    async def create_document(
        self,
        user_id: str,
        library_id: str,
        title: str,
        content: str,
        media_type: str,
    ) -> dict:
        now = datetime.now(UTC)
        doc = {
            "_id": str(uuid4()),
            "user_id": user_id,
            "library_id": library_id,
            "title": title,
            "content": content,
            "media_type": media_type,
            "size_bytes": len(content.encode("utf-8")),
            "chunk_count": 0,
            "embedding_status": "pending",
            "embedding_error": None,
            "retry_count": 0,
            "created_at": now,
            "updated_at": now,
        }
        await self._documents.insert_one(doc)
        return doc

    async def get_document(self, doc_id: str, user_id: str) -> dict | None:
        return await self._documents.find_one({"_id": doc_id, "user_id": user_id})

    async def list_documents(self, library_id: str, user_id: str) -> list[dict]:
        cursor = self._documents.find(
            {"library_id": library_id, "user_id": user_id},
            {"content": 0},  # Exclude content for list view
        ).sort("created_at", 1)
        return await cursor.to_list(length=1000)

    async def update_document(self, doc_id: str, user_id: str, updates: dict) -> dict | None:
        updates["updated_at"] = datetime.now(UTC)
        if "content" in updates:
            updates["size_bytes"] = len(updates["content"].encode("utf-8"))
        return await self._documents.find_one_and_update(
            {"_id": doc_id, "user_id": user_id},
            {"$set": updates},
            return_document=True,
        )

    async def set_embedding_status(
        self, doc_id: str, user_id: str,
        status: str, chunk_count: int = 0, error: str | None = None,
    ) -> None:
        update: dict = {
            "embedding_status": status,
            "updated_at": datetime.now(UTC),
        }
        if chunk_count:
            update["chunk_count"] = chunk_count
        if error is not None:
            update["embedding_error"] = error
        if status == "pending":
            update["embedding_error"] = None
        await self._documents.update_one(
            {"_id": doc_id, "user_id": user_id},
            {"$set": update},
        )

    async def increment_retry_count(self, doc_id: str, user_id: str) -> int:
        result = await self._documents.find_one_and_update(
            {"_id": doc_id, "user_id": user_id},
            {"$inc": {"retry_count": 1}},
            return_document=True,
        )
        return result["retry_count"] if result else 0

    async def reset_retry_count(self, doc_id: str, user_id: str) -> None:
        await self._documents.update_one(
            {"_id": doc_id, "user_id": user_id},
            {"$set": {"retry_count": 0}},
        )

    async def delete_document(self, doc_id: str, user_id: str) -> str | None:
        """Delete document and its chunks. Returns library_id or None."""
        doc = await self._documents.find_one_and_delete({"_id": doc_id, "user_id": user_id})
        if doc:
            await self._chunks.delete_many({"document_id": doc_id, "user_id": user_id})
            return doc["library_id"]
        return None

    # ── Chunks ───────────────────────────────────────────────

    async def upsert_chunks(self, user_id: str, document_id: str, library_id: str, chunks: list[dict]) -> None:
        """Replace all chunks for a document with new ones."""
        await self._chunks.delete_many({"document_id": document_id, "user_id": user_id})
        if chunks:
            docs = []
            for chunk in chunks:
                docs.append({
                    "_id": str(uuid4()),
                    "user_id": user_id,
                    "library_id": library_id,
                    "document_id": document_id,
                    "chunk_index": chunk["chunk_index"],
                    "text": chunk["text"],
                    "heading_path": chunk["heading_path"],
                    "preroll_text": chunk["preroll_text"],
                    "token_count": chunk["token_count"],
                    "vector": chunk["vector"],
                })
            await self._chunks.insert_many(docs)

    async def delete_chunks_for_document(self, document_id: str, user_id: str) -> int:
        result = await self._chunks.delete_many({"document_id": document_id, "user_id": user_id})
        return result.deleted_count

    async def vector_search(
        self,
        user_id: str,
        library_ids: list[str],
        query_vector: list[float],
        top_k: int = 5,
    ) -> list[dict]:
        """Run MongoDB Vector Search filtered by user and library IDs."""
        pipeline = [
            {
                "$vectorSearch": {
                    "index": "knowledge_vector_index",
                    "path": "vector",
                    "queryVector": query_vector,
                    "numCandidates": top_k * 10,
                    "limit": top_k,
                    "filter": {
                        "user_id": user_id,
                        "library_id": {"$in": library_ids},
                    },
                },
            },
            {
                "$project": {
                    "text": 1,
                    "heading_path": 1,
                    "preroll_text": 1,
                    "document_id": 1,
                    "library_id": 1,
                    "chunk_index": 1,
                    "score": {"$meta": "vectorSearchScore"},
                },
            },
        ]
        cursor = self._chunks.aggregate(pipeline)
        return await cursor.to_list(length=top_k)

    # ── DTO Conversions ──────────────────────────────────────

    @staticmethod
    def to_library_dto(doc: dict) -> KnowledgeLibraryDto:
        return KnowledgeLibraryDto(
            id=doc["_id"],
            name=doc["name"],
            description=doc.get("description"),
            nsfw=doc.get("nsfw", False),
            document_count=doc.get("document_count", 0),
            created_at=doc["created_at"],
            updated_at=doc["updated_at"],
        )

    @staticmethod
    def to_document_dto(doc: dict) -> KnowledgeDocumentDto:
        return KnowledgeDocumentDto(
            id=doc["_id"],
            library_id=doc["library_id"],
            title=doc["title"],
            media_type=doc["media_type"],
            size_bytes=doc.get("size_bytes", 0),
            chunk_count=doc.get("chunk_count", 0),
            embedding_status=doc.get("embedding_status", "pending"),
            embedding_error=doc.get("embedding_error"),
            created_at=doc["created_at"],
            updated_at=doc["updated_at"],
        )

    @staticmethod
    def to_document_detail_dto(doc: dict) -> KnowledgeDocumentDetailDto:
        return KnowledgeDocumentDetailDto(
            id=doc["_id"],
            library_id=doc["library_id"],
            title=doc["title"],
            content=doc.get("content", ""),
            media_type=doc["media_type"],
            size_bytes=doc.get("size_bytes", 0),
            chunk_count=doc.get("chunk_count", 0),
            embedding_status=doc.get("embedding_status", "pending"),
            embedding_error=doc.get("embedding_error"),
            created_at=doc["created_at"],
            updated_at=doc["updated_at"],
        )
```

- [ ] **Step 2: Verify syntax**

Run: `uv run python -m py_compile backend/modules/knowledge/_repository.py`

Expected: No output (success).

- [ ] **Step 3: Commit**

```bash
git add backend/modules/knowledge/_repository.py
git commit -m "Add knowledge repository — libraries, documents, chunks CRUD"
```

---

## Task 4: REST Handlers

**Files:**
- Create: `backend/modules/knowledge/_handlers.py`

- [ ] **Step 1: Create the handlers**

```python
"""FastAPI REST endpoints for knowledge libraries and documents."""

from datetime import datetime, timezone
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException

from backend.database import get_db
from backend.dependencies import require_active_session
from backend.modules.knowledge._chunker import chunk_document
from backend.modules.knowledge._repository import KnowledgeRepository
from backend.ws.event_bus import get_event_bus
from shared.dtos.knowledge import (
    CreateDocumentRequest,
    CreateLibraryRequest,
    UpdateDocumentRequest,
    UpdateLibraryRequest,
)
from shared.events.knowledge import (
    KnowledgeDocumentCreatedEvent,
    KnowledgeDocumentDeletedEvent,
    KnowledgeDocumentEmbeddingEvent,
    KnowledgeDocumentUpdatedEvent,
    KnowledgeLibraryCreatedEvent,
    KnowledgeLibraryDeletedEvent,
    KnowledgeLibraryUpdatedEvent,
)
from shared.topics import Topics

router = APIRouter(prefix="/api/knowledge")


def _repo() -> KnowledgeRepository:
    return KnowledgeRepository(get_db())


async def _trigger_embedding(
    repo: KnowledgeRepository,
    doc: dict,
    user_id: str,
    correlation_id: str,
) -> None:
    """Chunk a document and enqueue for embedding."""
    from backend.modules.embedding import embed_texts

    chunks = chunk_document(doc["content"])
    if not chunks:
        await repo.set_embedding_status(doc["_id"], user_id, "completed", chunk_count=0)
        return

    await repo.set_embedding_status(doc["_id"], user_id, "processing", chunk_count=len(chunks))

    event_bus = get_event_bus()
    now = datetime.now(timezone.utc)
    await event_bus.publish(
        Topics.KNOWLEDGE_DOCUMENT_EMBEDDING,
        KnowledgeDocumentEmbeddingEvent(
            document_id=doc["_id"],
            chunk_count=len(chunks),
            retry_count=doc.get("retry_count", 0),
            correlation_id=correlation_id,
            timestamp=now,
        ),
        scope=f"user:{user_id}",
        target_user_ids=[user_id],
        correlation_id=correlation_id,
    )

    # Store chunk metadata temporarily on the document for the embedding callback
    chunk_data = [
        {
            "chunk_index": c.chunk_index,
            "text": c.text,
            "heading_path": c.heading_path,
            "preroll_text": c.preroll_text,
            "token_count": c.token_count,
        }
        for c in chunks
    ]
    await repo.update_document(doc["_id"], user_id, {"_chunk_data": chunk_data})

    texts = [c.text for c in chunks]
    await embed_texts(texts, reference_id=doc["_id"], correlation_id=correlation_id)


# ── Libraries ────────────────────────────────────────────────


@router.get("/libraries")
async def list_libraries(user: dict = Depends(require_active_session)):
    repo = _repo()
    docs = await repo.list_libraries(user["sub"])
    return [KnowledgeRepository.to_library_dto(d) for d in docs]


@router.post("/libraries", status_code=201)
async def create_library(
    body: CreateLibraryRequest,
    user: dict = Depends(require_active_session),
):
    repo = _repo()
    doc = await repo.create_library(
        user_id=user["sub"],
        name=body.name,
        description=body.description,
        nsfw=body.nsfw,
    )
    dto = KnowledgeRepository.to_library_dto(doc)

    correlation_id = str(uuid4())
    now = datetime.now(timezone.utc)
    event_bus = get_event_bus()
    await event_bus.publish(
        Topics.KNOWLEDGE_LIBRARY_CREATED,
        KnowledgeLibraryCreatedEvent(library=dto, correlation_id=correlation_id, timestamp=now),
        scope=f"user:{user['sub']}",
        target_user_ids=[user["sub"]],
        correlation_id=correlation_id,
    )
    return dto


@router.put("/libraries/{library_id}")
async def update_library(
    library_id: str,
    body: UpdateLibraryRequest,
    user: dict = Depends(require_active_session),
):
    repo = _repo()
    updates = body.model_dump(exclude_none=True)
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")

    doc = await repo.update_library(library_id, user["sub"], updates)
    if not doc:
        raise HTTPException(status_code=404, detail="Library not found")

    dto = KnowledgeRepository.to_library_dto(doc)

    correlation_id = str(uuid4())
    now = datetime.now(timezone.utc)
    event_bus = get_event_bus()
    await event_bus.publish(
        Topics.KNOWLEDGE_LIBRARY_UPDATED,
        KnowledgeLibraryUpdatedEvent(library=dto, correlation_id=correlation_id, timestamp=now),
        scope=f"user:{user['sub']}",
        target_user_ids=[user["sub"]],
        correlation_id=correlation_id,
    )
    return dto


@router.delete("/libraries/{library_id}")
async def delete_library(
    library_id: str,
    user: dict = Depends(require_active_session),
):
    repo = _repo()
    deleted = await repo.delete_library(library_id, user["sub"])
    if not deleted:
        raise HTTPException(status_code=404, detail="Library not found")

    correlation_id = str(uuid4())
    now = datetime.now(timezone.utc)
    event_bus = get_event_bus()
    await event_bus.publish(
        Topics.KNOWLEDGE_LIBRARY_DELETED,
        KnowledgeLibraryDeletedEvent(library_id=library_id, correlation_id=correlation_id, timestamp=now),
        scope=f"user:{user['sub']}",
        target_user_ids=[user["sub"]],
        correlation_id=correlation_id,
    )
    return {"status": "ok"}


# ── Documents ────────────────────────────────────────────────


@router.get("/libraries/{library_id}/documents")
async def list_documents(
    library_id: str,
    user: dict = Depends(require_active_session),
):
    repo = _repo()
    lib = await repo.get_library(library_id, user["sub"])
    if not lib:
        raise HTTPException(status_code=404, detail="Library not found")

    docs = await repo.list_documents(library_id, user["sub"])
    return [KnowledgeRepository.to_document_dto(d) for d in docs]


@router.post("/libraries/{library_id}/documents", status_code=201)
async def create_document(
    library_id: str,
    body: CreateDocumentRequest,
    user: dict = Depends(require_active_session),
):
    repo = _repo()
    lib = await repo.get_library(library_id, user["sub"])
    if not lib:
        raise HTTPException(status_code=404, detail="Library not found")

    doc = await repo.create_document(
        user_id=user["sub"],
        library_id=library_id,
        title=body.title,
        content=body.content,
        media_type=body.media_type,
    )
    await repo.increment_document_count(library_id, user["sub"], 1)

    dto = KnowledgeRepository.to_document_dto(doc)
    correlation_id = str(uuid4())
    now = datetime.now(timezone.utc)
    event_bus = get_event_bus()
    await event_bus.publish(
        Topics.KNOWLEDGE_DOCUMENT_CREATED,
        KnowledgeDocumentCreatedEvent(document=dto, correlation_id=correlation_id, timestamp=now),
        scope=f"user:{user['sub']}",
        target_user_ids=[user["sub"]],
        correlation_id=correlation_id,
    )

    # Trigger async embedding
    await _trigger_embedding(repo, doc, user["sub"], correlation_id)

    return dto


@router.get("/libraries/{library_id}/documents/{doc_id}")
async def get_document(
    library_id: str,
    doc_id: str,
    user: dict = Depends(require_active_session),
):
    repo = _repo()
    doc = await repo.get_document(doc_id, user["sub"])
    if not doc or doc["library_id"] != library_id:
        raise HTTPException(status_code=404, detail="Document not found")
    return KnowledgeRepository.to_document_detail_dto(doc)


@router.put("/libraries/{library_id}/documents/{doc_id}")
async def update_document(
    library_id: str,
    doc_id: str,
    body: UpdateDocumentRequest,
    user: dict = Depends(require_active_session),
):
    repo = _repo()
    existing = await repo.get_document(doc_id, user["sub"])
    if not existing or existing["library_id"] != library_id:
        raise HTTPException(status_code=404, detail="Document not found")

    updates = body.model_dump(exclude_none=True)
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")

    content_changed = "content" in updates and updates["content"] != existing.get("content")

    doc = await repo.update_document(doc_id, user["sub"], updates)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    dto = KnowledgeRepository.to_document_dto(doc)
    correlation_id = str(uuid4())
    now = datetime.now(timezone.utc)
    event_bus = get_event_bus()
    await event_bus.publish(
        Topics.KNOWLEDGE_DOCUMENT_UPDATED,
        KnowledgeDocumentUpdatedEvent(document=dto, correlation_id=correlation_id, timestamp=now),
        scope=f"user:{user['sub']}",
        target_user_ids=[user["sub"]],
        correlation_id=correlation_id,
    )

    # Re-embed if content changed
    if content_changed:
        await repo.delete_chunks_for_document(doc_id, user["sub"])
        await repo.reset_retry_count(doc_id, user["sub"])
        await repo.set_embedding_status(doc_id, user["sub"], "pending")
        await _trigger_embedding(repo, doc, user["sub"], correlation_id)

    return dto


@router.delete("/libraries/{library_id}/documents/{doc_id}")
async def delete_document(
    library_id: str,
    doc_id: str,
    user: dict = Depends(require_active_session),
):
    repo = _repo()
    deleted_lib_id = await repo.delete_document(doc_id, user["sub"])
    if not deleted_lib_id:
        raise HTTPException(status_code=404, detail="Document not found")

    await repo.increment_document_count(library_id, user["sub"], -1)

    correlation_id = str(uuid4())
    now = datetime.now(timezone.utc)
    event_bus = get_event_bus()
    await event_bus.publish(
        Topics.KNOWLEDGE_DOCUMENT_DELETED,
        KnowledgeDocumentDeletedEvent(
            library_id=library_id, document_id=doc_id,
            correlation_id=correlation_id, timestamp=now,
        ),
        scope=f"user:{user['sub']}",
        target_user_ids=[user["sub"]],
        correlation_id=correlation_id,
    )
    return {"status": "ok"}


@router.post("/libraries/{library_id}/documents/{doc_id}/retry")
async def retry_embedding(
    library_id: str,
    doc_id: str,
    user: dict = Depends(require_active_session),
):
    repo = _repo()
    doc = await repo.get_document(doc_id, user["sub"])
    if not doc or doc["library_id"] != library_id:
        raise HTTPException(status_code=404, detail="Document not found")

    if doc.get("embedding_status") != "failed":
        raise HTTPException(status_code=400, detail="Document is not in failed state")

    await repo.reset_retry_count(doc_id, user["sub"])
    await repo.set_embedding_status(doc_id, user["sub"], "pending")

    correlation_id = str(uuid4())
    await _trigger_embedding(repo, doc, user["sub"], correlation_id)

    return {"status": "ok"}
```

- [ ] **Step 2: Verify syntax**

Run: `uv run python -m py_compile backend/modules/knowledge/_handlers.py`

Expected: No output (success).

- [ ] **Step 3: Commit**

```bash
git add backend/modules/knowledge/_handlers.py
git commit -m "Add knowledge REST handlers — library and document CRUD with embedding"
```

---

## Task 5: Retrieval & Tool Executor

**Files:**
- Create: `backend/modules/knowledge/_retrieval.py`
- Modify: `backend/modules/tools/_registry.py`
- Modify: `backend/modules/tools/_executors.py`

- [ ] **Step 1: Create the retrieval module**

```python
"""Knowledge retrieval — vector search and tool executor for knowledge_search."""

import json
import logging

from backend.database import get_db
from backend.modules.knowledge._repository import KnowledgeRepository
from shared.dtos.knowledge import RetrievedChunkDto

_log = logging.getLogger(__name__)

_MAX_CONTENT_LENGTH = 8000


async def search(
    user_id: str,
    query: str,
    persona_library_ids: list[str],
    session_library_ids: list[str],
    sanitised: bool = False,
    top_k: int = 5,
) -> list[RetrievedChunkDto]:
    """Search knowledge chunks by semantic similarity.

    Args:
        user_id: Owner of the knowledge base.
        query: Search query text.
        persona_library_ids: Library IDs assigned to the persona.
        session_library_ids: Library IDs assigned ad-hoc to the session.
        sanitised: If True, exclude NSFW libraries.
        top_k: Maximum number of results.

    Returns:
        List of RetrievedChunkDto sorted by relevance.
    """
    from backend.modules.embedding import query_embed

    effective_ids = list(set(persona_library_ids + session_library_ids))
    if not effective_ids:
        return []

    repo = KnowledgeRepository(get_db())

    # Filter out NSFW libraries if sanitised
    if sanitised:
        filtered: list[str] = []
        for lib_id in effective_ids:
            lib = await repo.get_library(lib_id, user_id)
            if lib and not lib.get("nsfw", False):
                filtered.append(lib_id)
        effective_ids = filtered

    if not effective_ids:
        return []

    # Get query embedding (blocking, high-priority)
    query_vector = await query_embed(query)

    # Vector search
    raw_results = await repo.vector_search(user_id, effective_ids, query_vector, top_k)

    # Enrich with library/document metadata
    results: list[RetrievedChunkDto] = []
    for r in raw_results:
        lib = await repo.get_library(r["library_id"], user_id)
        doc = await repo.get_document(r["document_id"], user_id)
        if not lib or not doc:
            continue

        content = r.get("text", "")
        if len(content) > _MAX_CONTENT_LENGTH:
            content = content[:_MAX_CONTENT_LENGTH] + "..."

        results.append(RetrievedChunkDto(
            library_name=lib["name"],
            document_title=doc["title"],
            heading_path=r.get("heading_path", []),
            preroll_text=r.get("preroll_text", ""),
            content=content,
            score=r.get("score", 0.0),
        ))

    return results
```

- [ ] **Step 2: Add `KnowledgeSearchExecutor` to `backend/modules/tools/_executors.py`**

Add at the end of the file:

```python
class KnowledgeSearchExecutor:
    """Dispatches knowledge_search tool calls to the knowledge retrieval module."""

    async def execute(self, user_id: str, tool_name: str, arguments: dict) -> str:
        from backend.modules.knowledge._retrieval import search

        try:
            query = arguments.get("query", "")
            if not query:
                return json.dumps({"error": "No query provided"})

            # Library IDs are injected by the chat module via tool call context
            persona_library_ids = arguments.get("_persona_library_ids", [])
            session_library_ids = arguments.get("_session_library_ids", [])
            sanitised = arguments.get("_sanitised", False)

            results = await search(
                user_id=user_id,
                query=query,
                persona_library_ids=persona_library_ids,
                session_library_ids=session_library_ids,
                sanitised=sanitised,
            )

            if not results:
                return json.dumps({"results": [], "message": "No relevant knowledge found."})

            return json.dumps(
                {"results": [r.model_dump() for r in results]},
                ensure_ascii=False,
            )

        except Exception as exc:
            _log.warning("Knowledge search failed for user %s: %s", user_id, exc)
            return json.dumps({"error": f"Knowledge search failed: {exc}"})
```

- [ ] **Step 3: Register `knowledge_search` in `backend/modules/tools/_registry.py`**

Update the `_build_groups` function to add the knowledge tool group. Add after the `web_search` group:

```python
        from backend.modules.tools._executors import KnowledgeSearchExecutor
        from shared.dtos.inference import ToolDefinition

        knowledge_defs = [
            ToolDefinition(
                name="knowledge_search",
                description="Search the user's knowledge base for relevant information. Use this when the user's question might relate to documents in their knowledge libraries.",
                parameters={
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "The search query to find relevant knowledge chunks",
                        },
                    },
                    "required": ["query"],
                },
            ),
        ]
```

And add to the returned dict:

```python
        "knowledge_search": ToolGroup(
            id="knowledge_search",
            display_name="Knowledge",
            description="Search your knowledge libraries",
            side="server",
            toggleable=True,
            tool_names=["knowledge_search"],
            definitions=knowledge_defs,
            executor=KnowledgeSearchExecutor(),
        ),
```

- [ ] **Step 4: Verify syntax**

Run: `uv run python -m py_compile backend/modules/knowledge/_retrieval.py && uv run python -m py_compile backend/modules/tools/_executors.py && uv run python -m py_compile backend/modules/tools/_registry.py`

Expected: No output (success).

- [ ] **Step 5: Commit**

```bash
git add backend/modules/knowledge/_retrieval.py backend/modules/tools/_executors.py backend/modules/tools/_registry.py
git commit -m "Add knowledge retrieval and tool executor — vector search via knowledge_search tool"
```

---

## Task 6: Module Public API & App Integration

**Files:**
- Create: `backend/modules/knowledge/__init__.py`
- Modify: `backend/main.py`
- Modify: `backend/ws/event_bus.py`

- [ ] **Step 1: Create `backend/modules/knowledge/__init__.py`**

```python
"""Knowledge module — libraries, documents, chunking, and retrieval.

Public API: import only from this file.
"""

import logging
from datetime import datetime, timezone
from uuid import uuid4

from backend.modules.knowledge._handlers import router as knowledge_router
from backend.modules.knowledge._repository import KnowledgeRepository
from shared.events.knowledge import (
    KnowledgeDocumentEmbedFailedEvent,
    KnowledgeDocumentEmbeddedEvent,
)
from shared.topics import Topics

_log = logging.getLogger("chatsune.knowledge")

_MAX_AUTO_RETRIES = 3


async def init_indexes(db) -> None:
    """Create MongoDB indexes for the knowledge module collections."""
    await KnowledgeRepository(db).create_indexes()


async def handle_embedding_completed(event: dict) -> None:
    """Callback for EmbeddingBatchCompleted — store vectors in knowledge_chunks."""
    from backend.database import get_db
    from backend.ws.event_bus import get_event_bus

    reference_id = event.get("reference_id", "")
    vectors = event.get("vectors", [])
    correlation_id = event.get("correlation_id", "")

    db = get_db()
    repo = KnowledgeRepository(db)

    # Find the document — reference_id is the document ID
    # Search across all users (we don't have user_id in the embedding event)
    doc = await db["knowledge_documents"].find_one({"_id": reference_id})
    if not doc:
        return  # Not a knowledge document embedding

    user_id = doc["user_id"]
    chunk_data = doc.get("_chunk_data", [])

    if len(vectors) != len(chunk_data):
        _log.error(
            "Vector count mismatch for doc %s: expected %d, got %d",
            reference_id, len(chunk_data), len(vectors),
        )
        return

    # Merge vectors into chunk data
    for i, chunk in enumerate(chunk_data):
        chunk["vector"] = vectors[i]

    await repo.upsert_chunks(user_id, reference_id, doc["library_id"], chunk_data)

    # Clear temporary chunk data and update status
    await repo.update_document(reference_id, user_id, {"_chunk_data": None})
    await repo.set_embedding_status(reference_id, user_id, "completed", chunk_count=len(chunk_data))

    event_bus = get_event_bus()
    now = datetime.now(timezone.utc)
    await event_bus.publish(
        Topics.KNOWLEDGE_DOCUMENT_EMBEDDED,
        KnowledgeDocumentEmbeddedEvent(
            document_id=reference_id,
            chunk_count=len(chunk_data),
            correlation_id=correlation_id,
            timestamp=now,
        ),
        scope=f"user:{user_id}",
        target_user_ids=[user_id],
        correlation_id=correlation_id,
    )

    _log.info("Document %s embedded: %d chunks", reference_id, len(chunk_data))


async def handle_embedding_error(event: dict) -> None:
    """Callback for EmbeddingError — retry or mark as failed."""
    from backend.database import get_db
    from backend.modules.knowledge._handlers import _trigger_embedding
    from backend.ws.event_bus import get_event_bus

    reference_id = event.get("reference_id", "")
    error_msg = event.get("error", "Unknown error")
    correlation_id = event.get("correlation_id", "")

    db = get_db()
    repo = KnowledgeRepository(db)

    doc = await db["knowledge_documents"].find_one({"_id": reference_id})
    if not doc:
        return  # Not a knowledge document

    user_id = doc["user_id"]
    retry_count = await repo.increment_retry_count(reference_id, user_id)

    event_bus = get_event_bus()
    now = datetime.now(timezone.utc)

    if retry_count < _MAX_AUTO_RETRIES:
        _log.warning("Embedding failed for doc %s, retrying (%d/%d)", reference_id, retry_count, _MAX_AUTO_RETRIES)
        await _trigger_embedding(repo, doc, user_id, str(uuid4()))
    else:
        _log.error("Embedding failed permanently for doc %s after %d retries", reference_id, retry_count)
        await repo.set_embedding_status(reference_id, user_id, "failed", error=error_msg)

        await event_bus.publish(
            Topics.KNOWLEDGE_DOCUMENT_EMBED_FAILED,
            KnowledgeDocumentEmbedFailedEvent(
                document_id=reference_id,
                error=error_msg,
                retry_count=retry_count,
                recoverable=False,
                correlation_id=correlation_id,
                timestamp=now,
            ),
            scope=f"user:{user_id}",
            target_user_ids=[user_id],
            correlation_id=correlation_id,
        )


__all__ = [
    "knowledge_router",
    "init_indexes",
    "handle_embedding_completed",
    "handle_embedding_error",
]
```

- [ ] **Step 2: Add knowledge to `backend/main.py`**

Add import at the top with the other module imports:

```python
from backend.modules.knowledge import (
    knowledge_router,
    init_indexes as knowledge_init_indexes,
    handle_embedding_completed,
    handle_embedding_error,
)
```

In the `lifespan` function, add after the other `init_indexes` calls:

```python
    await knowledge_init_indexes(db)
```

Add after `embedding_startup(...)`:

```python
    # Subscribe knowledge module to embedding events
    event_bus.subscribe(Topics.EMBEDDING_BATCH_COMPLETED, handle_embedding_completed)
    event_bus.subscribe(Topics.EMBEDDING_ERROR, handle_embedding_error)
```

Add router inclusion with the others:

```python
app.include_router(knowledge_router)
```

**Note:** The `subscribe` method may need to be added to EventBus if it doesn't exist yet. Check `event_bus.py` for a subscribe mechanism. If the EventBus uses a different pattern for internal subscriptions (not WebSocket fan-out), adapt accordingly. The embedding module publishes events — the knowledge module needs to react to `EmbeddingBatchCompleted` and `EmbeddingError`. If there's no internal subscribe mechanism, add a simple callback registry to EventBus.

- [ ] **Step 3: Add knowledge topics to `_FANOUT` in `backend/ws/event_bus.py`**

Add after the memory entries in the `_FANOUT` dict:

```python
    # Knowledge — target user only
    Topics.KNOWLEDGE_LIBRARY_CREATED: ([], True),
    Topics.KNOWLEDGE_LIBRARY_UPDATED: ([], True),
    Topics.KNOWLEDGE_LIBRARY_DELETED: ([], True),
    Topics.KNOWLEDGE_DOCUMENT_CREATED: ([], True),
    Topics.KNOWLEDGE_DOCUMENT_UPDATED: ([], True),
    Topics.KNOWLEDGE_DOCUMENT_DELETED: ([], True),
    Topics.KNOWLEDGE_DOCUMENT_EMBEDDING: ([], True),
    Topics.KNOWLEDGE_DOCUMENT_EMBEDDED: ([], True),
    Topics.KNOWLEDGE_DOCUMENT_EMBED_FAILED: ([], True),
    Topics.KNOWLEDGE_SEARCH_COMPLETED: ([], True),
```

- [ ] **Step 4: Verify syntax**

Run: `uv run python -m py_compile backend/modules/knowledge/__init__.py && uv run python -m py_compile backend/ws/event_bus.py`

Expected: No output (success).

- [ ] **Step 5: Commit**

```bash
git add backend/modules/knowledge/__init__.py backend/main.py backend/ws/event_bus.py
git commit -m "Integrate knowledge module into app startup and routing"
```

---

## Task 7: Frontend Types & API Client

**Files:**
- Create: `frontend/src/core/types/knowledge.ts`
- Create: `frontend/src/core/api/knowledge.ts`

- [ ] **Step 1: Create TypeScript types**

```typescript
export interface KnowledgeLibraryDto {
  id: string
  name: string
  description: string | null
  nsfw: boolean
  document_count: number
  created_at: string
  updated_at: string
}

export interface KnowledgeDocumentDto {
  id: string
  library_id: string
  title: string
  media_type: 'text/markdown' | 'text/plain'
  size_bytes: number
  chunk_count: number
  embedding_status: 'pending' | 'processing' | 'completed' | 'failed'
  embedding_error: string | null
  created_at: string
  updated_at: string
}

export interface KnowledgeDocumentDetailDto extends KnowledgeDocumentDto {
  content: string
}

export interface RetrievedChunkDto {
  library_name: string
  document_title: string
  heading_path: string[]
  preroll_text: string
  content: string
  score: number
}
```

- [ ] **Step 2: Create API client**

```typescript
import { api } from './client'
import type {
  KnowledgeDocumentDetailDto,
  KnowledgeDocumentDto,
  KnowledgeLibraryDto,
} from '../types/knowledge'

export const knowledgeApi = {
  // Libraries
  listLibraries: () =>
    api.get<KnowledgeLibraryDto[]>('/api/knowledge/libraries'),

  createLibrary: (body: { name: string; description?: string; nsfw?: boolean }) =>
    api.post<KnowledgeLibraryDto>('/api/knowledge/libraries', body),

  updateLibrary: (id: string, body: { name?: string; description?: string; nsfw?: boolean }) =>
    api.put<KnowledgeLibraryDto>(`/api/knowledge/libraries/${id}`, body),

  deleteLibrary: (id: string) =>
    api.delete<{ status: string }>(`/api/knowledge/libraries/${id}`),

  // Documents
  listDocuments: (libraryId: string) =>
    api.get<KnowledgeDocumentDto[]>(`/api/knowledge/libraries/${libraryId}/documents`),

  getDocument: (libraryId: string, docId: string) =>
    api.get<KnowledgeDocumentDetailDto>(`/api/knowledge/libraries/${libraryId}/documents/${docId}`),

  createDocument: (libraryId: string, body: { title: string; content: string; media_type?: string }) =>
    api.post<KnowledgeDocumentDto>(`/api/knowledge/libraries/${libraryId}/documents`, body),

  updateDocument: (libraryId: string, docId: string, body: { title?: string; content?: string; media_type?: string }) =>
    api.put<KnowledgeDocumentDto>(`/api/knowledge/libraries/${libraryId}/documents/${docId}`, body),

  deleteDocument: (libraryId: string, docId: string) =>
    api.delete<{ status: string }>(`/api/knowledge/libraries/${libraryId}/documents/${docId}`),

  retryEmbedding: (libraryId: string, docId: string) =>
    api.post<{ status: string }>(`/api/knowledge/libraries/${libraryId}/documents/${docId}/retry`),

  // Assignments
  getPersonaKnowledge: (personaId: string) =>
    api.get<{ library_ids: string[] }>(`/api/personas/${personaId}/knowledge`),

  setPersonaKnowledge: (personaId: string, libraryIds: string[]) =>
    api.put<{ status: string }>(`/api/personas/${personaId}/knowledge`, { library_ids: libraryIds }),

  getSessionKnowledge: (sessionId: string) =>
    api.get<{ library_ids: string[] }>(`/api/chat/sessions/${sessionId}/knowledge`),

  setSessionKnowledge: (sessionId: string, libraryIds: string[]) =>
    api.put<{ status: string }>(`/api/chat/sessions/${sessionId}/knowledge`, { library_ids: libraryIds }),
}
```

- [ ] **Step 3: Verify build**

Run: `cd /home/chris/workspace/chatsune/frontend && pnpm tsc --noEmit`

Expected: No errors.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/core/types/knowledge.ts frontend/src/core/api/knowledge.ts
git commit -m "Add frontend knowledge types and API client"
```

---

## Task 8: Frontend Knowledge Store

**Files:**
- Create: `frontend/src/core/store/knowledgeStore.ts`

- [ ] **Step 1: Create the Zustand store**

```typescript
import { create } from 'zustand'
import { knowledgeApi } from '../api/knowledge'
import type { KnowledgeDocumentDto, KnowledgeLibraryDto } from '../types/knowledge'

interface KnowledgeState {
  libraries: KnowledgeLibraryDto[]
  libraryDocuments: Record<string, KnowledgeDocumentDto[]>
  expandedLibraryIds: Set<string>
  isLoading: boolean

  // Actions
  fetchLibraries: () => Promise<void>
  fetchDocuments: (libraryId: string) => Promise<void>
  toggleExpanded: (libraryId: string) => void

  // Event-driven updates (called from WS event handlers)
  onLibraryCreated: (library: KnowledgeLibraryDto) => void
  onLibraryUpdated: (library: KnowledgeLibraryDto) => void
  onLibraryDeleted: (libraryId: string) => void
  onDocumentCreated: (document: KnowledgeDocumentDto) => void
  onDocumentUpdated: (document: KnowledgeDocumentDto) => void
  onDocumentDeleted: (libraryId: string, documentId: string) => void
  onDocumentEmbeddingStatus: (documentId: string, status: string, error?: string | null) => void
}

export const useKnowledgeStore = create<KnowledgeState>((set, get) => ({
  libraries: [],
  libraryDocuments: {},
  expandedLibraryIds: new Set(),
  isLoading: false,

  fetchLibraries: async () => {
    set({ isLoading: true })
    try {
      const libraries = await knowledgeApi.listLibraries()
      set({ libraries, isLoading: false })
    } catch {
      set({ isLoading: false })
    }
  },

  fetchDocuments: async (libraryId: string) => {
    try {
      const docs = await knowledgeApi.listDocuments(libraryId)
      set((s) => ({
        libraryDocuments: { ...s.libraryDocuments, [libraryId]: docs },
      }))
    } catch {
      // ignore
    }
  },

  toggleExpanded: (libraryId: string) => {
    const { expandedLibraryIds, libraryDocuments, fetchDocuments } = get()
    const next = new Set(expandedLibraryIds)
    if (next.has(libraryId)) {
      next.delete(libraryId)
    } else {
      next.add(libraryId)
      if (!libraryDocuments[libraryId]) {
        fetchDocuments(libraryId)
      }
    }
    set({ expandedLibraryIds: next })
  },

  onLibraryCreated: (library) =>
    set((s) => ({ libraries: [...s.libraries, library] })),

  onLibraryUpdated: (library) =>
    set((s) => ({
      libraries: s.libraries.map((l) => (l.id === library.id ? library : l)),
    })),

  onLibraryDeleted: (libraryId) =>
    set((s) => {
      const { [libraryId]: _, ...rest } = s.libraryDocuments
      const next = new Set(s.expandedLibraryIds)
      next.delete(libraryId)
      return {
        libraries: s.libraries.filter((l) => l.id !== libraryId),
        libraryDocuments: rest,
        expandedLibraryIds: next,
      }
    }),

  onDocumentCreated: (document) =>
    set((s) => {
      const existing = s.libraryDocuments[document.library_id] ?? []
      return {
        libraryDocuments: {
          ...s.libraryDocuments,
          [document.library_id]: [...existing, document],
        },
      }
    }),

  onDocumentUpdated: (document) =>
    set((s) => {
      const existing = s.libraryDocuments[document.library_id] ?? []
      return {
        libraryDocuments: {
          ...s.libraryDocuments,
          [document.library_id]: existing.map((d) =>
            d.id === document.id ? document : d,
          ),
        },
      }
    }),

  onDocumentDeleted: (libraryId, documentId) =>
    set((s) => {
      const existing = s.libraryDocuments[libraryId] ?? []
      return {
        libraryDocuments: {
          ...s.libraryDocuments,
          [libraryId]: existing.filter((d) => d.id !== documentId),
        },
      }
    }),

  onDocumentEmbeddingStatus: (documentId, status, error) =>
    set((s) => {
      const updated = { ...s.libraryDocuments }
      for (const libId of Object.keys(updated)) {
        updated[libId] = updated[libId].map((d) =>
          d.id === documentId
            ? { ...d, embedding_status: status as KnowledgeDocumentDto['embedding_status'], embedding_error: error ?? null }
            : d,
        )
      }
      return { libraryDocuments: updated }
    }),
}))
```

- [ ] **Step 2: Verify build**

Run: `cd /home/chris/workspace/chatsune/frontend && pnpm tsc --noEmit`

Expected: No errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/core/store/knowledgeStore.ts
git commit -m "Add knowledge Zustand store with event-driven updates"
```

---

## Task 9: User Modal Knowledge Tab

**Files:**
- Modify: `frontend/src/app/components/user-modal/KnowledgeTab.tsx`
- Create: `frontend/src/app/components/user-modal/LibraryEditorModal.tsx`
- Create: `frontend/src/app/components/user-modal/DocumentEditorModal.tsx`

- [ ] **Step 1: Create LibraryEditorModal**

```typescript
import { useState } from 'react'

interface LibraryEditorModalProps {
  initial?: { name: string; description: string; nsfw: boolean }
  onSave: (data: { name: string; description: string; nsfw: boolean }) => void
  onDelete?: () => void
  onClose: () => void
}

export function LibraryEditorModal({ initial, onSave, onDelete, onClose }: LibraryEditorModalProps) {
  const [name, setName] = useState(initial?.name ?? '')
  const [description, setDescription] = useState(initial?.description ?? '')
  const [nsfw, setNsfw] = useState(initial?.nsfw ?? false)
  const [confirmDelete, setConfirmDelete] = useState(false)

  const isEdit = !!initial

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      <div className="absolute inset-0 bg-black/60" onClick={onClose} />
      <div className="relative z-10 w-full max-w-md rounded-xl bg-elevated border border-white/8 p-5 shadow-2xl">
        <h3 className="text-[14px] font-semibold text-white/80 mb-4">
          {isEdit ? 'Edit Library' : 'New Library'}
        </h3>

        <label className="block mb-3">
          <span className="text-[11px] text-white/40 font-mono uppercase tracking-wide">Name</span>
          <input
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
            maxLength={200}
            className="mt-1 block w-full rounded-lg bg-surface border border-white/8 px-3 py-2 text-[13px] text-white/80 outline-none focus:border-gold/40"
            autoFocus
          />
        </label>

        <label className="block mb-3">
          <span className="text-[11px] text-white/40 font-mono uppercase tracking-wide">Description</span>
          <textarea
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            maxLength={1000}
            rows={3}
            className="mt-1 block w-full rounded-lg bg-surface border border-white/8 px-3 py-2 text-[13px] text-white/80 outline-none focus:border-gold/40 resize-none"
          />
        </label>

        <label className="flex items-center gap-2 mb-5 cursor-pointer">
          <input
            type="checkbox"
            checked={nsfw}
            onChange={(e) => setNsfw(e.target.checked)}
            className="rounded border-white/20"
          />
          <span className="text-[12px] text-white/60">💋 NSFW content</span>
        </label>

        <div className="flex items-center justify-between">
          <div>
            {isEdit && onDelete && (
              confirmDelete ? (
                <div className="flex items-center gap-2">
                  <span className="text-[11px] text-red-400">Are you sure?</span>
                  <button
                    type="button"
                    onClick={onDelete}
                    className="text-[11px] text-red-400 hover:text-red-300 underline"
                  >
                    Delete
                  </button>
                  <button
                    type="button"
                    onClick={() => setConfirmDelete(false)}
                    className="text-[11px] text-white/40 hover:text-white/60"
                  >
                    Cancel
                  </button>
                </div>
              ) : (
                <button
                  type="button"
                  onClick={() => setConfirmDelete(true)}
                  className="text-[11px] text-red-400/60 hover:text-red-400"
                >
                  Delete library
                </button>
              )
            )}
          </div>
          <div className="flex gap-2">
            <button
              type="button"
              onClick={onClose}
              className="px-3 py-1.5 text-[12px] text-white/50 hover:text-white/70 rounded-lg hover:bg-white/5"
            >
              Cancel
            </button>
            <button
              type="button"
              onClick={() => onSave({ name, description, nsfw })}
              disabled={!name.trim()}
              className="px-3 py-1.5 text-[12px] text-gold bg-gold/10 border border-gold/20 rounded-lg hover:bg-gold/15 disabled:opacity-40 disabled:cursor-not-allowed"
            >
              {isEdit ? 'Save' : 'Create'}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
```

- [ ] **Step 2: Create DocumentEditorModal**

```typescript
import { useCallback, useRef, useState } from 'react'

interface DocumentEditorModalProps {
  libraryId: string
  initial?: { title: string; content: string; media_type: 'text/markdown' | 'text/plain' }
  onSave: (data: { title: string; content: string; media_type: 'text/markdown' | 'text/plain' }) => void
  onDelete?: () => void
  onClose: () => void
}

export function DocumentEditorModal({ initial, onSave, onDelete, onClose }: DocumentEditorModalProps) {
  const [title, setTitle] = useState(initial?.title ?? '')
  const [content, setContent] = useState(initial?.content ?? '')
  const [mediaType, setMediaType] = useState<'text/markdown' | 'text/plain'>(initial?.media_type ?? 'text/markdown')
  const [showPreview, setShowPreview] = useState(false)
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [hasChanges, setHasChanges] = useState(false)
  const fileRef = useRef<HTMLInputElement>(null)

  const isEdit = !!initial

  const handleContentChange = useCallback((value: string) => {
    setContent(value)
    setHasChanges(true)
  }, [])

  const handleFileUpload = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return

    const reader = new FileReader()
    reader.onload = (ev) => {
      const text = ev.target?.result as string
      setContent(text)
      setHasChanges(true)
      if (!title) setTitle(file.name.replace(/\.(md|txt|markdown)$/, ''))
      if (file.name.endsWith('.md') || file.name.endsWith('.markdown')) {
        setMediaType('text/markdown')
      } else {
        setMediaType('text/plain')
      }
    }
    reader.readAsText(file)
  }, [title])

  const handleClose = useCallback(() => {
    if (hasChanges && !confirm('You have unsaved changes. Discard them?')) return
    onClose()
  }, [hasChanges, onClose])

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      <div className="absolute inset-0 bg-black/60" onClick={handleClose} />
      <div className="relative z-10 flex flex-col w-full max-w-3xl max-h-[80vh] rounded-xl bg-elevated border border-white/8 shadow-2xl overflow-hidden">
        {/* Header */}
        <div className="flex items-center gap-3 px-5 py-3 border-b border-white/6">
          <input
            type="text"
            value={title}
            onChange={(e) => { setTitle(e.target.value); setHasChanges(true) }}
            placeholder="Document title"
            maxLength={500}
            className="flex-1 bg-transparent text-[14px] text-white/80 outline-none placeholder:text-white/20"
            autoFocus
          />
          <div className="flex items-center gap-1.5">
            <button
              type="button"
              onClick={() => setMediaType(mediaType === 'text/markdown' ? 'text/plain' : 'text/markdown')}
              className="px-2 py-1 text-[10px] font-mono text-white/40 hover:text-white/60 rounded border border-white/8"
            >
              {mediaType === 'text/markdown' ? 'MD' : 'TXT'}
            </button>
            <button
              type="button"
              onClick={() => setShowPreview(!showPreview)}
              className={`px-2 py-1 text-[10px] font-mono rounded border border-white/8 ${showPreview ? 'text-gold' : 'text-white/40 hover:text-white/60'}`}
            >
              Preview
            </button>
          </div>
        </div>

        {/* Editor */}
        <div className="flex-1 overflow-hidden flex">
          <textarea
            value={content}
            onChange={(e) => handleContentChange(e.target.value)}
            className={`${showPreview ? 'w-1/2 border-r border-white/6' : 'w-full'} flex-shrink-0 bg-transparent px-5 py-4 text-[13px] text-white/70 outline-none resize-none font-mono leading-relaxed`}
            placeholder="Write your document here..."
          />
          {showPreview && (
            <div className="w-1/2 px-5 py-4 overflow-y-auto text-[13px] text-white/60 leading-relaxed chat-prose">
              {/* Simple markdown preview — render as pre for now, rich rendering can be added later */}
              <pre className="whitespace-pre-wrap font-sans">{content}</pre>
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="flex items-center justify-between px-5 py-3 border-t border-white/6">
          <div className="flex items-center gap-2">
            {isEdit && onDelete && (
              confirmDelete ? (
                <div className="flex items-center gap-2">
                  <span className="text-[11px] text-red-400">Are you sure?</span>
                  <button type="button" onClick={onDelete} className="text-[11px] text-red-400 hover:text-red-300 underline">Delete</button>
                  <button type="button" onClick={() => setConfirmDelete(false)} className="text-[11px] text-white/40">Cancel</button>
                </div>
              ) : (
                <button type="button" onClick={() => setConfirmDelete(true)} className="text-[11px] text-red-400/60 hover:text-red-400">
                  Delete document
                </button>
              )
            )}
          </div>
          <div className="flex items-center gap-2">
            <input ref={fileRef} type="file" accept=".md,.txt,.markdown" onChange={handleFileUpload} className="hidden" />
            <button
              type="button"
              onClick={() => fileRef.current?.click()}
              className="px-3 py-1.5 text-[12px] text-white/40 hover:text-white/60 rounded-lg hover:bg-white/5"
            >
              Upload file
            </button>
            <button type="button" onClick={handleClose} className="px-3 py-1.5 text-[12px] text-white/50 hover:text-white/70 rounded-lg hover:bg-white/5">
              Cancel
            </button>
            <button
              type="button"
              onClick={() => onSave({ title, content, media_type: mediaType })}
              disabled={!title.trim() || !content.trim()}
              className="px-3 py-1.5 text-[12px] text-gold bg-gold/10 border border-gold/20 rounded-lg hover:bg-gold/15 disabled:opacity-40 disabled:cursor-not-allowed"
            >
              {isEdit ? 'Save' : 'Create'}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
```

- [ ] **Step 3: Replace KnowledgeTab placeholder**

Replace the entire content of `frontend/src/app/components/user-modal/KnowledgeTab.tsx`:

```typescript
import { useCallback, useEffect, useState } from 'react'
import { useKnowledgeStore } from '../../../core/store/knowledgeStore'
import { useSanitisedMode } from '../../../core/store/sanitisedModeStore'
import { knowledgeApi } from '../../../core/api/knowledge'
import type { KnowledgeDocumentDto } from '../../../core/types/knowledge'
import { LibraryEditorModal } from './LibraryEditorModal'
import { DocumentEditorModal } from './DocumentEditorModal'

function EmbeddingDot({ status }: { status: string }) {
  if (status === 'completed') return <span className="inline-block w-2 h-2 rounded-full bg-live flex-shrink-0" title="Embedded" />
  if (status === 'processing') return <span className="inline-block w-2 h-2 rounded-full bg-yellow-500 animate-pulse flex-shrink-0" title="Processing" />
  if (status === 'failed') return <span className="inline-block w-2 h-2 rounded-full bg-red-400 flex-shrink-0" title="Failed — click to retry" />
  return <span className="inline-block w-2 h-2 rounded-full bg-white/20 flex-shrink-0" title="Pending" />
}

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  return `${(bytes / 1024).toFixed(1)} KB`
}

export function KnowledgeTab() {
  const {
    libraries, libraryDocuments, expandedLibraryIds, isLoading,
    fetchLibraries, fetchDocuments, toggleExpanded,
  } = useKnowledgeStore()
  const isSanitised = useSanitisedMode((s) => s.isSanitised)

  const [libraryModal, setLibraryModal] = useState<{ libraryId?: string } | null>(null)
  const [docModal, setDocModal] = useState<{ libraryId: string; docId?: string } | null>(null)
  const [editingDoc, setEditingDoc] = useState<{ title: string; content: string; media_type: 'text/markdown' | 'text/plain' } | undefined>()

  useEffect(() => { fetchLibraries() }, [fetchLibraries])

  const visibleLibraries = isSanitised ? libraries.filter((l) => !l.nsfw) : libraries

  const handleCreateLibrary = useCallback(async (data: { name: string; description: string; nsfw: boolean }) => {
    await knowledgeApi.createLibrary(data)
    setLibraryModal(null)
  }, [])

  const handleUpdateLibrary = useCallback(async (libraryId: string, data: { name: string; description: string; nsfw: boolean }) => {
    await knowledgeApi.updateLibrary(libraryId, data)
    setLibraryModal(null)
  }, [])

  const handleDeleteLibrary = useCallback(async (libraryId: string) => {
    await knowledgeApi.deleteLibrary(libraryId)
    setLibraryModal(null)
  }, [])

  const openDocEditor = useCallback(async (libraryId: string, docId?: string) => {
    if (docId) {
      const detail = await knowledgeApi.getDocument(libraryId, docId)
      setEditingDoc({ title: detail.title, content: detail.content, media_type: detail.media_type })
    } else {
      setEditingDoc(undefined)
    }
    setDocModal({ libraryId, docId })
  }, [])

  const handleSaveDoc = useCallback(async (data: { title: string; content: string; media_type: 'text/markdown' | 'text/plain' }) => {
    if (!docModal) return
    if (docModal.docId) {
      await knowledgeApi.updateDocument(docModal.libraryId, docModal.docId, data)
    } else {
      await knowledgeApi.createDocument(docModal.libraryId, data)
    }
    setDocModal(null)
    setEditingDoc(undefined)
    fetchDocuments(docModal.libraryId)
  }, [docModal, fetchDocuments])

  const handleDeleteDoc = useCallback(async () => {
    if (!docModal?.docId) return
    await knowledgeApi.deleteDocument(docModal.libraryId, docModal.docId)
    setDocModal(null)
    setEditingDoc(undefined)
  }, [docModal])

  const handleRetry = useCallback(async (libraryId: string, docId: string) => {
    await knowledgeApi.retryEmbedding(libraryId, docId)
  }, [])

  const hasEmbeddingIssue = (libraryId: string): boolean => {
    const docs = libraryDocuments[libraryId] ?? []
    return docs.some((d) => d.embedding_status === 'failed')
  }

  if (isLoading && libraries.length === 0) {
    return <div className="flex flex-1 items-center justify-center text-[13px] text-white/25 font-mono">Loading...</div>
  }

  return (
    <div className="flex flex-col h-full p-4 overflow-y-auto">
      {/* Header */}
      <div className="flex items-center justify-between mb-3">
        <span className="text-[14px] text-white/70">Your Libraries</span>
        <button
          type="button"
          onClick={() => setLibraryModal({})}
          className="px-3 py-1.5 text-[12px] text-gold bg-gold/10 border border-gold/20 rounded-lg hover:bg-gold/15"
        >
          + New Library
        </button>
      </div>

      {/* Library list */}
      {visibleLibraries.length === 0 ? (
        <div className="flex flex-1 items-center justify-center text-[13px] text-white/25 font-mono">
          No libraries yet
        </div>
      ) : (
        <div className="flex flex-col gap-2">
          {visibleLibraries.map((lib) => {
            const isExpanded = expandedLibraryIds.has(lib.id)
            const docs = libraryDocuments[lib.id] ?? []
            return (
              <div key={lib.id} className="border border-white/8 rounded-lg overflow-hidden">
                {/* Library row */}
                <div
                  className="flex items-center px-3 py-2.5 bg-white/3 cursor-pointer hover:bg-white/5 transition-colors"
                  onClick={() => toggleExpanded(lib.id)}
                >
                  <span className="text-white/40 mr-2 text-[10px]">{isExpanded ? '▼' : '▶'}</span>
                  <span className="text-white/90 text-[13px] flex-1">{lib.name}</span>
                  {lib.nsfw && <span className="mr-2" title="NSFW">💋</span>}
                  {hasEmbeddingIssue(lib.id) && <span className="text-yellow-500 mr-2 text-[13px]" title="Embedding issue">⚠</span>}
                  <span className="text-white/30 text-[11px] mr-2">{lib.document_count} docs</span>
                  <button
                    type="button"
                    onClick={(e) => { e.stopPropagation(); setLibraryModal({ libraryId: lib.id }) }}
                    className="text-white/30 text-[11px] hover:text-white/60"
                    title="Edit library"
                  >
                    ✎
                  </button>
                </div>

                {/* Documents */}
                {isExpanded && (
                  <div className="px-3 pb-2 pt-1 ml-5">
                    {docs.map((doc: KnowledgeDocumentDto) => (
                      <div
                        key={doc.id}
                        className="flex items-center py-1.5 border-b border-white/4 last:border-0 cursor-pointer hover:bg-white/3 rounded px-1 -mx-1"
                        onClick={() => openDocEditor(lib.id, doc.id)}
                      >
                        <span className="text-white/70 text-[12px] flex-1 truncate">{doc.title}</span>
                        <button
                          type="button"
                          onClick={(e) => {
                            e.stopPropagation()
                            if (doc.embedding_status === 'failed') handleRetry(lib.id, doc.id)
                          }}
                          className="mr-2"
                        >
                          <EmbeddingDot status={doc.embedding_status} />
                        </button>
                        <span className="text-white/30 text-[10px]">{formatSize(doc.size_bytes)}</span>
                      </div>
                    ))}
                    <button
                      type="button"
                      onClick={() => openDocEditor(lib.id)}
                      className="w-full mt-2 py-1.5 text-[11px] text-white/30 border border-dashed border-white/10 rounded-lg hover:border-white/20 hover:text-white/50"
                    >
                      + Add Document
                    </button>
                  </div>
                )}
              </div>
            )
          })}
        </div>
      )}

      {/* Modals */}
      {libraryModal && (
        <LibraryEditorModal
          initial={libraryModal.libraryId ? (() => {
            const lib = libraries.find((l) => l.id === libraryModal.libraryId)
            return lib ? { name: lib.name, description: lib.description ?? '', nsfw: lib.nsfw } : undefined
          })() : undefined}
          onSave={(data) => libraryModal.libraryId ? handleUpdateLibrary(libraryModal.libraryId, data) : handleCreateLibrary(data)}
          onDelete={libraryModal.libraryId ? () => handleDeleteLibrary(libraryModal.libraryId!) : undefined}
          onClose={() => setLibraryModal(null)}
        />
      )}
      {docModal && (
        <DocumentEditorModal
          libraryId={docModal.libraryId}
          initial={editingDoc}
          onSave={handleSaveDoc}
          onDelete={docModal.docId ? handleDeleteDoc : undefined}
          onClose={() => { setDocModal(null); setEditingDoc(undefined) }}
        />
      )}
    </div>
  )
}
```

- [ ] **Step 4: Verify build**

Run: `cd /home/chris/workspace/chatsune/frontend && pnpm tsc --noEmit`

Expected: No errors.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/app/components/user-modal/KnowledgeTab.tsx frontend/src/app/components/user-modal/LibraryEditorModal.tsx frontend/src/app/components/user-modal/DocumentEditorModal.tsx
git commit -m "Add User Modal Knowledge Tab with library and document management"
```

---

## Task 10: Persona Overlay Knowledge Tab

**Files:**
- Modify: `frontend/src/app/components/persona-overlay/KnowledgeTab.tsx`

- [ ] **Step 1: Replace placeholder with library assignment UI**

```typescript
import { useCallback, useEffect, useState } from 'react'
import type { ChakraPaletteEntry } from '../../../core/types/chakra'
import type { PersonaDto } from '../../../core/types/persona'
import { useKnowledgeStore } from '../../../core/store/knowledgeStore'
import { useSanitisedMode } from '../../../core/store/sanitisedModeStore'
import { knowledgeApi } from '../../../core/api/knowledge'

interface KnowledgeTabProps {
  persona: PersonaDto
  chakra: ChakraPaletteEntry
}

export function KnowledgeTab({ persona, chakra }: KnowledgeTabProps) {
  const { libraries, fetchLibraries } = useKnowledgeStore()
  const isSanitised = useSanitisedMode((s) => s.isSanitised)
  const [assignedIds, setAssignedIds] = useState<string[]>([])
  const [showDropdown, setShowDropdown] = useState(false)

  useEffect(() => { fetchLibraries() }, [fetchLibraries])

  useEffect(() => {
    knowledgeApi.getPersonaKnowledge(persona.id)
      .then((r) => setAssignedIds(r.library_ids))
      .catch(() => {})
  }, [persona.id])

  const visibleLibraries = isSanitised ? libraries.filter((l) => !l.nsfw) : libraries
  const assignedLibraries = visibleLibraries.filter((l) => assignedIds.includes(l.id))
  const unassignedLibraries = visibleLibraries.filter((l) => !assignedIds.includes(l.id))

  const handleAssign = useCallback(async (libraryId: string) => {
    const updated = [...assignedIds, libraryId]
    setAssignedIds(updated)
    setShowDropdown(false)
    await knowledgeApi.setPersonaKnowledge(persona.id, updated)
  }, [assignedIds, persona.id])

  const handleRemove = useCallback(async (libraryId: string) => {
    const updated = assignedIds.filter((id) => id !== libraryId)
    setAssignedIds(updated)
    await knowledgeApi.setPersonaKnowledge(persona.id, updated)
  }, [assignedIds, persona.id])

  return (
    <div className="flex flex-col h-full p-4">
      <p className="text-[12px] text-white/50 mb-4">
        Assigned libraries are available in every chat with this persona.
      </p>

      {/* Assigned libraries */}
      {assignedLibraries.length === 0 ? (
        <p className="text-[12px] text-white/25 font-mono mb-4">No libraries assigned yet</p>
      ) : (
        <div className="flex flex-col gap-2 mb-4">
          {assignedLibraries.map((lib) => (
            <div
              key={lib.id}
              className="flex items-center px-3 py-2 rounded-lg"
              style={{
                background: `${chakra.hex}0D`,
                border: `1px solid ${chakra.hex}33`,
              }}
            >
              <span className="text-white/80 text-[12px] flex-1">{lib.name}</span>
              {lib.nsfw && <span className="text-[11px] mr-2">💋</span>}
              <span className="text-white/30 text-[10px] mr-2">{lib.document_count} docs</span>
              <button
                type="button"
                onClick={() => handleRemove(lib.id)}
                className="text-white/30 text-[14px] hover:text-white/60"
                title="Remove"
              >
                ×
              </button>
            </div>
          ))}
        </div>
      )}

      {/* Assign button + dropdown */}
      <div className="relative">
        <button
          type="button"
          onClick={() => setShowDropdown(!showDropdown)}
          className="w-full py-2 text-[11px] rounded-lg cursor-pointer"
          style={{
            background: `${chakra.hex}0D`,
            border: `1px dashed ${chakra.hex}4D`,
            color: `${chakra.hex}B3`,
          }}
        >
          + Assign Library
        </button>
        {showDropdown && unassignedLibraries.length > 0 && (
          <div className="absolute left-0 right-0 mt-1 bg-elevated border border-white/10 rounded-lg p-1 z-10 shadow-lg">
            {unassignedLibraries.map((lib) => (
              <button
                key={lib.id}
                type="button"
                onClick={() => handleAssign(lib.id)}
                className="w-full text-left px-3 py-2 text-[12px] text-white/60 hover:bg-white/5 rounded cursor-pointer flex items-center"
              >
                <span className="flex-1">{lib.name}</span>
                {lib.nsfw && <span className="text-[11px]">💋</span>}
              </button>
            ))}
          </div>
        )}
        {showDropdown && unassignedLibraries.length === 0 && (
          <div className="absolute left-0 right-0 mt-1 bg-elevated border border-white/10 rounded-lg p-3 z-10 shadow-lg">
            <p className="text-[11px] text-white/30 text-center">All libraries are assigned</p>
          </div>
        )}
      </div>

      {/* Sanitised mode note */}
      {!isSanitised && libraries.some((l) => l.nsfw) && (
        <p className="mt-4 px-3 py-2 bg-white/3 rounded-lg text-[11px] text-white/35">
          💋 libraries are hidden when sanitised mode is active
        </p>
      )}
    </div>
  )
}
```

- [ ] **Step 2: Verify build**

Run: `cd /home/chris/workspace/chatsune/frontend && pnpm tsc --noEmit`

Expected: No errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/app/components/persona-overlay/KnowledgeTab.tsx
git commit -m "Add Persona Overlay Knowledge Tab with library assignment"
```

---

## Task 11: Chat Topbar Knowledge Dropdown

**Files:**
- Create: `frontend/src/features/chat/KnowledgeDropdown.tsx`
- Modify: `frontend/src/app/components/topbar/Topbar.tsx`

- [ ] **Step 1: Create KnowledgeDropdown component**

```typescript
import { useCallback, useEffect, useState } from 'react'
import { useKnowledgeStore } from '../../core/store/knowledgeStore'
import { useSanitisedMode } from '../../core/store/sanitisedModeStore'
import { knowledgeApi } from '../../core/api/knowledge'

interface KnowledgeDropdownProps {
  personaId: string
  personaName: string
  sessionId: string
  isOpen: boolean
  onClose: () => void
}

export function KnowledgeDropdown({ personaId, personaName, sessionId, isOpen, onClose }: KnowledgeDropdownProps) {
  const { libraries, fetchLibraries } = useKnowledgeStore()
  const isSanitised = useSanitisedMode((s) => s.isSanitised)
  const [personaLibIds, setPersonaLibIds] = useState<string[]>([])
  const [sessionLibIds, setSessionLibIds] = useState<string[]>([])

  useEffect(() => {
    if (!isOpen) return
    fetchLibraries()
    knowledgeApi.getPersonaKnowledge(personaId).then((r) => setPersonaLibIds(r.library_ids)).catch(() => {})
    knowledgeApi.getSessionKnowledge(sessionId).then((r) => setSessionLibIds(r.library_ids)).catch(() => {})
  }, [isOpen, personaId, sessionId, fetchLibraries])

  const visibleLibraries = isSanitised ? libraries.filter((l) => !l.nsfw) : libraries
  const availableLibraries = visibleLibraries.filter((l) => !personaLibIds.includes(l.id))

  const handleToggle = useCallback(async (libraryId: string) => {
    const isActive = sessionLibIds.includes(libraryId)
    const updated = isActive
      ? sessionLibIds.filter((id) => id !== libraryId)
      : [...sessionLibIds, libraryId]
    setSessionLibIds(updated)
    await knowledgeApi.setSessionKnowledge(sessionId, updated)
  }, [sessionId, sessionLibIds])

  if (!isOpen) return null

  return (
    <>
      <div className="fixed inset-0 z-10" onClick={onClose} />
      <div
        className="absolute right-0 top-full mt-1 z-20 min-w-[260px] max-w-[360px] rounded-lg p-3"
        style={{
          background: 'rgba(26, 21, 40, 0.98)',
          border: '1px solid rgba(140,118,215,0.2)',
          boxShadow: '0 4px 12px rgba(0,0,0,0.3)',
        }}
      >
        <div className="text-[11px] text-white/40 mb-1">Add knowledge for this session only</div>
        <div className="text-[10px] text-white/25 mb-3">
          Libraries already assigned to {personaName} are not shown here.
        </div>

        {availableLibraries.length === 0 ? (
          <p className="text-[11px] text-white/20 text-center py-2">No additional libraries available</p>
        ) : (
          <div className="flex flex-col gap-1">
            {availableLibraries.map((lib) => {
              const isActive = sessionLibIds.includes(lib.id)
              return (
                <button
                  key={lib.id}
                  type="button"
                  onClick={() => handleToggle(lib.id)}
                  className="flex items-center px-2.5 py-2 rounded cursor-pointer transition-colors"
                  style={{
                    background: isActive ? 'rgba(140,118,215,0.1)' : 'transparent',
                    border: `1px solid ${isActive ? 'rgba(140,118,215,0.25)' : 'rgba(255,255,255,0.06)'}`,
                  }}
                >
                  <span
                    className="flex items-center justify-center w-3.5 h-3.5 rounded-sm mr-2.5 flex-shrink-0 text-[9px]"
                    style={{
                      background: isActive ? '#8C76D7' : 'transparent',
                      border: isActive ? 'none' : '1.5px solid rgba(140,118,215,0.4)',
                      color: 'white',
                    }}
                  >
                    {isActive && '✓'}
                  </span>
                  <span className={`text-[12px] flex-1 text-left ${isActive ? 'text-white/90' : 'text-white/70'}`}>
                    {lib.name}
                  </span>
                  {lib.nsfw && <span className="text-[11px] mr-1">💋</span>}
                  <span className="text-white/30 text-[10px]">{lib.document_count} docs</span>
                </button>
              )
            })}
          </div>
        )}
      </div>
    </>
  )
}
```

- [ ] **Step 2: Add knowledge dropdown to Topbar**

In `Topbar.tsx`, add the import at the top:

```typescript
import { KnowledgeDropdown } from '../../features/chat/KnowledgeDropdown'
```

Add state inside the `Topbar` component:

```typescript
const [showKnowledge, setShowKnowledge] = useState(false)
```

In the chat match branch, add the 🎓 button before the model pill (in the `flex-shrink-0 flex items-center gap-1.5` div):

```tsx
<div className="relative">
  <button
    type="button"
    onClick={() => setShowKnowledge(!showKnowledge)}
    className="flex items-center justify-center w-7 h-7 rounded text-[15px] transition-colors"
    style={{ background: 'rgba(140,118,215,0.1)' }}
    title="Ad-hoc Knowledge"
  >
    🎓
  </button>
  {persona && chatMatch.params.sessionId && (
    <KnowledgeDropdown
      personaId={persona.id}
      personaName={persona.name}
      sessionId={chatMatch.params.sessionId}
      isOpen={showKnowledge}
      onClose={() => setShowKnowledge(false)}
    />
  )}
</div>
```

- [ ] **Step 3: Verify build**

Run: `cd /home/chris/workspace/chatsune/frontend && pnpm tsc --noEmit`

Expected: No errors.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/features/chat/KnowledgeDropdown.tsx frontend/src/app/components/topbar/Topbar.tsx
git commit -m "Add chat topbar knowledge dropdown for ad-hoc library assignment"
```

---

## Task 12: Knowledge Pills in Chat

**Files:**
- Create: `frontend/src/features/chat/KnowledgePills.tsx`
- Modify: `frontend/src/features/chat/ToolCallActivity.tsx`
- Modify: `frontend/src/core/store/chatStore.ts`

- [ ] **Step 1: Create KnowledgePills component**

```typescript
import { useState } from 'react'
import type { RetrievedChunkDto } from '../../core/types/knowledge'

interface KnowledgePillsProps {
  items: RetrievedChunkDto[]
}

export function KnowledgePills({ items }: KnowledgePillsProps) {
  const [expandedIdx, setExpandedIdx] = useState<number | null>(null)

  if (items.length === 0) return null

  return (
    <div className="mb-2">
      <div className="font-mono text-[10px] text-white/30 mb-1">RETRIEVED KNOWLEDGE</div>
      <div className="flex flex-wrap gap-1.5">
        {items.map((item, idx) => (
          <div key={`${item.document_title}-${idx}`} className="relative">
            <button
              type="button"
              onClick={() => setExpandedIdx(expandedIdx === idx ? null : idx)}
              className="flex items-center gap-1 rounded px-2 py-0.5 text-[11px] transition-opacity hover:opacity-90"
              style={{
                background: 'rgba(140,118,215,0.08)',
                border: '1px solid rgba(140,118,215,0.15)',
                color: 'rgba(140,118,215,0.9)',
                fontFamily: "'Courier New', monospace",
              }}
            >
              <span className="text-[9px]">📚</span>
              {item.document_title.length > 30 ? item.document_title.slice(0, 30) + '...' : item.document_title}
              <span style={{ color: 'rgba(140,118,215,0.4)', fontSize: '9px' }}>
                {item.score.toFixed(2)}
              </span>
            </button>

            {expandedIdx === idx && (
              <div
                className="absolute left-0 top-full z-20 mt-1 min-w-[300px] max-w-[450px] rounded-lg p-3"
                style={{
                  background: 'rgba(20, 18, 28, 0.98)',
                  border: '1px solid rgba(140,118,215,0.15)',
                  boxShadow: '0 8px 24px rgba(0,0,0,0.5)',
                }}
              >
                <div className="flex items-center justify-between mb-1">
                  <div>
                    <span
                      className="font-mono text-[9px] uppercase"
                      style={{ color: 'rgba(140,118,215,0.5)' }}
                    >
                      {item.library_name}
                    </span>
                    <span className="text-white/20 mx-1">›</span>
                    <span className="text-[12px]" style={{ color: '#8C76D7' }}>
                      {item.document_title}
                    </span>
                  </div>
                  <span className="font-mono text-[10px]" style={{ color: 'rgba(140,118,215,0.4)' }}>
                    score: {item.score.toFixed(2)}
                  </span>
                </div>
                {item.preroll_text && (
                  <div className="font-mono text-[10px] text-white/30 mb-1">
                    {item.preroll_text}
                  </div>
                )}
                <div
                  className="text-[12px] text-white/60 leading-relaxed"
                  style={{ fontFamily: "'Georgia', serif" }}
                >
                  {item.content.length > 500 ? item.content.slice(0, 500) + '...' : item.content}
                </div>
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  )
}
```

- [ ] **Step 2: Add `knowledge_search` to TOOL_LABELS in `ToolCallActivity.tsx`**

Add to the `TOOL_LABELS` object:

```typescript
  knowledge_search: (args) => `Searching knowledge for "${args.query ?? '...'}"`,
```

Also update the component to use lila colour for knowledge tools. Replace the static style object with a dynamic one:

```typescript
const isKnowledge = toolName === 'knowledge_search'
const colour = isKnowledge ? '140,118,215' : '137,180,250'
```

And use `colour` in the style:

```typescript
style={{
  background: `rgba(${colour},0.08)`,
  border: `1px solid rgba(${colour},0.15)`,
  color: `rgba(${colour},0.8)`,
  fontFamily: "'Courier New', monospace",
}}
```

- [ ] **Step 3: Add `streamingKnowledgeContext` to chatStore**

Add to the `ChatState` interface:

```typescript
streamingKnowledgeContext: RetrievedChunkDto[]
setStreamingKnowledgeContext: (items: RetrievedChunkDto[]) => void
```

Add to `INITIAL_STATE`:

```typescript
streamingKnowledgeContext: [] as RetrievedChunkDto[],
```

Add the action:

```typescript
setStreamingKnowledgeContext: (items) => set({ streamingKnowledgeContext: items }),
```

Update `startStreaming` to clear it:

```typescript
streamingKnowledgeContext: [],
```

Update `finishStreaming` to clear it:

```typescript
streamingKnowledgeContext: [],
```

Import the type at the top of chatStore.ts:

```typescript
import type { RetrievedChunkDto } from '../types/knowledge'
```

- [ ] **Step 4: Wire KnowledgePills into ChatView**

In `ChatView.tsx` (or wherever assistant messages are rendered), add the `KnowledgePills` component after `WebSearchPills`, using `streamingKnowledgeContext` from the chat store. Subscribe to `knowledge.search.completed` events in the WS event handler to populate the context.

The exact integration point depends on how `ChatView.tsx` renders streaming content — follow the same pattern as `WebSearchPills`.

- [ ] **Step 5: Verify build**

Run: `cd /home/chris/workspace/chatsune/frontend && pnpm tsc --noEmit`

Expected: No errors.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/features/chat/KnowledgePills.tsx frontend/src/features/chat/ToolCallActivity.tsx frontend/src/core/store/chatStore.ts
git commit -m "Add knowledge pills in chat — lila retrieval display with expandable chunks"
```

---

## Task 13: WS Event Subscriptions & Final Wiring

**Files:**
- Modify: Frontend WS event handler (where events are dispatched to stores)

- [ ] **Step 1: Subscribe knowledge store to WS events**

In the component or hook where WS events are handled (likely in `ChatView.tsx` or a dedicated `useKnowledgeEvents` hook), add subscriptions:

```typescript
import { useEffect } from 'react'
import { eventBus } from '../../core/websocket/eventBus'
import { useKnowledgeStore } from '../../core/store/knowledgeStore'
import { useChatStore } from '../../core/store/chatStore'

export function useKnowledgeEvents() {
  const store = useKnowledgeStore()
  const chatStore = useChatStore()

  useEffect(() => {
    const unsubs = [
      eventBus.on('knowledge.library.created', (e) => store.onLibraryCreated(e.payload.library)),
      eventBus.on('knowledge.library.updated', (e) => store.onLibraryUpdated(e.payload.library)),
      eventBus.on('knowledge.library.deleted', (e) => store.onLibraryDeleted(e.payload.library_id)),
      eventBus.on('knowledge.document.created', (e) => store.onDocumentCreated(e.payload.document)),
      eventBus.on('knowledge.document.updated', (e) => store.onDocumentUpdated(e.payload.document)),
      eventBus.on('knowledge.document.deleted', (e) => store.onDocumentDeleted(e.payload.library_id, e.payload.document_id)),
      eventBus.on('knowledge.document.embedding', (e) => store.onDocumentEmbeddingStatus(e.payload.document_id, 'processing')),
      eventBus.on('knowledge.document.embedded', (e) => store.onDocumentEmbeddingStatus(e.payload.document_id, 'completed')),
      eventBus.on('knowledge.document.embed_failed', (e) => {
        store.onDocumentEmbeddingStatus(e.payload.document_id, 'failed', e.payload.error)
        // Toast notification for final embedding failure
        if (!e.payload.recoverable) {
          const { addNotification } = useNotificationStore.getState()
          addNotification({ type: 'error', message: `Embedding failed: ${e.payload.error}` })
        }
      }),
      eventBus.on('knowledge.search.completed', (e) => chatStore.setStreamingKnowledgeContext(e.payload.results)),
    ]
    return () => unsubs.forEach((fn) => fn())
  }, [store, chatStore])
}
```

Import `useNotificationStore` from the notification store (check existing import path in the codebase).

Call `useKnowledgeEvents()` from `AppLayout.tsx` or a suitable top-level component.

**Note on sanitised mode:** The spec requires the `chat_sessions` document to carry a `sanitised: bool` field. When the frontend creates a session or toggles sanitised mode, it must update this field via the session API. The `knowledge_search` tool executor reads `sanitised` from the session document. Add this field to session creation in the chat module and expose it via the session update endpoint.

**Note:** The exact event payload structure depends on how the backend event bus serialises events. Check how existing events (e.g., bookmark events) arrive in the frontend and follow the same access pattern — it may be `e.payload.library` or directly `e.library` depending on the envelope structure.

- [ ] **Step 2: Verify build**

Run: `cd /home/chris/workspace/chatsune/frontend && pnpm tsc --noEmit`

Expected: No errors.

- [ ] **Step 3: Run full build**

Run: `cd /home/chris/workspace/chatsune/frontend && pnpm run build`

Expected: Build succeeds with no errors.

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "Wire knowledge WS events to frontend stores"
```

---

## Task 14: Persona & Session Assignment Endpoints (Backend)

**Files:**
- Modify: `backend/modules/persona/_handlers.py`
- Modify: `backend/modules/chat/_handlers.py` (or equivalent)

- [ ] **Step 1: Add persona knowledge endpoints**

Add to the persona router (`_handlers.py`):

```python
@router.get("/{persona_id}/knowledge")
async def get_persona_knowledge(
    persona_id: str,
    user: dict = Depends(require_active_session),
):
    repo = _repo()
    persona = await repo.find_by_id(persona_id, user["sub"])
    if not persona:
        raise HTTPException(status_code=404, detail="Persona not found")
    return {"library_ids": persona.get("knowledge_library_ids", [])}


@router.put("/{persona_id}/knowledge")
async def set_persona_knowledge(
    persona_id: str,
    body: SetKnowledgeLibrariesRequest,
    user: dict = Depends(require_active_session),
):
    repo = _repo()
    persona = await repo.find_by_id(persona_id, user["sub"])
    if not persona:
        raise HTTPException(status_code=404, detail="Persona not found")
    await repo.update(persona_id, user["sub"], {"knowledge_library_ids": body.library_ids})
    return {"status": "ok"}
```

Add import: `from shared.dtos.knowledge import SetKnowledgeLibrariesRequest`

- [ ] **Step 2: Add session knowledge endpoints**

Add to the chat session router:

```python
@router.get("/sessions/{session_id}/knowledge")
async def get_session_knowledge(
    session_id: str,
    user: dict = Depends(require_active_session),
):
    repo = _repo()
    session = await repo.get_session(session_id, user["sub"])
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"library_ids": session.get("knowledge_library_ids", [])}


@router.put("/sessions/{session_id}/knowledge")
async def set_session_knowledge(
    session_id: str,
    body: SetKnowledgeLibrariesRequest,
    user: dict = Depends(require_active_session),
):
    repo = _repo()
    session = await repo.get_session(session_id, user["sub"])
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    await repo.update_session(session_id, user["sub"], {"knowledge_library_ids": body.library_ids})
    return {"status": "ok"}
```

Add import: `from shared.dtos.knowledge import SetKnowledgeLibrariesRequest`

**Note:** Adapt the exact repository method names to match the existing persona and chat module patterns. Check `_repository.py` in each module for the correct method names (`find_by_id`, `update`, `get_session`, `update_session`, etc.).

- [ ] **Step 3: Verify syntax**

Run: `uv run python -m py_compile backend/modules/persona/_handlers.py && uv run python -m py_compile backend/modules/chat/_handlers.py`

Expected: No output (success).

- [ ] **Step 4: Commit**

```bash
git add backend/modules/persona/_handlers.py backend/modules/chat/_handlers.py
git commit -m "Add persona and session knowledge assignment endpoints"
```

---

## Task 15: MongoDB Vector Search Index & Final Verification

**Files:**
- None (infrastructure setup)

- [ ] **Step 1: Create MongoDB Vector Search index**

The Vector Search index must be created via `mongosh` or MongoDB Atlas CLI. Create a script or document the command:

```javascript
// Run in mongosh connected to the Chatsune database
db.knowledge_chunks.createSearchIndex(
  "knowledge_vector_index",
  "vectorSearch",
  {
    fields: [
      {
        type: "vector",
        path: "vector",
        numDimensions: 768,
        similarity: "cosine"
      },
      {
        type: "filter",
        path: "user_id"
      },
      {
        type: "filter",
        path: "library_id"
      }
    ]
  }
)
```

**Note:** If using Docker Compose with MongoDB RS0 (single-node replica set), vector search indexes require MongoDB 7.0+ with Atlas Search. For local development, you may need `mongod` started with `--setParameter` flags or use `mongot`. Check the existing Docker Compose setup and adapt accordingly. If vector search is not available locally, add a fallback text search in `_retrieval.py` for development.

- [ ] **Step 2: End-to-end verification**

1. Start the backend: `uv run python -m backend.main`
2. Start the frontend: `cd frontend && pnpm dev`
3. Log in, open User Modal → Knowledge tab
4. Create a library, add a document, verify embedding status updates
5. Assign library to a persona in Persona Overlay → Knowledge tab
6. Start a chat, verify 🎓 dropdown shows in topbar
7. Ask a question that should trigger knowledge search
8. Verify lila pills appear with retrieved chunks

- [ ] **Step 3: Final commit**

```bash
git add -A
git commit -m "Add MongoDB vector search index setup and complete knowledge base integration"
```

---

## Dependency Graph

```
Task 1 (Shared Contracts) ──┬──> Task 2 (Chunker + TDD)
                             ├──> Task 3 (Repository)
                             └──> Task 7 (Frontend Types + API)
                                    │
Task 3 (Repository) ────────┬──> Task 4 (Handlers)
                             └──> Task 5 (Retrieval + Tool)
                                    │
Task 4 + 5 ──────────────────┬──> Task 6 (Module API + Integration)
                             └──> Task 14 (Assignment Endpoints)
                                    │
Task 7 (Frontend Types) ────┬──> Task 8 (Knowledge Store)
                             │       │
                             │       ├──> Task 9 (User Modal Tab)
                             │       ├──> Task 10 (Persona Tab)
                             │       ├──> Task 11 (Topbar Dropdown)
                             │       └──> Task 12 (Knowledge Pills)
                             │               │
                             └───────────> Task 13 (WS Events)
                                              │
All Tasks ───────────────────────────────> Task 15 (Vector Index + E2E)
```
