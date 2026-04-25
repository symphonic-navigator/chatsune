"""Unit tests for PTI cooldown / cap logic."""
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
        candidates=[], pti_last_inject={}, user_msg_index=10,
        token_cap=8000, doc_cap=10,
    )
    assert items == []
    assert overflow is None


def test_single_hit_passes_through():
    cand = _doc("d1", "Andromeda", "andromedagalaxie", position=5)
    items, overflow = apply_cooldown_and_caps(
        candidates=[cand], pti_last_inject={}, user_msg_index=10,
        token_cap=8000, doc_cap=10,
    )
    assert len(items) == 1
    assert items[0].document_title == "Andromeda"
    assert items[0].triggered_by == "andromedagalaxie"
    assert items[0].source == "trigger"
    assert overflow is None


def test_duplicate_doc_id_only_injected_once():
    c1 = _doc("d1", "T", "phrase-a", position=5)
    c2 = _doc("d1", "T", "phrase-b", position=15)
    items, _ = apply_cooldown_and_caps(
        candidates=[c1, c2], pti_last_inject={}, user_msg_index=10,
        token_cap=8000, doc_cap=10,
    )
    assert len(items) == 1
    assert items[0].triggered_by == "phrase-a"


def test_cooldown_blocks_within_window():
    cand = _doc("d1", "T", "p", position=0)
    items, overflow = apply_cooldown_and_caps(
        candidates=[cand], pti_last_inject={"d1": 5}, user_msg_index=10,
        token_cap=8000, doc_cap=10,
    )
    assert items == []
    assert overflow is None


def test_cooldown_passes_after_window():
    cand = _doc("d1", "T", "p", position=0)
    items, _ = apply_cooldown_and_caps(
        candidates=[cand], pti_last_inject={"d1": 5}, user_msg_index=12,
        token_cap=8000, doc_cap=10,
    )
    assert len(items) == 1


def test_cooldown_uses_document_refresh_override():
    cand = _doc("d1", "T", "p", position=0, refresh="often")
    items, _ = apply_cooldown_and_caps(
        candidates=[cand], pti_last_inject={"d1": 10}, user_msg_index=14,
        token_cap=8000, doc_cap=10,
    )
    assert items == []


def test_cooldown_uses_library_default_when_doc_refresh_none():
    cand = _doc("d1", "T", "p", position=0, refresh=None, library_default="rarely")
    items, _ = apply_cooldown_and_caps(
        candidates=[cand], pti_last_inject={"d1": 0}, user_msg_index=8,
        token_cap=8000, doc_cap=10,
    )
    assert items == []


def test_doc_cap_enforced_with_overflow():
    candidates = [
        _doc(f"d{i}", f"Title{i}", f"phrase{i}", position=i, token_count=100)
        for i in range(15)
    ]
    items, overflow = apply_cooldown_and_caps(
        candidates=candidates, pti_last_inject={}, user_msg_index=0,
        token_cap=10_000, doc_cap=10,
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
        candidates=candidates, pti_last_inject={}, user_msg_index=0,
        token_cap=8000, doc_cap=10,
    )
    assert len(items) == 2
    assert overflow is not None
    assert overflow.dropped_count == 3


def test_caps_count_only_emitted_documents():
    cooldown = {f"cool{i}": 0 for i in range(5)}
    candidates = [
        _doc(f"cool{i}", f"C{i}", "p", position=i, token_count=100)
        for i in range(5)
    ] + [
        _doc(f"hot{i}", f"H{i}", "p", position=i + 100, token_count=100)
        for i in range(12)
    ]
    items, overflow = apply_cooldown_and_caps(
        candidates=candidates, pti_last_inject=cooldown, user_msg_index=1,
        token_cap=10_000, doc_cap=10,
    )
    assert len(items) == 10
    assert all(i.document_title.startswith("H") for i in items)
    assert overflow is not None
    assert overflow.dropped_count == 2
