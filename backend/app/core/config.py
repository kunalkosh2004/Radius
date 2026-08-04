from pydantic_settings import BaseSettings, SettingsConfigDict
from functools import lru_cache

class Settings(BaseSettings):
    APP_NAME: str = "Radius"
    ENVIRONMENT: str = "development"
    DEBUG: bool = True

    DATABASE_URL: str
    REDIS_URL: str

    API_V1_PREFIX: str = "/api/v1"

    PRESENCE_HEARTBEAT_TIMEOUT_S: int = 90
    PRESENCE_SWEEP_INTERVAL_S: int = 15
    PRESENCE_NEARBY_RADIUS_M: int = 500
    NEARBY_BROADCAST_INTERVAL_S: int = 30

    MESSAGE_MAX_LENGTH: int = 2000
    MESSAGE_PAGE_SIZE: int = 50

    WS_TOKEN_SECRET: str = "dev-ws-token-secret-change-me"
    WS_TOKEN_TTL_S: int = 60

    model_config = SettingsConfigDict(
        env_file=".env",
        case_sensitive=True,
    )

@lru_cache
def get_settings() -> Settings:
    return Settings()