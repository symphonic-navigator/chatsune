"""Unit tests for the ChatGPT-import parser.

These tests cover only the pure logic of ``backend.modules.chatgpt_import._parser``
— no DB, no Redis, no event bus, no LLM. The parser is deliberately written
as a pure transformation over the export-tree shape so it can be exercised
exhaustively without any infrastructure.

Two regressions are explicitly pinned here:

* ``test_iter_conversations_decodes_floats_as_python_float`` — guards
  against ``ijson`` returning ``decimal.Decimal`` for JSON numbers, which
  PyMongo cannot BSON-encode (the export dict is persisted verbatim as
  ``raw_data``).
* ``test_parse_conversation_does_not_emit_pseudo_model_id`` — guards
  against the removed ``imported:<slug>`` pseudo-id concept ever
  re-appearing on parsed messages.
"""
from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest

from backend.modules.chatgpt_import._parser import (
    is_message_keepable,
    iter_conversations_from_file,
    linearise,
    parse_conversation,
)


# ---------------------------------------------------------------------------
# Tiny builders for export-shape dicts. Kept inline so each test makes the
# fixture's intent obvious without indirection.
# ---------------------------------------------------------------------------

def _msg(
    *,
    role: str,
    text: str | None,
    status: str | None = "finished_successfully",
    content_type: str = "text",
    hidden: bool = False,
    model_slug: str | None = None,
    create_time: float | None = None,
    extra_metadata: dict | None = None,
    content_override: dict | None = None,
) -> dict:
    """Build a message dict in the shape ChatGPT's export uses."""
    metadata: dict = {"is_visually_hidden_from_conversation": hidden}
    if model_slug is not None:
        metadata["model_slug"] = model_slug
    if extra_metadata:
        metadata.update(extra_metadata)
    content: dict
    if content_override is not None:
        content = content_override
    elif content_type == "text":
        content = {"content_type": "text", "parts": [text] if text is not None else []}
    else:
        content = {"content_type": content_type, "parts": [text] if text is not None else []}
    return {
        "id": "msg-id",
        "author": {"role": role},
        "create_time": create_time,
        "status": status,
        "content": content,
        "metadata": metadata,
    }


def _node(message: dict | None, parent: str | None) -> dict:
    return {"message": message, "parent": parent}


# ---------------------------------------------------------------------------
# linearise()
# ---------------------------------------------------------------------------


def test_linearise_returns_chain_in_root_to_leaf_order():
    mapping = {
        "root": _node(None, None),
        "a": _node(_msg(role="user", text="first"), "root"),
        "b": _node(_msg(role="assistant", text="second"), "a"),
        "c": _node(_msg(role="user", text="third"), "b"),
    }
    chain = linearise(mapping, "c")
    assert [m["content"]["parts"][0] for m in chain] == ["first", "second", "third"]


def test_linearise_skips_nodes_without_message_field():
    """The synthetic root carries ``message=None`` and must not appear in the chain."""
    mapping = {
        "root": _node(None, None),
        "leaf": _node(_msg(role="user", text="hello"), "root"),
    }
    chain = linearise(mapping, "leaf")
    assert len(chain) == 1
    assert chain[0]["content"]["parts"] == ["hello"]


def test_linearise_tolerates_cycle_in_parent_chain():
    """A→B→A would be an infinite loop without the visited-set guard."""
    mapping = {
        "a": _node(_msg(role="user", text="a"), "b"),
        "b": _node(_msg(role="assistant", text="b"), "a"),
    }
    chain = linearise(mapping, "a")
    # Both nodes appear exactly once — no infinite loop, no duplicates.
    assert len(chain) == 2
    contents = [m["content"]["parts"][0] for m in chain]
    assert set(contents) == {"a", "b"}


def test_linearise_returns_empty_when_current_node_id_missing():
    mapping = {"a": _node(_msg(role="user", text="x"), None)}
    assert linearise(mapping, "does-not-exist") == []


