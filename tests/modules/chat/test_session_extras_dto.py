import pytest
from pydantic import ValidationError
from shared.dtos.chat import ChatSessionExtras


def test_chat_session_extras_requires_all_three_fields():
    extras = ChatSessionExtras(
        tools_enabled=True, reasoning_mode="off", reasoning_effort=None
    )
    assert extras.tools_enabled is True
    assert extras.reasoning_mode == "off"
    assert extras.reasoning_effort is None


def test_chat_session_extras_rejects_invalid_mode():
    with pytest.raises(ValidationError):
        ChatSessionExtras(
            tools_enabled=True, reasoning_mode="maybe", reasoning_effort=None
        )


def test_chat_session_extras_effort_can_be_set():
    extras = ChatSessionExtras(
        tools_enabled=False, reasoning_mode="on", reasoning_effort="medium"
    )
    assert extras.reasoning_effort == "medium"
