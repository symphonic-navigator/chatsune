import logging

from backend.modules.chat._prompt_sanitiser import sanitise

_log = logging.getLogger(__name__)


async def _get_admin_prompt() -> str | None:
    """Fetch the global system prompt from settings."""
    from backend.modules.settings import get_setting
    return await get_setting("system_prompt")


async def _get_model_instructions(user_id: str, model_unique_id: str) -> str | None:
    """Fetch the user's per-model system prompt addition."""
    from backend.modules.llm import UserModelConfigRepository
    from backend.database import get_db
    repo = UserModelConfigRepository(get_db())
    config = await repo.find(user_id, model_unique_id)
    if config is None:
        return None
    return config.get("system_prompt_addition")


async def _get_persona_prompt(persona_id: str | None, user_id: str) -> str | None:
    """Fetch the persona's system prompt."""
    if not persona_id:
        return None
    from backend.modules.persona import get_persona
    persona = await get_persona(persona_id, user_id)
    if persona is None:
        return None
    return persona.get("system_prompt")


async def _get_project_prompt(project_id: str | None, user_id: str) -> str | None:
    """Fetch the project's Custom Instructions, or None.

    Tolerant of any error — chat inference must not die because of a
    CI lookup. Errors are caught and logged; the layer is then simply
    omitted, mirroring the project-library lookup pattern in the
    orchestrator.
    """
    if not project_id:
        return None
    try:
        from backend.modules import project as project_service
        return await project_service.get_system_prompt(project_id, user_id)
    except Exception:
        _log.exception(
            "project CI lookup failed for project=%s user=%s",
            project_id, user_id,
        )
        return None


async def _get_persona_doc(persona_id: str | None, user_id: str) -> dict | None:
    """Fetch the full persona document (used for soft_cot_enabled lookup)."""
    if not persona_id:
        return None
    from backend.modules.persona import get_persona
    return await get_persona(persona_id, user_id)


async def _get_user_about_me(user_id: str) -> str | None:
    """Fetch the user's about_me text."""
    from backend.modules.user import get_user_about_me
    return await get_user_about_me(user_id)


