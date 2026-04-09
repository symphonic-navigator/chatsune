import base64
import binascii
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings

_PROJECT_ROOT = Path(__file__).parent.parent


class Settings(BaseSettings):
    master_admin_pin: str
    jwt_secret: str
    encryption_key: str  # Fernet key for encrypting API keys at rest
    # Optional: separate signing key for avatar URLs. Falls back to jwt_secret with
    # a startup warning if unset (see backend.modules.persona._avatar_url).
    avatar_signing_key: str | None = None
    mongodb_uri: str = "mongodb://mongodb:27017/chatsune?directConnection=true"
    mongo_db_name: str = "chatsune"
    redis_uri: str = "redis://redis:6379/0"
    upload_root: str = "/data/uploads"
    avatar_root: str = "/data/avatars"
    upload_quota_bytes: int = 1_073_741_824  # 1 GB

    embedding_cache_enabled: bool = True
    embedding_cache_max_entries: int = 16384

    jwt_access_token_expire_minutes: int = 15
    jwt_refresh_token_expire_days: int = 30

    cors_allowed_origins: list[str] = ["http://localhost:5173"]
    cookie_domain: str | None = None

    # Periodic fallback memory extraction interval. 15 minutes in production,
    # override via PERIODIC_EXTRACTION_INTERVAL_SECONDS for local testing.
    periodic_extraction_interval_seconds: int = 900

    # Logging
    log_level: str = "INFO"
    log_console: bool = True
    log_console_format: str = "pretty"  # "pretty" or "json"
    log_file: bool = True
    log_file_path: str = "backend/logs/chatsune.log"
    log_file_backup_count: int = 14
    log_level_uvicorn_access: str = "WARNING"
    log_level_third_party: str = "WARNING"

    model_config = {"env_file": str(_PROJECT_ROOT / ".env"), "extra": "ignore"}

    @field_validator("encryption_key")
    @classmethod
    def _validate_encryption_key(cls, v: str) -> str:
        """Fernet expects a 32-byte url-safe base64-encoded key.

        Validate at startup so a misconfigured key fails fast instead of
        crashing the first time a credential is decrypted at runtime.
        """
        try:
            decoded = base64.urlsafe_b64decode(v.encode())
        except (binascii.Error, ValueError) as exc:
            raise ValueError(
                "encryption_key must be url-safe base64 (Fernet format)",
            ) from exc
        if len(decoded) != 32:
            raise ValueError(
                f"encryption_key must decode to 32 bytes (got {len(decoded)})",
            )
        return v


settings = Settings()
