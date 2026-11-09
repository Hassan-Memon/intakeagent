"""Application settings.

Everything is read from environment variables (or a local .env file) so the same image runs
in docker compose, on Render, or on a laptop. Defaults are chosen so that the service starts
with no API keys at all: DEMO_MODE=1 uses scripted speech-to-text, a rule-based extractor and
mock exporters.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

LLMProvider = Literal["auto", "openinfer", "ollama", "groq", "gemini", "openrouter", "stub"]
STTProvider = Literal["auto", "stub", "groq", "faster_whisper"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    demo_mode: bool = Field(default=True, alias="DEMO_MODE")
    database_url: str = Field(default="sqlite:///./intakeagent.db", alias="DATABASE_URL")

    # LLM
    llm_provider: LLMProvider = Field(default="auto", alias="LLM_PROVIDER")
    llm_model: str = Field(default="llama-3.1-8b-instant", alias="LLM_MODEL")
    openinfer_base_url: str = Field(default="", alias="OPENINFER_BASE_URL")
    openinfer_api_key: str = Field(default="", alias="OPENINFER_API_KEY")
    ollama_base_url: str = Field(default="http://localhost:11434", alias="OLLAMA_BASE_URL")
    groq_api_key: str = Field(default="", alias="GROQ_API_KEY")
    gemini_api_key: str = Field(default="", alias="GEMINI_API_KEY")
    openrouter_api_key: str = Field(default="", alias="OPENROUTER_API_KEY")
    allow_cloud_llm: bool = Field(default=False, alias="ALLOW_CLOUD_LLM")

    # Speech to text
    stt_provider: STTProvider = Field(default="auto", alias="STT_PROVIDER")
    faster_whisper_model: str = Field(default="base", alias="FASTER_WHISPER_MODEL")

    # Exporters
    fhir_push: bool = Field(default=False, alias="FHIR_PUSH")
    fhir_base_url: str = Field(default="https://hapi.fhir.org/baseR4", alias="FHIR_BASE_URL")
    clio_base_url: str = Field(default="https://app.clio.com", alias="CLIO_BASE_URL")
    clio_client_id: str = Field(default="", alias="CLIO_CLIENT_ID")
    clio_client_secret: str = Field(default="", alias="CLIO_CLIENT_SECRET")
    clio_redirect_uri: str = Field(
        default="http://localhost:8000/oauth/clio/callback", alias="CLIO_REDIRECT_URI"
    )
    clio_access_token: str = Field(default="", alias="CLIO_ACCESS_TOKEN")
    clio_refresh_token: str = Field(default="", alias="CLIO_REFRESH_TOKEN")

    # Web
    cors_origins: str = Field(
        default="http://localhost:3000,http://127.0.0.1:3000", alias="CORS_ORIGINS"
    )

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def clio_configured(self) -> bool:
        return bool(self.clio_access_token or (self.clio_client_id and self.clio_client_secret))


@lru_cache
def get_settings() -> Settings:
    return Settings()


def reset_settings_cache() -> None:
    """Used by tests that change environment variables."""
    get_settings.cache_clear()
