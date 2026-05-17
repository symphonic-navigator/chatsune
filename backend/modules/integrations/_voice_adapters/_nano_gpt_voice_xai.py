"""nano-gpt voice adapter — routes xAI TTS/STT through nano-gpt.

See devdocs/superpowers/specs/2026-05-17-nano-gpt-voice-design.md.

nano-gpt exposes OpenAI-compatible voice endpoints at
``/v1/audio/speech`` (TTS) and ``/v1/audio/transcriptions`` (STT) and
authenticates them via an ``x-api-key`` header (NOT the ``Authorization:
Bearer`` header used by the LLM endpoints).

The xAI voice model slugs are nano-gpt internal identifiers and aren't in
nano-gpt's public docs as of 2026-05-17; the values here are confirmed
working by nano-gpt's owners.
"""

from __future__ import annotations

import logging

import httpx

from backend.modules.integrations._voice_adapters._base import (
    VoiceAdapter,
    VoiceAdapterError,
    VoiceAuthError,
    VoiceBadRequestError,
    VoiceInfo,
    VoiceRateLimitError,
    VoiceUnavailableError,
    log_upstream_failure,
)

_log = logging.getLogger(__name__)

# Hardcoded — nano-gpt does not expose an xAI voice list endpoint. Keep
# this list in lock-step with the mirror at
# frontend/src/features/integrations/plugins/nano_gpt_voice_xai/voices.ts.
_VOICES: list[VoiceInfo] = [
    VoiceInfo(id="Eve", name="Eve", gender="female"),
    VoiceInfo(id="Ara", name="Ara", gender="female"),
    VoiceInfo(id="Leo", name="Leo", gender="male"),
    VoiceInfo(id="Rex", name="Rex", gender="male"),
    VoiceInfo(id="Sal", name="Sal", gender="neutral"),
]


class NanoGptVoiceXaiAdapter(VoiceAdapter):
    BASE_URL = "https://nano-gpt.com/api/v1"
    TTS_MODEL = "xai-tts"
    STT_MODEL = "xai/speech-to-text/v1"

    # Premium Provider Account slug that carries this adapter's API key.
    PREMIUM_PROVIDER_ID = "nano_gpt"

    def __init__(self, http: httpx.AsyncClient) -> None:
        self._http = http

    async def list_voices(self, api_key: str) -> list[VoiceInfo]:
        # api_key is unused — voice list is hardcoded. We still accept
        # the parameter so the VoiceAdapter contract is honoured.
        return list(_VOICES)

    async def synthesise(
        self, text: str, voice_id: str, api_key: str,
    ) -> tuple[bytes, str]:
        url = f"{self.BASE_URL}/audio/speech"
        payload = {
            "model": self.TTS_MODEL,
            "voice": voice_id,
            "input": text,
        }
        try:
            resp = await self._http.post(
                url, headers=self._auth(api_key), json=payload,
            )
        except (httpx.TimeoutException, httpx.TransportError) as e:
            raise VoiceUnavailableError(str(e)) from e
        self._raise_for_status(
            resp,
            operation="synthesise",
            request_context={
                "url": url,
                "text_len": len(text),
                "voice_id": voice_id,
                "model": self.TTS_MODEL,
            },
        )
        content_type = resp.headers.get("content-type", "audio/mpeg").split(";")[0].strip()
        return resp.content, content_type

    async def transcribe(
        self, audio: bytes, content_type: str, api_key: str, language: str | None,
    ) -> str:
        url = f"{self.BASE_URL}/audio/transcriptions"
        # nano-gpt's OpenAI-compatible endpoint expects the standard
        # Whisper-style ``file`` multipart field plus ``model``.
        #
        # nano-gpt rejects ``audio/webm`` at an early content-type
        # whitelist. webm IS a restricted MKV profile and ffmpeg reads
        # the bytes fine when told to expect MKV, so we spoof the
        # declared container for webm uploads. The audio bytes are
        # unchanged. See INSIGHTS INS-054.
        if "webm" in content_type:
            upload_filename = "audio.mkv"
            upload_content_type = "audio/x-matroska"
        else:
            ext = "wav" if "wav" in content_type else "webm"
            upload_filename = f"audio.{ext}"
            upload_content_type = content_type
        files = {"file": (upload_filename, audio, upload_content_type)}
        data: dict[str, str] = {"model": self.STT_MODEL}
        if language:
            data["language"] = language
        try:
            resp = await self._http.post(
                url, headers=self._auth(api_key), files=files, data=data,
            )
        except (httpx.TimeoutException, httpx.TransportError) as e:
            raise VoiceUnavailableError(str(e)) from e
        self._raise_for_status(
            resp,
            operation="transcribe",
            request_context={
                "url": url,
                "audio_bytes": len(audio),
                "content_type": content_type,
                "language": language,
                "model": self.STT_MODEL,
            },
        )
        body = resp.json()
        return body["text"]

    async def validate_credentials(self, api_key: str) -> None:
        # Cheap probe — reuse nano-gpt's models endpoint that the Premium
        # Provider already hits during account setup.
        url = "https://nano-gpt.com/api/personalized/v1/models"
        try:
            resp = await self._http.get(url, headers=self._auth(api_key))
        except (httpx.TimeoutException, httpx.TransportError) as e:
            raise VoiceUnavailableError(str(e)) from e
        self._raise_for_status(
            resp, operation="validate_credentials", request_context={"url": url},
        )

    def _auth(self, api_key: str) -> dict[str, str]:
        return {"x-api-key": api_key}

    def _raise_for_status(
        self,
        resp: httpx.Response,
        *,
        operation: str | None = None,
        request_context: dict | None = None,
    ) -> None:
        if resp.is_success:
            return
        status = resp.status_code
        if status in (401, 403):
            raise VoiceAuthError()
        if status == 429:
            raise VoiceRateLimitError()
        if status in (400, 422):
            try:
                msg = resp.json().get("error") or resp.text
            except Exception:
                msg = resp.text
            raise VoiceBadRequestError(str(msg))
        if 500 <= status < 600:
            log_upstream_failure(
                _log, "nano_gpt_voice_xai", operation or "unknown",
                resp, request_context or {},
            )
            raise VoiceUnavailableError(f"Upstream {status}")
        raise VoiceAdapterError(f"Unexpected status {status}")
