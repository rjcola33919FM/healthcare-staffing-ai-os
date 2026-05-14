"""
Centralized settings management for Healthcare Staffing AI OS.
All environment variables are validated here at startup.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):

    # ── App ───────────────────────────────────────────────────────────────────
    app_env: Literal["development", "staging", "production"] = "development"
    allowed_origins: str = "*"

    # ── Anthropic / Claude ────────────────────────────────────────────────────
    anthropic_api_key: str = Field(..., alias="ANTHROPIC_API_KEY")
    claude_model_production: str = "claude-opus-4-6"
    claude_model_development: str = "claude-sonnet-4-6"

    @property
    def claude_model(self) -> str:
        return self.claude_model_production if self.app_env == "production" else self.claude_model_development

    # ── GoHighLevel ───────────────────────────────────────────────────────────
    ghl_api_key: str = Field(default="", alias="GHL_API_KEY")
    ghl_location_id: str = Field(default="", alias="GHL_LOCATION_ID")

    # ── Twilio ────────────────────────────────────────────────────────────────
    twilio_account_sid: str = Field(default="", alias="TWILIO_ACCOUNT_SID")
    twilio_auth_token: str = Field(default="", alias="TWILIO_AUTH_TOKEN")
    twilio_from_number: str = Field(default="", alias="TWILIO_FROM_NUMBER")
    twilio_failover_number: str = Field(default="", alias="TWILIO_FAILOVER_NUMBER")

    # ── VAPI ──────────────────────────────────────────────────────────────────
    vapi_api_key: str = Field(default="", alias="VAPI_API_KEY")
    vapi_assistant_id: str = Field(default="", alias="VAPI_ASSISTANT_ID")

    # ── Redis ─────────────────────────────────────────────────────────────────
    redis_url: str = Field(default="redis://localhost:6379/0", alias="REDIS_URL")

    # ── PostgreSQL ────────────────────────────────────────────────────────────
    postgres_db: str = Field(default="healthcare_staffing", alias="POSTGRES_DB")
    postgres_user: str = Field(default="staffing_user", alias="POSTGRES_USER")
    postgres_password: str = Field(default="", alias="POSTGRES_PASSWORD")
    postgres_host: str = Field(default="localhost", alias="POSTGRES_HOST")
    postgres_port: int = Field(default=5432, alias="POSTGRES_PORT")

    @property
    def database_url(self) -> str:
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    # ── Auth0 ─────────────────────────────────────────────────────────────────
    auth0_domain: str = Field(default="", alias="AUTH0_DOMAIN")
    auth0_api_audience: str = Field(default="", alias="AUTH0_API_AUDIENCE")

    # ── Vector DB (Pinecone) ──────────────────────────────────────────────────
    pinecone_api_key: str = Field(default="", alias="PINECONE_API_KEY")
    pinecone_environment: str = Field(default="", alias="PINECONE_ENVIRONMENT")
    pinecone_index_name: str = Field(default="healthcare-staffing-kb", alias="PINECONE_INDEX_NAME")

    # ── Langfuse ──────────────────────────────────────────────────────────────
    langfuse_secret_key: str = Field(default="", alias="LANGFUSE_SECRET_KEY")
    langfuse_public_key: str = Field(default="", alias="LANGFUSE_PUBLIC_KEY")
    langfuse_host: str = Field(default="https://cloud.langfuse.com", alias="LANGFUSE_HOST")

    # ── Agent defaults ────────────────────────────────────────────────────────
    agent_temperature: float = 0.05
    agent_top_p: float = 0.1
    agent_max_tokens: int = 1024
    agent_max_retries: int = 3

    model_config = {"env_file": ".env", "populate_by_name": True}


@lru_cache
def get_settings() -> Settings:
    return Settings()