def test_linearise_only_follows_parent_chain_not_children():
    """A branch sibling on the same parent must be ignored — we only walk parents."""
    mapping = {
        "root": _node(None, None),
        "parent": _node(_msg(role="user", text="parent"), "root"),
        "branch_kept": _node(_msg(role="assistant", text="kept"), "parent"),
        "branch_dropped": _node(_msg(role="assistant", text="dropped"), "parent"),
    }
    chain = linearise(mapping, "branch_kept")
    contents = [m["content"]["parts"][0] for m in chain]
    assert contents == ["parent", "kept"]
    assert "dropped" not in contents


# ---------------------------------------------------------------------------
# is_message_keepable()
# ---------------------------------------------------------------------------


def test_keepable_user_text_with_finished_successfully():
    assert is_message_keepable(_msg(role="user", text="hi")) is True


def test_keepable_assistant_text_with_none_status():
    assert is_message_keepable(_msg(role="assistant", text="hi", status=None)) is True


def test_keepable_user_editable_context_even_when_hidden():
    """Custom Instructions live in a hidden ``user_editable_context`` message —
    they must survive the hidden-filter as a deliberate exception."""
    msg = _msg(
        role="user",
        text=None,
        content_type="user_editable_context",
        hidden=True,
        content_override={"content_type": "user_editable_context", "parts": []},
    )
    assert is_message_keepable(msg) is True


def test_drop_system_role():
    assert is_message_keepable(_msg(role="system", text="hi")) is False


def test_drop_tool_role():
    assert is_message_keepable(_msg(role="tool", text="hi")) is False


def test_drop_status_in_progress():
    assert is_message_keepable(_msg(role="assistant", text="hi", status="in_progress")) is False


def test_drop_status_interrupted():
    assert is_message_keepable(_msg(role="assistant", text="hi", status="interrupted")) is False


def test_drop_content_type_code():
    assert is_message_keepable(_msg(role="assistant", text="x", content_type="code")) is False


def test_drop_content_type_multimodal_text():
    assert (
        is_message_keepable(_msg(role="assistant", text="x", content_type="multimodal_text"))
        is False
    )


def test_drop_hidden_text_message():
    """A hidden plain-text message must drop (e.g. system reminders, tool prep)."""
    assert is_message_keepable(_msg(role="user", text="hi", hidden=True)) is False


def test_drop_empty_parts():
    msg = _msg(role="user", text=None, content_override={"content_type": "text", "parts": []})
    assert is_message_keepable(msg) is False


def test_drop_whitespace_only_parts():
    msg = _msg(role="user", text=None, content_override={"content_type": "text", "parts": ["   \n\t"]})
    assert is_message_keepable(msg) is False


def test_message_none_returns_false():
    assert is_message_keepable(None) is False


# ---------------------------------------------------------------------------
# parse_conversation()
# ---------------------------------------------------------------------------


def _conv(
    *,
    mapping: dict,
    current_node: str | None,
    title: str = "T",
    create_time: float = 1_700_000_000.0,
    update_time: float = 1_700_000_500.0,
    default_model_slug: str | None = None,
    conversation_id: str = "conv-1",
) -> dict:
    return {
        "conversation_id": conversation_id,
        "title": title,
        "create_time": create_time,
        "update_time": update_time,
        "default_model_slug": default_model_slug,
        "current_node": current_node,
        "mapping": mapping,
    }


def test_parse_conversation_happy_path():
    mapping = {
        "root": _node(None, None),
        "u1": _node(_msg(role="user", text="hello"), "root"),
        "a1": _node(_msg(role="assistant", text="hi there", model_slug="gpt-4o"), "u1"),
    }
    conv = _conv(mapping=mapping, current_node="a1", default_model_slug="gpt-4o")
    out = parse_conversation(conv)
    assert out.message_count == 2
    assert [m.role for m in out.messages] == ["user", "assistant"]
    assert out.messages[0].content == "hello"
    assert out.messages[1].content == "hi there"
    assert out.messages[1].imported_model_slug == "gpt-4o"
    assert out.default_model_slug == "gpt-4o"
    assert out.first_user_message_preview == "hello"
    assert out.first_assistant_message_preview == "hi there"
    assert out.chatgpt_conversation_id == "conv-1"


