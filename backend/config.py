from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    master_admin_pin: str
    jwt_secret: str
    mongodb_uri: str = "mongodb://mongodb:27017/chatsune?replicaSet=rs0"
    redis_uri: str = "redis://redis:6379/0"

    jwt_access_token_expire_minutes: int = 15
    jwt_refresh_token_expire_days: int = 30

    model_config = {"env_file": ".env"}


settings = Settings()
