from functools import lru_cache
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

from pydantic import (
    AliasChoices,
    Field,
    PositiveInt,
    SecretStr,
    field_validator,
    model_validator,
)
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
    dashscope_api_key: SecretStr | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "DASHSCOPE_API_KEY", "LISTENING_DASHSCOPE_API_KEY"
        ),
    )
    dashscope_base_url: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "DASHSCOPE_BASE_URL", "LISTENING_DASHSCOPE_BASE_URL"
        ),
    )
    dashscope_model: str | None = Field(
        default=None,
        validation_alias=AliasChoices("DASHSCOPE_MODEL", "LISTENING_DASHSCOPE_MODEL"),
    )
    dialogue_silence_milliseconds: int = Field(default=500, ge=0, le=10_000)
    debug_auth_enabled: bool = False
    auth_session_secret: SecretStr = SecretStr("development-only-change-before-use")
    metrics_token: SecretStr | None = None
    auth_session_cookie_name: str = "listening_session"
    auth_session_max_age_seconds: PositiveInt = 8 * 60 * 60
    oidc_enabled: bool = False
    oidc_discovery_url: str | None = None
    oidc_client_id: str | None = None
    oidc_client_secret: SecretStr | None = None
    oidc_redirect_uri: str | None = None
    oidc_post_login_url: str = "/"
    oidc_scopes: str = "openid profile email phone"
    oidc_token_endpoint_auth_method: Literal[
        "client_secret_basic", "client_secret_post"
    ] = "client_secret_basic"
    oidc_pkce_enabled: bool = False
    oidc_flow_cookie_name: str = "listening_oidc_flow"
    oidc_flow_max_age_seconds: PositiveInt = 10 * 60
    cosyvoice_model_dir: Path = Field(
        validation_alias=AliasChoices(
            "COSYVOICE_MODEL_DIR", "LISTENING_COSYVOICE_MODEL_DIR"
        )
    )
    log_rotation_bytes: PositiveInt = 10 * 1024 * 1024
    log_retention_files: PositiveInt = 5
    rate_limit_window_seconds: PositiveInt = 60
    login_rate_limit: PositiveInt = 20
    search_rate_limit: PositiveInt = 120
    upload_rate_limit: PositiveInt = 20
    generation_rate_limit: PositiveInt = 60
    playback_rate_limit: PositiveInt = 600

    @field_validator("auth_session_secret")
    @classmethod
    def validate_auth_session_secret(cls, value: SecretStr) -> SecretStr:
        if len(value.get_secret_value()) < 32:
            raise ValueError(
                "Authentication session secret must be at least 32 characters"
            )
        return value

    @model_validator(mode="after")
    def validate_oidc_settings(self) -> "Settings":
        if not self.oidc_enabled:
            return self

        required = {
            "oidc_discovery_url": self.oidc_discovery_url,
            "oidc_client_id": self.oidc_client_id,
            "oidc_client_secret": (
                self.oidc_client_secret.get_secret_value()
                if self.oidc_client_secret is not None
                else None
            ),
            "oidc_redirect_uri": self.oidc_redirect_uri,
        }
        missing = [name for name, value in required.items() if not value]
        if missing:
            raise ValueError(
                "OIDC is enabled but required settings are missing: "
                + ", ".join(missing)
            )

        assert self.oidc_discovery_url is not None
        assert self.oidc_redirect_uri is not None
        discovery = urlparse(self.oidc_discovery_url)
        redirect = urlparse(self.oidc_redirect_uri)
        if discovery.scheme != "https" or not discovery.netloc:
            raise ValueError("OIDC discovery URL must use HTTPS")
        if redirect.scheme not in {"http", "https"} or not redirect.netloc:
            raise ValueError("OIDC redirect URI must be an absolute HTTP(S) URL")
        if "openid" not in self.oidc_scopes.split():
            raise ValueError("OIDC scopes must include openid")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
