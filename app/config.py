from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "Data Referee"
    database_url: str = "postgresql+psycopg://data_referee:data_referee@localhost:5432/data_referee"
    api_default_limit: int = 50
    data_referee_api_key: str = "local-development-key"
    data_referee_api_url: str = "http://localhost:8000"
    data_referee_client_id: str = "public-ui"
    max_upload_size_mb: int = 25
    max_upload_rows: int = 250000

    @field_validator("database_url", mode="before")
    @classmethod
    def use_psycopg_driver(cls, value: str) -> str:
        """Use psycopg 3 for provider-issued PostgreSQL connection strings."""
        if value.startswith("postgres://"):
            return value.replace("postgres://", "postgresql+psycopg://", 1)
        if value.startswith("postgresql://"):
            return value.replace("postgresql://", "postgresql+psycopg://", 1)
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
