"""Backend tests for clone-on-branch.

See devdocs/specs/2026-05-17-branching-design.md §8.1 / §8.2.
"""

import asyncio
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from httpx import AsyncClient

from backend.database import connect_db, disconnect_db, get_db, get_redis
from backend.modules.chat._repository import ChatRepository
from shared.dtos.chat import ChatSessionExtras


@pytest.fixture
async def repo(clean_db):
    await connect_db()
    r = ChatRepository(get_db())
    await r.create_indexes()
    yield r
    await disconnect_db()


async def _build_session_with_messages(
    repo: ChatRepository,
    *,
    user_id: str = "user-1",
    persona_id: str = "p-1",
    pairs: int = 2,
    correlation_prefix: str = "corr",
) -> tuple[dict, list[dict]]:
    """Create a session with ``pairs`` user/assistant turns.

    Each pair shares a unique correlation_id (``corr-1``, ``corr-2``, …)
    so the clone's correlation-id preservation can be verified.
    """
    session = await repo.create_session(user_id=user_id, persona_id=persona_id)
    sid = session["_id"]
    for n in range(1, pairs + 1):
        cid = f"{correlation_prefix}-{n}"
        await repo.save_message(
            session_id=sid, role="user", content=f"u-{n}",
            token_count=1, correlation_id=cid, user_id=user_id,
        )
        await repo.save_message(
            session_id=sid, role="assistant", content=f"a-{n}",
            token_count=1, correlation_id=cid, user_id=user_id,
        )
    messages = await repo.list_messages(sid)
    fresh_session = await repo.get_session(sid, user_id)
    return fresh_session, messages


async def test_clone_basic(repo):
    """4 messages, fork at message 2 (assistant). Branch carries M1+M2 with
    new _ids, preserved correlation_ids, re-stamped session_seq 1..2."""
    parent, parent_msgs = await _build_session_with_messages(repo, pairs=2)
    fork_msg = parent_msgs[1]  # assistant of pair-1, seq=2
    assert fork_msg["role"] == "assistant"

    branch = await repo.clone_session_at(
        parent_session_id=parent["_id"],
        fork_message_id=fork_msg["_id"],
        new_name="My Branch",
        user_id="user-1",
    )

    # Distinct session id, owner / persona inherited.
    assert branch["_id"] != parent["_id"]
    assert branch["user_id"] == parent["user_id"]
    assert branch["persona_id"] == parent["persona_id"]
    assert branch["title"] == "My Branch"
    assert branch["state"] == "idle"
    assert branch["pinned"] is False

    # Branch has two messages with re-stamped session_seq + new _ids.
    cloned = await repo.list_messages(branch["_id"])
    assert len(cloned) == 2
    parent_ids = {m["_id"] for m in parent_msgs[:2]}
    for idx, m in enumerate(cloned, start=1):
        assert m["_id"] not in parent_ids
        assert m["session_seq"] == idx
        assert m["session_id"] == branch["_id"]

    # Correlation IDs preserved 1:1.
    assert [m.get("correlation_id") for m in cloned] == [
        parent_msgs[0].get("correlation_id"),
        parent_msgs[1].get("correlation_id"),
    ]

    # last_message_seq matches cloned count.
    assert branch["last_message_seq"] == 2

    # Forked_from lineage pointer populated.
    forked = branch["forked_from"]
    assert forked["session_id"] == parent["_id"]
    assert forked["message_id"] == fork_msg["_id"]
    assert forked["session_seq"] == fork_msg["session_seq"]


async def test_clone_preserves_extras(repo):
    """Parent extras carry over to the branch verbatim."""
    parent, _ = await _build_session_with_messages(repo, pairs=1)
    extras = ChatSessionExtras(
        tools_enabled=False,
        reasoning_mode="off",
        replay_tool_history=False,
    )
    await repo.update_session_extras(parent["_id"], parent["user_id"], extras)

    parent_msgs = await repo.list_messages(parent["_id"])
    fork_msg = parent_msgs[1]

    branch = await repo.clone_session_at(
        parent_session_id=parent["_id"],
        fork_message_id=fork_msg["_id"],
        new_name="branch",
        user_id="user-1",
    )
    assert branch["extras"] == extras.model_dump()


