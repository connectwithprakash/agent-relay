"""
Application configuration using pydantic-settings
"""
from typing import Literal
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # Application
    app_name: str = "Agent Relay"
    app_version: str = "2.1.0"
    environment: Literal["development", "production", "test"] = "development"
    debug: bool = False

    # Server
    host: str = "0.0.0.0"
    port: int = 8000

    # Database
    database_url: str = "sqlite:///./relay.db"
    db_echo: bool = False
    db_pool_size: int = 5
    db_max_overflow: int = 10
    allow_legacy_shared_pairing: bool = False
    allow_unauthenticated_registry_enrollment: bool = False

    # CORS
    cors_origins: list[str] = ["*"]

    # Logging
    log_level: str = "INFO"
    log_format: Literal["json", "text"] = "text"

    # Webhooks
    webhook_max_retries: int = 3
    webhook_timeout_seconds: float = 5.0

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")

    @property
    def is_postgres(self) -> bool:
        return self.database_url.startswith(("postgres://", "postgresql://", "postgresql+"))

    @property
    def sqlalchemy_database_url(self) -> str:
        """Return a SQLAlchemy URL using the installed psycopg v3 driver."""
        if self.database_url.startswith("postgres://"):
            return self.database_url.replace("postgres://", "postgresql+psycopg://", 1)
        if self.database_url.startswith("postgresql://"):
            return self.database_url.replace("postgresql://", "postgresql+psycopg://", 1)
        return self.database_url


settings = Settings()
