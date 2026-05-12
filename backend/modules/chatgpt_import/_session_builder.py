"""Map a ``ParsedConversation`` to ``CreateImportedSessionRequest``.

Pure conversion — no IO. The job handler calls this just before passing the
result into ``ChatService.create_imported_session``.
"""
from backend.modules.chatgpt_import._models import ParsedConversation
from shared.dtos.chat import (
    CreateImportedSessionRequest,
    ImportedMessageInput,
)


def build_imported_session_request(
    *, parsed: ParsedConversation, persona_id: str
) -> CreateImportedSessionRequest:
    """Build the args for ``create_imported_session``.

    Resolves ``imported_model_slug`` from the conversation's
    ``default_model_slug`` first, then falls back to the first assistant
    message's per-message ``model_slug``. Falls through to ``None`` when
    neither is set — the resulting session simply records no original
    model slug and otherwise behaves like any native session, with the
    persona's default model handling follow-up sends.
    """
    model_slug = parsed.default_model_slug
    if model_slug is None:
        for m in parsed.messages:
            if m.role == "assistant" and m.imported_model_slug:
                model_slug = m.imported_model_slug
                break

    messages = [
        ImportedMessageInput(
            role=m.role,  # type: ignore[arg-type]
            content=m.content,
            created_at=m.created_at,
            imported_model_slug=m.imported_model_slug,
        )
        for m in parsed.messages
        if m.role in ("user", "assistant")
    ]
    return CreateImportedSessionRequest(
        persona_id=persona_id,
        title=parsed.title or "Imported conversation",
        messages=messages,
        imported_from="chatgpt",
        imported_model_slug=model_slug,
        original_created_at=parsed.create_time,
    )
