from shared.dtos.knowledge import (
    KnowledgeDocumentDetailDto,
    KnowledgeDocumentDto,
    KnowledgeLibraryDto,
)


def test_document_dto_defaults_pti_fields():
    """Existing documents (no PTI fields in DB) deserialise cleanly."""
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
