"""Pure-Pydantic tests for ChatSessionDocument.extras — no live DB."""
from datetime import UTC, datetime

from backend.modules.chat._models import ChatSessionDocument
from shared.dtos.chat import ChatSessionExtras


def _doc(**overrides):
    """Build a ChatSessionDocument with the required fields. The required
    set is taken from backend/modules/chat/_models.py: ``_id``, ``user_id``,
    ``persona_id``, ``created_at``, ``updated_at``. State/pinned/project_id
    have defaults."""
    now = datetime.now(UTC)
    base = dict(
        _id="sess-1",
        user_id="user-1",
        persona_id="persona-1",
        created_at=now,
        updated_at=now,
    )
    base.update(overrides)
    return ChatSessionDocument(**base)


def test_chat_session_document_extras_default_none():
    """Default None means 'compute from model capability on first read'."""
    doc = _doc()
    assert doc.extras is None


def test_chat_session_document_extras_round_trips():
    extras = ChatSessionExtras(
        tools_enabled=True, reasoning_mode="on", reasoning_effort="medium",
    )
    doc = _doc(extras=extras)
    payload = doc.model_dump()
    assert payload["extras"]["reasoning_mode"] == "on"
    assert payload["extras"]["tools_enabled"] is True
    assert payload["extras"]["reasoning_effort"] == "medium"
