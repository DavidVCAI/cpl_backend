from pydantic_settings import BaseSettings
from typing import Optional


class Settings(BaseSettings):
    """Application settings"""

    # App Configuration
    APP_NAME: str = "CityPulse Live"
    DEBUG: bool = True
    API_VERSION: str = "v1"

    # Server
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    INSTANCE_ID: str = "unknown"  # For load balancer identification

    # MongoDB
    MONGODB_URL: str
    DATABASE_NAME: str = "citypulse_live"

    # AWS Cognito Configuration
    AWS_REGION: str = "us-east-2"
    COGNITO_USER_POOL_ID: str = "us-east-2_iwKIqXJ1E"
    COGNITO_CLIENT_ID: str = "1evngaudtn03ef7pikqt9maeut"

    # Daily.co
    DAILY_API_KEY: Optional[str] = None
    DAILY_DOMAIN: Optional[str] = None

    # Deepgram
    DEEPGRAM_API_KEY: Optional[str] = None

    # CORS
    CORS_ORIGINS: str = "http://localhost:5173,http://localhost:3000"

    # Collectibles
    COLLECTIBLE_DROP_INTERVAL: int = 300  # 5 minutes

    # Feature Flags
    ENABLE_TRANSCRIPTION: bool = True

    # Rate Limiting Configuration
    RATE_LIMIT_MAX_ATTEMPTS: int = 5  # Max failed attempts per minute
    RATE_LIMIT_BLOCK_DURATION: int = 900  # 15 minutes in seconds

    class Config:
        env_file = ".env"
        case_sensitive = True


settings = Settings()
