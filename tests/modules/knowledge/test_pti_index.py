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
    cache.invalidate("nonexistent")


def test_cache_drop_session():
    cache = PtiIndexCache()
    cache.set("s1", TriggerIndex())
    cache.drop_session("s1")
    assert cache.get("s1") is None
