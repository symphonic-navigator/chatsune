"""Roundtrip smoke test: TTS → STT against live nano-gpt (xAI backend).

Usage:
    uv run python -m backend.llm_harness.nano_gpt_voice_roundtrip

Reads the API key from ``.nano-test-key`` (repo root, plain text,
gitignored).

Why this exists: nano-gpt's voice routes are not formally documented for
xAI, and we have seen documented shapes diverge for image-gen. This
script exercises the real adapter end-to-end and prints the request /
response shapes so any divergence from
``devdocs/superpowers/specs/2026-05-17-nano-gpt-voice-design.md``
surfaces immediately.
"""

from __future__ import annotations

import asyncio
import re
import sys
from pathlib import Path

import httpx

from backend.modules.integrations._voice_adapters._nano_gpt_voice_xai import (
    NanoGptVoiceXaiAdapter,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
KEY_FILE = REPO_ROOT / ".nano-test-key"

SAMPLE_TEXT = "The quick brown fox jumps over the lazy dog."
SAMPLE_VOICE = "Eve"
SAMPLE_LANG = "en"


def _word_overlap(a: str, b: str) -> float:
    """Return the fraction of ``a``'s tokens that appear in ``b``."""
    tokens_a = set(re.findall(r"[a-z]+", a.lower()))
    tokens_b = set(re.findall(r"[a-z]+", b.lower()))
    if not tokens_a:
        return 0.0
    return len(tokens_a & tokens_b) / len(tokens_a)


async def main() -> int:
    if not KEY_FILE.exists():
        print(f"ERROR: API key file not found at {KEY_FILE}")
        return 2
    api_key = KEY_FILE.read_text().strip()
    if not api_key:
        print(f"ERROR: API key file at {KEY_FILE} is empty")
        return 2

    async with httpx.AsyncClient(timeout=60.0) as client:
        adapter = NanoGptVoiceXaiAdapter(client)

        print(f"→ TTS: model={adapter.TTS_MODEL!r} voice={SAMPLE_VOICE!r} "
              f"text={SAMPLE_TEXT!r}")
        audio_bytes, ctype = await adapter.synthesise(
            text=SAMPLE_TEXT, voice_id=SAMPLE_VOICE, api_key=api_key,
        )
        print(f"  ← {len(audio_bytes)} bytes  content-type={ctype}")
        if len(audio_bytes) == 0:
            print("FAIL: TTS returned empty audio")
            return 1

        print(f"→ STT: model={adapter.STT_MODEL!r} language={SAMPLE_LANG!r}")
        text = await adapter.transcribe(
            audio=audio_bytes,
            content_type=ctype,
            api_key=api_key,
            language=SAMPLE_LANG,
        )
        print(f"  ← text={text!r}")
        overlap = _word_overlap(SAMPLE_TEXT, text)
        print(f"  ← word overlap with original: {overlap:.0%}")
        if overlap < 0.6:
            print(f"FAIL: STT transcription differs too much from original "
                  f"(overlap {overlap:.0%}, need ≥60%)")
            return 1

    print("OK: roundtrip succeeded")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
