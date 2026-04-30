import pytest

from backend.modules.chat._soft_cot import SOFT_COT_MARKER
from backend.modules.chat._prompt_assembler import assemble


def _async_return(value):
    async def _f(*args, **kwargs):
        return value
    return _f


async def _stub_prompt_layers(monkeypatch, persona_doc):
    """Make all optional prompt layers return None except the persona layer."""
    monkeypatch.setattr(
        "backend.modules.chat._prompt_assembler._get_admin_prompt",
        _async_return(None),
    )
    monkeypatch.setattr(
        "backend.modules.chat._prompt_assembler._get_model_instructions",
        _async_return(None),
    )
    monkeypatch.setattr(
        "backend.modules.chat._prompt_assembler._get_user_about_me",
        _async_return(None),
    )
    monkeypatch.setattr(
        "backend.modules.chat._prompt_assembler._get_persona_prompt",
        _async_return(persona_doc.get("system_prompt")),
    )
    monkeypatch.setattr(
        "backend.modules.chat._prompt_assembler._get_persona_doc",
        _async_return(persona_doc),
    )
    # get_memory_context lives in backend.modules.memory — stub via import path
    import backend.modules.memory as memory_module
    monkeypatch.setattr(memory_module, "get_memory_context", _async_return(None))
    # get_enabled_integration_ids is invoked unconditionally; stub to keep
    # the assembler off the integrations DB path in this isolation test.
    import backend.modules.integrations as integrations_module
    monkeypatch.setattr(
        integrations_module, "get_enabled_integration_ids", _async_return([]),
    )


@pytest.mark.asyncio
async def test_block_appended_when_non_reasoning_model_with_soft_cot_on(monkeypatch):
    await _stub_prompt_layers(
        monkeypatch,
        {"system_prompt": "you are a helpful assistant", "soft_cot_enabled": True},
    )
    result = await assemble(
        user_id="u1",
        persona_id="p1",
        model_unique_id="provider:slug",
        supports_reasoning=False,
        reasoning_enabled_for_call=False,
    )
    assert SOFT_COT_MARKER in result


@pytest.mark.asyncio
async def test_block_not_appended_when_hard_cot_active(monkeypatch):
    await _stub_prompt_layers(
        monkeypatch,
        {"system_prompt": "you are a helpful assistant", "soft_cot_enabled": True},
    )
    result = await assemble(
        user_id="u1",
        persona_id="p1",
        model_unique_id="provider:slug",
        supports_reasoning=True,
        reasoning_enabled_for_call=True,
    )
    assert SOFT_COT_MARKER not in result


@pytest.mark.asyncio
async def test_block_appended_when_reasoning_capable_but_hard_cot_off(monkeypatch):
    await _stub_prompt_layers(
        monkeypatch,
        {"system_prompt": "you are a helpful assistant", "soft_cot_enabled": True},
    )
    result = await assemble(
        user_id="u1",
        persona_id="p1",
        model_unique_id="provider:slug",
        supports_reasoning=True,
        reasoning_enabled_for_call=False,
    )
    assert SOFT_COT_MARKER in result


@pytest.mark.asyncio
async def test_block_not_appended_when_soft_cot_off(monkeypatch):
    await _stub_prompt_layers(
        monkeypatch,
        {"system_prompt": "you are a helpful assistant", "soft_cot_enabled": False},
    )
    result = await assemble(
        user_id="u1",
        persona_id="p1",
        model_unique_id="provider:slug",
        supports_reasoning=False,
        reasoning_enabled_for_call=False,
    )
    assert SOFT_COT_MARKER not in result
