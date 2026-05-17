# Nano-GPT Voice (xAI) Integration — Design

**Date:** 2026-05-17
**Status:** Draft, awaiting review
**Scope:** Make nano-gpt a TTS and STT provider by routing voice calls to xAI through nano-gpt's API. First-cut covers xAI's five voices; the architecture leaves room for additional backends (Mistral, ElevenLabs, …) without restructuring.

---

## 1. Context

Nano-gpt is already wired into Chatsune as a Premium Provider for LLM and TTI (image generation). Holding a nano-gpt API key has become a near-universal baseline in the community because nano-gpt acts as a "Swiss-army-knife" aggregator: one key unlocks dozens of upstream providers under a single account and billing relationship.

xAI Voice is currently available in Chatsune only through a direct xAI integration (`xai_voice`). Voice users therefore need two paid accounts (xAI for voice + nano-gpt for everything else) to get the full stack. Adding xAI Voice through nano-gpt collapses this to one account and is expected to roughly tenfold the user base that can use voice mode out of the box.

The nano-gpt docs do not yet list the xAI voice routes, but nano-gpt's owners have confirmed availability. Voice names are not exposed by any list endpoint; we hardcode them for now.

## 2. Goals

- Add `TTS` and `STT` to the `nano_gpt` Premium Provider's capability list so the UI badges reflect what the key unlocks.
- Add a new Integration `nano_gpt_voice_xai` (display: "xAI Voice via nano-gpt") that exposes xAI TTS and STT through nano-gpt.
- Hardcode the five xAI voices (Eve, Ara, Leo, Rex, Sal).
- Keep the door open for future backends (Mistral via nano-gpt, ElevenLabs via nano-gpt) by making the integration backend-specific, not generic.

## 3. Non-Goals

- **Other nano-gpt voice backends** (Mistral, ElevenLabs, MiniMax voice clone, Qwen voice clone). Each gets its own Integration when added; this spec ships only the xAI one.
- **Translation layer for expression markup across backends.** Our existing expression-tag vocabulary is 1:1 xAI's — we built the markup feature specifically for xAI. The user has confirmed (via manual testing on the nano-gpt website, 2026-05-17) that nano-gpt passes the tags straight through to xAI. We therefore keep `tts_expressive_markup` on the integration. If a future Mistral/ElevenLabs backend lands behind nano-gpt, that's when a translation layer becomes relevant — out of scope here.
- **Voice cloning.** xAI has no cloning endpoint. Not exposed.
- **Data-model migrations.** The change is purely additive — new Integration entry, new adapter file, no field changes to existing personas or users.
- **Replacing the direct `xai_voice` integration.** Users who already have an xAI account keep using it. The new integration is parallel.

## 4. Architecture

### 4.1 Premium Provider capability extension

Update `backend/modules/providers/_registry.py:113-125`:

```python
register(PremiumProviderDefinition(
    id="nano_gpt",
    ...
    capabilities=[Capability.LLM, Capability.TTI, Capability.TTS, Capability.STT],
    ...
))
```

UI effect: `PremiumAccountCard.tsx:120-140` and `CoverageRow.tsx:9-40` automatically render TTS and STT badges for the nano-gpt account. No frontend code change.

### 4.2 New Integration entry

Add to `backend/modules/integrations/_registry.py` (alongside `xai_voice` and `mistral_voice` at lines 170-283):

```python
register(IntegrationDefinition(
    id="nano_gpt_voice_xai",
    display_name="xAI Voice via nano-gpt",
    description="Speech-to-text and text-to-speech via xAI, routed through nano-gpt. Uses the nano-gpt account's API key — no separate xAI account required.",
    icon="nano_gpt",
    execution_mode="hybrid",
    hydrate_secrets=False,
    system_prompt_template=build_system_prompt_extension(),
    capabilities=[
        IntegrationCapability.TTS_PROVIDER,
        IntegrationCapability.STT_PROVIDER,
        IntegrationCapability.TTS_EXPRESSIVE_MARKUP,
    ],
    linked_premium_provider="nano_gpt",
    config_fields=[
        {
            "key": "playback_gap_ms",
            "label": "Pause between chunks",
            "field_type": "select",
            "required": False,
            "description": (
                "Gap inserted between sentences and speaker switches. "
                "xAI already leaves a natural silence at sentence ends, "
                "so no extra gap is needed by default."
            ),
            "options": [
                {"value": "0",   "label": "0 ms (default)"},
                {"value": "100", "label": "100 ms"},
                {"value": "200", "label": "200 ms"},
                {"value": "300", "label": "300 ms"},
                {"value": "400", "label": "400 ms"},
                {"value": "500", "label": "500 ms"},
                {"value": "600", "label": "600 ms"},
                {"value": "700", "label": "700 ms"},
                {"value": "800", "label": "800 ms"},
            ],
        },
    ],
    persona_config_fields=[
        {
            "key": "voice_id",
            "label": "Voice",
            "field_type": "select",
            "options_source": OptionsSource.PLUGIN,
            "required": True,
            "description": "Voice used when this persona speaks.",
        },
        {
            "key": "narrator_voice_id",
            "label": "Narrator Voice",
            "field_type": "select",
            "options_source": OptionsSource.PLUGIN,
            "required": False,
            "description": (
                "Voice used for narration / prose when narrator mode "
                "is active. Leave at 'Inherit' to use the primary voice."
            ),
        },
    ],
    tool_definitions=[],
))
```

