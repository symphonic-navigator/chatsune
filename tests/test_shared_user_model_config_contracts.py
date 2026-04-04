from shared.dtos.llm import UserModelConfigDto, SetUserModelConfigDto
from shared.events.llm import LlmUserModelConfigUpdatedEvent
from shared.topics import Topics


def test_user_model_config_dto():
    dto = UserModelConfigDto(
        model_unique_id="ollama_cloud:llama3.2",
        is_favourite=True,
        is_hidden=False,
        notes="Great for coding",
        system_prompt_addition="Focus on the last message.",
    )
    assert dto.model_unique_id == "ollama_cloud:llama3.2"
    assert dto.is_favourite is True
    assert dto.system_prompt_addition == "Focus on the last message."


def test_user_model_config_dto_defaults():
    dto = UserModelConfigDto(model_unique_id="ollama_cloud:llama3.2")
    assert dto.is_favourite is False
    assert dto.is_hidden is False
    assert dto.notes is None
    assert dto.system_prompt_addition is None


def test_set_user_model_config_dto_all_optional():
    dto = SetUserModelConfigDto()
    assert dto.is_favourite is None
    assert dto.is_hidden is None
    assert dto.notes is None
    assert dto.system_prompt_addition is None


def test_set_user_model_config_dto_partial():
    dto = SetUserModelConfigDto(is_favourite=True)
    assert dto.is_favourite is True
    assert dto.is_hidden is None


def test_user_model_config_updated_event():
    from datetime import datetime, timezone
    config = UserModelConfigDto(model_unique_id="ollama_cloud:llama3.2")
    now = datetime.now(timezone.utc)
    event = LlmUserModelConfigUpdatedEvent(
        model_unique_id="ollama_cloud:llama3.2",
        config=config,
        timestamp=now,
    )
    assert event.type == "llm.user_model_config.updated"
    assert event.config.is_favourite is False
    assert event.timestamp == now


def test_topic_constant():
    assert Topics.LLM_USER_MODEL_CONFIG_UPDATED == "llm.user_model_config.updated"


def test_user_model_config_dto_with_new_fields():
    dto = UserModelConfigDto(
        model_unique_id="ollama_cloud:llama3.2",
        custom_display_name="My Llama",
        custom_context_window=128_000,
    )
    assert dto.custom_display_name == "My Llama"
    assert dto.custom_context_window == 128_000


def test_user_model_config_dto_new_fields_default_none():
    dto = UserModelConfigDto(model_unique_id="ollama_cloud:llama3.2")
    assert dto.custom_display_name is None
    assert dto.custom_context_window is None


def test_set_user_model_config_dto_new_fields():
    dto = SetUserModelConfigDto(
        custom_display_name="My Llama",
        custom_context_window=128_000,
    )
    assert dto.custom_display_name == "My Llama"
    assert dto.custom_context_window == 128_000


def test_set_user_model_config_dto_new_fields_default_none():
    dto = SetUserModelConfigDto()
    assert dto.custom_display_name is None
    assert dto.custom_context_window is None
