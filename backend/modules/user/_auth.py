import secrets
import string
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import bcrypt
import jwt

from backend.config import settings

JWT_ISSUER = "chatsune"
JWT_AUDIENCE = "chatsune"


def hash_password(password: str) -> str:
    return bcrypt.hashpw(
        password.encode(), bcrypt.gensalt()
    ).decode()


def verify_password(password: str, password_hash: str) -> bool:
    return bcrypt.checkpw(
        password.encode(), password_hash.encode()
    )


def generate_random_password(length: int = 20) -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


def create_access_token(
    user_id: str,
    role: str,
    session_id: str,
    must_change_password: bool = False,
    expires_delta: timedelta | None = None,
) -> str:
    if expires_delta is None:
        expires_delta = timedelta(
            minutes=settings.jwt_access_token_expire_minutes
        )
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "role": role,
        "session_id": session_id,
        "iat": now,
        "exp": now + expires_delta,
        "iss": JWT_ISSUER,
        "aud": JWT_AUDIENCE,
    }
    if must_change_password:
        payload["mcp"] = True
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


def decode_access_token(token: str) -> dict:
    return jwt.decode(
        token,
        settings.jwt_secret,
        algorithms=["HS256"],
        audience=JWT_AUDIENCE,
        issuer=JWT_ISSUER,
    )


def generate_refresh_token() -> str:
    return secrets.token_urlsafe(48)


def generate_session_id() -> str:
    return str(uuid4())
