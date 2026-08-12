from functools import lru_cache
from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEVELOPMENT_SENTINELS = {
    "app_secret_key": "development-only-secret-key",
    "s3_access_key": "development-s3-access-key",
    "s3_secret_key": "development-s3-secret-key",
    "llm_api_key": "development-llm-api-key",
    "llm_model": "development-llm-model",
}
PRODUCTION_PLACEHOLDERS = {
    "REPLACE_WITH_APPROVED_LLM_API_KEY",
    "REPLACE_WITH_APPROVED_MODEL_ID",
}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="RADAR_", env_file=".env", extra="ignore")

    environment: Literal["development", "test", "production"] = "development"
    log_format: Literal["pretty", "json"] = "pretty"
    service_role: Literal["api", "migrate", "ingest-worker", "enrichment-worker"] = "api"

    # Development defaults are deliberately non-secret local stubs. Production
    # configuration is validated below and cannot accidentally use them.
    app_secret_key: str = "development-only-secret-key"
    database_url: str = "sqlite+pysqlite:///:memory:"
    valkey_url: str = "redis://localhost:6379/0"
    s3_endpoint: str = "http://localhost:9000"
    s3_access_key: str = "development-s3-access-key"
    s3_secret_key: str = "development-s3-secret-key"
    s3_bucket: str = "radar-development"
    s3_public_endpoint: str = "http://localhost:9000"
    smtp_url: str = "smtp://localhost:1025"
    llm_api_key: str = "development-llm-api-key"
    llm_base_url: str = "https://api.openai.com/v1"
    llm_model: str = "development-llm-model"

    public_base_url: str = "http://localhost:8000"
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:3000"])
    synthetic_repository: bool = True
    session_ttl_seconds: int = 3600
    secure_cookies: bool = True

    register_ip_limit: int = Field(default=10, ge=1, le=10_000)
    register_account_limit: int = Field(default=3, ge=1, le=10_000)
    register_window_seconds: int = Field(default=300, ge=1, le=86_400)
    login_ip_limit: int = Field(default=30, ge=1, le=10_000)
    login_account_limit: int = Field(default=10, ge=1, le=10_000)
    login_window_seconds: int = Field(default=300, ge=1, le=86_400)
    ask_ip_limit: int = Field(default=60, ge=1, le=10_000)
    ask_account_limit: int = Field(default=30, ge=1, le=10_000)
    ask_window_seconds: int = Field(default=60, ge=1, le=86_400)
    high_cost_concurrency_limit: int = Field(default=8, ge=1, le=256)
    high_cost_retry_after_seconds: int = Field(default=1, ge=1, le=60)

    @model_validator(mode="after")
    def production_defaults_are_safe(self) -> "Settings":
        if self.environment == "production":
            all_values = {
                "app_secret_key": self.app_secret_key,
                "database_url": self.database_url,
                "valkey_url": self.valkey_url,
                "s3_endpoint": self.s3_endpoint,
                "s3_access_key": self.s3_access_key,
                "s3_secret_key": self.s3_secret_key,
                "s3_bucket": self.s3_bucket,
                "smtp_url": self.smtp_url,
                "llm_api_key": self.llm_api_key,
                "llm_base_url": self.llm_base_url,
                "llm_model": self.llm_model,
            }
            required_by_role = {
                "api": {
                    "app_secret_key",
                    "database_url",
                    "valkey_url",
                    "smtp_url",
                },
                "migrate": {"database_url"},
                "ingest-worker": {
                    "database_url",
                    "valkey_url",
                    "s3_endpoint",
                    "s3_access_key",
                    "s3_secret_key",
                    "s3_bucket",
                },
                "enrichment-worker": {
                    "database_url",
                    "valkey_url",
                    "s3_endpoint",
                    "s3_access_key",
                    "s3_secret_key",
                    "s3_bucket",
                    "llm_api_key",
                    "llm_base_url",
                    "llm_model",
                },
            }
            required_names = required_by_role[self.service_role]
            required_values = {name: all_values[name] for name in required_names}
            missing = [name for name, value in required_values.items() if not value.strip()]
            if missing:
                raise ValueError(
                    "production requires non-empty values for: " + ", ".join(sorted(missing))
                )
            inherited_defaults = [
                name
                for name, sentinel in DEVELOPMENT_SENTINELS.items()
                if name in required_values and required_values[name] == sentinel
            ]
            if inherited_defaults:
                raise ValueError(
                    "production rejects development defaults for: "
                    + ", ".join(sorted(inherited_defaults))
                )
            placeholders = [
                name for name, value in required_values.items() if value in PRODUCTION_PLACEHOLDERS
            ]
            if placeholders:
                raise ValueError(
                    "production rejects unresolved placeholders for: "
                    + ", ".join(sorted(placeholders))
                )
            if "app_secret_key" in required_names and len(self.app_secret_key) < 32:
                raise ValueError("production app_secret_key must contain at least 32 characters")
            if "s3_secret_key" in required_names and len(self.s3_secret_key) < 24:
                raise ValueError("production s3_secret_key must contain at least 24 characters")
            if not self.database_url.startswith("postgresql+"):
                raise ValueError("production requires a PostgreSQL SQLAlchemy URL")
            if self.synthetic_repository:
                raise ValueError("synthetic repository must be disabled in production")
            if self.service_role == "api" and not self.public_base_url.startswith("https://"):
                raise ValueError("production public_base_url must use HTTPS")
            if self.service_role == "api" and not self.secure_cookies:
                raise ValueError("production requires secure cookies")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
