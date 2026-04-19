"""xAI voice adapter — TTS + STT via api.x.ai.

See docs:
  https://docs.x.ai/developers/model-capabilities/audio/text-to-speech
  https://docs.x.ai/developers/model-capabilities/audio/speech-to-text
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
)

_log = logging.getLogger(__name__)


class XaiVoiceAdapter(VoiceAdapter):
    BASE_URL = "https://api.x.ai/v1"
    # Model identifiers are fixed by xAI — one model per capability.
    # Update here if / when xAI releases new model generations.
    TTS_MODEL = "grok-tts-1"
    STT_MODEL = "grok-stt-1"

    def __init__(self, http: httpx.AsyncClient) -> None:
        self._http = http

    async def list_voices(self, api_key: str) -> list[VoiceInfo]:
        url = f"{self.BASE_URL}/tts/voices"
        try:
            resp = await self._http.get(url, headers=self._auth(api_key))
        except (httpx.TimeoutException, httpx.TransportError) as e:
            raise VoiceUnavailableError(str(e)) from e
        self._raise_for_status(resp)
        data = resp.json()
        return [
            VoiceInfo(
                id=v.get("voice_id") or v["id"],
                name=v["name"],
                language=v.get("language"),
                gender=v.get("gender"),
            )
            for v in data.get("voices", [])
        ]

    async def transcribe(
        self, audio: bytes, content_type: str, api_key: str, language: str | None,
    ) -> str:
        raise NotImplementedError  # implemented in a later task

    async def synthesise(
        self, text: str, voice_id: str, api_key: str,
    ) -> tuple[bytes, str]:
        raise NotImplementedError  # implemented in a later task

    def _auth(self, api_key: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {api_key}"}

    def _raise_for_status(self, resp: httpx.Response) -> None:
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
            raise VoiceUnavailableError(f"Upstream {status}")
        # Unexpected status — treat as unavailable
        raise VoiceAdapterError(f"Unexpected status {status}")
