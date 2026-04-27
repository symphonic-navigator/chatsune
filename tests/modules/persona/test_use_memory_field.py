from datetime import UTC, datetime

from backend.modules.persona._models import PersonaDocument
from shared.dtos.persona import CreatePersonaDto, PersonaDto, UpdatePersonaDto


def _persona_doc_payload(**overrides) -> dict:
    base = {
        "_id": "p-1",
        "user_id": "u-1",
        "name": "Aria",
        "tagline": "Your helpful companion",
        "model_unique_id": "ollama_cloud:llama3.2",
        "system_prompt": "You are helpful.",
        "temperature": 0.8,
        "reasoning_enabled": False,
        "nsfw": False,
        "colour_scheme": "solar",
        "display_order": 0,
        "monogram": "AR",
        "pinned": False,
        "profile_image": None,
        "created_at": datetime.now(UTC),
        "updated_at": datetime.now(UTC),
    }
    base.update(overrides)
    return base


def test_persona_document_defaults_use_memory_to_true():
    doc = PersonaDocument(**_persona_doc_payload())
    assert doc.use_memory is True


def test_persona_document_round_trips_use_memory_false():
    doc = PersonaDocument(**_persona_doc_payload(use_memory=False))
    assert doc.use_memory is False


def test_persona_dto_defaults_use_memory_to_true():
    dto = PersonaDto(
        id="p-1",
        user_id="u-1",
        name="Aria",
        tagline="Your helpful companion",
        system_prompt="You are helpful.",
        temperature=0.8,
        reasoning_enabled=False,
        nsfw=False,
        colour_scheme="solar",
        display_order=0,
        monogram="AR",
        pinned=False,
        profile_image=None,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    assert dto.use_memory is True


def test_create_persona_dto_defaults_use_memory_to_true():
    dto = CreatePersonaDto(
        name="Aria",
        tagline="t",
        model_unique_id="ollama_cloud:llama3.2",
        system_prompt="p",
    )
    assert dto.use_memory is True


def test_create_persona_dto_accepts_use_memory_false():
    dto = CreatePersonaDto(
        name="Aria",
        tagline="t",
        model_unique_id="ollama_cloud:llama3.2",
        system_prompt="p",
        use_memory=False,
    )
    assert dto.use_memory is False


def test_update_persona_dto_use_memory_optional_default_none():
    dto = UpdatePersonaDto()
    assert dto.use_memory is None
    assert "use_memory" not in dto.model_dump(exclude_none=True)


def test_update_persona_dto_use_memory_round_trips_explicit_false():
    dto = UpdatePersonaDto(use_memory=False)
    assert dto.use_memory is False
    assert dto.model_dump(exclude_none=True)["use_memory"] is False


from backend.modules.persona._repository import PersonaRepository


def _doc_with_memory_flag(value: bool | None) -> dict:
    base = _persona_doc_payload()
    if value is None:
        # legacy document — field absent entirely
        base.pop("use_memory", None)
    else:
        base["use_memory"] = value
    return base


def test_to_dto_defaults_missing_use_memory_to_true():
    dto = PersonaRepository.to_dto(_doc_with_memory_flag(None))
    assert dto.use_memory is True


def test_to_dto_preserves_explicit_false_use_memory():
    dto = PersonaRepository.to_dto(_doc_with_memory_flag(False))
    assert dto.use_memory is False


def test_to_dto_preserves_explicit_true_use_memory():
    dto = PersonaRepository.to_dto(_doc_with_memory_flag(True))
    assert dto.use_memory is True
