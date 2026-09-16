from functools import lru_cache
from pathlib import Path

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


PROJECT_ROOT = Path(__file__).resolve().parents[3]
ENV_FILE = PROJECT_ROOT / ".env"


class Settings(BaseSettings):
    app_name: str = "Generative AI Music Research API"
    app_version: str = "0.1.0"
    environment: str = "development"

    frontend_url: str = "http://localhost:5173"

    backend_openai_api_key: SecretStr | None = None
    backend_openai_model: str = "gpt-5.6-luna"

    backend_use_mock_llm: bool = True
    backend_use_mock_rag: bool = True

    model_config = SettingsConfigDict(
        env_file=ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()