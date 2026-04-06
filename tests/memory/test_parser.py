"""Tests for the tolerant JSON parser used in memory extraction."""

import pytest

from backend.modules.memory._parser import parse_extraction_output


class TestCleanJsonOutput:
    def test_valid_json_array(self):
        raw = '[{"content": "Likes dark themes", "category": "preference", "is_correction": false}]'
        result = parse_extraction_output(raw)
        assert len(result) == 1
        assert result[0]["content"] == "Likes dark themes"
        assert result[0]["is_correction"] is False

    def test_multiple_entries(self):
        raw = '[{"content": "A", "category": "fact", "is_correction": false}, {"content": "B", "category": null, "is_correction": true}]'
        result = parse_extraction_output(raw)
        assert len(result) == 2
        assert result[1]["is_correction"] is True

    def test_empty_array(self):
        result = parse_extraction_output("[]")
        assert result == []


class TestMarkdownFences:
    def test_json_fence(self):
        raw = '```json\n[{"content": "Uses Arch", "category": "fact", "is_correction": false}]\n```'
        result = parse_extraction_output(raw)
        assert len(result) == 1
        assert result[0]["content"] == "Uses Arch"

    def test_plain_fence(self):
        raw = '```\n[{"content": "Test", "category": null, "is_correction": false}]\n```'
        result = parse_extraction_output(raw)
        assert len(result) == 1

    def test_fence_with_surrounding_text(self):
        raw = 'Here are the entries:\n```json\n[{"content": "Test", "category": "fact", "is_correction": false}]\n```\nDone.'
        result = parse_extraction_output(raw)
        assert len(result) == 1


class TestTrailingCommas:
    def test_trailing_comma_in_array(self):
        raw = '[{"content": "A", "category": "fact", "is_correction": false},]'
        result = parse_extraction_output(raw)
        assert len(result) == 1

    def test_trailing_comma_in_object(self):
        raw = '[{"content": "A", "category": "fact", "is_correction": false,}]'
        result = parse_extraction_output(raw)
        assert len(result) == 1


class TestMissingFields:
    def test_missing_category(self):
        raw = '[{"content": "Test"}]'
        result = parse_extraction_output(raw)
        assert len(result) == 1
        assert result[0]["content"] == "Test"
        assert result[0].get("category") is None
        assert result[0].get("is_correction") is False

    def test_missing_is_correction(self):
        raw = '[{"content": "Test", "category": "fact"}]'
        result = parse_extraction_output(raw)
        assert result[0]["is_correction"] is False


class TestFallbackRegexExtraction:
    def test_objects_without_array_wrapper(self):
        raw = '{"content": "A", "category": "fact", "is_correction": false}\n{"content": "B", "category": "fact", "is_correction": false}'
        result = parse_extraction_output(raw)
        assert len(result) == 2

    def test_prose_with_embedded_json(self):
        raw = 'I found these facts:\n1. {"content": "Uses Linux", "category": "fact", "is_correction": false}\n2. {"content": "Likes Redis", "category": "preference", "is_correction": false}'
        result = parse_extraction_output(raw)
        assert len(result) == 2


class TestGarbageInput:
    def test_empty_string(self):
        result = parse_extraction_output("")
        assert result == []

    def test_none(self):
        result = parse_extraction_output(None)
        assert result == []

    def test_pure_prose(self):
        result = parse_extraction_output("The user likes dark themes and uses Arch Linux.")
        assert result == []

    def test_whitespace_only(self):
        result = parse_extraction_output("   \n\n  ")
        assert result == []
