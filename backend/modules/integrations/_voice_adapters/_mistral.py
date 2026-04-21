"""Mistral voice adapter — TTS + STT + voice cloning via api.mistral.ai.

Mistral exposes OpenAI-compatible endpoints under ``/v1/audio/...`` but the
voice-catalogue / clone / delete endpoints are Mistral-specific. Unlike xAI,
Mistral supports user-supplied voice samples (cloning).

Notable quirks (lifted from the previous browser-side SDK implementation):

* STT model:  ``voxtral-mini-latest`` (multipart/form-data; ``file`` field).
* TTS model:  ``voxtral-mini-tts-2603`` — DIFFERENT snapshot from STT. JSON
  body; response has ``audio_data`` (base64-encoded mp3).
* Clone:      base64-encoded JSON body (NOT multipart); fields
  ``name``, ``sample_audio``, ``sample_filename``.
* List:       paginated via ``limit`` / ``offset``.
"""

from __future__ import annotations

import base64
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

_STT_MODEL = "voxtral-mini-latest"
_TTS_MODEL = "voxtral-mini-tts-2603"
_LIST_PAGE_SIZE = 100


def _filename_for_content_type(content_type: str) -> str:
    """Pick a sensible filename extension from a MIME type.

    Mistral's server inspects the filename extension as a fallback hint
    when the ``Content-Type`` is generic. Mirror the frontend mapping
    so server-side requests match what browser-side callers used to send.
    """
    ct = (content_type or "").lower()
    if ct.startswith("audio/webm"):
        return "recording.webm"
    if ct.startswith("audio/mp4"):
        return "recording.m4a"
    return "recording.wav"


class MistralVoiceAdapter(VoiceAdapter):
    BASE_URL = "https://api.mistral.ai/v1"

    # The slug of the Premium Provider Account that carries this adapter's
    # API key. Matches the ``linked_premium_provider`` on the mistral_voice
    # integration definition.
    PREMIUM_PROVIDER_ID = "mistral"

    def __init__(self, http: httpx.AsyncClient) -> None:
        self._http = http

    # -- Core methods --------------------------------------------------

    async def transcribe(
        self, audio: bytes, content_type: str, api_key: str, language: str | None,
    ) -> str:
        url = f"{self.BASE_URL}/audio/transcriptions"
        filename = _filename_for_content_type(content_type)
        files = {"file": (filename, audio, content_type or "audio/wav")}
        data: dict[str, str] = {"model": _STT_MODEL}
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
                "content_type": content_type or "audio/wav",
                "language": language or "auto",
                "filename": filename,
            },
        )
        body = resp.json()
        return body["text"]

    async def synthesise(
        self, text: str, voice_id: str, api_key: str,
    ) -> tuple[bytes, str]:
        url = f"{self.BASE_URL}/audio/speech"
        payload = {
            "model": _TTS_MODEL,
            "input": text,
            "voice_id": voice_id,
            "stream": False,
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
                "model": _TTS_MODEL,
            },
        )
        body = resp.json()
        # The API returns base64-encoded mp3 under ``audio_data`` (snake_case
        # on the wire; the SDK surfaces it as ``audioData``).
        b64 = body.get("audio_data")
        if not b64:
            raise VoiceUnavailableError("Mistral TTS response missing audio_data")
        mp3_bytes = base64.b64decode(b64)
        return mp3_bytes, "audio/mpeg"

    async def list_voices(self, api_key: str) -> list[VoiceInfo]:
        voices: list[VoiceInfo] = []
        offset = 0
        while True:
            url = (
                f"{self.BASE_URL}/audio/voices"
                f"?limit={_LIST_PAGE_SIZE}&offset={offset}"
            )
            try:
                resp = await self._http.get(url, headers=self._auth(api_key))
            except (httpx.TimeoutException, httpx.TransportError) as e:
                raise VoiceUnavailableError(str(e)) from e
            self._raise_for_status(
                resp,
                operation="list_voices",
                request_context={"url": url, "offset": offset},
            )
            body = resp.json()
            items = body.get("items", []) or []
            for raw in items:
                voices.append(VoiceInfo(
                    id=raw["id"],
                    name=raw.get("name") or raw["id"],
                    # Mistral's voices-list payload does not reliably carry
                    # language or gender; leave them None.
                    language=None,
                    gender=None,
                ))
            page = body.get("page", 1) or 1
            total_pages = body.get("total_pages", 1) or 1
            if page >= total_pages or not items:
                break
            offset += _LIST_PAGE_SIZE
        return voices

    # -- Cloning -------------------------------------------------------

    async def clone_voice(
        self, audio: bytes, content_type: str, name: str, api_key: str,
    ) -> VoiceInfo:
        url = f"{self.BASE_URL}/audio/voices"
        # Mistral's clone endpoint takes base64-encoded audio in a JSON
        # body — NOT multipart. Mirror the previous frontend shape.
        payload = {
            "name": name,
            "sample_audio": base64.b64encode(audio).decode("ascii"),
            "sample_filename": _filename_for_content_type(content_type),
        }
        try:
            resp = await self._http.post(
                url, headers=self._auth(api_key), json=payload,
            )
        except (httpx.TimeoutException, httpx.TransportError) as e:
            raise VoiceUnavailableError(str(e)) from e
        self._raise_for_status(
            resp,
            operation="clone_voice",
            request_context={
                "url": url,
                "audio_bytes": len(audio),
                "content_type": content_type or "audio/wav",
                "name_len": len(name),
            },
        )
        body = resp.json()
        return VoiceInfo(
            id=body["id"],
            name=body.get("name") or name,
            language=None,
            gender=None,
        )

    async def delete_voice(self, voice_id: str, api_key: str) -> None:
        url = f"{self.BASE_URL}/audio/voices/{voice_id}"
        try:
            resp = await self._http.delete(url, headers=self._auth(api_key))
        except (httpx.TimeoutException, httpx.TransportError) as e:
            raise VoiceUnavailableError(str(e)) from e
        self._raise_for_status(
            resp,
            operation="delete_voice",
            request_context={"url": url, "voice_id": voice_id},
        )
        # No response body expected on success.

    # -- Helpers -------------------------------------------------------

    def _auth(self, api_key: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {api_key}"}

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
                body = resp.json()
                # Mistral error shapes vary: {"error": "..."} or
                # {"message": "..."} or {"detail": "..."}.
                msg = (
                    body.get("error")
                    or body.get("message")
                    or body.get("detail")
                    or resp.text
                )
            except Exception:
                msg = resp.text
            raise VoiceBadRequestError(str(msg))
        if 500 <= status < 600:
            # Structured diagnosis log before the raise — mirrors the xAI
            # adapter so Grafana / Loki can filter by adapter=mistral.
            log_upstream_failure(
                _log,
                "mistral",
                operation or "unknown",
                resp,
                request_context or {},
            )
            raise VoiceUnavailableError(f"Upstream {status}")
        # Unexpected status — treat as generic adapter error.
        raise VoiceAdapterError(f"Unexpected status {status}")
