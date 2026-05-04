"""Mindspace Phase 3 (task 19) — library merge with project source.

The chat orchestrator's ``_make_tool_executor`` closure now captures
a third source — ``project_lib_ids`` — alongside persona and session
libraries. The knowledge module's ``_retrieval.search`` accepts a
parallel ``project_library_ids`` parameter and unions all three into
the effective set with de-duplication.

These tests target the seams directly so they need no LLM, no DB
state, and no event bus.
"""

import json

import pytest

from backend.modules.chat._orchestrator import _make_tool_executor


@pytest.mark.asyncio
async def test_executor_injects_project_library_ids_into_knowledge_search(
    monkeypatch,
):
    """When the executor is invoked for ``knowledge_search`` it must
    pass ``_project_library_ids`` through ``arguments`` so the
    downstream tool dispatcher can forward it to retrieval."""
    captured: dict = {}

    async def fake_execute_tool(
        user_id, tool_name, arguments_json, *,
        tool_call_id, session_id, originating_connection_id, model,
    ):
        captured["tool_name"] = tool_name
        captured["arguments"] = json.loads(arguments_json)
        return "{}"

    monkeypatch.setattr(
        "backend.modules.chat._orchestrator.execute_tool", fake_execute_tool,
    )

    session = {
        "_id": "s1",
        "knowledge_library_ids": ["L-session"],
    }
    persona = {"_id": "p1", "knowledge_library_ids": ["L-persona"]}

    executor = _make_tool_executor(
        session, persona,
        correlation_id="corr-1",
        connection_id="conn-1",
        model_slug="m",
        project_lib_ids=["L-project-1", "L-project-2"],
    )

    await executor(
        user_id="u1",
        tool_name="knowledge_search",
        arguments_json='{"query": "hi"}',
        tool_call_id="tc-1",
    )

    args = captured["arguments"]
    assert args["_persona_library_ids"] == ["L-persona"]
    assert args["_session_library_ids"] == ["L-session"]
    assert args["_project_library_ids"] == ["L-project-1", "L-project-2"]


@pytest.mark.asyncio
async def test_executor_falls_back_to_empty_project_libs(monkeypatch):
    """No project_lib_ids → empty list, not missing — keeps the
    downstream contract uniform across project / non-project chats."""
    captured: dict = {}

    async def fake_execute_tool(
        user_id, tool_name, arguments_json, *,
        tool_call_id, session_id, originating_connection_id, model,
    ):
        captured["arguments"] = json.loads(arguments_json)
        return "{}"

    monkeypatch.setattr(
        "backend.modules.chat._orchestrator.execute_tool", fake_execute_tool,
    )

    session = {"_id": "s1", "knowledge_library_ids": []}
    persona = {"_id": "p1", "knowledge_library_ids": []}

    executor = _make_tool_executor(
        session, persona,
        correlation_id="c", connection_id=None, model_slug="m",
    )
    await executor(
        user_id="u1",
        tool_name="knowledge_search",
        arguments_json='{"query": "hi"}',
        tool_call_id="tc-1",
    )
    assert captured["arguments"]["_project_library_ids"] == []


@pytest.mark.asyncio
async def test_search_merges_three_sources_with_dedup(monkeypatch):
    """The retrieval function unions persona ∪ session ∪ project lib
    ids and deduplicates — no library is searched twice when two
    sources reference it."""
    captured = {"effective_ids": None}

    class _FakeRepo:
        async def vector_search(self, user_id, lib_ids, vector, top_k):
            captured["effective_ids"] = list(lib_ids)
            return []

    async def _fake_query_embed(query):
        return [0.0, 0.0, 0.0]

    monkeypatch.setattr(
        "backend.modules.knowledge._retrieval.KnowledgeRepository",
        lambda db: _FakeRepo(),
    )
    monkeypatch.setattr(
        "backend.modules.knowledge._retrieval.get_db",
        lambda: object(),
    )
    monkeypatch.setattr(
        "backend.modules.embedding.query_embed", _fake_query_embed,
    )

    from backend.modules.knowledge._retrieval import search

    await search(
        user_id="u1",
        query="hi",
        persona_library_ids=["A", "B"],
        session_library_ids=["B", "C"],
        project_library_ids=["C", "D"],
    )

    assert captured["effective_ids"] is not None
    assert set(captured["effective_ids"]) == {"A", "B", "C", "D"}


@pytest.mark.asyncio
async def test_search_default_project_library_ids_empty(monkeypatch):
    """Callers that pre-date Mindspace can call ``search`` without
    passing ``project_library_ids`` and the merge still works
    (defaulting to ``()``)."""
    captured = {"effective_ids": None}

    class _FakeRepo:
        async def vector_search(self, user_id, lib_ids, vector, top_k):
            captured["effective_ids"] = list(lib_ids)
            return []

    async def _fake_query_embed(query):
        return [0.0]

    monkeypatch.setattr(
        "backend.modules.knowledge._retrieval.KnowledgeRepository",
        lambda db: _FakeRepo(),
    )
    monkeypatch.setattr(
        "backend.modules.knowledge._retrieval.get_db",
        lambda: object(),
    )
    monkeypatch.setattr(
        "backend.modules.embedding.query_embed", _fake_query_embed,
    )

    from backend.modules.knowledge._retrieval import search

    await search(
        user_id="u1",
        query="hi",
        persona_library_ids=["A"],
        session_library_ids=["B"],
        # ``project_library_ids`` deliberately omitted.
    )

    assert set(captured["effective_ids"]) == {"A", "B"}
