from pathlib import Path
from typing import Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/app/core/config.py -> repo root is parents[3]
BACKEND_DIR = Path(__file__).resolve().parents[2]
REPO_ROOT = BACKEND_DIR.parent
ENV_FILE = REPO_ROOT / ".env"


class Settings(BaseSettings):
    APP_NAME: str = "Multi-Tenant Agent Platform"
    APP_ENV: str = "development"
    DATABASE_URL: str = f"sqlite+aiosqlite:///{(BACKEND_DIR / 'platform.db').as_posix()}"
    SYNC_DATABASE_URL: str = f"sqlite:///{(BACKEND_DIR / 'platform.db').as_posix()}"
    SECRET_KEY: str
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24
    BCRYPT_ROUNDS: int = 12  # the tests use 4 so seeding is fast; never lower this in production
    RATE_LIMIT_PER_MINUTE: int = 20
    AUTH_RATE_LIMIT_PER_MINUTE: int = 10
    # Comma separated list of browser origins allowed to call the API.
    CORS_ORIGINS: str = "http://localhost:3000,http://127.0.0.1:3000,http://localhost:5173"

    LLM_PROVIDER: Literal["gemini", "mistral", "groq", "ollama", "mock"] = "mock"
    EMBEDDING_PROVIDER: Literal["gemini", "bm25"] = "gemini"
    # Delay between tokens of the MOCK model so streaming and the Stop button are visible in demos. Tests set 0.
    MOCK_TOKEN_DELAY_MS: int = 25
    GEMINI_API_KEY: str = ""
    MISTRAL_API_KEY: str = ""
    GEMINI_MODEL: str = "gemini-3.8-flash"
    GEMINI_EMBEDDING_MODEL: str = "gemini-embedding-2"
    MISTRAL_MODEL: str = "mistral-small-latest"
    GROQ_API_KEY: str = ""
    GROQ_MODEL: str = "llama-3.3-70b-versatile"
    # A local model through Ollama's OpenAI-compatible endpoint. Needs no key and no quota; pick a model that supports tools.
    OLLAMA_BASE_URL: str = "http://localhost:11434/v1"
    OLLAMA_MODEL: str = "llama3.1:8b"
    CHROMA_PATH: str = str(BACKEND_DIR / "chroma_data")
    # Relevance floors. Passages scoring below these are dropped so unanswerable questions return nothing.
    KB_MIN_SIMILARITY: float = 0.66     # cosine similarity floor, calibrated on live Gemini Embedding 2 scores
    KB_BM25_MIN_COVERAGE: float = 0.5    # share of the question's meaningful words a passage must contain

    SQLITE_BUSY_TIMEOUT_MS: int = 5000

    model_config = SettingsConfigDict(
        env_file=str(ENV_FILE) if ENV_FILE.exists() else None,
        extra="ignore",
    )

    @field_validator("SECRET_KEY")
    @classmethod
    def secret_must_be_set(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("SECRET_KEY is required. Set it in the repo-root .env file.")
        return value.strip()

    @field_validator("LLM_PROVIDER", "EMBEDDING_PROVIDER", mode="before")
    @classmethod
    def strip_provider(cls, value: str) -> str:
        return value.strip().lower() if isinstance(value, str) else value


def load_settings() -> Settings:
    # An explicit env var wins. Never promote mock to gemini because a key exists.
    return Settings()


settings = load_settings()
