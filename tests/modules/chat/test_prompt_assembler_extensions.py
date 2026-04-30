"""Tests for the integration prompt-extensions layer in ``assemble``.

The refactor decouples non-tool extensions from ``tools_enabled``: voice and
screen-effect-style integrations have system_prompt instructions but no
``tool_definitions``, so they must remain injected even when tools are
disabled. Tool-providing integrations (e.g. lovense) stay gated.
"""

from unittest.mock import AsyncMock, patch

from backend.modules.chat._prompt_assembler import assemble
from backend.modules.integrations._models import IntegrationDefinition
from shared.dtos.inference import ToolDefinition


def _voice_defn() -> IntegrationDefinition:
    return IntegrationDefinition(
        id="voice",
        display_name="Voice",
        description="",
        icon="",
        execution_mode="frontend",
        config_fields=[],
        system_prompt_template="<voice-prompt>VOICE</voice-prompt>",
        tool_definitions=[],
    )


def _lovense_defn() -> IntegrationDefinition:
    return IntegrationDefinition(
        id="lovense",
        display_name="Lovense",
        description="",
        icon="",
        execution_mode="frontend",
        config_fields=[],
        system_prompt_template="<lovense-prompt>LOVENSE</lovense-prompt>",
        tool_definitions=[
            ToolDefinition(
                name="lovense_vibrate",
                description="",
                parameters={"type": "object", "properties": {}},
            ),
        ],
    )


async def _run_assemble(
    *,
    enabled_ids: list[str],
    defns: dict[str, IntegrationDefinition],
    tools_enabled: bool,
) -> str:
    with patch(
        "backend.modules.chat._prompt_assembler._get_admin_prompt",
        new=AsyncMock(return_value=None),
    ), patch(
        "backend.modules.chat._prompt_assembler._get_model_instructions",
        new=AsyncMock(return_value=None),
    ), patch(
        "backend.modules.chat._prompt_assembler._get_persona_prompt",
        new=AsyncMock(return_value=None),
    ), patch(
        "backend.modules.chat._prompt_assembler._get_persona_doc",
        new=AsyncMock(return_value=None),
    ), patch(
        "backend.modules.chat._prompt_assembler._get_user_about_me",
        new=AsyncMock(return_value=None),
    ), patch(
        "backend.modules.memory.get_memory_context",
        new=AsyncMock(return_value=None),
    ), patch(
        "backend.modules.integrations.get_enabled_integration_ids",
        new=AsyncMock(return_value=enabled_ids),
    ), patch(
        "backend.modules.integrations.get_integration",
        side_effect=lambda iid: defns.get(iid),
    ):
        return await assemble(
            user_id="u-1",
            persona_id="p-1",
            model_unique_id="conn:model",
            tools_enabled=tools_enabled,
        )


async def test_tools_enabled_includes_voice_and_lovense_extensions() -> None:
    defns = {"voice": _voice_defn(), "lovense": _lovense_defn()}
    prompt = await _run_assemble(
        enabled_ids=["voice", "lovense"],
        defns=defns,
        tools_enabled=True,
    )

    assert "VOICE" in prompt
    assert "LOVENSE" in prompt
    assert "no tools available" not in prompt


async def test_tools_disabled_keeps_voice_drops_lovense_and_announces_no_tools() -> None:
    defns = {"voice": _voice_defn(), "lovense": _lovense_defn()}
    prompt = await _run_assemble(
        enabled_ids=["voice", "lovense"],
        defns=defns,
        tools_enabled=False,
    )

    assert "VOICE" in prompt
    assert "LOVENSE" not in prompt
    assert "no tools available" in prompt


async def test_empty_system_prompt_templates_are_skipped() -> None:
    voice_blank = IntegrationDefinition(
        id="voice",
        display_name="Voice",
        description="",
        icon="",
        execution_mode="frontend",
        config_fields=[],
        system_prompt_template="",
        tool_definitions=[],
    )
    lovense_blank = IntegrationDefinition(
        id="lovense",
        display_name="Lovense",
        description="",
        icon="",
        execution_mode="frontend",
        config_fields=[],
        system_prompt_template="",
        tool_definitions=[
            ToolDefinition(
                name="lovense_vibrate",
                description="",
                parameters={"type": "object", "properties": {}},
            ),
        ],
    )
    defns = {"voice": voice_blank, "lovense": lovense_blank}
    prompt = await _run_assemble(
        enabled_ids=["voice", "lovense"],
        defns=defns,
        tools_enabled=True,
    )

    assert "VOICE" not in prompt
    assert "LOVENSE" not in prompt
