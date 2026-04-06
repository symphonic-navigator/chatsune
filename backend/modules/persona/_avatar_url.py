import hashlib
import hmac
import time

from backend.config import settings


def sign_avatar_url(persona_id: str, user_id: str, ttl: int = 3600) -> dict:
    """Generate signed avatar URL query params (expires, sig)."""
    expires = int(time.time()) + ttl
    message = f"{persona_id}:{user_id}:{expires}"
    sig = hmac.new(
        settings.jwt_secret.encode(), message.encode(), hashlib.sha256
    ).hexdigest()
    return {"expires": str(expires), "uid": user_id, "sig": sig}


def verify_avatar_signature(persona_id: str, user_id: str, expires: str, sig: str) -> bool:
    """Verify a signed avatar URL."""
    if int(expires) < int(time.time()):
        return False
    message = f"{persona_id}:{user_id}:{expires}"
    expected = hmac.new(
        settings.jwt_secret.encode(), message.encode(), hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(sig, expected)