async def test_clone_compaction_checkpoints(repo):
    """Parent has 2 checkpoints; only the one whose tail_start_message_id
    falls inside the cloned message set survives, with the id remapped."""
    parent, msgs = await _build_session_with_messages(repo, pairs=3)
    # msgs order: u1, a1, u2, a2, u3, a3 (session_seq 1..6).
    # Place two checkpoints — one anchored at msg-3 (inside the cloned
    # range when forking at a2), one anchored at msg-5 (outside).
    cp_inside = {
        "id": "cp-1",
        "created_at": datetime.now(UTC),
        "model_unique_id": "test:model",
        "summary_markdown": "summary 1",
        "last_message_id_before": msgs[1]["_id"],
        "tail_start_message_id": msgs[2]["_id"],  # seq=3
        "tokens_before": 100,
        "tokens_after": 50,
        "tail_token_count": 30,
        "prev_checkpoint_id": None,
    }
    cp_outside = {
        "id": "cp-2",
        "created_at": datetime.now(UTC),
        "model_unique_id": "test:model",
        "summary_markdown": "summary 2",
        "last_message_id_before": msgs[3]["_id"],
        "tail_start_message_id": msgs[4]["_id"],  # seq=5 (outside fork)
        "tokens_before": 150,
        "tokens_after": 80,
        "tail_token_count": 40,
        "prev_checkpoint_id": "cp-1",
    }
    await repo._sessions.update_one(
        {"_id": parent["_id"]},
        {"$set": {"compaction_checkpoints": [cp_inside, cp_outside]}},
    )

    fork_msg = msgs[3]  # assistant of pair-2, seq=4
    branch = await repo.clone_session_at(
        parent_session_id=parent["_id"],
        fork_message_id=fork_msg["_id"],
        new_name="branch",
        user_id="user-1",
    )

    cps = branch["compaction_checkpoints"]
    assert len(cps) == 1
    assert cps[0]["id"] == "cp-1"

    # tail_start_message_id remapped onto the cloned tail (seq=3 in branch).
    cloned = await repo.list_messages(branch["_id"])
    seq_3_id = next(m["_id"] for m in cloned if m["session_seq"] == 3)
    assert cps[0]["tail_start_message_id"] == seq_3_id
    assert cps[0]["tail_start_message_id"] != msgs[2]["_id"]


async def test_clone_tool_events_flagged(repo):
    """Cloned assistant docs' ``events`` entries gain ``cloned_from_branch: True``."""
    parent = await repo.create_session(user_id="user-1", persona_id="p-1")
    sid = parent["_id"]
    await repo.save_message(
        session_id=sid, role="user", content="hi",
        token_count=1, correlation_id="c-1", user_id="user-1",
    )
    events = [
        {
            "kind": "tool_call",
            "seq": 0,
            "tool_call_id": "tc-1",
            "tool_name": "web_search",
            "arguments": {"q": "x"},
            "success": True,
            "moderated_count": 0,
            "result_content": "stub",
        },
        {
            "kind": "web_search",
            "seq": 1,
            "items": [],
        },
    ]
    asst = await repo.save_message(
        session_id=sid, role="assistant", content="ok",
        token_count=1, correlation_id="c-1", user_id="user-1",
        events=events,
    )

    branch = await repo.clone_session_at(
        parent_session_id=sid,
        fork_message_id=asst["_id"],
        new_name="branch",
        user_id="user-1",
    )
    cloned = await repo.list_messages(branch["_id"])
    cloned_asst = next(m for m in cloned if m["role"] == "assistant")
    cloned_events = cloned_asst["events"]
    assert len(cloned_events) == 2
    for ev in cloned_events:
        assert ev["cloned_from_branch"] is True
    # Original kinds and seqs preserved.
    assert cloned_events[0]["kind"] == "tool_call"
    assert cloned_events[1]["kind"] == "web_search"


async def test_clone_session_start_None(repo):
    """``fork_message_id=None`` → new session with zero messages and
    ``forked_from.message_id`` is None (session-start branch, §7.7)."""
    parent, _ = await _build_session_with_messages(repo, pairs=2)
    branch = await repo.clone_session_at(
        parent_session_id=parent["_id"],
        fork_message_id=None,
        new_name="empty branch",
        user_id="user-1",
    )
    cloned = await repo.list_messages(branch["_id"])
    assert cloned == []
    assert branch["last_message_seq"] == 0
    forked = branch["forked_from"]
    assert forked["session_id"] == parent["_id"]
    assert forked["message_id"] is None
    assert forked["session_seq"] is None


