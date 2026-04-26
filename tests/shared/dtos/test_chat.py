"""Tests for shared/dtos/chat.py — backwards-compat and new fields."""

from datetime import datetime

import pytest

from shared.dtos.chat import ChatMessageDto, ToolCallRefDto
from shared.dtos.images import ImageRefDto


# ---------------------------------------------------------------------------
# ToolCallRefDto — moderated_count
# ---------------------------------------------------------------------------

def test_tool_call_ref_dto_moderated_count_defaults_to_zero():
    dto = ToolCallRefDto(
        tool_call_id="tc_1",
        tool_name="web_search",
        arguments={"query": "hello"},
        success=True,
    )
    assert dto.moderated_count == 0


def test_tool_call_ref_dto_moderated_count_accepts_integer():
    dto = ToolCallRefDto(
        tool_call_id="tc_2",
        tool_name="imagine",
        arguments={"prompt": "a cat"},
        success=True,
        moderated_count=3,
    )
    assert dto.moderated_count == 3


# ---------------------------------------------------------------------------
# ChatMessageDto — image_refs
# ---------------------------------------------------------------------------

_MINIMAL_MSG = dict(
    id="msg_1",
    session_id="sess_1",
    role="assistant",
    content="Here you go.",
    token_count=10,
    created_at=datetime(2026, 4, 26, 12, 0, 0),
)


def test_chat_message_dto_image_refs_defaults_to_none():
    dto = ChatMessageDto(**_MINIMAL_MSG)
    assert dto.image_refs is None


def test_chat_message_dto_image_refs_accepts_list():
    ref = ImageRefDto(
        id="img_a",
        blob_url="/api/images/img_a/blob",
        thumb_url="/api/images/img_a/thumb",
        width=1024,
        height=1024,
        prompt="a dog",
        model_id="grok-imagine",
        tool_call_id="tc_1",
    )
    dto = ChatMessageDto(**_MINIMAL_MSG, image_refs=[ref])
    assert dto.image_refs is not None
    assert len(dto.image_refs) == 1
    assert dto.image_refs[0].id == "img_a"


# ---------------------------------------------------------------------------
# Backwards compatibility — existing documents (no image_refs, no
# moderated_count) must deserialise without error and show correct defaults.
# ---------------------------------------------------------------------------

def test_existing_assistant_message_document_deserialises_unchanged():
    """Simulates a MongoDB document written before this change."""
    raw = {
        "id": "msg_old",
        "session_id": "sess_old",
        "role": "assistant",
        "content": "Old message content.",
        "token_count": 42,
        "created_at": datetime(2025, 1, 1, 0, 0, 0),
        "tool_calls": [
            {
                "tool_call_id": "tc_old",
                "tool_name": "web_search",
                "arguments": {"query": "test"},
                "success": True,
                # moderated_count is absent — must default to 0
            }
        ],
        # image_refs is absent — must default to None
    }
    dto = ChatMessageDto.model_validate(raw)
    assert dto.image_refs is None
    assert dto.tool_calls is not None
    assert dto.tool_calls[0].moderated_count == 0
