from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "Live Music Data Quality Pipeline"
    database_url: str = "postgresql+psycopg://live_music:live_music@localhost:5432/live_music"
    api_default_limit: int = 50


@lru_cache
def get_settings() -> Settings:
    return Settings()
