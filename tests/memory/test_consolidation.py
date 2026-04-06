import pytest

from backend.modules.memory._consolidation import build_consolidation_prompt, validate_memory_body


class TestBuildConsolidationPrompt:
    def test_includes_existing_body(self):
        prompt = build_consolidation_prompt(
            existing_body="User likes dark themes.",
            entries=[{"content": "Uses Arch Linux", "is_correction": False}],
        )
        assert "User likes dark themes." in prompt
        assert "Arch Linux" in prompt

    def test_no_existing_body(self):
        prompt = build_consolidation_prompt(
            existing_body=None,
            entries=[{"content": "Name is Chris", "is_correction": False}],
        )
        assert "Chris" in prompt

    def test_marks_corrections(self):
        prompt = build_consolidation_prompt(
            existing_body="User's name is Christian.",
            entries=[{"content": "Name is Chris, not Christian", "is_correction": True}],
        )
        assert "CORRECTION" in prompt or "correction" in prompt


class TestValidateMemoryBody:
    def test_valid_body(self):
        assert validate_memory_body("User likes dark themes and uses Arch Linux.", max_tokens=3000) is True

    def test_empty_body(self):
        assert validate_memory_body("", max_tokens=3000) is False

    def test_whitespace_only(self):
        assert validate_memory_body("   \n  ", max_tokens=3000) is False

    def test_over_token_limit(self):
        long_text = "word " * 4000
        assert validate_memory_body(long_text, max_tokens=3000) is False

    def test_none(self):
        assert validate_memory_body(None, max_tokens=3000) is False
