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

    model_config = SettingsConfigDict(
        env_file=".env",
        case_sensitive=True,
    )

@lru_cache
def get_settings() -> Settings:
    return Settings()