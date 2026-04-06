"""Tests for the document chunker — ported from Prototype 2."""

import pytest

from backend.modules.knowledge._chunker import DocumentChunk, chunk_document


class TestChunkerBasics:
    def test_empty_content_returns_empty(self):
        assert chunk_document("") == []
        assert chunk_document("   ") == []

    def test_single_paragraph_under_limit(self):
        text = "This is a short paragraph."
        chunks = chunk_document(text, max_tokens=512)
        assert len(chunks) == 1
        assert chunks[0].text.strip() == text
        assert chunks[0].chunk_index == 0
        assert chunks[0].heading_path == []
        assert chunks[0].preroll_text == ""

    def test_heading_path_tracked(self):
        text = "# Top\n\nSome text\n\n## Sub\n\nMore text"
        chunks = chunk_document(text, max_tokens=512)
        assert len(chunks) >= 1
        sub_chunk = [c for c in chunks if "More text" in c.text]
        assert len(sub_chunk) == 1
        assert sub_chunk[0].heading_path == ["# Top", "## Sub"]
        assert sub_chunk[0].preroll_text == "# Top > ## Sub"

    def test_heading_hierarchy_pops_correctly(self):
        text = "# A\n\nText A\n\n## B\n\nText B\n\n# C\n\nText C"
        chunks = chunk_document(text, max_tokens=512)
        c_chunk = [c for c in chunks if "Text C" in c.text]
        assert len(c_chunk) == 1
        assert c_chunk[0].heading_path == ["# C"]


class TestOversizedSplitting:
    def test_splits_by_paragraphs(self):
        paras = ["Paragraph number " + str(i) + ". " * 20 for i in range(10)]
        text = "\n\n".join(paras)
        chunks = chunk_document(text, max_tokens=50)
        assert len(chunks) > 1
        for c in chunks:
            assert c.token_count <= 60

    def test_splits_by_sentences_when_paragraph_too_large(self):
        sentences = ["This is sentence number " + str(i) + "." for i in range(50)]
        text = " ".join(sentences)
        chunks = chunk_document(text, max_tokens=50)
        assert len(chunks) > 1

    def test_hard_split_as_last_resort(self):
        text = "word " * 200
        chunks = chunk_document(text, max_tokens=30)
        assert len(chunks) > 1


class TestSmallChunkMerging:
    def test_tiny_chunks_merged(self):
        text = "# Section\n\nA.\n\nB.\n\nC."
        chunks = chunk_document(text, max_tokens=512, merge_threshold=100)
        assert len(chunks) <= 2

    def test_different_heading_parents_not_merged(self):
        text = "# A\n\nTiny A.\n\n# B\n\nTiny B."
        chunks = chunk_document(text, max_tokens=512, merge_threshold=100)
        a_chunks = [c for c in chunks if "Tiny A" in c.text]
        b_chunks = [c for c in chunks if "Tiny B" in c.text]
        assert len(a_chunks) == 1
        assert len(b_chunks) == 1
        assert a_chunks[0].chunk_index != b_chunks[0].chunk_index


class TestPrerollGeneration:
    def test_mid_section_split_gets_preroll_context(self):
        lines = [f"Line {i} with some extra text to pad it out a bit." for i in range(30)]
        text = "# My Section\n\n" + "\n\n".join(lines)
        chunks = chunk_document(text, max_tokens=50, preroll_lines=3)
        if len(chunks) > 1:
            for c in chunks[1:]:
                if not c.text.startswith("# My Section"):
                    assert "Line 0" in c.text or c.heading_path == ["# My Section"]


class TestChunkIndexing:
    def test_chunk_indexes_are_sequential(self):
        text = "# A\n\nText A\n\n# B\n\nText B\n\n# C\n\nText C"
        chunks = chunk_document(text, max_tokens=512)
        for i, c in enumerate(chunks):
            assert c.chunk_index == i

    def test_token_counts_are_positive(self):
        text = "Some text with a few words in it."
        chunks = chunk_document(text, max_tokens=512)
        for c in chunks:
            assert c.token_count > 0
