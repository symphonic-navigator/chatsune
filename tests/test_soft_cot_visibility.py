from backend.modules.chat._soft_cot import (
    SOFT_COT_INSTRUCTIONS,
    SOFT_COT_MARKER,
    is_soft_cot_active,
)
from shared.dtos.chat import ChatSessionExtras


def _extras(reasoning_on: bool) -> ChatSessionExtras:
    return ChatSessionExtras(
        tools_enabled=False,
        reasoning_mode="on" if reasoning_on else "off",
    )


def test_inactive_when_soft_cot_disabled():
    assert is_soft_cot_active(False, supports_reasoning=False, extras=_extras(False)) is False
    assert is_soft_cot_active(False, supports_reasoning=True, extras=_extras(False)) is False
    assert is_soft_cot_active(False, supports_reasoning=True, extras=_extras(True)) is False


def test_active_when_non_reasoning_model():
    assert is_soft_cot_active(True, supports_reasoning=False, extras=_extras(False)) is True
    # reasoning_mode is moot when the model can't reason
    assert is_soft_cot_active(True, supports_reasoning=False, extras=_extras(True)) is True


def test_inactive_when_hard_cot_takes_over():
    assert is_soft_cot_active(True, supports_reasoning=True, extras=_extras(True)) is False


def test_active_when_reasoning_capable_but_hard_cot_off():
    assert is_soft_cot_active(True, supports_reasoning=True, extras=_extras(False)) is True


def test_marker_is_present_in_block():
    assert SOFT_COT_MARKER in SOFT_COT_INSTRUCTIONS