async def assemble(
    user_id: str,
    persona_id: str | None,
    model_unique_id: str,
    *,
    project_id: str | None = None,
    supports_reasoning: bool = False,
    reasoning_enabled_for_call: bool = False,
    tools_enabled: bool = False,
) -> str:
    """Assemble the full XML system prompt for LLM consumption.

    ``project_id`` enables the project Custom Instructions layer, inserted
    between model-instructions and persona; ``None`` skips the layer entirely.
    ``supports_reasoning`` and ``reasoning_enabled_for_call`` drive the
    Soft-CoT visibility decision. ``tools_enabled`` gates only the
    prompt extensions of integrations that provide tools — those
    instructions are misleading when no tools are callable. Tool-less
    integrations (e.g. voice providers, screen effects) inject their
    extensions regardless. Defaults preserve legacy behaviour for
    callers that don't know about these layers (preview, scripts).
    """
    from backend.modules.chat._soft_cot import (
        SOFT_COT_INSTRUCTIONS,
        is_soft_cot_active,
    )

    admin_prompt = await _get_admin_prompt()
    model_instructions = await _get_model_instructions(user_id, model_unique_id)
    project_prompt = await _get_project_prompt(project_id, user_id)
    persona_prompt = await _get_persona_prompt(persona_id, user_id)
    persona_doc = await _get_persona_doc(persona_id, user_id)
    user_about_me = await _get_user_about_me(user_id)

    parts: list[str] = []

    # Layer 1: Admin — trusted, NOT sanitised
    if admin_prompt and admin_prompt.strip():
        parts.append(
            f'<systeminstructions priority="highest">\n{admin_prompt.strip()}\n</systeminstructions>'
        )

    # Layer 2: Model instructions — user-controlled, sanitised
    if model_instructions and model_instructions.strip():
        cleaned = sanitise(model_instructions.strip())
        if cleaned:
            parts.append(
                f'<modelinstructions priority="high">\n{cleaned}\n</modelinstructions>'
            )

    # Layer 3: Project Custom Instructions — user-controlled, sanitised.
    # Sits between model-instructions and persona so project-level scope
    # brackets the persona's voice. Layer is omitted entirely when no
    # project is bound to the session, or when the project has no CI.
    if project_prompt and project_prompt.strip():
        cleaned = sanitise(project_prompt.strip())
        if cleaned:
            parts.append(
                f'<projectinstructions priority="high">\n{cleaned}\n</projectinstructions>'
            )

    # Layer 4: Persona — user-controlled, sanitised
    if persona_prompt and persona_prompt.strip():
        cleaned = sanitise(persona_prompt.strip())
        if cleaned:
            parts.append(f'<you priority="normal">\n{cleaned}\n</you>')

    # Soft-CoT instruction block — sits between persona and memory so it
    # is "felt" alongside the persona voice but does not displace admin or
    # model instructions. Injected only when the persona has opted in and
    # native Hard-CoT is not taking over this inference call.
    soft_cot_enabled = bool(persona_doc and persona_doc.get("soft_cot_enabled"))
    if is_soft_cot_active(soft_cot_enabled, supports_reasoning, reasoning_enabled_for_call):
        parts.append(SOFT_COT_INSTRUCTIONS)

    # Layer: User memory (if available, and the persona opts in to injection).
    # Generation jobs continue regardless — only the prompt-time read path
    # is gated. See devdocs/specs/2026-04-27-persona-use-memory-toggle-design.md.
    use_memory = bool(persona_doc.get("use_memory", True)) if persona_doc else True
    if persona_id and use_memory:
        from backend.modules.memory import get_memory_context
        memory_xml = await get_memory_context(user_id, persona_id)
        if memory_xml:
            parts.append(memory_xml)

    # Layer: Integration prompt extensions (active integrations for this persona).
    # An extension whose integration has tools is gated on tools_enabled —
    # otherwise its instructions on how to call tools would be misleading.
    # Extensions for tool-less integrations (xai_voice, screen_effects, ...)
    # are always injected when the integration is active.
    from backend.modules.integrations import get_integration_prompt_extensions
    extensions = await get_integration_prompt_extensions(
        user_id, persona_id, tools_enabled=tools_enabled,
    )
    if extensions:
        parts.append(extensions)

    if not tools_enabled:
        # Without an explicit "no tools available" instruction, the model
        # answers "which tools do you have?" from its own training / the
        # prior assistant turns in the conversation history — where
        # previous responses may have listed tools that were once active.
        # This layer tells it plainly that nothing is callable right now.
        parts.append(
            '<toolavailability priority="high">\n'
            'You have no tools available in this conversation right now. '
            'Do not attempt to call any tool, and do not claim to have '
            'any — if asked about your tools, say they are disabled for '
            'this session.\n'
            '</toolavailability>'
        )

    # Layer 5: User about_me — user-controlled, sanitised
    if user_about_me and user_about_me.strip():
        cleaned = sanitise(user_about_me.strip())
        if cleaned:
            parts.append(
                f'<userinfo priority="low">\nWhat the user wants you to know about themselves:\n{cleaned}\n</userinfo>'
            )

    result = "\n\n".join(parts)

    if len(result) > 16000:  # ~4000 tokens rough estimate
        _log.warning(
            "Assembled system prompt is very large (%d chars) for user=%s model=%s — "
            "this may consume a significant portion of the context window",
            len(result), user_id, model_unique_id,
        )

    return result


async def assemble_preview(
    user_id: str,
    persona_id: str | None,
    model_unique_id: str,
) -> str:
    """Assemble a human-readable preview (excludes admin prompt)."""
    model_instructions = await _get_model_instructions(user_id, model_unique_id)
    persona_prompt = await _get_persona_prompt(persona_id, user_id)
    user_about_me = await _get_user_about_me(user_id)

    parts: list[str] = []

    if model_instructions and model_instructions.strip():
        cleaned = sanitise(model_instructions.strip())
        if cleaned:
            parts.append(f"--- Model Instructions ---\n{cleaned}")

    if persona_prompt and persona_prompt.strip():
        cleaned = sanitise(persona_prompt.strip())
        if cleaned:
            parts.append(f"--- Persona ---\n{cleaned}")

    if user_about_me and user_about_me.strip():
        cleaned = sanitise(user_about_me.strip())
        if cleaned:
            parts.append(f"--- About Me ---\n{cleaned}")

    return "\n\n".join(parts)
