from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


BACKEND_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    APP_NAME: str = "VeriReview"
    APP_ENV: str = "development"
    DEBUG: bool = True

    # Database
    DATABASE_URL: str

    # Authentication
    JWT_SECRET_KEY: str
    JWT_ALGORITHM: str = "HS256"

    ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # OpenRouter configuration
    OPENROUTER_API_KEY: str = Field(
        default="",
        repr=False,
    )

    OPENROUTER_BASE_URL: str = (
        "https://openrouter.ai/api/v1"
    )

    OPENROUTER_MODEL: str = "openrouter/free"

    OPENROUTER_TIMEOUT: float = Field(
        default=60.0,
        gt=0,
        le=300,
    )

    OPENROUTER_MAX_RETRIES: int = Field(
        default=2,
        ge=0,
        le=5,
    )

    model_config = SettingsConfigDict(
        env_file=BACKEND_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()