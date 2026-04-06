from backend.database import get_redis

_LOGIN_RATE_LIMIT = 10  # max attempts
_LOGIN_RATE_WINDOW = 300  # 5 minutes in seconds


async def check_login_rate_limit(ip: str) -> bool:
    """Return True if the request is within rate limits, False if blocked."""
    redis = get_redis()
    key = f"rate:login:{ip}"
    count = await redis.incr(key)
    if count == 1:
        await redis.expire(key, _LOGIN_RATE_WINDOW)
    return count <= _LOGIN_RATE_LIMIT
