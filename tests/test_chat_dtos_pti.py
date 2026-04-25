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
