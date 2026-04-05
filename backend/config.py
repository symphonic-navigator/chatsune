from pathlib import Path

from pydantic_settings import BaseSettings

_PROJECT_ROOT = Path(__file__).parent.parent


class Settings(BaseSettings):
    master_admin_pin: str
    jwt_secret: str
    encryption_key: str  # Fernet key for encrypting API keys at rest
    mongodb_uri: str = "mongodb://mongodb:27017/chatsune?replicaSet=rs0"
    redis_uri: str = "redis://redis:6379/0"
    upload_root: str = "/data/uploads"
    avatar_root: str = "/data/avatars"
    upload_quota_bytes: int = 1_073_741_824  # 1 GB

    jwt_access_token_expire_minutes: int = 15
    jwt_refresh_token_expire_days: int = 30

    model_config = {"env_file": str(_PROJECT_ROOT / ".env"), "extra": "ignore"}


settings = Settings()
