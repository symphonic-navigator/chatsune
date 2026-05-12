"""Session-builder tests for chatgpt_import."""
from datetime import UTC, datetime

from backend.modules.chatgpt_import._models import ParsedConversation, ParsedMessage
from backend.modules.chatgpt_import._session_builder import (
    build_imported_session_request,
)


def test_builds_request_with_correct_fields():
    parsed = ParsedConversation(
        chatgpt_conversation_id="conv-1",
        title="Test conv",
        create_time=datetime(2024, 7, 2, 12, 0, tzinfo=UTC),
        update_time=datetime(2024, 7, 2, 12, 5, tzinfo=UTC),
        default_model_slug="gpt-4o",
        messages=[
            ParsedMessage(
                role="user",
                content="hi",
                created_at=datetime(2024, 7, 2, 12, 1, tzinfo=UTC),
            ),
            ParsedMessage(
                role="assistant",
                content="hello",
                created_at=datetime(2024, 7, 2, 12, 2, tzinfo=UTC),
                imported_model_slug="gpt-4o",
            ),
        ],
        first_user_message_preview="hi",
        first_assistant_message_preview="hello",
    )

    req = build_imported_session_request(parsed=parsed, persona_id="p1")

    assert req.persona_id == "p1"
    assert req.title == "Test conv"
    assert req.imported_from == "chatgpt"
    assert req.imported_model_slug == "gpt-4o"
    assert req.original_created_at == datetime(2024, 7, 2, 12, 0, tzinfo=UTC)
    assert len(req.messages) == 2
    assert req.messages[0].role == "user"
    assert req.messages[1].imported_model_slug == "gpt-4o"


def test_imported_model_slug_falls_back_to_first_assistant_message():
    parsed = ParsedConversation(
        chatgpt_conversation_id="conv-1",
        title="Test",
        create_time=datetime(2024, 1, 1, tzinfo=UTC),
        update_time=datetime(2024, 1, 1, tzinfo=UTC),
        default_model_slug=None,
        messages=[
            ParsedMessage(
                role="user",
                content="x",
                created_at=datetime(2024, 1, 1, tzinfo=UTC),
            ),
            ParsedMessage(
                role="assistant",
                content="y",
                created_at=datetime(2024, 1, 1, tzinfo=UTC),
                imported_model_slug="gpt-4",
            ),
        ],
        first_user_message_preview="x",
        first_assistant_message_preview="y",
    )
    req = build_imported_session_request(parsed=parsed, persona_id="p1")
    assert req.imported_model_slug == "gpt-4"


def test_no_model_information_anywhere_yields_none():
    parsed = ParsedConversation(
        chatgpt_conversation_id="c",
        title="t",
        create_time=datetime(2024, 1, 1, tzinfo=UTC),
        update_time=datetime(2024, 1, 1, tzinfo=UTC),
        default_model_slug=None,
        messages=[
            ParsedMessage(
                role="user",
                content="x",
                created_at=datetime(2024, 1, 1, tzinfo=UTC),
            ),
        ],
        first_user_message_preview="x",
        first_assistant_message_preview="",
    )
    req = build_imported_session_request(parsed=parsed, persona_id="p1")
    assert req.imported_model_slug is None


def test_default_title_when_missing():
    parsed = ParsedConversation(
        chatgpt_conversation_id="c",
        title="",
        create_time=datetime(2024, 1, 1, tzinfo=UTC),
        update_time=datetime(2024, 1, 1, tzinfo=UTC),
        default_model_slug=None,
        messages=[
            ParsedMessage(
                role="user", content="x",
                created_at=datetime(2024, 1, 1, tzinfo=UTC),
            ),
        ],
        first_user_message_preview="x",
        first_assistant_message_preview="",
    )
    req = build_imported_session_request(parsed=parsed, persona_id="p1")
    assert req.title == "Imported conversation"