def test_parse_conversation_without_current_node_yields_empty_messages_but_metadata():
    conv = _conv(mapping={}, current_node=None, title="No leaf")
    out = parse_conversation(conv)
    assert out.messages == []
    assert out.title == "No leaf"
    assert out.chatgpt_conversation_id == "conv-1"
    assert out.first_user_message_preview == ""
    assert out.first_assistant_message_preview == ""


def test_parse_conversation_synthesises_user_editable_context_with_labels_before_create_time():
    ci_msg = {
        "id": "ci",
        "author": {"role": "user"},
        "create_time": None,
        "status": "finished_successfully",
        "content": {"content_type": "user_editable_context", "parts": []},
        "metadata": {
            "is_visually_hidden_from_conversation": True,
            "user_context_message_data": {
                "about_user_message": "I am a developer.",
                "about_model_message": "Be concise.",
            },
        },
    }
    mapping = {
        "root": _node(None, None),
        "ci": _node(ci_msg, "root"),
        "u1": _node(_msg(role="user", text="hi"), "ci"),
    }
    conv_create_ts = 1_700_000_000.0
    conv = _conv(mapping=mapping, current_node="u1", create_time=conv_create_ts)
    out = parse_conversation(conv)

    # First message is the synthesised user-profile/custom-instructions block.
    assert out.messages[0].role == "user"
    assert "[User Profile]" in out.messages[0].content
    assert "I am a developer." in out.messages[0].content
    assert "[Custom Instructions]" in out.messages[0].content
    assert "Be concise." in out.messages[0].content

    expected_ts = datetime.fromtimestamp(conv_create_ts, UTC) - timedelta(seconds=1)
    assert out.messages[0].created_at == expected_ts

    # The real user message follows.
    assert out.messages[1].role == "user"
    assert out.messages[1].content == "hi"


def test_parse_conversation_filters_non_keepable_code_blocks():
    mapping = {
        "root": _node(None, None),
        "u1": _node(_msg(role="user", text="run this"), "root"),
        "code": _node(_msg(role="assistant", text="print(1)", content_type="code"), "u1"),
        "a1": _node(_msg(role="assistant", text="done"), "code"),
    }
    conv = _conv(mapping=mapping, current_node="a1")
    out = parse_conversation(conv)
    assert [m.content for m in out.messages] == ["run this", "done"]


def test_parse_conversation_without_default_model_slug_is_none():
    mapping = {
        "root": _node(None, None),
        "u1": _node(_msg(role="user", text="hi"), "root"),
    }
    conv = _conv(mapping=mapping, current_node="u1", default_model_slug=None)
    out = parse_conversation(conv)
    assert out.default_model_slug is None


def test_parse_conversation_takes_per_message_model_slug_from_metadata():
    mapping = {
        "root": _node(None, None),
        "u1": _node(_msg(role="user", text="hi"), "root"),
        "a1": _node(_msg(role="assistant", text="ok", model_slug="gpt-4o-mini"), "u1"),
    }
    conv = _conv(mapping=mapping, current_node="a1")
    out = parse_conversation(conv)
    assert out.messages[1].imported_model_slug == "gpt-4o-mini"
    # The user message has no model_slug in metadata.
    assert out.messages[0].imported_model_slug is None


def test_parse_conversation_previews_use_first_nonempty_message_and_truncate_at_200():
    long_text = "x" * 300
    mapping = {
        "root": _node(None, None),
        "u1": _node(_msg(role="user", text=long_text), "root"),
        "a1": _node(_msg(role="assistant", text=long_text), "u1"),
    }
    conv = _conv(mapping=mapping, current_node="a1")
    out = parse_conversation(conv)
    assert len(out.first_user_message_preview) == 200
    assert len(out.first_assistant_message_preview) == 200
    assert out.first_user_message_preview == "x" * 200


