"""Application configuration loaded from environment variables.

Secrets (encryption key, AI keys, admin bootstrap password) come only from the
environment or a deployment secret store. They are never returned by the API.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(str(BACKEND_DIR.parent / ".env"), str(BACKEND_DIR / ".env")),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "TouQA AI"
    environment: Literal["development", "test", "production"] = "development"
    log_level: str = "INFO"

    database_url: str = "postgresql+psycopg://touqa:touqa@localhost:5432/touqa"

    # Fernet key (urlsafe base64, 32 bytes). Generate with:
    #   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    encryption_key: SecretStr | None = None

    # Application authentication
    auth_enabled: bool = True
    admin_email: str = "admin@touqa.local"
    admin_password: SecretStr | None = None
    session_ttl_hours: int = 12
    cookie_secure: bool = False  # set True behind HTTPS
    # "none" only when the UI is served from a different site than the API (requires COOKIE_SECURE=true).
    cookie_samesite: Literal["lax", "strict", "none"] = "lax"
    cors_origins: Annotated[list[str], NoDecode] = Field(default_factory=lambda: ["http://localhost:5173"])

    # Demo mode: synthetic data, simulated AI, external writes disabled by default.
    demo_mode: bool = False
    demo_allow_external_writes: bool = False

    # AI provider: anthropic | openai_compatible | local | simulated
    ai_provider: Literal["anthropic", "openai_compatible", "local", "simulated"] = "anthropic"
    ai_model: str = "claude-opus-5-5"
    ai_vision_model: str | None = None
    ai_base_url: str | None = None  # for openai_compatible / local (e.g. http://localhost:11434/v1)
    ai_api_key: SecretStr | None = None
    anthropic_api_key: SecretStr | None = None
    ai_effort: Literal["low", "medium", "high", "xhigh", "max"] = "high"
    ai_max_tokens: int = 32000
    ai_timeout_seconds: float = 300.0
    # Server-side refusal fallback for Claude models (beta). Disable if your account rejects it.
    anthropic_enable_fallbacks: bool = True

    # Outbound integration HTTP policy
    http_timeout_seconds: float = 30.0
    http_max_retries: int = 4
    http_backoff_base_seconds: float = 0.5
    allow_private_network_targets: bool = False  # SSRF guard for integration URLs
    verify_tls: bool = True  # never disable in production

    # Uploads
    upload_dir: Path = BACKEND_DIR / "data" / "uploads"
    max_upload_bytes: int = 10 * 1024 * 1024
    allowed_upload_types: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: [
            "image/png", "image/jpeg", "image/gif", "image/webp",
            "text/plain", "application/json", "text/csv", "application/pdf",
        ]
    )

    # Background jobs
    job_workers: int = 4

    # Rate limiting (per client, per minute) for API endpoints
    rate_limit_per_minute: int = 240
    ai_rate_limit_per_minute: int = 20

    # Optional live integration tests (never run by default)
    live_tests_enabled: bool = False

    @field_validator("cors_origins", "allowed_upload_types", mode="before")
    @classmethod
    def _split_csv(cls, v):
        if isinstance(v, str):
            return [s.strip() for s in v.split(",") if s.strip()]
        return v

    @field_validator("database_url", mode="before")
    @classmethod
    def _psycopg_driver(cls, v):
        # Hosted Postgres (Render, Railway, Heroku) hands out postgres:// or postgresql:// URLs;
        # route them to the installed psycopg 3 driver.
        if isinstance(v, str):
            for prefix in ("postgres://", "postgresql://"):
                if v.startswith(prefix):
                    return "postgresql+psycopg://" + v[len(prefix):]
        return v

    @property
    def is_production(self) -> bool:
        return self.environment == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()
