"""Core configuration module."""

from pydantic_settings import BaseSettings
from functools import lru_cache
from typing import Optional


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # Application
    APP_NAME: str = "SmartMenu QR"
    APP_ENV: str = "development"
    DEBUG: bool = True
    SECRET_KEY: str = "change-this-to-a-random-secret-key-in-production"
    FRONTEND_URL: str = "http://localhost:5173"
    API_V1_PREFIX: str = "/api/v1"

    # Database
    DATABASE_URL: str = "postgresql+asyncpg://postgres:437734@localhost:5432/smartmenu_db"

    # Redis
    REDIS_URL: str = "redis://default:k8N2FiwlfeMKobIcZgQRb5ZxsTg1b8eH@redis-16632.crce281.ap-south-1-3.ec2.cloud.redislabs.com:16632"

    # JWT
    JWT_SECRET_KEY: str = "change-this-jwt-secret-key"
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    JWT_REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # Email
    EMAIL_BACKEND: str = "smtp"  # console | smtp
    SMTP_HOST: str = "smtp.gmail.com"
    SMTP_PORT: int = 465
    SMTP_USER: str = "siva967763@gmail.com"
    SMTP_PASSWORD: str = "esyr iqiq mzbo bppj"
    SMTP_FROM_EMAIL: str = "noreply@smartmenuqr.com"

    # Azure Blob Storage
    AZURE_STORAGE_CONNECTION_STRING: Optional[str] = None
    AZURE_STORAGE_CONTAINER: str = "smartmenu-images"

    # Upload
    UPLOAD_DIR: str = "uploads"
    MAX_IMAGE_SIZE_MB: int = 5

    # OTP
    OTP_EXPIRE_SECONDS: int = 300  # 5 minutes
    OTP_MAX_ATTEMPTS: int = 3
    OTP_RATE_LIMIT_SECONDS: int = 900  # 15 minutes

    class Config:
        env_file = ".env"
        case_sensitive = True


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()
