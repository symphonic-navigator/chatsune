"""Pure-function tests for the chatgpt_import parser."""
from datetime import UTC, datetime

from backend.modules.chatgpt_import._parser import (
    is_message_keepable,
    linearise,
    parse_conversation,
)


# --- linearise --------------------------------------------------------


def test_linearise_simple_chain():
    mapping = {
        "root": {"id": "root", "message": None, "parent": None, "children": ["m1"]},
        "m1": {
            "id": "m1",
            "message": {"id": "m1", "content": "first"},
            "parent": "root",
            "children": ["m2"],
        },
        "m2": {
            "id": "m2",
            "message": {"id": "m2", "content": "second"},
            "parent": "m1",
            "children": [],
        },
    }
    chain = linearise(mapping, "m2")
    assert [m["id"] for m in chain] == ["m1", "m2"]


def test_linearise_discards_alternative_branch():
    mapping = {
        "root": {"id": "root", "message": None, "parent": None, "children": ["m1"]},
        "m1": {
            "id": "m1",
            "message": {"id": "m1", "content": "user"},
            "parent": "root",
            "children": ["m2a", "m2b"],
        },
        "m2a": {
            "id": "m2a",
            "message": {"id": "m2a", "content": "interrupted"},
            "parent": "m1",
            "children": [],
        },
        "m2b": {
            "id": "m2b",
            "message": {"id": "m2b", "content": "finished"},
            "parent": "m1",
            "children": [],
        },
    }
    chain = linearise(mapping, "m2b")
    assert [m["id"] for m in chain] == ["m1", "m2b"]


def test_linearise_handles_cycle_defensively():
    mapping = {
        "a": {
            "id": "a",
            "message": {"id": "a", "content": "x"},
            "parent": "b",
            "children": [],
        },
        "b": {
            "id": "b",
            "message": {"id": "b", "content": "y"},
            "parent": "a",
            "children": [],
        },
    }
    chain = linearise(mapping, "a")
    assert len(chain) == 2  # both visited once


def test_linearise_unknown_start_node_returns_empty():
    assert linearise({}, "missing") == []


# --- is_message_keepable ---------------------------------------------


def _msg(
    role="user",
    content_type="text",
    parts=None,
    hidden=False,
    status="finished_successfully",
    **extra_meta,
):
    return {
        "author": {"role": role},
        "content": {"content_type": content_type, "parts": parts or [""]},
        "status": status,
        "metadata": {
            "is_visually_hidden_from_conversation": hidden,
            **extra_meta,
        },
    }


def test_filter_keeps_normal_user_message():
    assert is_message_keepable(_msg(role="user", parts=["hello"])) is True


def test_filter_keeps_normal_assistant_message():
    assert is_message_keepable(_msg(role="assistant", parts=["reply"])) is True


def test_filter_drops_system_role():
    assert is_message_keepable(_msg(role="system", parts=["whatever"])) is False


def test_filter_drops_tool_role():
    assert is_message_keepable(_msg(role="tool", parts=["whatever"])) is False


def test_filter_drops_hidden_text_message():
    assert is_message_keepable(_msg(role="user", parts=["x"], hidden=True)) is False


def test_filter_keeps_user_editable_context_even_if_hidden():
    m = {
        "author": {"role": "user"},
        "content": {"content_type": "user_editable_context"},
        "status": "finished_successfully",
        "metadata": {"is_visually_hidden_from_conversation": True},
    }
    assert is_message_keepable(m) is True


def test_filter_drops_empty_parts():
    assert is_message_keepable(_msg(role="assistant", parts=[""])) is False
    assert is_message_keepable(_msg(role="assistant", parts=["", "  "])) is False


def test_filter_drops_unsupported_content_type():
    m = {
        "author": {"role": "assistant"},
        "content": {"content_type": "code", "text": "print(1)"},
        "status": "finished_successfully",
        "metadata": {},
    }
    assert is_message_keepable(m) is False


def test_filter_drops_interrupted_status():
    assert is_message_keepable(
        _msg(role="assistant", parts=["x"], status="in_progress")
    ) is False


# --- parse_conversation -----------------------------------------------


