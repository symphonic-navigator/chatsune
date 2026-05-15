"""Validate compact-markdown output against the required-sections contract."""

import pytest

from backend.modules.chat._compaction import (
    CompactionValidationError,
    validate_compact_markdown,
)


_GOOD_OUTPUT = """\
## Topic & Goal
This conversation is about X.

## Established Facts
- A
- B

## Open Threads
- C

## User Preferences Observed
- D

## Pending References
_(none)_

## Tone & Persona Adherence
Friendly.
"""


def test_valid_output_passes():
    validate_compact_markdown(_GOOD_OUTPUT)


def test_missing_section_raises():
    bad = _GOOD_OUTPUT.replace("## Open Threads", "## Random Heading")
    with pytest.raises(CompactionValidationError):
        validate_compact_markdown(bad)


def test_empty_raises():
    with pytest.raises(CompactionValidationError):
        validate_compact_markdown("")


def test_unclosed_code_fence_raises():
    bad = _GOOD_OUTPUT + "\n```\nleftover"
    with pytest.raises(CompactionValidationError):
        validate_compact_markdown(bad)


def test_accepts_heading_variations_from_real_models():
    """Real models paraphrase headings — single hash, ``and`` instead of
    ``&``, trailing colons, bold-only. We accept any rendering that
    surfaces all six section topics."""
    relaxed = """\
# Topic and Goal:
Talk about something.

# Established Facts:
- a

# Open Thread:
- b

**User Preferences:**
- terse

# Pending References
- file.txt

# Tone and Persona Adherence
Friendly.
"""
    validate_compact_markdown(relaxed)