All shapes mirror `xai_voice` exactly (see `_registry.py:223-283`) with three deltas: `linked_premium_provider="nano_gpt"`, the display name, and a description that names the proxy relationship. Crucially, `system_prompt_template=build_system_prompt_extension()` is kept identical — without the prompt extension the LLM won't generate xAI's expression tags, and `TTS_EXPRESSIVE_MARKUP` would be meaningless. The integration inherits the nano-gpt API key from the linked Premium Provider account.

### 4.3 New voice adapter

New file: `backend/modules/integrations/_voice_adapters/_nano_gpt_voice_xai.py`. Inherits from `VoiceAdapter` (base: `_voice_adapters/_base.py:60-108`).

**Constants:**
- `BASE_URL = "https://nano-gpt.com/api/v1"`
- `TTS_MODEL = "xai-tts"`
- `STT_MODEL = "xai/speech-to-text/v1"`
- `VOICES = [Eve, Ara, Leo, Rex, Sal]` — see §4.4.

**Auth header:** `x-api-key: <key>`. Per nano-gpt voice docs this differs from the `Authorization: Bearer …` header used by the LLM adapter. If the smoke test in §6 shows nano-gpt also accepts Bearer on voice routes, we can unify later; for now the spec follows the docs.

**`synthesise(text, voice_id, api_key) -> (bytes, content_type)`:**
- `POST {BASE_URL}/audio/speech`
- JSON body: `{"model": "xai-tts", "voice": voice_id, "input": text}`
- Response: binary audio. Content-Type from response header (`audio/mpeg` expected).
- `voice_id` is the plain voice name ("Eve", "Ara", …), straight from the hardcoded list.

**`transcribe(audio, content_type, api_key, language) -> str`:**
- `POST {BASE_URL}/audio/transcriptions` (OpenAI-compatible)
- `multipart/form-data` with `file=<audio>`, `model="xai/speech-to-text/v1"`, optional `language=<iso639-1>`
- Response: JSON Whisper-style `{"text": "...", ...}` → return `text`.

**`list_voices(api_key) -> list[VoiceInfo]`:**
Hardcoded — nano-gpt does not expose an xAI voice list endpoint:

```python
[
    VoiceInfo(id="Eve", name="Eve", gender="female"),
    VoiceInfo(id="Ara", name="Ara", gender="female"),
    VoiceInfo(id="Leo", name="Leo", gender="male"),
    VoiceInfo(id="Rex", name="Rex", gender="male"),
    VoiceInfo(id="Sal", name="Sal", gender="neutral"),
]
```

Gender assignments are best-guess from names — useful for sorting/icons. If xAI's actual assignments differ we'll correct in a follow-up.

**`validate_credentials(api_key)`:** light `GET https://nano-gpt.com/api/personalized/v1/models` with the API key — same probe the Premium Provider already uses.

**`clone_voice` / `delete_voice`:** raise `NotImplementedError`. Capability is not advertised.

**Registration:** add to `_register_builtin_voice_adapters()` (currently around `_registry.py:304-315`) so the adapter is wired up at module import.

### 4.4 Voice list — single source of truth

The hardcoded list lives in the Python adapter. The frontend re-declares it for client-side display hints only; the authoritative list flows from the backend through the existing integration-listing API. Add a note to the top of both files reminding future-us to keep them aligned (same pattern as `_voice_expression_tags.py` / `expressionTags.ts` already used in the codebase).

Files:
- `backend/modules/integrations/_voice_adapters/_nano_gpt_voice_xai.py` (authoritative)
- `frontend/src/features/integrations/plugins/nano_gpt_voice_xai/voices.ts` (display mirror)

### 4.5 Frontend plugin

New directory: `frontend/src/features/integrations/plugins/nano_gpt_voice_xai/`, parallel to the existing `xai_voice/`:

