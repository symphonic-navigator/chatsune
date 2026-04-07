import hashlib
import hmac
import logging
import time

from backend.config import settings

_log = logging.getLogger(__name__)


def _signing_key() -> bytes:
    """Return the avatar URL signing key, falling back to jwt_secret with a warning."""
    if settings.avatar_signing_key:
        return settings.avatar_signing_key.encode()
    _log.warning(
        "avatar_signing_key not configured — falling back to jwt_secret. "
        "Set AVATAR_SIGNING_KEY in .env to separate avatar URL signing from JWTs.",
    )
    return settings.jwt_secret.encode()


def sign_avatar_url(persona_id: str, user_id: str, ttl: int = 3600) -> dict:
    """Generate signed avatar URL query params (expires, sig)."""
    expires = int(time.time()) + ttl
    message = f"{persona_id}:{user_id}:{expires}"
    sig = hmac.new(_signing_key(), message.encode(), hashlib.sha256).hexdigest()
    return {"expires": str(expires), "uid": user_id, "sig": sig}


def verify_avatar_signature(persona_id: str, user_id: str, expires: str, sig: str) -> bool:
    """Verify a signed avatar URL."""
    if int(expires) < int(time.time()):
        return False
    message = f"{persona_id}:{user_id}:{expires}"
    expected = hmac.new(_signing_key(), message.encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(sig, expected)
