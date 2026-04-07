from fastapi import Request

from backend.database import get_redis

_LOGIN_RATE_LIMIT = 10  # max attempts
_LOGIN_RATE_WINDOW = 300  # 5 minutes in seconds


def get_client_ip(request: Request) -> str:
    """Resolve the originating client IP, honouring X-Forwarded-For when present.

    Takes the left-most entry of X-Forwarded-For (the original client) and falls
    back to the direct socket peer when the header is absent.
    """
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        first = forwarded.split(",")[0].strip()
        if first:
            return first
    if request.client and request.client.host:
        return request.client.host
    return "unknown"


async def check_login_rate_limit(ip: str) -> bool:
    """Return True if the request is within rate limits, False if blocked."""
    redis = get_redis()
    key = f"rate:login:{ip}"
    count = await redis.incr(key)
    if count == 1:
        await redis.expire(key, _LOGIN_RATE_WINDOW)
    return count <= _LOGIN_RATE_LIMIT
