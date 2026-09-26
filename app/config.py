import os
from functools import lru_cache
from typing import List, Optional, Dict
from pydantic_settings import BaseSettings, SettingsConfigDict

CANONICAL_CATEGORIES: List[str] = [
    "cybersec",
    "ai",
    "programming",
    "robotics",
    "defense_aerospace",
    "hardware",
    "finance",
]

CATEGORY_ALIASES: Dict[str, str] = {
    "cybersecurity": "cybersec",
    "cybersec": "cybersec",
    "ai": "ai",
    "artificial_intelligence": "ai",
    "programming": "programming",
    "dev": "programming",
    "software": "programming",
    "robotics": "robotics",
    "defense_aerospace": "defense_aerospace",
    "defense": "defense_aerospace",
    "aerospace": "defense_aerospace",
    "hardware": "hardware",
    "finance": "finance",
    "markets": "finance",
    "commodities": "finance",
    "pharma": "finance",
    "energy": "finance",
}


def normalize_category_key(cat: str) -> Optional[str]:
    if not cat:
        return None
    cleaned = cat.strip().lower()
    return CATEGORY_ALIASES.get(cleaned)


class Settings(BaseSettings):
    # AWS Configuration
    AWS_REGION: str = "us-east-1"
    DYNAMODB_TABLE_NAME: str = "zerodaily-articles"
    DYNAMODB_USERS_TABLE_NAME: str = "zerodaily-users"
    DYNAMODB_STREAM_ARN: Optional[str] = "arn:aws:dynamodb:us-east-1:339087217625:table/zerodaily-articles/stream/2026-09-16T09:39:09.468"
    AWS_ACCESS_KEY_ID: Optional[str] = None
    AWS_SECRET_ACCESS_KEY: Optional[str] = None

    # JWT Authentication Configuration
    JWT_SECRET_KEY: str = "zerodaily-auth-jwt-secret-key-prod-2026-secure-us-east-1"
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 43200  # 30 days session validity

    # Firebase / FCM HTTP v1 Configuration
    FIREBASE_PROJECT_ID: Optional[str] = "zerodaily-prod"
    FIREBASE_SERVICE_ACCOUNT_JSON: Optional[str] = None
    FIREBASE_SECRET_NAME: Optional[str] = "zerodaily/firebase-key"
    FIREBASE_API_KEY: Optional[str] = "AIzaSyDRRO8C8mpknJoJmlcOAJtqDR6b44sQOpc"

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
