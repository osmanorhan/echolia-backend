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

    # OAuth Providers
    google_client_id: Optional[str] = None
    google_client_secret: Optional[str] = None
    apple_team_id: Optional[str] = None
    apple_key_id: Optional[str] = None
    apple_private_key: Optional[str] = None

    # LLM Provider API Keys (Optional)
    anthropic_api_key: Optional[str] = None
    openai_api_key: Optional[str] = None
    gemini_api_key: Optional[str] = None

    # Payment Configuration (Optional)
    apple_shared_secret: Optional[str] = None
    google_service_account_json: Optional[str] = None

    # Product IDs for Add-Ons
    product_id_sync_ios: str = "echolia.sync.monthly"
    product_id_sync_android: str = "echolia.sync.monthly"
    product_id_ai_ios: str = "echolia.ai.monthly"
    product_id_ai_android: str = "echolia.ai.monthly"
    product_id_support_small: str = "echolia.support.small"
    product_id_support_medium: str = "echolia.support.medium"
    product_id_support_large: str = "echolia.support.large"

    # AI Add-on Rate Limiting (Anti-abuse)
    ai_rate_limit_hourly: int = 500
    ai_rate_limit_daily: int = 5000

    # E2EE Inference Rate Limiting
    inference_free_tier_daily_limit: int = 10
    inference_paid_tier_daily_limit: int = 5000

    # General Rate Limiting
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
