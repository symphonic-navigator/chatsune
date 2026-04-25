import pytest

from backend.modules.knowledge._pti_index import (
    PtiIndexCache,
    TriggerIndex,
    match_phrases,
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
    cache.invalidate("nonexistent")


def test_cache_drop_session():
    cache = PtiIndexCache()
    cache.set("s1", TriggerIndex())
    cache.drop_session("s1")
    assert cache.get("s1") is None


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
    assert hits == [("d1", "andromedagalaxie", 18)]


def test_match_multi_word_phrase():
    idx = _idx(("dragon ball z", "d1"))
    hits = match_phrases("Ich liebe Dragon Ball Z einfach.", idx)
    assert len(hits) == 1
    assert hits[0][0] == "d1"
    assert hits[0][1] == "dragon ball z"


def test_match_whitespace_robust():
    idx = _idx(("dragon ball z", "d1"))
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
    assert [h[0] for h in hits] == ["d1", "d2", "d3"]


def test_match_one_phrase_multi_docs():
    idx = _idx(
        ("andromedagalaxie", "d1"),
        ("andromedagalaxie", "d2"),
    )
    hits = match_phrases("die Andromedagalaxie ist schön", idx)
    assert sorted(h[0] for h in hits) == ["d1", "d2"]
    assert all(h[1] == "andromedagalaxie" and h[2] == 4 for h in hits)