- `index.ts` — plugin registration; mounts engines.
- `ttsEngine.ts` — implements the TTS engine interface; calls the backend integration endpoint for TTS.
- `sttEngine.ts` — analogous STT engine; calls the backend integration endpoint for STT.
- `voices.ts` — mirror of the backend voice list (display hint, not authoritative).

Engines register in `ttsRegistry` / `sttRegistry`. The resolver at `frontend/src/features/voice/engines/resolver.ts:51-73` picks them up automatically once the integration is enabled:

- **Persona-side (TTS):** when `persona.voice_config.tts_provider_id === "nano_gpt_voice_xai"`.
- **User-side (STT):** when `voiceSettingsStore.stt_provider_id === "nano_gpt_voice_xai"`.

### 4.6 Persona-config UI

No new components. The persona voice-config view iterates over `tts_provider`-capable integrations from the integrations-listing API and renders each one's `persona_config_fields`. The new integration appears as a selectable TTS provider in the dropdown, labelled "xAI Voice via nano-gpt", with the five voices in the Voice and Narrator Voice selectors.

### 4.7 User-STT-settings UI

No new components. The user voice-settings panel already lists `stt_provider`-capable integrations. The new integration appears automatically as "xAI Voice via nano-gpt".

## 5. Data flow

### TTS (Persona speaks)

```
Persona view → TTS engine (nano_gpt_voice_xai) →
  backend /api/integrations/nano_gpt_voice_xai/tts →
    _nano_gpt_voice_xai.synthesise() →
      POST https://nano-gpt.com/api/v1/audio/speech (x-api-key) →
    audio bytes → response → frontend audio sink
```

### STT (User speaks)

```
Mic capture → STT engine (nano_gpt_voice_xai) →
  backend /api/integrations/nano_gpt_voice_xai/stt (multipart) →
    _nano_gpt_voice_xai.transcribe() →
      POST https://nano-gpt.com/api/v1/audio/transcriptions (x-api-key) →
    {"text": "..."} → response → chat input
```

Both the `/api/integrations/<id>/tts` and `/api/integrations/<id>/stt` routes exist generically — the integration ID dispatches to the registered adapter. No new HTTP routes.

## 6. Verification — Roundtrip smoke test

Image gen against nano-gpt diverged from the documented shapes in subtle ways. We will not assume the voice routes match the docs verbatim.

A smoke-test script lands in `backend/llm_harness/` (next to existing LLM harness tools), reading the API key from `.nano-test-key` (gitignored, repo-root, plain text — same pattern as `.llm-test-key`):

1. Read API key from `.nano-test-key`.
2. Pick a fixed sample sentence (something distinctive, e.g. "The quick brown fox jumps over the lazy dog.").
3. TTS call → audio bytes. Assert HTTP 200, `content-length > 0`, content-type starts with `audio/`.
4. Feed the same bytes into the STT call.
5. Assert HTTP 200, returned `text` is non-empty. Recognisable-match heuristic: lowercase both strings, split on whitespace, require at least 60% of original word tokens to appear in the transcription. (Whisper-class STT is reliable enough on a known sentence; exact-match is too strict because of punctuation/casing differences.)

If any of (auth header, request body field names, response keys, content-types) deviate from this spec, fix the adapter before declaring the work done. Update §4.3 inline if the request shape diverges.

The smoke test is also useful as a permanent regression check.

## 7. Build verification

- Frontend: `pnpm tsc --noEmit` clean.
- Backend: `uv run python -m py_compile <new files>` clean.
- Roundtrip smoke test passes against the live nano-gpt API (§6).

## 8. Rollout

Single commit (per project convention: spec + implementation squashed before merge to master). No staged feature flag — additive integration, default-off until a user selects it in persona or settings.

## 9. Risks & open questions

| Risk | Mitigation |
|------|------------|
| ~~nano-gpt strips xAI expression tags inside the input text~~ | **Resolved before implementation:** user-confirmed via website testing that tags pass through. No action needed. |
| Voice names diverge from xAI's actual catalogue (gender, casing, missing voice) | Smoke test verifies each voice produces audio. If any voice 4xx's, remove from the list. |
| Auth header is Bearer instead of `x-api-key` on voice routes | Smoke test will 401 — try the other header, update §4.3, move on. |
| nano-gpt voice routes return async `runId` rather than synchronous audio | Smoke test will surface this. If async, add polling against `/v1/audio/speech/status` (or equivalent) and stash the URL. |
| Future Mistral-via-nano-gpt arrives and we need to refactor voice naming | Not a real risk — current design supports it via a second Integration with no changes to the xAI one. |
| User enables both `xai_voice` and `nano_gpt_voice_xai` simultaneously, double-applying the expression-tag system-prompt extension | Low impact (redundant text in the system prompt). Acceptable; revisit if it surfaces in practice. |
