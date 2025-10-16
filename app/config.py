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

    # MongoDB
    MONGODB_URL: str
    DATABASE_NAME: str = "citypulse_live"

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

    class Config:
        env_file = ".env"
        case_sensitive = True


settings = Settings()
