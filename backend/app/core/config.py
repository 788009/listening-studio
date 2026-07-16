from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, Field, PositiveInt, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from backend.app.integrations.llm import MAX_GENERATION_COUNT


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
    max_corpus_bytes: PositiveInt = 1 * 1024 * 1024
    max_batch_generation_count: int = Field(
        default=MAX_GENERATION_COUNT,
        ge=1,
        le=MAX_GENERATION_COUNT,
    )
    dialogue_silence_milliseconds: int = Field(default=500, ge=0, le=10_000)
    debug_auth_enabled: bool = False
    auth_session_secret: SecretStr = SecretStr("development-only-change-before-use")
    auth_session_cookie_name: str = "listening_session"
    auth_session_max_age_seconds: PositiveInt = 8 * 60 * 60
    cosyvoice_model_dir: Path = Field(
        validation_alias=AliasChoices(
            "COSYVOICE_MODEL_DIR", "LISTENING_COSYVOICE_MODEL_DIR"
        )
    )
    log_rotation_bytes: PositiveInt = 10 * 1024 * 1024
    log_retention_files: PositiveInt = 5

    @field_validator("auth_session_secret")
    @classmethod
    def validate_auth_session_secret(cls, value: SecretStr) -> SecretStr:
        if len(value.get_secret_value()) < 32:
            raise ValueError(
                "Authentication session secret must be at least 32 characters"
            )
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
