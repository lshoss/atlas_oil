from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ENV_FILE = Path(__file__).resolve().parents[1] / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ENV_FILE, extra="ignore")

    bob_api_key: str = ""
    bob_model: str = "premium-ide"
    bob_base_url: str = ""
    finnhub_api_key: str = ""
    database_url: str = "postgresql+asyncpg://barril:barril@db:5432/barril"


@lru_cache
def get_settings() -> Settings:
    return Settings()
