"""Unit tests for ``backend.modules.chatgpt_import._session_builder``.

The builder is a pure conversion from ``ParsedConversation`` to
``CreateImportedSessionRequest``. These tests pin the exact resolution
rules for ``imported_model_slug`` and guard against the removed
``imported:`` pseudo-id concept re-appearing in the request.
"""
from __future__ import annotations

from datetime import UTC, datetime

import pytest

from backend.modules.chatgpt_import._models import ParsedConversation, ParsedMessage
from backend.modules.chatgpt_import._session_builder import build_imported_session_request


def _parsed(
    *,
    messages: list[ParsedMessage] | None = None,
    default_model_slug: str | None = None,
    title: str = "T",
    conv_id: str = "conv-1",
) -> ParsedConversation:
    create_time = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
    update_time = datetime(2026, 1, 1, 12, 5, 0, tzinfo=UTC)
    return ParsedConversation(
        chatgpt_conversation_id=conv_id,
        title=title,
        create_time=create_time,
        update_time=update_time,
        default_model_slug=default_model_slug,
        messages=messages or [],
        first_user_message_preview="",
        first_assistant_message_preview="",
    )


def _msg(role: str, content: str, slug: str | None = None) -> ParsedMessage:
    return ParsedMessage(
        role=role,
        content=content,
        created_at=datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC),
        imported_model_slug=slug,
    )


def test_happy_path_builds_request_with_preserved_order_and_metadata():
    parsed = _parsed(
        messages=[
            _msg("user", "hello"),
            _msg("assistant", "hi", slug="gpt-4o"),
            _msg("user", "again"),
            _msg("assistant", "ok", slug="gpt-4o"),
        ],
        default_model_slug="gpt-4o",
        title="My chat",
    )
    req = build_imported_session_request(parsed=parsed, persona_id="persona-xyz")

    assert req.persona_id == "persona-xyz"
    assert req.title == "My chat"
    assert req.imported_from == "chatgpt"
    assert req.imported_model_slug == "gpt-4o"
    assert req.original_created_at == parsed.create_time
    assert [m.role for m in req.messages] == ["user", "assistant", "user", "assistant"]
    assert [m.content for m in req.messages] == ["hello", "hi", "again", "ok"]
    # Per-message slug carried through.
    assert req.messages[1].imported_model_slug == "gpt-4o"
    assert req.messages[0].imported_model_slug is None


def test_imported_model_slug_prefers_conversation_default_over_message_slug():
    """Spec: when ``default_model_slug`` is set on the conversation, it wins
    over any per-message ``imported_model_slug`` — even when a later assistant
    message ran on a different model."""
    parsed = _parsed(
        messages=[
            _msg("user", "hi"),
            _msg("assistant", "first", slug="gpt-4o-mini"),
            _msg("assistant", "second", slug="o1-preview"),
        ],
        default_model_slug="gpt-4o",
    )
    req = build_imported_session_request(parsed=parsed, persona_id="p1")
    assert req.imported_model_slug == "gpt-4o"


def test_imported_model_slug_falls_back_to_first_assistant_with_slug():
    """Spec: when ``default_model_slug`` is ``None``, the builder picks the
    FIRST assistant message that carries an ``imported_model_slug`` (not the
    last). This test pins that order so any future change is intentional."""
    parsed = _parsed(
        messages=[
            _msg("user", "hi"),
            _msg("assistant", "first", slug="gpt-4o-mini"),
            _msg("assistant", "second", slug="o1-preview"),
        ],
        default_model_slug=None,
    )
    req = build_imported_session_request(parsed=parsed, persona_id="p1")
    assert req.imported_model_slug == "gpt-4o-mini"


def test_imported_model_slug_skips_assistant_messages_without_slug():
    parsed = _parsed(
        messages=[
            _msg("user", "hi"),
            _msg("assistant", "first-no-slug", slug=None),
            _msg("assistant", "second", slug="o1-preview"),
        ],
        default_model_slug=None,
    )
    req = build_imported_session_request(parsed=parsed, persona_id="p1")
    assert req.imported_model_slug == "o1-preview"


def test_imported_model_slug_none_when_no_slug_anywhere():
    """Spec: the builder falls through to ``None`` (NOT ``'unknown'``) when
    neither the conversation default nor any assistant message has a slug.
    The session then records no original model slug and follow-up sends use
    the persona's default model."""
    parsed = _parsed(
        messages=[
            _msg("user", "hi"),
            _msg("assistant", "no slug"),
        ],
        default_model_slug=None,
    )
    req = build_imported_session_request(parsed=parsed, persona_id="p1")
    assert req.imported_model_slug is None


def test_empty_messages_list_is_passed_through_without_filtering():
    parsed = _parsed(messages=[], default_model_slug=None)
    req = build_imported_session_request(parsed=parsed, persona_id="p1")
    assert req.messages == []
    assert req.title == "T"


def test_empty_title_falls_back_to_imported_conversation_label():
    """Spec: an empty title is replaced with ``'Imported conversation'`` so
    the row UI always has something to render."""
    parsed = _parsed(messages=[_msg("user", "hi")], title="")
    req = build_imported_session_request(parsed=parsed, persona_id="p1")
    assert req.title == "Imported conversation"


def test_does_not_emit_pseudo_model_unique_id():
    """Regression: the removed ``imported:<slug>`` pseudo-model-id concept
    must not appear anywhere in the produced request — neither as a field
    on the request itself nor as part of any string field."""
    parsed = _parsed(
        messages=[
            _msg("user", "hi"),
            _msg("assistant", "ok", slug="gpt-4o"),
        ],
        default_model_slug="gpt-4o",
    )
    req = build_imported_session_request(parsed=parsed, persona_id="p1")

    # No field named anything like ``model_unique_id``.
    assert not hasattr(req, "model_unique_id")
    # No imported: prefix in any of the slug-bearing fields.
    assert not (req.imported_model_slug or "").startswith("imported:")
    for m in req.messages:
        assert not (m.imported_model_slug or "").startswith("imported:")


def test_persona_id_is_forwarded_verbatim():
    parsed = _parsed(messages=[_msg("user", "hi")])
    req = build_imported_session_request(parsed=parsed, persona_id="some-uuid-here")
    assert req.persona_id == "some-uuid-here"


def test_original_created_at_is_parsed_create_time():
    parsed = _parsed(messages=[_msg("user", "hi")])
    req = build_imported_session_request(parsed=parsed, persona_id="p1")
    assert req.original_created_at == parsed.create_time


def test_messages_keep_only_user_and_assistant_roles():
    """Spec: the builder's list-comprehension filters on
    ``role in ('user', 'assistant')``. If a stray role somehow slips in
    (defensive against parser bugs), it is dropped silently. We pin that
    behaviour by passing an unexpected role and asserting it is removed."""
    rogue = ParsedMessage.model_construct(
        role="system",
        content="should be dropped",
        created_at=datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC),
        imported_model_slug=None,
    )
    parsed = _parsed(
        messages=[
            _msg("user", "hi"),
            rogue,
            _msg("assistant", "ok"),
        ],
    )
    req = build_imported_session_request(parsed=parsed, persona_id="p1")
    assert [m.role for m in req.messages] == ["user", "assistant"]
    assert all(m.content != "should be dropped" for m in req.messages)