async def test_clone_rejects_user_fork_point(repo):
    """Passing a user message id → ValueError(``fork_message_invalid``)."""
    parent, msgs = await _build_session_with_messages(repo, pairs=2)
    user_msg = msgs[0]
    assert user_msg["role"] == "user"
    with pytest.raises(ValueError, match="fork_message_invalid"):
        await repo.clone_session_at(
            parent_session_id=parent["_id"],
            fork_message_id=user_msg["_id"],
            new_name="branch",
            user_id="user-1",
        )


async def test_clone_rejects_wrong_owner(repo):
    """Parent belongs to user A; user B's clone request raises LookupError
    so the handler can return 404."""
    parent, msgs = await _build_session_with_messages(
        repo, user_id="user-A", pairs=1,
    )
    fork_msg = msgs[1]
    with pytest.raises(LookupError):
        await repo.clone_session_at(
            parent_session_id=parent["_id"],
            fork_message_id=fork_msg["_id"],
            new_name="branch",
            user_id="user-B",
        )


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def test_clone_under_compaction_lock(client: AsyncClient, seeded_admin_token):
    """HTTP endpoint returns 409 when the parent compaction lock is held."""
    user_id, token = seeded_admin_token

    db_repo = ChatRepository(get_db())
    session = await db_repo.create_session(user_id=user_id, persona_id="p-x")
    session_id = session["_id"]
    await db_repo.save_message(
        session_id=session_id, role="user", content="hi", token_count=1,
        correlation_id="c-1", user_id=user_id,
    )
    asst = await db_repo.save_message(
        session_id=session_id, role="assistant", content="ok", token_count=1,
        correlation_id="c-1", user_id=user_id,
    )

    # Hold the compaction lock manually.
    redis = get_redis()
    await redis.set(f"compaction:lock:{session_id}", "held", ex=60)

    try:
        resp = await client.post(
            f"/api/chat/sessions/{session_id}/branch",
            json={"fork_message_id": asst["_id"], "name": "branch"},
            headers=_auth(token),
        )
        assert resp.status_code == 409
        body = resp.json()
        # FastAPI wraps the detail dict under "detail"
        assert body["detail"]["error_code"] == "compaction_in_progress"
    finally:
        await redis.delete(f"compaction:lock:{session_id}")


async def test_clone_concurrency(repo):
    """Two concurrent ``clone_session_at`` calls on the same parent both
    succeed and return distinct branch _ids."""
    parent, msgs = await _build_session_with_messages(repo, pairs=2)
    fork_msg = msgs[1]

    async def _do_clone(name: str) -> dict:
        return await repo.clone_session_at(
            parent_session_id=parent["_id"],
            fork_message_id=fork_msg["_id"],
            new_name=name,
            user_id="user-1",
        )

    b1, b2 = await asyncio.gather(_do_clone("b1"), _do_clone("b2"))
    assert b1["_id"] != b2["_id"]
    assert b1["title"] == "b1"
    assert b2["title"] == "b2"

    # Each branch has its own 2-message tail with distinct _ids.
    msgs1 = await repo.list_messages(b1["_id"])
    msgs2 = await repo.list_messages(b2["_id"])
    assert len(msgs1) == 2
    assert len(msgs2) == 2
    ids1 = {m["_id"] for m in msgs1}
    ids2 = {m["_id"] for m in msgs2}
    assert ids1.isdisjoint(ids2)


# --- §8.2: integration smoke through the public HTTP endpoint --------------


async def test_branch_endpoint_returns_full_dto(client: AsyncClient, seeded_admin_token):
    """POST /branch returns a fully-shaped ChatSessionDto with the
    ``forked_from`` pointer populated."""
    user_id, token = seeded_admin_token

    db_repo = ChatRepository(get_db())
    session = await db_repo.create_session(user_id=user_id, persona_id="p-x")
    session_id = session["_id"]
    await db_repo.save_message(
        session_id=session_id, role="user", content="hi",
        token_count=1, correlation_id="c-1", user_id=user_id,
    )
    asst = await db_repo.save_message(
        session_id=session_id, role="assistant", content="ok",
        token_count=1, correlation_id="c-1", user_id=user_id,
    )

    resp = await client.post(
        f"/api/chat/sessions/{session_id}/branch",
        json={"fork_message_id": asst["_id"], "name": "Branch A"},
        headers=_auth(token),
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["title"] == "Branch A"
    assert body["forked_from"] is not None
    assert body["forked_from"]["session_id"] == session_id
    assert body["forked_from"]["message_id"] == asst["_id"]
    assert body["id"] != session_id
