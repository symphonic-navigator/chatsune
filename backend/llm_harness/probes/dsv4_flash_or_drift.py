"""Drift probe for the OR-Flash xhigh quirk (see ``_quirks.py``).

Run quarterly:
    uv run python -m backend.llm_harness.probes.dsv4_flash_or_drift

Reads the OR API key from ``.or-test-key`` in the project root.

Verdict logic: ratio = xhigh_reasoning_tokens / high_reasoning_tokens.
- ratio < 0.85 → STILL BROKEN (OR's xhigh halves Flash reasoning)
- ratio > 1.15 → FIXED (or different bug — investigate before relying)
- otherwise   → INCONCLUSIVE (ratio in noise band; re-run with a different prompt)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import httpx


_OR_URL = "https://openrouter.ai/api/v1/chat/completions"
_MODEL = "deepseek/deepseek-v4-flash"
_PROMPT = (
    "Finde drei strukturell verschiedene Beweise für die Unendlichkeit "
    "der Primzahlen (mindestens einer muss nicht-konstruktiv oder "
    "analytisch sein) und vergleiche ihre Eleganz, Stärke und welche "
    "Verallgemeinerungen sie nahelegen."
)


def _load_key() -> str:
    candidates = [
        Path(__file__).resolve().parents[3] / ".or-test-key",  # repo root
        Path.cwd() / ".or-test-key",
    ]
    for path in candidates:
        if path.is_file():
            return path.read_text().strip()
    raise SystemExit(
        "could not locate .or-test-key — looked in: "
        + ", ".join(str(p) for p in candidates)
    )


def _probe(client: httpx.Client, api_key: str, effort: str) -> dict[str, Any]:
    body = {
        "model": _MODEL,
        "messages": [{"role": "user", "content": _PROMPT}],
        "stream": False,
        "reasoning": {"effort": effort},
    }
    response = client.post(
        _OR_URL,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        content=json.dumps(body),
        timeout=120.0,
    )
    response.raise_for_status()
    return response.json()


def _reasoning_tokens(payload: dict[str, Any]) -> int:
    usage = payload.get("usage") or {}
    details = usage.get("completion_tokens_details") or {}
    tokens = details.get("reasoning_tokens")
    if tokens is None:
        raise SystemExit(
            f"no reasoning_tokens in payload: {json.dumps(payload)[:300]}"
        )
    return int(tokens)


def main() -> int:
    api_key = _load_key()
    with httpx.Client() as client:
        print(f"probing {_MODEL} @ openrouter, effort=high (baseline)…", flush=True)
        high_payload = _probe(client, api_key, "high")
        high_tokens = _reasoning_tokens(high_payload)
        print(f"  reasoning_tokens={high_tokens}", flush=True)

        print(f"probing {_MODEL} @ openrouter, effort=xhigh (test)…", flush=True)
        xhigh_payload = _probe(client, api_key, "xhigh")
        xhigh_tokens = _reasoning_tokens(xhigh_payload)
        print(f"  reasoning_tokens={xhigh_tokens}", flush=True)

    if high_tokens == 0:
        print("\nERROR: baseline returned zero reasoning_tokens — probe inconclusive")
        return 2

    ratio = xhigh_tokens / high_tokens
    print()
    print(f"ratio (xhigh / high) = {ratio:.2f}")
    if ratio < 0.85:
        print("verdict: STILL BROKEN — keep capability override + builder downgrade")
        return 1
    if ratio > 1.15:
        print("verdict: FIXED (or different bug — investigate)")
        print("  → drop the override in _capability.py and _builders.py")
        print("  → drop _is_or_flash_quirk_applicable from _quirks.py")
        return 0
    print("verdict: INCONCLUSIVE (ratio in noise band)")
    print("  → re-run with a different reasoning-demanding prompt")
    return 3


if __name__ == "__main__":
    sys.exit(main())
