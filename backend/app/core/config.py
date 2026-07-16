from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, Field, PositiveInt
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="LISTENING_",
        extra="ignore",
        populate_by_name=True,
    )

    database_url: str = "sqlite:///data/listening.db"
    environment: Literal["development", "production", "test"] = "development"
    data_dir: Path = Path("data")
    log_dir: Path = Path("logs")
    frontend_dist_dir: Path = Path("frontend/dist")
    max_upload_bytes: PositiveInt = 50 * 1024 * 1024
    debug_auth_enabled: bool = False
    cosyvoice_model_dir: Path = Field(
        validation_alias=AliasChoices(
            "COSYVOICE_MODEL_DIR", "LISTENING_COSYVOICE_MODEL_DIR"
        )
    )
    log_rotation_bytes: PositiveInt = 10 * 1024 * 1024
    log_retention_files: PositiveInt = 5


@lru_cache
def get_settings() -> Settings:
    return Settings()
