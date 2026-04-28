"""xAI voice adapter — TTS + STT via api.x.ai.

See docs:
  https://docs.x.ai/developers/model-capabilities/audio/text-to-speech
  https://docs.x.ai/developers/model-capabilities/audio/speech-to-text

xAI publishes its own audio endpoints (``/v1/tts`` and ``/v1/stt``) —
they are NOT OpenAI-compatible. The payload shapes differ from OpenAI's
audio API and no ``model`` field is accepted.
"""

from __future__ import annotations

import logging

import httpx

from backend.database import get_db
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

# When the caller does not specify a language, xAI accepts "auto" and
# runs its own language detection. Explicit codes like "en" / "de" are
# also valid and slightly speed up synthesis and transcription.
_DEFAULT_LANGUAGE = "auto"


class XaiVoiceAdapter(VoiceAdapter):
    BASE_URL = "https://api.x.ai/v1"

    # The slug of the Premium Provider Account that carries this adapter's
    # API key. Matches the ``linked_premium_provider`` on the xai_voice
    # integration definition.
    PREMIUM_PROVIDER_ID = "xai"

    def __init__(self, http: httpx.AsyncClient) -> None:
        self._http = http

    async def _resolve_user_key(self, user_id: str) -> str:
        """Return the decrypted xAI API key for ``user_id``.

        Resolves via :class:`PremiumProviderService` so that the key is
        shared with any other integration / LLM connection the user has
        configured for xAI. Raises :class:`LookupError` if the user has
        no configured Premium Provider Account for xAI.
        """
        # Deferred import to avoid a circular import at module load time
        # (providers → integrations, in some startup paths).
        from backend.modules.providers import (
            PremiumProviderAccountRepository,
            PremiumProviderService,
        )
        svc = PremiumProviderService(PremiumProviderAccountRepository(get_db()))
        key = await svc.get_decrypted_secret(
            user_id, self.PREMIUM_PROVIDER_ID, "api_key",
        )
        if key is None:
            raise LookupError(
                f"No Premium Provider Account configured for provider "
                f"'{self.PREMIUM_PROVIDER_ID}' (user={user_id})"
            )
        return key

    async def list_voices(self, api_key: str) -> list[VoiceInfo]:
        url = f"{self.BASE_URL}/tts/voices"
        try:
            resp = await self._http.get(url, headers=self._auth(api_key))
        except (httpx.TimeoutException, httpx.TransportError) as e:
            raise VoiceUnavailableError(str(e)) from e
        self._raise_for_status(
            resp,
            operation="list_voices",
            request_context={"url": url},
        )
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
        # POST /v1/stt, multipart/form-data — NOT /v1/audio/transcriptions.
        # Fields: file (required), language (optional), format (optional;
        # enables text normalisation, needs a concrete language code so
        # we only set it when one was provided).
        url = f"{self.BASE_URL}/stt"
        ext = "wav" if "wav" in content_type else "webm"
        files = {"file": (f"audio.{ext}", audio, content_type)}
        data: dict[str, str] = {}
        if language is not None and language != _DEFAULT_LANGUAGE:
            data["language"] = language
            data["format"] = "true"
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
                "language": language or _DEFAULT_LANGUAGE,
                "filename_ext": ext,
            },
        )
        body = resp.json()
        return body["text"]

    async def synthesise(
        self, text: str, voice_id: str, api_key: str,
    ) -> tuple[bytes, str]:
        # POST /v1/tts, JSON — NOT /v1/audio/speech. xAI does not accept
        # a ``model`` field; the provider chooses the current TTS model
        # internally. Response is mp3 bytes.
        url = f"{self.BASE_URL}/tts"
        payload: dict[str, str] = {
            "text": text,
            "voice_id": voice_id,
            "language": _DEFAULT_LANGUAGE,
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
                "language": _DEFAULT_LANGUAGE,
            },
        )
        content_type = resp.headers.get("content-type", "audio/mpeg").split(";")[0].strip()
        return resp.content, content_type

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
                msg = resp.json().get("error") or resp.text
            except Exception:
                msg = resp.text
            raise VoiceBadRequestError(str(msg))
        if 500 <= status < 600:
            # Structured diagnosis log before the raise so the handler-
            # level retry log and the adapter-level upstream log can be
            # correlated per attempt.
            log_upstream_failure(
                _log,
                "xai",
                operation or "unknown",
                resp,
                request_context or {},
            )
            raise VoiceUnavailableError(f"Upstream {status}")
        # Unexpected status — treat as unavailable
        raise VoiceAdapterError(f"Unexpected status {status}")
