"""ChatGPT export parser.

The export file is a top-level JSON array of conversation objects. Each
conversation carries a ``mapping`` (tree of messages keyed by node id) and
a ``current_node`` (the leaf the user last saw — typically the assistant's
final reply). We walk back from ``current_node`` to root, filter the chain,
and emit a flat user/assistant transcript.

This module is **pure** — no DB, no event-bus, no IO except ``ijson`` stream
parsing in :func:`parse_export_stream`. That makes the linearise/filter logic
easy to unit-test without a Mongo fixture.
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Iterator

from backend.modules.chatgpt_import._models import (
    ParsedConversation,
    ParsedMessage,
)

_log = logging.getLogger(__name__)
_PREVIEW_MAX = 200

SUPPORTED_CONTENT_TYPES = {"text", "user_editable_context"}
KEEPABLE_ROLES = {"user", "assistant"}


def linearise(mapping: dict, current_node_id: str) -> list[dict]:
    """Walk the parent chain from current_node back to root.

    Returns the message objects in root→leaf order. Nodes with no
    ``message`` (the synthetic root) are skipped. Cycles are tolerated
    defensively — each node id is visited at most once.
    """
    chain: list[dict] = []
    visited: set[str] = set()
    node_id: str | None = current_node_id
    while node_id and node_id not in visited:
        visited.add(node_id)
        node = mapping.get(node_id)
        if not node:
            break
        msg = node.get("message")
        if msg is not None:
            chain.append(msg)
        node_id = node.get("parent")
    return list(reversed(chain))


def is_message_keepable(message: dict | None) -> bool:
    """Apply the keep/drop filter rules for parsed ChatGPT messages.

    Keeps:
    - user / assistant messages with finished_successfully status (or no status)
    - ``user_editable_context`` (Custom Instructions) even when hidden
    Drops:
    - system / tool roles
    - hidden messages (except Custom Instructions)
    - unsupported content_types (code, multimodal_text, image, …)
    - empty parts
    - non-completed (in_progress / interrupted) status
    """
    if message is None:
        return False
    author = message.get("author") or {}
    role = author.get("role")
    if role not in KEEPABLE_ROLES:
        return False
    status = message.get("status")
    if status not in (None, "finished_successfully"):
        return False
    content = message.get("content") or {}
    ctype = content.get("content_type")
    if ctype not in SUPPORTED_CONTENT_TYPES:
        return False
    metadata = message.get("metadata") or {}
    is_hidden = metadata.get("is_visually_hidden_from_conversation", False)
    if is_hidden and ctype != "user_editable_context":
        return False
    if ctype == "text":
        parts = content.get("parts") or []
        if not parts or all(not (p or "").strip() for p in parts if isinstance(p, str)):
            return False
    return True


def _build_custom_instructions_text(message: dict) -> str:
    """Turn a ``user_editable_context`` message into a synthetic user text.

    The user's profile and custom-instruction blocks are combined into a
    single labelled string that the persona can read on import. Returns
    an empty string when neither block has content.
    """
    meta = (message.get("metadata") or {}).get("user_context_message_data") or {}
    about_user = (meta.get("about_user_message") or "").strip()
    about_model = (meta.get("about_model_message") or "").strip()
    parts: list[str] = []
    if about_user:
        parts.append(f"[User Profile]\n{about_user}")
    if about_model:
        parts.append(f"[Custom Instructions]\n{about_model}")
    return "\n\n".join(parts)


def _ts_to_dt(ts: float | None) -> datetime:
    if ts is None:
        return datetime.now(UTC)
    try:
        return datetime.fromtimestamp(float(ts), UTC)
    except (TypeError, ValueError, OSError):
        return datetime.now(UTC)


def _message_to_parsed(
    message: dict, conversation_create_time: datetime
) -> ParsedMessage:
    role = message["author"]["role"]
    create_time = message.get("create_time")
    ts = _ts_to_dt(create_time) if create_time is not None else conversation_create_time
    metadata = message.get("metadata") or {}
    parts = (message.get("content") or {}).get("parts") or []
    content_chunks = [
        p for p in parts if isinstance(p, str) and p is not None
    ]
    content = "\n".join(content_chunks)
    return ParsedMessage(
        role=role,
        content=content,
        created_at=ts,
        imported_model_slug=metadata.get("model_slug"),
    )


def parse_conversation(conv: dict) -> ParsedConversation:
    """Tree → filter → Chatsune-shape. Pure function on one conversation."""
    mapping = conv.get("mapping") or {}
    current_node = conv.get("current_node")
    conv_create_dt = _ts_to_dt(conv.get("create_time"))
    conv_update_dt = _ts_to_dt(conv.get("update_time"))
    conv_id = (
        conv.get("conversation_id")
        or conv.get("id")
        or ""
    )

    if not current_node:
        return ParsedConversation(
            chatgpt_conversation_id=conv_id,
            title=conv.get("title") or "",
            create_time=conv_create_dt,
            update_time=conv_update_dt,
            default_model_slug=conv.get("default_model_slug"),
            messages=[],
            first_user_message_preview="",
            first_assistant_message_preview="",
        )

    raw_chain = linearise(mapping, current_node)

    parsed: list[ParsedMessage] = []
    for msg in raw_chain:
        if not is_message_keepable(msg):
            ctype = ((msg.get("content") or {}).get("content_type")) or "<missing>"
            if ctype not in SUPPORTED_CONTENT_TYPES:
                _log.debug(
                    "chatgpt_import.unsupported_content_type",
                    extra={
                        "content_type": ctype,
                        "conversation_id": conv_id,
                    },
                )
            continue
        ctype = msg["content"]["content_type"]
        if ctype == "user_editable_context":
            ci_text = _build_custom_instructions_text(msg)
            if ci_text:
                # Stamp it 1s before the conversation start so chronological
                # ordering puts it first regardless of any rounding.
                parsed.append(
                    ParsedMessage(
                        role="user",
                        content=ci_text,
                        created_at=conv_create_dt - timedelta(seconds=1),
                    )
                )
            continue
        parsed.append(_message_to_parsed(msg, conv_create_dt))

    # Previews for the row UI — first non-empty user / assistant message.
    first_user = next((m for m in parsed if m.role == "user" and m.content), None)
    first_asst = next((m for m in parsed if m.role == "assistant" and m.content), None)
    user_prev = (first_user.content if first_user else "")[:_PREVIEW_MAX]
    asst_prev = (first_asst.content if first_asst else "")[:_PREVIEW_MAX]

    return ParsedConversation(
        chatgpt_conversation_id=conv_id,
        title=conv.get("title") or "",
        create_time=conv_create_dt,
        update_time=conv_update_dt,
        default_model_slug=conv.get("default_model_slug"),
        messages=parsed,
        first_user_message_preview=user_prev,
        first_assistant_message_preview=asst_prev,
    )


def iter_conversations_from_file(file_path: str) -> Iterator[dict]:
    """Stream-parse a ChatGPT export and yield each top-level conversation dict.

    Uses ``ijson`` to avoid loading the full ~100 MB file into memory. The
    export is always a top-level JSON array, so the path ``item`` selects
    each element of that array.
    """
    import ijson  # local import — heavy
    with open(file_path, "rb") as f:
        yield from ijson.items(f, "item")
