import os
from pathlib import Path
from pydantic_settings import BaseSettings
from typing import Literal

BASE_DIR = Path(__file__).resolve().parent.parent.parent
DEFAULT_DB_FILE = (BASE_DIR / "platform.db").as_posix()

class Settings(BaseSettings):
    APP_NAME: str = "Multi-Tenant Agent Platform"
    APP_ENV: str = "development"
    DATABASE_URL: str = f"sqlite+aiosqlite:///{DEFAULT_DB_FILE}"
    SYNC_DATABASE_URL: str = f"sqlite:///{DEFAULT_DB_FILE}"
    SECRET_KEY: str = "super-secret-takehome-key-change-in-production-123456789"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24  # 24 hours
    RATE_LIMIT_PER_MINUTE: int = 20

    # LLM Settings
    LLM_PROVIDER: Literal["gemini", "mistral", "mock"] = "mock"
    GEMINI_API_KEY: str = ""
    MISTRAL_API_KEY: str = ""
    GEMINI_MODEL: str = "gemini-2.0-flash"
    MISTRAL_MODEL: str = "mistral-small-latest"

    # Default Timezone for Org B
    STUDIO_TIMEZONE: str = "Asia/Kathmandu"

    class Config:
        env_file = ".env"
        extra = "allow"

settings = Settings()

# Auto-detect if API keys exist
if settings.GEMINI_API_KEY and settings.LLM_PROVIDER == "mock":
    settings.LLM_PROVIDER = "gemini"
elif settings.MISTRAL_API_KEY and settings.LLM_PROVIDER == "mock":
    settings.LLM_PROVIDER = "mistral"
