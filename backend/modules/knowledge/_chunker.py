"""Document chunker — ported from the Prototype 2 C# DocumentChunker.

Splits documents by heading structure, then by paragraphs, sentences, and
finally hard word boundaries. Merges tiny adjacent chunks and prepends
preroll context for mid-section splits.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import tiktoken

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+)$", re.MULTILINE)
_PARAGRAPH_SPLIT_RE = re.compile(r"\n\s*\n")
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")

_ENCODING = tiktoken.get_encoding("cl100k_base")


def _count_tokens(text: str) -> int:
    return len(_ENCODING.encode(text))


@dataclass(frozen=True)
class DocumentChunk:
    chunk_index: int
    text: str
    heading_path: list[str]
    preroll_text: str
    token_count: int


@dataclass
class _SectionCandidate:
    text: str
    heading_path: list[str]  # full heading strings, e.g. ["# Top", "## Sub"]


@dataclass
class _ChunkCandidate:
    text: str
    heading_path: list[str]
    preroll_text: str


def _heading_level(heading_line: str) -> int:
    """Return the numeric level of a heading string like '## Sub'."""
    return len(heading_line) - len(heading_line.lstrip("#"))


def _build_preroll(heading_path: list[str]) -> str:
    return " > ".join(heading_path)


def _hard_split(text: str, max_tokens: int) -> list[str]:
    """Split text into word-boundary chunks when no other split point works."""
    words = text.split()
    chunks: list[str] = []
    current: list[str] = []
    current_tokens = 0

    for word in words:
        word_tokens = _count_tokens(word + " ")
        if current_tokens + word_tokens > max_tokens and current:
            chunks.append(" ".join(current))
            current = [word]
            current_tokens = word_tokens
        else:
            current.append(word)
            current_tokens += word_tokens

    if current:
        chunks.append(" ".join(current))

    return chunks


def _split_text(text: str, max_tokens: int) -> list[str]:
    """Recursively split text until every piece is within max_tokens."""
    if _count_tokens(text) <= max_tokens:
        return [text]

    # Try paragraph boundaries first
    paragraphs = _PARAGRAPH_SPLIT_RE.split(text)
    if len(paragraphs) > 1:
        results: list[str] = []
        for para in paragraphs:
            results.extend(_split_text(para, max_tokens))
        return results

    # Try sentence boundaries
    sentences = _SENTENCE_SPLIT_RE.split(text)
    if len(sentences) > 1:
        # Accumulate sentences into groups that fit within max_tokens
        results = []
        current_sentences: list[str] = []
        current_tokens = 0
        for sentence in sentences:
            sentence_tokens = _count_tokens(sentence)
            if current_tokens + sentence_tokens > max_tokens and current_sentences:
                results.append(" ".join(current_sentences))
                current_sentences = [sentence]
                current_tokens = sentence_tokens
            else:
                current_sentences.append(sentence)
                current_tokens += sentence_tokens
        if current_sentences:
            results.append(" ".join(current_sentences))
        return results

    # Last resort: hard word split
    return _hard_split(text, max_tokens)


def _split_into_sections(content: str) -> list[_SectionCandidate]:
    """Split content at heading boundaries, tracking the heading hierarchy."""
    sections: list[_SectionCandidate] = []
    heading_stack: list[str] = []  # heading strings in current path

    # Find all heading positions
    heading_matches = list(_HEADING_RE.finditer(content))

    if not heading_matches:
        # No headings — the whole document is one section
        stripped = content.strip()
        if stripped:
            sections.append(_SectionCandidate(text=stripped, heading_path=[]))
        return sections

    # Text before first heading
    preamble = content[: heading_matches[0].start()].strip()
    if preamble:
        sections.append(_SectionCandidate(text=preamble, heading_path=[]))

    for i, match in enumerate(heading_matches):
        level = len(match.group(1))  # number of # characters
        heading_str = match.group(0).rstrip()

        # Pop headings at the same or deeper level
        heading_stack = [h for h in heading_stack if _heading_level(h) < level]
        heading_stack.append(heading_str)

        # The section body is the text between this heading and the next
        body_start = match.end()
        body_end = heading_matches[i + 1].start() if i + 1 < len(heading_matches) else len(content)
        body = content[body_start:body_end].strip()

        # Include the heading line itself in the section text
        section_text = heading_str
        if body:
            section_text = heading_str + "\n\n" + body

        sections.append(
            _SectionCandidate(
                text=section_text,
                heading_path=list(heading_stack),
            )
        )

    return sections


def _section_to_chunks(
    section: _SectionCandidate,
    max_tokens: int,
    preroll_lines: int,
) -> list[_ChunkCandidate]:
    """Convert a section into one or more chunk candidates."""
    text = section.text.strip()
    heading_path = section.heading_path
    base_preroll = _build_preroll(heading_path)

    if _count_tokens(text) <= max_tokens:
        return [_ChunkCandidate(text=text, heading_path=heading_path, preroll_text=base_preroll)]

    # Section is too large — split it
    pieces = _split_text(text, max_tokens)

    # Determine preroll context lines from the start of the section
    all_lines = text.splitlines()
    context_lines = [ln for ln in all_lines[:preroll_lines] if ln.strip()]

    chunks: list[_ChunkCandidate] = []
    for idx, piece in enumerate(pieces):
        piece = piece.strip()
        if not piece:
            continue

        if idx == 0:
            # First piece carries only the heading preroll
            chunk_preroll = base_preroll
        else:
            # Subsequent pieces prepend context lines from the start of the section
            if context_lines:
                preroll_parts = context_lines + ([base_preroll] if base_preroll else [])
                chunk_preroll = "\n".join(preroll_parts)
            else:
                chunk_preroll = base_preroll

        chunks.append(
            _ChunkCandidate(
                text=piece,
                heading_path=heading_path,
                preroll_text=chunk_preroll,
            )
        )

    return chunks


def _merge_small_chunks(
    candidates: list[_ChunkCandidate],
    max_tokens: int,
    merge_threshold: int,
) -> list[_ChunkCandidate]:
    """Merge adjacent chunks that share the same heading path when either is tiny."""
    if not candidates:
        return []

    merged: list[_ChunkCandidate] = [candidates[0]]

    for current in candidates[1:]:
        previous = merged[-1]

        # Only merge if both share the same heading path
        if previous.heading_path != current.heading_path:
            merged.append(current)
            continue

        prev_tokens = _count_tokens(previous.text)
        curr_tokens = _count_tokens(current.text)

        # Merge if either is below threshold and the combined result fits
        if (prev_tokens < merge_threshold or curr_tokens < merge_threshold) and (
            prev_tokens + curr_tokens <= max_tokens
        ):
            combined_text = previous.text + "\n\n" + current.text
            # Keep the preroll from the first chunk
            merged[-1] = _ChunkCandidate(
                text=combined_text,
                heading_path=previous.heading_path,
                preroll_text=previous.preroll_text,
            )
        else:
            merged.append(current)

    return merged


def chunk_document(
    content: str,
    max_tokens: int = 512,
    merge_threshold: int = 64,
    preroll_lines: int = 3,
) -> list[DocumentChunk]:
    """Split a Markdown document into embedding-sized chunks.

    Args:
        content: Raw document text (Markdown).
        max_tokens: Maximum tokens per chunk (cl100k_base encoding).
        merge_threshold: Chunks below this token count are candidates for merging.
        preroll_lines: Number of context lines prepended to mid-section chunks.

    Returns:
        Ordered list of DocumentChunk objects with sequential chunk_index values.
    """
    if not content or not content.strip():
        return []

    sections = _split_into_sections(content)

    candidates: list[_ChunkCandidate] = []
    for section in sections:
        candidates.extend(_section_to_chunks(section, max_tokens, preroll_lines))

    candidates = _merge_small_chunks(candidates, max_tokens, merge_threshold)

    return [
        DocumentChunk(
            chunk_index=i,
            text=c.text,
            heading_path=c.heading_path,
            preroll_text=c.preroll_text,
            token_count=_count_tokens(c.text),
        )
        for i, c in enumerate(candidates)
    ]
