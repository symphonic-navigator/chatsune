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
