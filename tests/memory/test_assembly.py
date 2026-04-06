import pytest

from backend.modules.memory._assembly import assemble_memory_context


class TestAssembleMemoryContext:
    def test_body_only(self):
        result = assemble_memory_context(
            memory_body="User likes dark themes.",
            committed_entries=[],
            uncommitted_entries=[],
            max_tokens=6000,
        )
        assert "<memory-body>" in result
        assert "User likes dark themes." in result
        assert "<journal>" not in result

    def test_body_plus_journal(self):
        result = assemble_memory_context(
            memory_body="User likes dark themes.",
            committed_entries=[{"content": "Works as C# developer", "created_at": "2026-04-06"}],
            uncommitted_entries=[{"content": "Uses Arch Linux", "created_at": "2026-04-06"}],
            max_tokens=6000,
        )
        assert "<memory-body>" in result
        assert "<journal>" in result
        assert "C# developer" in result
        assert "Arch Linux" in result

    def test_no_memory_returns_none(self):
        result = assemble_memory_context(
            memory_body=None,
            committed_entries=[],
            uncommitted_entries=[],
            max_tokens=6000,
        )
        assert result is None

    def test_budget_respected(self):
        long_body = "x " * 2500
        many_entries = [{"content": f"Entry {i} " * 50, "created_at": "2026-04-06"} for i in range(20)]
        result = assemble_memory_context(
            memory_body=long_body,
            committed_entries=many_entries,
            uncommitted_entries=[],
            max_tokens=3000,
        )
        assert result is not None
        # Each entry contains the word "Entry" 50 times; fewer than 4 entries should fit
        # (not all 20 entries) given the tight token budget
        assert result.count("Entry") < 200

    def test_committed_before_uncommitted(self):
        result = assemble_memory_context(
            memory_body="Body.",
            committed_entries=[{"content": "COMMITTED_MARKER", "created_at": "2026-04-06"}],
            uncommitted_entries=[{"content": "UNCOMMITTED_MARKER", "created_at": "2026-04-06"}],
            max_tokens=6000,
        )
        committed_pos = result.index("COMMITTED_MARKER")
        uncommitted_pos = result.index("UNCOMMITTED_MARKER")
        assert committed_pos < uncommitted_pos

    def test_wraps_in_usermemory_tag(self):
        result = assemble_memory_context(
            memory_body="Test.",
            committed_entries=[],
            uncommitted_entries=[],
            max_tokens=6000,
        )
        assert result.startswith('<usermemory priority="normal">')
        assert result.endswith("</usermemory>")
