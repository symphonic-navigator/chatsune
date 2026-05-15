"""Verify ChatSessionDocument deserialises pre-feature documents (no
compaction_checkpoints field) without error and defaults to an empty list."""

from datetime import datetime, timezone

from backend.modules.chat._models import ChatSessionDocument


def test_legacy_session_deserialises_with_empty_checkpoints():
    doc = {
        "_id": "session-abc",
        "user_id": "u1",
        "persona_id": "p1",
        "state": "idle",
        "pinned": False,
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
    }
    session = ChatSessionDocument.model_validate(doc)
    assert session.compaction_checkpoints == []


def test_session_with_one_checkpoint_round_trips():
    cp = {
        "id": "cp-1",
        "created_at": datetime.now(timezone.utc),
        "model_unique_id": "ollama:llama3.2",
        "summary_markdown": "## Topic & Goal\nx\n",
        "last_message_id_before": "m-9",
        "tail_start_message_id": "m-10",
        "tokens_before": 100,
        "tokens_after": 20,
        "tail_token_count": 80,
        "prev_checkpoint_id": None,
    }
    doc = {
        "_id": "session-abc",
        "user_id": "u1",
        "persona_id": "p1",
        "state": "idle",
        "pinned": False,
        "compaction_checkpoints": [cp],
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
    }
    session = ChatSessionDocument.model_validate(doc)
    assert len(session.compaction_checkpoints) == 1
    assert session.compaction_checkpoints[0].id == "cp-1"