def test_parse_conversation_timestamps_are_utc_aware():
    ts = 1_700_000_000.5
    mapping = {
        "root": _node(None, None),
        "u1": _node(_msg(role="user", text="hi", create_time=ts), "root"),
    }
    conv = _conv(mapping=mapping, current_node="u1", create_time=ts, update_time=ts)
    out = parse_conversation(conv)
    assert out.create_time == datetime.fromtimestamp(ts, UTC)
    assert out.update_time == datetime.fromtimestamp(ts, UTC)
    assert out.create_time.tzinfo == UTC
    assert out.messages[0].created_at == datetime.fromtimestamp(ts, UTC)


def test_parse_conversation_falls_back_to_now_for_invalid_timestamp():
    """Invalid timestamps must not crash the parser — fall back to ``now(UTC)``."""
    mapping = {
        "root": _node(None, None),
        "u1": _node(_msg(role="user", text="hi"), "root"),
    }
    before = datetime.now(UTC)
    conv = _conv(mapping=mapping, current_node="u1", create_time="not-a-number")  # type: ignore[arg-type]
    out = parse_conversation(conv)
    after = datetime.now(UTC)
    assert before <= out.create_time <= after


def test_parse_conversation_does_not_emit_pseudo_model_id():
    """Regression: the removed ``imported:<slug>`` pseudo-id concept must not
    creep back into the parsed messages or conversation metadata."""
    mapping = {
        "root": _node(None, None),
        "u1": _node(_msg(role="user", text="hi"), "root"),
        "a1": _node(_msg(role="assistant", text="ok", model_slug="gpt-4o"), "u1"),
    }
    conv = _conv(mapping=mapping, current_node="a1", default_model_slug="gpt-4o")
    out = parse_conversation(conv)
    assert not (out.default_model_slug or "").startswith("imported:")
    for m in out.messages:
        assert not (m.imported_model_slug or "").startswith("imported:")


# ---------------------------------------------------------------------------
# iter_conversations_from_file()
# ---------------------------------------------------------------------------


def test_iter_conversations_yields_each_top_level_conversation(tmp_path):
    payload = [
        {"conversation_id": "c1", "title": "first", "mapping": {}, "current_node": None},
        {"conversation_id": "c2", "title": "second", "mapping": {}, "current_node": None},
    ]
    f = tmp_path / "export.json"
    f.write_text(json.dumps(payload), encoding="utf-8")

    convs = list(iter_conversations_from_file(str(f)))
    assert len(convs) == 2
    assert convs[0]["conversation_id"] == "c1"
    assert convs[1]["conversation_id"] == "c2"


def test_iter_conversations_decodes_floats_as_python_float(tmp_path):
    """Regression: ijson defaults to ``decimal.Decimal`` for JSON numbers,
    which PyMongo cannot BSON-encode. ``use_float=True`` keeps them as native
    ``float``. This is the test that would have caught the ijson-Decimal bug
    fixed earlier in this session."""
    from decimal import Decimal

    payload = [
        {
            "conversation_id": "c1",
            "title": "ts",
            "create_time": 1760077465.434278,
            "update_time": 1760077465.434278,
            "mapping": {},
            "current_node": None,
        }
    ]
    f = tmp_path / "export.json"
    f.write_text(json.dumps(payload), encoding="utf-8")

    conv = next(iter_conversations_from_file(str(f)))
    assert type(conv["create_time"]) is float
    assert type(conv["update_time"]) is float
    assert not isinstance(conv["create_time"], Decimal)


def test_iter_conversations_on_empty_array(tmp_path):
    f = tmp_path / "empty.json"
    f.write_text("[]", encoding="utf-8")
    assert list(iter_conversations_from_file(str(f))) == []
