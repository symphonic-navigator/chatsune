import pytest
from backend.modules.memory._extraction import strip_technical_content, build_extraction_prompt


class TestStripTechnicalContent:
    def test_removes_fenced_code_blocks(self):
        text = "I have a bug:\n```python\ndef foo():\n    pass\n```\nCan you help?"
        result = strip_technical_content(text)
        assert "def foo" not in result
        assert "I have a bug" in result
        assert "Can you help?" in result

    def test_removes_indented_code_blocks(self):
        text = "Check this:\n\n    SELECT * FROM users;\n    WHERE id = 1;\n\nWhat do you think?"
        result = strip_technical_content(text)
        assert "SELECT" not in result
        assert "What do you think?" in result

    def test_removes_stacktraces(self):
        text = "Got this error:\nTraceback (most recent call last):\n  File \"main.py\", line 1\nValueError: bad\n\nWhat's wrong?"
        result = strip_technical_content(text)
        assert "Traceback" not in result
        assert "What's wrong?" in result

    def test_removes_json_dumps(self):
        text = 'The response was:\n{"status": 200, "data": [{"id": 1, "name": "test"}]}\n\nLooks wrong.'
        result = strip_technical_content(text)
        assert '"status"' not in result
        assert "Looks wrong." in result

    def test_preserves_human_context(self):
        text = "I'm working on a Redis caching problem. The cache keeps expiring too early. I prefer TTL of 1 hour."
        result = strip_technical_content(text)
        assert "Redis caching problem" in result
        assert "prefer TTL of 1 hour" in result

    def test_preserves_short_inline_code(self):
        text = "I use `vim` as my editor and love `tmux`."
        result = strip_technical_content(text)
        assert "vim" in result
        assert "tmux" in result

    def test_removes_log_output(self):
        text = "Server logs:\n2026-04-06 12:00:00 INFO Starting server\n2026-04-06 12:00:01 ERROR Connection refused\n\nIt crashed."
        result = strip_technical_content(text)
        assert "2026-04-06 12:00:00" not in result
        assert "It crashed." in result

    def test_removes_xml_yaml_dumps(self):
        text = "Config:\n```yaml\nserver:\n  port: 8080\n  host: 0.0.0.0\n```\nNeed to change the port."
        result = strip_technical_content(text)
        assert "port: 8080" not in result
        assert "Need to change the port." in result

    def test_removes_tilde_fenced_code_blocks(self):
        text = "Here:\n~~~\nsome code\n~~~\nDone."
        result = strip_technical_content(text)
        assert "some code" not in result
        assert "Done." in result

    def test_removes_java_stacktraces(self):
        text = "Crash:\njava.lang.NullPointerException: null\n\tat com.example.Foo.bar(Foo.java:42)\n\tat com.example.Main.main(Main.java:10)\n\nHelp?"
        result = strip_technical_content(text)
        assert "NullPointerException" not in result
        assert "Help?" in result

    def test_empty_string(self):
        result = strip_technical_content("")
        assert result == ""

    def test_plain_text_unchanged(self):
        text = "I love cooking pasta on weekends."
        result = strip_technical_content(text)
        assert result.strip() == text.strip()


class TestBuildExtractionPrompt:
    def test_includes_memory_body(self):
        prompt = build_extraction_prompt(
            memory_body="User likes dark themes.",
            journal_entries=["Works as C# developer"],
            messages=["I switched to Go recently."],
        )
        assert "User likes dark themes." in prompt
        assert "C# developer" in prompt
        assert "switched to Go" in prompt

    def test_no_memory_body(self):
        prompt = build_extraction_prompt(
            memory_body=None,
            journal_entries=[],
            messages=["My name is Chris."],
        )
        assert "My name is Chris." in prompt
        assert "no existing memory" in prompt.lower() or "empty" in prompt.lower() or "none" in prompt.lower()

    def test_instructs_json_output(self):
        prompt = build_extraction_prompt(
            memory_body=None,
            journal_entries=[],
            messages=["Hello"],
        )
        assert "json" in prompt.lower() or "JSON" in prompt

    def test_includes_is_correction_field(self):
        prompt = build_extraction_prompt(
            memory_body=None,
            journal_entries=[],
            messages=["Hello"],
        )
        assert "is_correction" in prompt

    def test_includes_category_field(self):
        prompt = build_extraction_prompt(
            memory_body=None,
            journal_entries=[],
            messages=["Hello"],
        )
        assert "category" in prompt

    def test_includes_content_field(self):
        prompt = build_extraction_prompt(
            memory_body=None,
            journal_entries=[],
            messages=["Hello"],
        )
        assert "content" in prompt

    def test_multiple_messages_all_included(self):
        prompt = build_extraction_prompt(
            memory_body=None,
            journal_entries=[],
            messages=["I like cats.", "I dislike dogs."],
        )
        assert "I like cats." in prompt
        assert "I dislike dogs." in prompt

    def test_multiple_journal_entries_all_included(self):
        prompt = build_extraction_prompt(
            memory_body=None,
            journal_entries=["Prefers dark mode", "Works remotely"],
            messages=["Hello"],
        )
        assert "Prefers dark mode" in prompt
        assert "Works remotely" in prompt