def test_parse_conversation_minimal():
    conv = {
        "id": "conv-1",
        "title": "Test",
        "create_time": 1719928256.0,
        "update_time": 1719928266.0,
        "current_node": "m2",
        "default_model_slug": "gpt-4o",
        "mapping": {
            "root": {"id": "root", "message": None, "parent": None, "children": ["m1"]},
            "m1": {
                "id": "m1",
                "message": {
                    "id": "m1", "author": {"role": "user"},
                    "content": {"content_type": "text", "parts": ["hi"]},
                    "status": "finished_successfully",
                    "create_time": 1719928256.0,
                    "metadata": {},
                },
                "parent": "root",
                "children": ["m2"],
            },
            "m2": {
                "id": "m2",
                "message": {
                    "id": "m2", "author": {"role": "assistant"},
                    "content": {"content_type": "text", "parts": ["hello world"]},
                    "status": "finished_successfully",
                    "create_time": 1719928266.0,
                    "metadata": {"model_slug": "gpt-4o"},
                },
                "parent": "m1",
                "children": [],
            },
        },
    }
    parsed = parse_conversation(conv)
    assert parsed.chatgpt_conversation_id == "conv-1"
    assert parsed.title == "Test"
    assert parsed.default_model_slug == "gpt-4o"
    assert parsed.message_count == 2
    assert parsed.messages[0].role == "user"
    assert parsed.messages[0].content == "hi"
    assert parsed.messages[1].role == "assistant"
    assert parsed.messages[1].imported_model_slug == "gpt-4o"
    assert parsed.first_user_message_preview == "hi"
    assert parsed.first_assistant_message_preview == "hello world"


def test_parse_conversation_custom_instructions_become_first_user_message():
    conv = {
        "id": "conv-ci", "title": "Has CI",
        "create_time": 1719928256.0, "update_time": 1719928266.0,
        "current_node": "m2",
        "mapping": {
            "root": {"id": "root", "message": None, "parent": None, "children": ["mci"]},
            "mci": {
                "id": "mci",
                "message": {
                    "id": "mci", "author": {"role": "user"},
                    "content": {"content_type": "user_editable_context"},
                    "status": "finished_successfully",
                    "metadata": {
                        "is_visually_hidden_from_conversation": True,
                        "user_context_message_data": {
                            "about_user_message": "Preferred name: Chris",
                            "about_model_message": "Reply terse.",
                        },
                    },
                },
                "parent": "root", "children": ["m1"],
            },
            "m1": {
                "id": "m1",
                "message": {
                    "id": "m1", "author": {"role": "user"},
                    "content": {"content_type": "text", "parts": ["hello"]},
                    "status": "finished_successfully",
                    "metadata": {},
                },
                "parent": "mci", "children": ["m2"],
            },
            "m2": {
                "id": "m2",
                "message": {
                    "id": "m2", "author": {"role": "assistant"},
                    "content": {"content_type": "text", "parts": ["hi"]},
                    "status": "finished_successfully",
                    "metadata": {},
                },
                "parent": "m1", "children": [],
            },
        },
    }
    parsed = parse_conversation(conv)
    assert parsed.messages[0].role == "user"
    assert "[User Profile]" in parsed.messages[0].content
    assert "[Custom Instructions]" in parsed.messages[0].content
    assert "Preferred name: Chris" in parsed.messages[0].content
    assert parsed.messages[0].created_at < parsed.messages[1].created_at


def test_parse_conversation_no_current_node():
    parsed = parse_conversation({"title": "Empty", "create_time": 0, "update_time": 0})
    assert parsed.messages == []
    assert parsed.first_user_message_preview == ""


def test_preview_strings_are_capped():
    long = "x" * 500
    conv = {
        "id": "p", "title": "p",
        "create_time": 1.0, "update_time": 1.0,
        "current_node": "m1",
        "mapping": {
            "root": {"id": "root", "message": None, "parent": None, "children": ["m1"]},
            "m1": {"id": "m1", "message": {
                "id": "m1", "author": {"role": "user"},
                "content": {"content_type": "text", "parts": [long]},
                "status": "finished_successfully", "metadata": {},
            }, "parent": "root", "children": []},
        },
    }
    parsed = parse_conversation(conv)
    assert len(parsed.first_user_message_preview) <= 200
