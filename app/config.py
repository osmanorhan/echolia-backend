"""
Application configuration management.
"""
from pydantic_settings import BaseSettings
from typing import Optional


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # Application
    app_name: str = "Echolia Backend"
    environment: str = "development"
    debug: bool = False
    log_level: str = "info"

    # Server
    host: str = "0.0.0.0"
    port: int = 8000

    # Turso Database Configuration
    turso_org_url: str
    turso_auth_token: str
    embedded_replica: bool = True
    sync_interval: int = 60  # seconds
    max_cached_connections: int = 100

    # Authentication
    jwt_secret: str
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60
    refresh_token_expire_days: int = 30

    # LLM Provider API Keys (Optional)
    anthropic_api_key: Optional[str] = None
    openai_api_key: Optional[str] = None
    gemini_api_key: Optional[str] = None

    # Payment Configuration (Optional)
    apple_shared_secret: Optional[str] = None
    google_service_account_json: Optional[str] = None

    # Rate Limiting
    rate_limit_per_minute: int = 100
    rate_limit_burst: int = 20

    # Sync Configuration
    max_sync_size_mb: int = 50
    max_entries_per_sync: int = 1000

    # Storage
    data_dir: str = "./data"

    class Config:
        env_file = ".env"
        case_sensitive = False


# Global settings instance
settings = Settings()
