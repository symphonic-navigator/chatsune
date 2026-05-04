"""Mindspace Phase 10 / Task 40 — POST /api/chat/sessions accepts ``project_id``.

The neutral-trigger flow (sidebar persona pin, persona overlay, modal
PersonasTab) reads the persona's ``default_project_id`` and forwards
it on session create. The endpoint must:

1. Accept the new optional ``project_id`` field.
2. Default it to ``None`` so existing clients keep working.
3. Pass it through to the repository so the new session document
   carries the field from the very first turn.

This is a pure schema-and-repo test; no DB / no auth / no event bus.
"""

from backend.modules.chat._handlers import CreateSessionRequest


def test_create_session_request_accepts_project_id():
    body = CreateSessionRequest.model_validate({
        "persona_id": "p1",
        "project_id": "proj-trek",
    })
    assert body.persona_id == "p1"
    assert body.project_id == "proj-trek"


def test_create_session_request_defaults_project_id_to_none():
    body = CreateSessionRequest.model_validate({"persona_id": "p1"})
    assert body.persona_id == "p1"
    assert body.project_id is None


def test_create_session_request_accepts_explicit_null_project_id():
    body = CreateSessionRequest.model_validate({
        "persona_id": "p1",
        "project_id": None,
    })
    assert body.project_id is None
