import os
from functools import lru_cache
from typing import List, Optional
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # AWS Configuration
    AWS_REGION: str = "us-east-1"
    DYNAMODB_TABLE_NAME: str = "zerodaily-articles"
    DYNAMODB_STREAM_ARN: Optional[str] = "arn:aws:dynamodb:us-east-1:339087217625:table/zerodaily-articles/stream/2026-09-16T09:39:09.468"
    AWS_ACCESS_KEY_ID: Optional[str] = None
    AWS_SECRET_ACCESS_KEY: Optional[str] = None

    # Firebase / FCM HTTP v1 Configuration
    FIREBASE_PROJECT_ID: Optional[str] = "zerodaily-prod"
    FIREBASE_SERVICE_ACCOUNT_JSON: Optional[str] = None
    FIREBASE_SECRET_NAME: Optional[str] = "zerodaily/firebase-key"

    # Notification & Cooldown
    NOTIFICATION_COOLDOWN_MINUTES: int = 30
    ENABLE_ALL_BREAKING_TOPIC: bool = True

    # Cloudflare CDN Configuration
    CLOUDFLARE_ZONE_ID: Optional[str] = None
    CLOUDFLARE_API_TOKEN: Optional[str] = None
    API_DOMAIN: str = "https://api.zerodaily.in"
    MEDIA_DOMAIN: str = "https://media.zerodaily.in"

    # Server Configuration
    ENVIRONMENT: str = "development"
    PORT: int = 8000
    HOST: str = "0.0.0.0"
    CORS_ORIGINS: str = "*"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

    @property
    def cors_origins_list(self) -> List[str]:
        if self.CORS_ORIGINS == "*":
            return ["*"]
        return [origin.strip() for origin in self.CORS_ORIGINS.split(",") if origin.strip()]


@lru_cache()
def get_settings() -> Settings:
    return Settings()
